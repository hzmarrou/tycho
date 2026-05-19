"""Model family — extracts entities, attributes, vocabularies, behaviors from
class/dataclass/Pydantic/ORM/Enum definitions.

Mirrors the v1.1 SourceDIngester emissions (parity per AC6) but produces IR
facts rather than IntermediateCandidate directly.
"""
from __future__ import annotations

import ast
from collections.abc import Iterable

from .ir import (
    AttributeFact,
    BehaviorFact,
    EntityFact,
    EvidenceSpan,
    RuleFact,
    VocabularyFact,
)
from .parse import ParsedModule

ENUM_BASES = {"Enum", "IntEnum", "StrEnum", "Flag", "IntFlag"}
PYDANTIC_BASES = {"BaseModel", "GenericModel"}
ORM_BASES = {"Base", "Document"}


def _span(node: ast.AST, file: str, source: str) -> EvidenceSpan:
    start = getattr(node, "lineno", 1)
    end = getattr(node, "end_lineno", start)
    snippet = ast.get_source_segment(source, node) or ""
    return EvidenceSpan(file=file, start_line=start, end_line=end, snippet=snippet[:200])


def _base_names(cls: ast.ClassDef) -> list[str]:
    out: list[str] = []
    for b in cls.bases:
        if isinstance(b, ast.Name):
            out.append(b.id)
        elif isinstance(b, ast.Attribute):
            out.append(b.attr)
    return out


def _is_enum(cls: ast.ClassDef) -> bool:
    return any(b in ENUM_BASES for b in _base_names(cls))


def _enum_members(cls: ast.ClassDef) -> list[str]:
    members: list[str] = []
    for stmt in cls.body:
        if isinstance(stmt, ast.Assign):
            for tgt in stmt.targets:
                if isinstance(tgt, ast.Name):
                    members.append(tgt.id)
    return members


def extract_model(pm: ParsedModule) -> Iterable[object]:
    file = str(pm.path)
    for cls_name, cls in pm.classes.items():
        if _is_enum(cls):
            yield VocabularyFact(
                name=cls_name,
                members=_enum_members(cls),
                evidence_span=_span(cls, file, pm.source),
                extractor_family="model",
            )
            continue

        yield EntityFact(
            name=cls_name,
            evidence_span=_span(cls, file, pm.source),
            extractor_family="model",
            docstring=ast.get_docstring(cls),
            bases=_base_names(cls),
            raw_type="class",
        )

        for stmt in cls.body:
            if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                yield AttributeFact(
                    name=stmt.target.id,
                    subject_entity=cls_name,
                    evidence_span=_span(stmt, file, pm.source),
                    extractor_family="model",
                    annotation=ast.unparse(stmt.annotation) if stmt.annotation else None,
                    has_default=stmt.value is not None,
                )
            elif isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)) and not stmt.name.startswith("_"):
                yield BehaviorFact(
                    name=stmt.name,
                    subject_entity=cls_name,
                    evidence_span=_span(stmt, file, pm.source),
                    extractor_family="model",
                )
                yield from _extract_inline_rules(cls_name, stmt, pm.source, file)
            elif isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)) and stmt.name == "__init__":
                yield from _extract_inline_rules(cls_name, stmt, pm.source, file)


# Predicate inversion: detect a guard `if <bad>: raise` and promote
# the positive constraint that must hold for the code to pass.
# Example: `if x <= 0: raise` -> emit `x gt 0` (LtE -> gt).
_CMP_INVERSE: dict[type, str] = {
    ast.Lt: "gte",
    ast.LtE: "gt",
    ast.Gt: "lte",
    ast.GtE: "lt",
    ast.Eq: "neq",
    ast.NotEq: "eq",
}


def _attr_target(node: ast.expr) -> str | None:
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "self":
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return None


def _literal_value(node: ast.expr):
    if isinstance(node, ast.Constant):
        return node.value
    return None


def _decorator_field_name(deco: ast.expr) -> str | None:
    if isinstance(deco, ast.Call) and isinstance(deco.func, ast.Name) and deco.func.id == "field_validator":
        if deco.args and isinstance(deco.args[0], ast.Constant):
            return deco.args[0].value
    return None


def _extract_inline_rules(cls_name: str, method: ast.FunctionDef, source: str, file: str):
    bound: str | None = None
    for deco in method.decorator_list:
        bound = _decorator_field_name(deco)
        if bound:
            break

    arg_to_attr: dict[str, str] = {}
    if bound and method.args.args:
        param_name = method.args.args[-1].arg
        arg_to_attr[param_name] = bound

    for node in ast.walk(method):
        if not (isinstance(node, ast.If) and node.body and isinstance(node.body[0], ast.Raise)):
            continue
        test = node.test
        if not isinstance(test, ast.Compare) or len(test.ops) != 1:
            continue
        op_type = type(test.ops[0])
        if op_type not in _CMP_INVERSE:
            continue
        lhs = test.left
        rhs = test.comparators[0]
        attr = _attr_target(lhs)
        if attr is None:
            continue
        if attr in arg_to_attr:
            attr = arg_to_attr[attr]
        val = _literal_value(rhs)
        if val is None:
            continue
        predicate = _CMP_INVERSE[op_type]
        yield RuleFact(
            rule_kind="validation",
            subject_entity=cls_name,
            subject_attribute=attr,
            predicate=predicate,
            object_value=val,
            expression=ast.unparse(test),
            evidence_span=_span(node, file, source),
            code_context=f"class {cls_name}, def {method.name}",
            confidence=0.9,
            extractor_family="model",
        )
