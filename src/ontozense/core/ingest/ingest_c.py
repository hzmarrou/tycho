"""Source C ingester — extracts candidates from SQL DDL files.

Uses sqlglot to parse DDL. Tables become ``entity`` candidates;
columns and FKs are added in subsequent tasks. Default strength for a
schema-attested entity is ``STRONG`` because a database constraint is
the highest-fidelity attestation a concept can have.

This module is purely deterministic — no LLM calls. See the design
spec §3.3 for the determinism property.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Iterable

import sqlglot
from sqlglot import expressions as exp

from .base import (
    ArtifactKind,
    IngestionPolicy,
    IntermediateCandidate,
    Strength,
)

logger = logging.getLogger(__name__)


class SourceCIngester(IngestionPolicy):
    """Ingester for Source C — SQL DDL files via sqlglot.

    Task 6 scaffold: only CREATE TABLE statements are recognised,
    each yielding one entity candidate. Tasks 7-9 add columns, FKs,
    code-table detection, and noise filters.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}

    def ingest(self, raw_input: Any) -> Iterable[IntermediateCandidate]:
        if not isinstance(raw_input, dict):
            return
        for path_str in raw_input.get("files", []) or []:
            path = Path(path_str)
            if path.suffix.lower() != ".sql":
                continue
            try:
                statements = sqlglot.parse(
                    path.read_text(encoding="utf-8", errors="replace")
                )
            except Exception as exc:  # sqlglot.errors.ParseError is too narrow
                logger.warning(
                    "Source C: could not parse %s (%s); skipping.",
                    path, exc,
                )
                continue

            for stmt in statements or []:
                if not isinstance(stmt, exp.Create):
                    continue
                if (stmt.args.get("kind") or "").upper() != "TABLE":
                    continue
                yield from self._yield_for_table(stmt, path)

    # ─── Per-table emission ────────────────────────────────────────────────

    def _yield_for_table(
        self, stmt: exp.Create, source_path: Path,
    ) -> Iterable[IntermediateCandidate]:
        table_name = self._table_name(stmt)
        if not table_name:
            return

        columns = self._extract_columns(stmt)
        foreign_keys = self._extract_foreign_keys(stmt, table_name)

        # Identify PK column(s) for demotion.
        pk_columns = self._extract_pk_columns(stmt)

        # Entity for the table itself.
        yield IntermediateCandidate(
            label=table_name,
            definition="",
            source_type="C",
            source_artifact=str(source_path),
            raw_type="table",
            eid="",
            artifact_kind=ArtifactKind.ENTITY,
            strength=Strength.STRONG,
            promotion_reason=(
                f"Source C: table '{table_name}' "
                f"(deterministic schema attestation)."
            ),
            suppression_reason=None,
            suppressed=False,
        )

        # Attributes for non-PK, non-FK columns.
        fk_column_names = {fk["column"] for fk in foreign_keys}
        for col_name, col_type in columns:
            if col_name in pk_columns:
                continue  # PK demoted to identifier-of-parent
            if col_name in fk_column_names:
                continue  # FK columns handled via relationship below
            yield IntermediateCandidate(
                label=col_name,
                definition="",
                source_type="C",
                source_artifact=f"{source_path}#{table_name}.{col_name}",
                raw_type=col_type,
                eid="",
                artifact_kind=ArtifactKind.ATTRIBUTE,
                strength=Strength.STRONG,
                promotion_reason=(
                    f"Source C: column '{table_name}.{col_name}' "
                    f"(type {col_type})."
                ),
                suppression_reason=None,
                suppressed=False,
            )

        # Relationships for foreign keys.
        for fk in foreign_keys:
            yield IntermediateCandidate(
                label=f"{table_name}__{fk['column']}__{fk['ref_table']}",
                definition=(
                    f"Foreign key: {table_name}.{fk['column']} -> "
                    f"{fk['ref_table']}.{fk['ref_column']}"
                ),
                source_type="C",
                source_artifact=f"{source_path}#{table_name}.{fk['column']}",
                raw_type="foreign_key",
                eid="",
                artifact_kind=ArtifactKind.RELATIONSHIP,
                strength=Strength.MEDIUM,
                promotion_reason=(
                    f"Source C: FK from {table_name}.{fk['column']} to "
                    f"{fk['ref_table']}.{fk['ref_column']}."
                ),
                suppression_reason=None,
                suppressed=False,
            )

    @staticmethod
    def _table_name(stmt: exp.Create) -> str:
        this = stmt.this  # usually exp.Schema with the table inside
        if isinstance(this, exp.Schema):
            table = this.this
            if isinstance(table, exp.Table):
                return table.name
        if isinstance(this, exp.Table):
            return this.name
        return ""

    # ─── DDL parsing helpers ───────────────────────────────────────────────

    @staticmethod
    def _extract_columns(stmt: exp.Create) -> list[tuple[str, str]]:
        """Return list of (col_name, col_type) for table columns."""
        out: list[tuple[str, str]] = []
        this = stmt.this
        if not isinstance(this, exp.Schema):
            return out
        for expression in this.expressions or []:
            if isinstance(expression, exp.ColumnDef):
                col_name = expression.name
                kind = expression.args.get("kind")
                col_type = kind.sql().lower() if kind else ""
                out.append((col_name, col_type))
        return out

    @staticmethod
    def _extract_pk_columns(stmt: exp.Create) -> set[str]:
        """Return set of column names that are PRIMARY KEY (inline or
        out-of-line)."""
        pk: set[str] = set()
        this = stmt.this
        if not isinstance(this, exp.Schema):
            return pk

        for expression in this.expressions or []:
            # Inline PK on a column.
            if isinstance(expression, exp.ColumnDef):
                for constraint in expression.args.get("constraints") or []:
                    kind = constraint.args.get("kind")
                    if isinstance(kind, exp.PrimaryKeyColumnConstraint):
                        pk.add(expression.name)
            # Out-of-line PRIMARY KEY (col1, col2)
            if isinstance(expression, exp.PrimaryKey):
                for col in expression.expressions or []:
                    pk.add(col.name)
        return pk

    @staticmethod
    def _extract_foreign_keys(
        stmt: exp.Create, table_name: str,
    ) -> list[dict[str, str]]:
        """Return list of {column, ref_table, ref_column} for FK constraints."""
        out: list[dict[str, str]] = []
        this = stmt.this
        if not isinstance(this, exp.Schema):
            return out

        for expression in this.expressions or []:
            if isinstance(expression, exp.ForeignKey):
                # FOREIGN KEY (col) REFERENCES ref_table(ref_col)
                # In sqlglot 30.7.0 FK expressions contains Identifier nodes.
                fk_columns = [c.name for c in expression.expressions or []]
                ref = expression.args.get("reference")
                if not ref or not fk_columns:
                    continue
                ref_table = ""
                ref_column = ""
                ref_this = getattr(ref, "this", None)
                if isinstance(ref_this, exp.Schema):
                    inner_table = ref_this.this
                    if isinstance(inner_table, exp.Table):
                        ref_table = inner_table.name
                    # ref column identifiers live in ref_this.expressions
                    ref_cols = [c.name for c in ref_this.expressions or []]
                    if ref_cols:
                        ref_column = ref_cols[0]
                elif isinstance(ref_this, exp.Table):
                    ref_table = ref_this.name
                if ref_table:
                    out.append({
                        "column": fk_columns[0],
                        "ref_table": ref_table,
                        "ref_column": ref_column or "",
                    })
        return out
