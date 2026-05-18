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

        # Tasks 7-9 will add columns, FKs, code-table detection, suppression.
        # Task 6 just emits the entity.
        yield IntermediateCandidate(
            label=table_name,
            definition="",  # no COMMENT-on-TABLE handling in v1.1
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
