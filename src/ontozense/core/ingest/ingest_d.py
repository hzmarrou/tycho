"""Source D ingester — extracts candidates from Python source files.

Pure AST-based; no LLM calls. The existing
``code_extractor.py`` provides a more elaborate pattern (deterministic
parse + LLM labelling), but its LLM step is marked future work in
its own docstring. This v1.1 ingester uses only the deterministic
AST output, classifying via Python-native shapes (class, dataclass,
Enum, etc.).

Task 10 scaffold: classes / dataclasses / Pydantic BaseModel /
SQLAlchemy-style models emit as ENTITY at STRONG strength. Private
classes (``_*``) are suppressed by default. Tasks 11-13 add fields,
Enum, methods, rules, DTO flag, and full noise filters.

See the design spec §3.3, §7 for the determinism property and the
artifact taxonomy.
"""

from __future__ import annotations

import ast
import logging
from pathlib import Path
from typing import Any, Iterable

from .base import (
    ArtifactKind,
    IngestionPolicy,
    IntermediateCandidate,
    Strength,
)
from .filters import (
    DEFAULT_SOURCE_D_CLASS_SUPPRESSIONS,
    glob_match,
)

logger = logging.getLogger(__name__)


# Class-base names that mark a class as a Pydantic/SQLAlchemy/dataclass-style model.
ENTITY_BASE_NAMES: set[str] = {
    "BaseModel",          # Pydantic
    "Base",               # SQLAlchemy declarative_base()
    "Document",           # Mongo / Beanie
}


class SourceDIngester(IngestionPolicy):
    """Ingester for Source D — Python AST."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}

    def ingest(self, raw_input: Any) -> Iterable[IntermediateCandidate]:
        if not isinstance(raw_input, dict):
            return
        for path_str in raw_input.get("files", []) or []:
            path = Path(path_str)
            if path.suffix.lower() != ".py":
                continue
            try:
                tree = ast.parse(
                    path.read_text(encoding="utf-8", errors="replace")
                )
            except SyntaxError as exc:
                logger.warning(
                    "Source D: could not parse %s (%s); skipping.",
                    path, exc,
                )
                continue
            yield from self._yield_for_module(tree, path)

    def _yield_for_module(
        self, tree: ast.Module, source_path: Path,
    ) -> Iterable[IntermediateCandidate]:
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            if glob_match(node.name, DEFAULT_SOURCE_D_CLASS_SUPPRESSIONS):
                continue

            raw_type = self._classify_class_node(node)
            if raw_type is None:
                continue

            if raw_type == "enum":
                yield IntermediateCandidate(
                    label=node.name,
                    definition=ast.get_docstring(node) or "",
                    source_type="D",
                    source_artifact=f"{source_path}:{node.lineno}",
                    raw_type="enum",
                    eid="",
                    artifact_kind=ArtifactKind.VOCABULARY,
                    strength=Strength.MEDIUM,
                    promotion_reason=(
                        f"Source D: Enum subclass '{node.name}' "
                        f"({source_path.name}:{node.lineno})."
                    ),
                    suppression_reason=None,
                    suppressed=False,
                )
                continue  # don't extract Enum members as attributes

            # Entity classes: emit entity then annotated fields as attributes.
            yield IntermediateCandidate(
                label=node.name,
                definition=ast.get_docstring(node) or "",
                source_type="D",
                source_artifact=f"{source_path}:{node.lineno}",
                raw_type=raw_type,
                eid="",
                artifact_kind=ArtifactKind.ENTITY,
                strength=Strength.STRONG,
                promotion_reason=(
                    f"Source D: {raw_type} '{node.name}' "
                    f"({source_path.name}:{node.lineno})."
                ),
                suppression_reason=None,
                suppressed=False,
            )

            for stmt in node.body:
                if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                    field_name = stmt.target.id
                    type_annotation = self._render_annotation(stmt.annotation)
                    yield IntermediateCandidate(
                        label=field_name,
                        definition="",
                        source_type="D",
                        source_artifact=(
                            f"{source_path}:{node.name}.{field_name}:{stmt.lineno}"
                        ),
                        raw_type=type_annotation,
                        eid="",
                        artifact_kind=ArtifactKind.ATTRIBUTE,
                        strength=Strength.STRONG,
                        promotion_reason=(
                            f"Source D: field '{node.name}.{field_name}' "
                            f"(type {type_annotation})."
                        ),
                        suppression_reason=None,
                        suppressed=False,
                    )

            # Methods on entity classes -> BEHAVIOR (private methods skipped).
            for stmt in node.body:
                if isinstance(stmt, ast.FunctionDef) and not stmt.name.startswith("_"):
                    yield IntermediateCandidate(
                        label=f"{node.name}.{stmt.name}",
                        definition=ast.get_docstring(stmt) or "",
                        source_type="D",
                        source_artifact=(
                            f"{source_path}:{node.name}.{stmt.name}:{stmt.lineno}"
                        ),
                        raw_type="method",
                        eid="",
                        artifact_kind=ArtifactKind.BEHAVIOR,
                        strength=Strength.WEAK,
                        promotion_reason=(
                            f"Source D: method '{node.name}.{stmt.name}' "
                            f"({source_path.name}:{stmt.lineno})."
                        ),
                        suppression_reason=None,
                        suppressed=False,
                    )

        # Module-level functions: look for validate_*/check_*/assert_* -> RULE.
        for node in tree.body:
            if isinstance(node, ast.FunctionDef):
                if (node.name.startswith("validate_")
                        or node.name.startswith("check_")
                        or node.name.startswith("assert_")):
                    yield IntermediateCandidate(
                        label=node.name,
                        definition=ast.get_docstring(node) or "",
                        source_type="D",
                        source_artifact=f"{source_path}:{node.lineno}",
                        raw_type="validation_function",
                        eid="",
                        artifact_kind=ArtifactKind.RULE,
                        strength=Strength.WEAK,
                        promotion_reason=(
                            f"Source D: validation function "
                            f"'{node.name}' ({source_path.name}:{node.lineno})."
                        ),
                        suppression_reason=None,
                        suppressed=False,
                    )

    @staticmethod
    def _classify_class_node(node: ast.ClassDef) -> str | None:
        """Return a raw_type string for entity-flavoured classes, or
        None when the class doesn't look like a domain entity.

        Order of checks:
          1. Enum subclass (Enum / IntEnum / StrEnum / Flag / IntFlag) -> 'enum'
          2. @dataclass decorator -> 'dataclass'
          3. Pydantic BaseModel base -> 'pydantic_model'
          4. SQLAlchemy / known entity base -> 'sqlalchemy_model'
          5. Plain class with at least one annotated attribute -> 'class'
          6. Otherwise None.
        """
        # Enum detection (base must be Enum or a known Enum subclass name).
        for base in node.bases:
            base_name = (
                base.id if isinstance(base, ast.Name)
                else base.attr if isinstance(base, ast.Attribute)
                else None
            )
            if base_name in ("Enum", "IntEnum", "StrEnum", "Flag", "IntFlag"):
                return "enum"

        has_dataclass_decorator = any(
            (isinstance(d, ast.Name) and d.id == "dataclass") or
            (isinstance(d, ast.Call) and isinstance(d.func, ast.Name)
                and d.func.id == "dataclass")
            for d in node.decorator_list
        )
        if has_dataclass_decorator:
            return "dataclass"

        for base in node.bases:
            base_name = (
                base.id if isinstance(base, ast.Name)
                else base.attr if isinstance(base, ast.Attribute)
                else None
            )
            if base_name == "BaseModel":
                return "pydantic_model"
            if base_name in ENTITY_BASE_NAMES:
                return "sqlalchemy_model"

        has_annotated_attr = any(
            isinstance(stmt, ast.AnnAssign)
            for stmt in node.body
        )
        if has_annotated_attr:
            return "class"

        return None

    @staticmethod
    def _render_annotation(node: ast.expr) -> str:
        """Render a type annotation AST node back to a string."""
        try:
            return ast.unparse(node)
        except Exception:
            return ""
