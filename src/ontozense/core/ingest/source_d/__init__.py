"""Source D v1.2 — shape-adaptive executable rule extractor.

Six-stage pipeline: parse -> dispatch -> lift to IR -> anchor/filter -> emit -> optional LLM normalize.
See docs/superpowers/specs/2026-05-19-source-d-v1.2-executable-rule-extraction-design.md.

``run()`` is the public entry point used by SourceDIngester (Task 15).
It produces v1.1-compatible IntermediateCandidate output so that all 23
AC6 parity tests continue to pass.
"""
from __future__ import annotations

import ast
from collections.abc import Iterable
from pathlib import Path

from ontozense.core.ingest.base import ArtifactKind, IntermediateCandidate, Strength
from ontozense.core.ingest.filters import (
    DEFAULT_SOURCE_D_CLASS_SUPPRESSIONS,
    glob_match,
)

from .model_extractor import _classify_class, _is_enum
from .parse import ParsedModule, parse_module


# DTO suffix → raw_type mapping (mirrors v1.1 SourceDIngester.DTO_SUFFIXES).
# Only applied to pydantic_model classes unless include_classes overrides.
_DTO_SUFFIXES: tuple[str, ...] = (
    "DTO", "Request", "Response", "Schema", "Model",
)


def _render_annotation(node: ast.expr) -> str:
    try:
        return ast.unparse(node)
    except Exception:
        return ""


def run(path: Path, config: dict | None = None) -> Iterable[IntermediateCandidate]:
    """Run the Source D pipeline against a single Python file and yield
    v1.1-compatible IntermediateCandidate objects.

    This is the entry point wired by SourceDIngester (Task 15).
    Path-level suppression and generated-marker checks are performed by
    SourceDIngester.ingest() BEFORE calling this function.

    SyntaxError (unparseable Python) is caught and the file is silently
    skipped, preserving the v1.1 SourceDIngester test_unparseable_python_skipped
    behavior.
    """
    config = config or {}
    try:
        pm = parse_module(path)
    except SyntaxError:
        return

    yield from _yield_model_candidates(pm, config)
    yield from _yield_procedural_candidates(pm, path)


def _yield_model_candidates(
    pm: ParsedModule, config: dict
) -> Iterable[IntermediateCandidate]:
    """Emit v1.1-compatible candidates for class definitions."""
    user_exclude_classes: list[str] = list(config.get("exclude_classes", []) or [])
    user_include_classes: list[str] = list(config.get("include_classes", []) or [])
    user_force_vocabulary: list[str] = list(config.get("force_vocabulary", []) or [])
    source_path = pm.path

    for cls_name, cls in pm.classes.items():
        # ── Default class suppressions (includes private _* and Meta/Config) ──
        if glob_match(cls_name, DEFAULT_SOURCE_D_CLASS_SUPPRESSIONS):
            continue

        # ── User exclude_classes suppression ──────────────────────────────
        class_suppressed = False
        class_suppression_reason: str | None = None
        if glob_match(cls_name, user_exclude_classes):
            class_suppressed = True
            for p in user_exclude_classes:
                if glob_match(cls_name, [p]):
                    class_suppression_reason = (
                        f"Per-domain config: class '{cls_name}' matches "
                        f"exclude_classes pattern '{p}'."
                    )
                    break

        # ── Enum → VocabularyFact ─────────────────────────────────────────
        if _is_enum(cls):
            yield IntermediateCandidate(
                label=cls_name,
                definition=ast.get_docstring(cls) or "",
                source_type="D",
                source_artifact=f"{source_path}:{cls.lineno}",
                raw_type="enum",
                eid="",
                artifact_kind=ArtifactKind.VOCABULARY,
                strength=Strength.MEDIUM,
                promotion_reason=(
                    f"Source D: Enum subclass '{cls_name}' "
                    f"({source_path.name}:{cls.lineno})."
                ),
                suppression_reason=class_suppression_reason,
                suppressed=class_suppressed,
            )
            continue

        # ── Classify the class ────────────────────────────────────────────
        # _classify_class returns 'dataclass' | 'pydantic_model' |
        # 'sqlalchemy_model' | 'class'. For v1.1 parity, a class that has
        # no annotated attrs and only methods returns 'class' from _classify_class
        # but we need to return None (skip) to preserve the v1.1 logic where
        # unrecognised shapes are skipped unless suppressed.
        raw_type = _classify_class_v11(cls)
        if raw_type is None:
            # Unrecognised shape: emit suppressed marker only if user suppressed.
            if class_suppressed:
                yield IntermediateCandidate(
                    label=cls_name,
                    definition=ast.get_docstring(cls) or "",
                    source_type="D",
                    source_artifact=f"{source_path}:{cls.lineno}",
                    raw_type="class",
                    eid="",
                    artifact_kind=ArtifactKind.ENTITY,
                    strength=Strength.STRONG,
                    promotion_reason="",
                    suppression_reason=class_suppression_reason,
                    suppressed=True,
                )
            continue

        class_is_force_included = glob_match(cls_name, user_include_classes)

        # ── DTO flagging (pydantic_model + DTO suffix, not force-included) ─
        emitted_raw_type = raw_type
        if (
            raw_type == "pydantic_model"
            and any(cls_name.endswith(s) for s in _DTO_SUFFIXES)
            and not class_is_force_included
        ):
            emitted_raw_type = "dto_candidate"

        # ── force_vocabulary override ──────────────────────────────────────
        if user_force_vocabulary and glob_match(cls_name, user_force_vocabulary):
            matched_pattern = next(
                p for p in user_force_vocabulary if glob_match(cls_name, [p])
            )
            yield IntermediateCandidate(
                label=cls_name,
                definition=ast.get_docstring(cls) or "",
                source_type="D",
                source_artifact=f"{source_path}:{cls.lineno}",
                raw_type=emitted_raw_type,
                eid="",
                artifact_kind=ArtifactKind.VOCABULARY,
                strength=Strength.MEDIUM,
                promotion_reason=(
                    f"Source D: {emitted_raw_type} '{cls_name}' "
                    f"reclassified to vocabulary by force_vocabulary "
                    f"pattern '{matched_pattern}' "
                    f"({source_path.name}:{cls.lineno})."
                ),
                suppression_reason=class_suppression_reason,
                suppressed=class_suppressed,
            )
            if class_suppressed:
                continue
            # Emit fields for the force-vocabulary class.
            for stmt in cls.body:
                if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                    field_name = stmt.target.id
                    type_annotation = _render_annotation(stmt.annotation)
                    yield IntermediateCandidate(
                        label=field_name,
                        definition="",
                        source_type="D",
                        source_artifact=(
                            f"{source_path}:{cls_name}.{field_name}:{stmt.lineno}"
                        ),
                        raw_type=type_annotation,
                        eid="",
                        artifact_kind=ArtifactKind.ATTRIBUTE,
                        strength=Strength.STRONG,
                        promotion_reason=(
                            f"Source D: field '{cls_name}.{field_name}' "
                            f"(type {type_annotation})."
                        ),
                        suppression_reason=None,
                        suppressed=False,
                    )
            continue

        # ── Emit entity ───────────────────────────────────────────────────
        yield IntermediateCandidate(
            label=cls_name,
            definition=ast.get_docstring(cls) or "",
            source_type="D",
            source_artifact=f"{source_path}:{cls.lineno}",
            raw_type=emitted_raw_type,
            eid="",
            artifact_kind=ArtifactKind.ENTITY,
            strength=Strength.STRONG,
            promotion_reason=(
                f"Source D: {emitted_raw_type} '{cls_name}' "
                f"({source_path.name}:{cls.lineno})."
            ),
            suppression_reason=class_suppression_reason,
            suppressed=class_suppressed,
        )

        # If class is suppressed, skip fields and methods.
        if class_suppressed:
            continue

        # ── Class fields → ATTRIBUTE ──────────────────────────────────────
        for stmt in cls.body:
            if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                field_name = stmt.target.id
                type_annotation = _render_annotation(stmt.annotation)
                yield IntermediateCandidate(
                    label=field_name,
                    definition="",
                    source_type="D",
                    source_artifact=(
                        f"{source_path}:{cls_name}.{field_name}:{stmt.lineno}"
                    ),
                    raw_type=type_annotation,
                    eid="",
                    artifact_kind=ArtifactKind.ATTRIBUTE,
                    strength=Strength.STRONG,
                    promotion_reason=(
                        f"Source D: field '{cls_name}.{field_name}' "
                        f"(type {type_annotation})."
                    ),
                    suppression_reason=None,
                    suppressed=False,
                )

        # ── Class methods → BEHAVIOR ──────────────────────────────────────
        for stmt in cls.body:
            if isinstance(stmt, ast.FunctionDef) and not stmt.name.startswith("_"):
                yield IntermediateCandidate(
                    label=f"{cls_name}.{stmt.name}",
                    definition=ast.get_docstring(stmt) or "",
                    source_type="D",
                    source_artifact=(
                        f"{source_path}:{cls_name}.{stmt.name}:{stmt.lineno}"
                    ),
                    raw_type="method",
                    eid="",
                    artifact_kind=ArtifactKind.BEHAVIOR,
                    strength=Strength.WEAK,
                    promotion_reason=(
                        f"Source D: method '{cls_name}.{stmt.name}' "
                        f"({source_path.name}:{stmt.lineno})."
                    ),
                    suppression_reason=None,
                    suppressed=False,
                )


def _yield_procedural_candidates(
    pm: ParsedModule, path: Path
) -> Iterable[IntermediateCandidate]:
    """Emit v1.1-compatible RULE candidates for module-level validate_*/check_*/assert_* functions."""
    source_path = path
    for func_name, func in pm.functions.items():
        if (
            func_name.startswith("validate_")
            or func_name.startswith("check_")
            or func_name.startswith("assert_")
        ):
            yield IntermediateCandidate(
                label=func_name,
                definition=ast.get_docstring(func) or "",
                source_type="D",
                source_artifact=f"{source_path}:{func.lineno}",
                raw_type="validation_function",
                eid="",
                artifact_kind=ArtifactKind.RULE,
                strength=Strength.WEAK,
                promotion_reason=(
                    f"Source D: validation function "
                    f"'{func_name}' ({source_path.name}:{func.lineno})."
                ),
                suppression_reason=None,
                suppressed=False,
            )


def _classify_class_v11(cls: ast.ClassDef) -> str | None:
    """Return a v1.1-compatible raw_type for a class, or None if unrecognised.

    Mirrors v1.1 SourceDIngester._classify_class_node exactly:
      1. Enum subclass → handled separately (caller checks _is_enum first)
      2. @dataclass decorator → 'dataclass'
      3. Pydantic BaseModel base → 'pydantic_model'
      4. SQLAlchemy / entity base → 'sqlalchemy_model'
      5. Plain class with ≥1 annotated attribute → 'class'
      6. Otherwise → None (unrecognised shape)
    """
    _ENTITY_BASE_NAMES: set[str] = {"BaseModel", "Base", "Document"}

    has_dataclass_decorator = any(
        (isinstance(d, ast.Name) and d.id == "dataclass") or
        (isinstance(d, ast.Call) and isinstance(d.func, ast.Name) and d.func.id == "dataclass")
        for d in cls.decorator_list
    )
    if has_dataclass_decorator:
        return "dataclass"

    for base in cls.bases:
        base_name = (
            base.id if isinstance(base, ast.Name)
            else base.attr if isinstance(base, ast.Attribute)
            else None
        )
        if base_name == "BaseModel":
            return "pydantic_model"
        if base_name in _ENTITY_BASE_NAMES:
            return "sqlalchemy_model"

    has_annotated_attr = any(
        isinstance(stmt, ast.AnnAssign) for stmt in cls.body
    )
    if has_annotated_attr:
        return "class"

    return None
