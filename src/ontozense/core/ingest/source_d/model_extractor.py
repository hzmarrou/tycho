"""Model family — extracts entities, attributes, vocabularies, behaviors from
class/dataclass/Pydantic/ORM/Enum definitions.

Mirrors the v1.1 SourceDIngester emissions (parity per AC6) but produces IR
facts rather than IntermediateCandidate directly.
"""
from __future__ import annotations

import ast
from collections.abc import Iterable

from ontozense.core.ingest.filters import (
    DEFAULT_SOURCE_D_CLASS_SUPPRESSIONS,
    glob_match,
)

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

# DTO suffixes: a Pydantic model whose name ends in one of these is classified
# as 'dto_candidate' unless include_classes overrides. This is the v1.1
# convention preserved for downstream consumers.
_DTO_SUFFIXES: tuple[str, ...] = ("DTO", "Request", "Response", "Schema", "Model")


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


def _has_decorator(cls: ast.ClassDef, name: str) -> bool:
    """True if cls is decorated with @<name> or @<name>(...)."""
    for deco in cls.decorator_list:
        if isinstance(deco, ast.Name) and deco.id == name:
            return True
        if isinstance(deco, ast.Call) and isinstance(deco.func, ast.Name) and deco.func.id == name:
            return True
        if isinstance(deco, ast.Attribute) and deco.attr == name:
            return True
    return False


def _classify_class(cls: ast.ClassDef) -> str:
    """Return the v1.1-compatible raw_type label for a class:
    'dataclass' | 'pydantic_model' | 'dto_candidate' | 'sqlalchemy_model' | 'class'.

    Enums are handled separately by extract_model (they become VocabularyFact).

    DTO detection: a Pydantic model whose name ends in one of the DTO
    suffixes is classified as 'dto_candidate'. This is the v1.1
    convention preserved for downstream consumers.
    """
    if _has_decorator(cls, "dataclass"):
        return "dataclass"
    bases = _base_names(cls)
    if any(b in PYDANTIC_BASES for b in bases):
        if any(cls.name.endswith(s) for s in _DTO_SUFFIXES):
            return "dto_candidate"
        return "pydantic_model"
    if any(b in ORM_BASES for b in bases):
        return "sqlalchemy_model"
    return "class"


def _enum_members(cls: ast.ClassDef) -> list[str]:
    members: list[str] = []
    for stmt in cls.body:
        if isinstance(stmt, ast.Assign):
            for tgt in stmt.targets:
                if isinstance(tgt, ast.Name):
                    members.append(tgt.id)
    return members


def extract_model(pm: ParsedModule, config: dict | None = None) -> Iterable[object]:
    """Extract entity, attribute, vocabulary, behavior, and inline rule facts
    from class definitions in a parsed module.

    Config keys honored (all optional):
      - ``exclude_classes``: glob patterns (case-insensitive). Matching
        classes are emitted as suppressed EntityFacts unless overridden by
        ``include_classes``.
      - ``include_classes``: glob patterns (case-insensitive). Overrides
        both default suppressions and ``exclude_classes``. When a class
        matches ``include_classes``, its raw_type is restored to the
        real classifier result (never 'dto_candidate').
      - ``force_vocabulary``: glob patterns. Matching classes emit as
        VocabularyFact (VOCABULARY kind) at MEDIUM strength instead of
        EntityFact.

    Default class suppressions (from ``DEFAULT_SOURCE_D_CLASS_SUPPRESSIONS``):
      Private classes (``_*``) and ``Meta`` / ``Config`` are silently
      skipped UNLESS ``include_classes`` overrides.
    """
    config = config or {}
    user_exclude: list[str] = list(config.get("exclude_classes", []) or [])
    user_include: list[str] = list(config.get("include_classes", []) or [])
    user_force_vocab: list[str] = list(config.get("force_vocabulary", []) or [])
    file = str(pm.path)
    constants = _collect_module_constants(pm)

    for cls_name, cls in pm.classes.items():
        # ── Private-class skip ────────────────────────────────────────────
        if cls_name.startswith("_") and not glob_match(cls_name, user_include):
            continue

        # ── Resolve include/exclude/default suppression status ────────────
        force_included = glob_match(cls_name, user_include)

        # Default class suppressions (Meta, Config; also _* but handled above).
        if not force_included and glob_match(cls_name, DEFAULT_SOURCE_D_CLASS_SUPPRESSIONS):
            continue

        # User exclude_classes: emit as suppressed EntityFact (not skipped)
        # so downstream audit / tests can see the suppression decision.
        class_suppressed = False
        class_suppression_reason: str | None = None
        if not force_included and glob_match(cls_name, user_exclude):
            class_suppressed = True
            for p in user_exclude:
                if glob_match(cls_name, [p]):
                    class_suppression_reason = (
                        f"Per-domain config: class '{cls_name}' matches "
                        f"exclude_classes pattern '{p}'."
                    )
                    break

        # ── Enum → VocabularyFact ─────────────────────────────────────────
        if _is_enum(cls):
            yield VocabularyFact(
                name=cls_name,
                members=_enum_members(cls),
                evidence_span=_span(cls, file, pm.source),
                extractor_family="model",
            )
            continue

        # ── Classify the class ────────────────────────────────────────────
        raw_type = _classify_class(cls)

        # include_classes overrides dto_candidate flagging: restore to base type.
        if force_included and raw_type == "dto_candidate":
            raw_type = "pydantic_model"

        # ── force_vocabulary override ─────────────────────────────────────
        if not class_suppressed and user_force_vocab and glob_match(cls_name, user_force_vocab):
            yield VocabularyFact(
                name=cls_name,
                members=[],          # class-based vocab: no Enum members
                evidence_span=_span(cls, file, pm.source),
                extractor_family="model",
            )
            # Also emit fields as AttributeFacts (v1.1 force_vocabulary contract).
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
            continue

        # ── Emit entity ───────────────────────────────────────────────────
        yield EntityFact(
            name=cls_name,
            evidence_span=_span(cls, file, pm.source),
            extractor_family="model",
            docstring=ast.get_docstring(cls),
            bases=_base_names(cls),
            raw_type=raw_type,
            suppressed=class_suppressed,
            suppression_reason=class_suppression_reason,
        )

        # Skip children when the class is user-suppressed.
        if class_suppressed:
            continue

        # ── Class fields → AttributeFact ──────────────────────────────────
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
                # Pattern A + B (multi-condition): try before single-return eligibility.
                multi = list(_extract_multi_condition_method(
                    cls_name, stmt, constants, pm.source, file,
                ))
                if multi:
                    yield from multi
                else:
                    # Single-return eligibility (v1.2).
                    elig = _extract_eligibility_method(cls_name, stmt, pm.source, file)
                    if elig is not None:
                        yield elig
                yield from _extract_transition_assigns(cls_name, stmt, pm.source, file)
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

_ELIGIBILITY_PREFIXES = ("is_", "can_", "may_", "should_", "must_")

_MULTI_ELIGIBILITY_PREFIXES = _ELIGIBILITY_PREFIXES + (
    "classify_",
    "determine_",
    "predict_",
    "decide_",
    "evaluate_",
)

_UNRESOLVED = object()

# Direct (NOT inverted) — same as procedural_extractor.
_DIRECT_CMP = {
    ast.Lt: "lt", ast.LtE: "lte", ast.Gt: "gt", ast.GtE: "gte",
    ast.Eq: "eq", ast.NotEq: "neq",
}

_TRANSITION_FIELD_NAMES = frozenset({"status", "state", "phase", "stage", "lifecycle_state"})


def _literal_value(node: ast.expr):
    if isinstance(node, ast.Constant):
        return node.value
    return None


def _collect_module_constants(pm: "ParsedModule") -> dict[str, object]:
    """Identical to procedural_extractor's helper — duplicated per v1.2
    convention. Future v1.3 may consolidate into a shared module."""
    out: dict[str, object] = {}
    for stmt in pm.tree.body:
        if not isinstance(stmt, ast.Assign):
            continue
        if len(stmt.targets) != 1:
            continue
        target = stmt.targets[0]
        if not isinstance(target, ast.Name):
            continue
        if not isinstance(stmt.value, ast.Constant):
            continue
        out[target.id] = stmt.value.value
    return out


def _resolve_constant(node: ast.expr, constants: dict[str, object]) -> object:
    """Return the constant value for an ast.Constant or for an ast.Name
    that maps to a module-level constant. Returns _UNRESOLVED for any
    other shape."""
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name) and node.id in constants:
        return constants[node.id]
    return _UNRESOLVED


def _resolve_subject(expr: ast.expr, param_names: set[str]) -> str | None:
    """Return the subject_attribute name for a valid LHS shape, else None.

    Accepts:
      - <param>.<attr>        -> returns <attr>
      - <param>["<key>"]      -> returns <key>
      - bare <param>          -> returns <param>

    Rejects everything else, including chained attribute access,
    method calls, module-level constants, and subscripts on non-param
    receivers. The receiver must be a direct ast.Name in param_names.
    """
    if isinstance(expr, ast.Attribute):
        if isinstance(expr.value, ast.Name) and expr.value.id in param_names:
            return expr.attr
        return None
    if isinstance(expr, ast.Subscript):
        if not isinstance(expr.value, ast.Name) or expr.value.id not in param_names:
            return None
        slice_node = expr.slice
        if isinstance(slice_node, ast.Constant) and isinstance(slice_node.value, str):
            return slice_node.value
        return None
    if isinstance(expr, ast.Name):
        if expr.id in param_names:
            return expr.id
        return None
    return None


def _extract_eligibility_method(cls_name: str, method: ast.FunctionDef, source: str, file: str) -> "RuleFact | None":
    """Detect ``def is_*/can_*/may_*/should_*/must_*(self, ...): return <Compare>``
    inside a class. The Compare's LHS may be ``self.<attr>``, a subscript
    ``<param>["<field>"]``, or a bare param name (last param) — the latter
    only if the method is bound via @field_validator (rare for eligibility
    but symmetric with Task 9's discipline)."""
    if not method.name.startswith(_ELIGIBILITY_PREFIXES):
        return None
    if not method.body:
        return None
    last = method.body[-1]
    if not isinstance(last, ast.Return) or not isinstance(last.value, ast.Compare):
        return None
    cmp = last.value
    if len(cmp.ops) != 1:
        return None
    op = type(cmp.ops[0])
    if op not in _DIRECT_CMP:
        return None
    rhs = cmp.comparators[0]
    if not isinstance(rhs, ast.Constant):
        return None
    lhs = cmp.left
    attr: str | None = None
    param_names = {a.arg for a in method.args.args}
    if isinstance(lhs, ast.Attribute) and isinstance(lhs.value, ast.Name) and lhs.value.id == "self":
        attr = lhs.attr
    elif (
        isinstance(lhs, ast.Subscript)
        and isinstance(lhs.slice, ast.Constant)
        and isinstance(lhs.slice.value, str)
        and isinstance(lhs.value, ast.Name)
        and lhs.value.id in param_names
    ):
        attr = lhs.slice.value
    if attr is None:
        return None
    return RuleFact(
        rule_kind="eligibility",
        subject_entity=cls_name,
        subject_attribute=attr,
        predicate=_DIRECT_CMP[op],
        object_value=rhs.value,
        expression=ast.unparse(cmp),
        evidence_span=_span(method, file, source),
        code_context=f"class {cls_name}, def {method.name}",
        confidence=0.85,
        extractor_family="model",
    )


def _extract_multi_condition_method(
    cls_name: str,
    method: ast.FunctionDef,
    constants: dict[str, object],
    source: str,
    file: str,
) -> Iterable[RuleFact]:
    """Class-method analogue of procedural_extractor._extract_multi_condition_returns.

    subject_entity is set to cls_name (anchored). Otherwise identical
    pattern matching and polarity logic.

    Subject discipline — `self` is INCLUDED in param_names so that
    `self.<attr>` is a valid LHS. This is the canonical anchored
    subject form for class methods and matches v1.2's existing
    _extract_eligibility_method contract.
    Bare-param subjects on other method parameters also work.
    """
    if not method.name.startswith(_MULTI_ELIGIBILITY_PREFIXES):
        return
    if not method.body:
        return
    last = method.body[-1]
    if not isinstance(last, ast.Return) or not isinstance(last.value, ast.Constant):
        return
    if last.value.value is True:
        target_return = False
    elif last.value.value is False:
        target_return = True
    else:
        return

    # INCLUDE `self` in param_names so `self.<attr>` resolves as a
    # valid LHS — this is the canonical anchored subject form for
    # class methods and matches v1.2's _extract_eligibility_method.
    # Other method parameters work the same way as procedural.
    param_names = {a.arg for a in method.args.args}

    for stmt in method.body:  # TOP-LEVEL ONLY — no ast.walk()
        if not isinstance(stmt, ast.If):
            continue
        if len(stmt.body) != 1:
            continue
        inner = stmt.body[0]
        if not isinstance(inner, ast.Return):
            continue
        if not isinstance(inner.value, ast.Constant) or inner.value.value is not target_return:
            continue

        rule = _multi_condition_rule_from_test_method(
            stmt.test, target_return, cls_name, param_names, constants,
            stmt, method, source, file,
        )
        if rule is not None:
            yield rule


def _multi_condition_rule_from_test_method(
    test: ast.expr,
    target_return: bool,
    cls_name: str,
    param_names: set[str],
    constants: dict[str, object],
    if_node: ast.If,
    method: ast.FunctionDef,
    source: str,
    file: str,
) -> "RuleFact | None":
    """Per-condition rule builder for class methods. subject_entity is
    cls_name (anchored). Otherwise mirrors the procedural builder."""
    negated = False
    raw = test
    if isinstance(raw, ast.UnaryOp) and isinstance(raw.op, ast.Not):
        negated = True
        raw = raw.operand

    if not isinstance(raw, ast.Compare):
        subject = _resolve_subject(raw, param_names)
        if subject is None:
            return None
        if target_return is False:
            object_value = True if negated else False
        else:
            object_value = False if negated else True
        return RuleFact(
            rule_kind="eligibility",
            subject_entity=cls_name,
            subject_attribute=subject,
            predicate="required",
            object_value=object_value,
            expression=ast.unparse(test),
            evidence_span=_span(if_node, file, source),
            code_context=f"class {cls_name}, def {method.name}",
            confidence=0.75,
            extractor_family="model",
        )

    if negated:
        return None
    if len(raw.ops) != 1:
        return None
    op_type = type(raw.ops[0])
    subject = _resolve_subject(raw.left, param_names)
    if subject is None:
        return None
    rhs_value = _resolve_constant(raw.comparators[0], constants)
    if rhs_value is _UNRESOLVED:
        return None
    if target_return is False:
        if op_type not in _CMP_INVERSE:
            return None
        predicate = _CMP_INVERSE[op_type]
    else:
        if op_type not in _DIRECT_CMP:
            return None
        predicate = _DIRECT_CMP[op_type]
    return RuleFact(
        rule_kind="eligibility",
        subject_entity=cls_name,
        subject_attribute=subject,
        predicate=predicate,
        object_value=rhs_value,
        expression=ast.unparse(test),
        evidence_span=_span(if_node, file, source),
        code_context=f"class {cls_name}, def {method.name}",
        confidence=0.75,
        extractor_family="model",
    )


def _extract_transition_assigns(cls_name: str, method: ast.FunctionDef, source: str, file: str):
    """Yield RuleFacts for `if <guard>: self.<status_field> = <literal>`
    patterns inside ``method``. <status_field> must match a status-like
    name (status / state / phase / stage / lifecycle_state)."""
    for node in ast.walk(method):
        if not (isinstance(node, ast.If) and node.body):
            continue
        for stmt in node.body:
            if not isinstance(stmt, ast.Assign) or len(stmt.targets) != 1:
                continue
            tgt = stmt.targets[0]
            # Target: self.<field>
            if not (
                isinstance(tgt, ast.Attribute)
                and isinstance(tgt.value, ast.Name)
                and tgt.value.id == "self"
                and tgt.attr in _TRANSITION_FIELD_NAMES
            ):
                continue
            if not isinstance(stmt.value, ast.Constant):
                continue
            yield RuleFact(
                rule_kind="transition",
                subject_entity=cls_name,
                subject_attribute=tgt.attr,
                predicate="transitions_to",
                object_value=stmt.value.value,
                condition=ast.unparse(node.test),
                expression=ast.unparse(stmt),
                evidence_span=_span(node, file, source),
                code_context=f"class {cls_name}, def {method.name}",
                confidence=0.85,
                extractor_family="model",
            )


def _decorator_field_name(deco: ast.expr) -> str | None:
    if isinstance(deco, ast.Call) and isinstance(deco.func, ast.Name) and deco.func.id == "field_validator":
        if deco.args and isinstance(deco.args[0], ast.Constant):
            return deco.args[0].value
    return None


def _extract_inline_rules(cls_name: str, method: ast.FunctionDef, source: str, file: str):
    """Yield RuleFacts for `if <cond>: raise` patterns inside ``method``.

    Subject-attribute resolution depends on context:
      - ``self.attr`` is always accepted (any method).
      - A bare ``ast.Name`` is accepted only when:
          * it matches a Pydantic ``@field_validator("...")``-bound
            param (rebound via ``arg_to_attr``), OR
          * the method is ``__init__`` (convention: param name doubles
            as attribute name).
      - Any other LHS shape is skipped — a bare name in a regular
        method is almost always a local temporary and would produce
        a false-positive ontology rule.
    """
    bound: str | None = None
    for deco in method.decorator_list:
        bound = _decorator_field_name(deco)
        if bound:
            break

    arg_to_attr: dict[str, str] = {}
    if bound and method.args.args:
        param_name = method.args.args[-1].arg
        arg_to_attr[param_name] = bound

    is_init = method.name == "__init__"

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

        # Resolve subject_attribute based on LHS shape and context.
        attr: str | None = None
        if isinstance(lhs, ast.Attribute) and isinstance(lhs.value, ast.Name) and lhs.value.id == "self":
            attr = lhs.attr
        elif isinstance(lhs, ast.Name):
            name = lhs.id
            if name in arg_to_attr:
                attr = arg_to_attr[name]
            elif is_init:
                attr = name
            # else: bare name in a regular method — skip.
        if attr is None:
            continue

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
