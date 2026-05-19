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
