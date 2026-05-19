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
from .source_d.rule_payload import canonical_rule_label

logger = logging.getLogger(__name__)


_SIMPLE_OP_MAP: dict[type, str] = {
    exp.GT: "gt",
    exp.GTE: "gte",
    exp.LT: "lt",
    exp.LTE: "lte",
    exp.EQ: "eq",
    exp.NEQ: "neq",
}


def _try_extract_simple_check(
    check_expr: exp.Expression, table_name: str, source_path: Path
) -> tuple[dict | None, str | None]:
    """Return (rule_payload, None) for a simple <col> <op> <literal> CHECK.
    Return (None, suppression_reason) for any non-trivial CHECK.
    """
    op_type = type(check_expr)
    if op_type not in _SIMPLE_OP_MAP:
        return None, "non_trivial_check_constraint:unsupported_operator"
    left, right = check_expr.this, check_expr.expression
    if not isinstance(left, exp.Column):
        return None, "non_trivial_check_constraint:non_column_lhs"
    if not isinstance(right, exp.Literal):
        return None, "non_trivial_check_constraint:non_literal_rhs"
    col_name = left.name
    raw = right.this
    try:
        value = int(raw) if right.is_int else float(raw)
    except (TypeError, ValueError):
        value = raw
    payload = {
        "rule_kind": "validation",
        "subject_entity": table_name,
        "subject_attribute": col_name,
        "predicate": _SIMPLE_OP_MAP[op_type],
        "object_value": value,
        "condition": None,
        "depends_on": [],
        "expression": check_expr.sql(),
        # sqlglot does not surface per-token line numbers reliably;
        # the file-level provenance is in source_artifact.
        "evidence_span": {
            "file": str(source_path),
            "start_line": 0,
            "end_line": 0,
            "snippet": check_expr.sql(),
        },
        "code_context": f"CREATE TABLE {table_name}",
        "confidence": 1.0,
        "extractor_family": "source_c_ddl",
        "normalization_status": "deterministic",
    }
    return payload, None


def _build_required_rule_payload(
    table_name: str, column_name: str, source_path: Path
) -> dict:
    return {
        "rule_kind": "validation",
        "subject_entity": table_name,
        "subject_attribute": column_name,
        "predicate": "required",
        "object_value": True,
        "condition": None,
        "depends_on": [],
        "expression": f"{column_name} IS NOT NULL",
        # sqlglot does not surface per-column line numbers reliably;
        # the file-level provenance is in source_artifact.
        "evidence_span": {
            "file": str(source_path),
            "start_line": 0,
            "end_line": 0,
            "snippet": f"{column_name} NOT NULL",
        },
        "code_context": f"CREATE TABLE {table_name}",
        "confidence": 1.0,
        "extractor_family": "source_c_ddl",
        "normalization_status": "deterministic",
    }


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

        # ── Pass 1: parse all tables into a structured index ──
        tables: dict[str, dict] = {}
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
                name = self._table_name(stmt)
                if not name:
                    continue
                tables[name] = {
                    "stmt": stmt,
                    "source_path": path,
                    "columns": self._extract_columns(stmt),
                    "pk": self._extract_pk_columns(stmt),
                    "fks": self._extract_foreign_keys(stmt, name),
                    "constraints": self._extract_column_constraints(stmt),
                }

        # ── Compute FK-in counts for code-table detection ──
        fk_in: dict[str, int] = {}
        for tname, tdata in tables.items():
            for fk in tdata["fks"]:
                ref = fk["ref_table"]
                fk_in[ref] = fk_in.get(ref, 0) + 1

        # ── Pass 2: emit candidates per table ──
        for tname, tdata in tables.items():
            yield from self._emit_for_table(
                tname, tdata, fk_in_count=fk_in.get(tname, 0),
            )

    # ─── Per-table emission ────────────────────────────────────────────────

    def _emit_for_table(
        self,
        tname: str,
        tdata: dict,
        fk_in_count: int,
    ) -> Iterable[IntermediateCandidate]:
        from .filters import (
            DEFAULT_SOURCE_C_TABLE_SUPPRESSIONS,
            column_is_suppressed,
            glob_match,
        )

        columns = tdata["columns"]
        pk = tdata["pk"]
        fks = tdata["fks"]
        source_path = tdata["source_path"]

        user_exclude_tables = self.config.get("exclude_tables", []) or []
        user_include_tables = self.config.get("include_tables", []) or []
        user_force_vocab = self.config.get("force_vocabulary", []) or []
        user_force_entity = self.config.get("force_entity", []) or []
        user_exclude_columns = self.config.get("exclude_columns", []) or []

        # ─── Table-level suppression decision ───────────────────────────
        table_suppressed = False
        table_suppression_reason: str | None = None

        if glob_match(tname, user_exclude_tables):
            table_suppressed = True
            for p in user_exclude_tables:
                if glob_match(tname, [p]):
                    table_suppression_reason = (
                        f"Per-domain config: table matches exclude_tables "
                        f"pattern '{p}'."
                    )
                    break
        elif not glob_match(tname, user_include_tables):
            if glob_match(tname, DEFAULT_SOURCE_C_TABLE_SUPPRESSIONS):
                table_suppressed = True
                for p in DEFAULT_SOURCE_C_TABLE_SUPPRESSIONS:
                    if glob_match(tname, [p]):
                        table_suppression_reason = (
                            f"Default Source C suppression: table name "
                            f"matches pattern '{p}'."
                        )
                        break

        # ─── Classification (with user overrides) ───────────────────────
        non_pk_non_fk_columns = [
            (cn, ct) for cn, ct in columns
            if cn not in pk and not any(fk["column"] == cn for fk in fks)
        ]
        is_bridge = (
            len(fks) >= 2 and len(non_pk_non_fk_columns) == 0
        )

        code_table_triggers = 0
        name_lower = tname.lower()
        if (
            name_lower.endswith("_codes") or name_lower.endswith("_lookup")
            or name_lower.startswith("ref_") or name_lower.endswith("_code_master")
            or name_lower.startswith("cd_")
        ):
            code_table_triggers += 1
        col_names_lower = [c.lower() for c, _ in columns]
        has_code_col = any(
            cn in ("code", "code_value", "id") for cn in col_names_lower
        )
        has_desc_col = any(
            cn in ("description", "name", "label") for cn in col_names_lower
        )
        if 2 <= len(columns) <= 3 and has_code_col and has_desc_col:
            code_table_triggers += 1
        if fk_in_count >= 2 and len(fks) == 0:
            code_table_triggers += 1
        is_code_table = code_table_triggers >= 2

        # User override of classification (case-insensitive globbing,
        # per spec §6.5).
        force_vocab_pattern: str | None = None
        force_entity_pattern: str | None = None
        if glob_match(tname, user_force_vocab):
            is_code_table = True
            is_bridge = False
            for p in user_force_vocab:
                if glob_match(tname, [p]):
                    force_vocab_pattern = p
                    break
        elif glob_match(tname, user_force_entity):
            is_code_table = False
            is_bridge = False
            for p in user_force_entity:
                if glob_match(tname, [p]):
                    force_entity_pattern = p
                    break

        # ─── Bridge emission (no entity/columns/FKs separately) ────────
        if is_bridge:
            ref_a, ref_b = fks[0]["ref_table"], fks[1]["ref_table"]
            yield IntermediateCandidate(
                label=f"{ref_a}__{tname}__{ref_b}",
                definition=f"Bridge table '{tname}' linking {ref_a} and {ref_b}.",
                source_type="C",
                source_artifact=str(source_path),
                raw_type="bridge_table",
                eid="",
                artifact_kind=ArtifactKind.RELATIONSHIP,
                strength=Strength.MEDIUM,
                promotion_reason=(
                    f"Source C: bridge table '{tname}' "
                    f"(≥2 FKs, no other domain columns)."
                ),
                suppression_reason=table_suppression_reason,
                suppressed=table_suppressed,
            )
            return

        # ─── Code-table emission (vocabulary only) ─────────────────────
        if is_code_table:
            yield IntermediateCandidate(
                label=tname,
                definition="",
                source_type="C",
                source_artifact=str(source_path),
                raw_type="table",
                eid="",
                artifact_kind=ArtifactKind.VOCABULARY,
                strength=Strength.MEDIUM,
                promotion_reason=(
                    f"Source C: table '{tname}' classified as vocabulary "
                    f"by per-domain config force_vocabulary pattern "
                    f"'{force_vocab_pattern}'."
                    if force_vocab_pattern is not None else
                    f"Source C: table '{tname}' classified as code-table / "
                    f"vocabulary ({code_table_triggers} of 3 detection "
                    f"triggers fired)."
                ),
                suppression_reason=table_suppression_reason,
                suppressed=table_suppressed,
            )
            return

        # ─── Regular entity emission ────────────────────────────────────
        yield IntermediateCandidate(
            label=tname,
            definition="",
            source_type="C",
            source_artifact=str(source_path),
            raw_type="table",
            eid="",
            artifact_kind=ArtifactKind.ENTITY,
            strength=Strength.STRONG,
            promotion_reason=(
                f"Source C: table '{tname}' classified as entity by "
                f"per-domain config force_entity pattern "
                f"'{force_entity_pattern}'."
                if force_entity_pattern is not None else
                f"Source C: table '{tname}' (deterministic schema attestation)."
            ),
            suppression_reason=table_suppression_reason,
            suppressed=table_suppressed,
        )

        # Columns → attributes; NOT NULL rules; per-column inline CHECK rules.
        # All three share the column's suppression decision.
        constraints = tdata["constraints"]
        column_decisions: dict[str, tuple[bool, str | None]] = {}
        seen_check_sql: set[str] = set()

        for col_name, col_type in columns:
            if col_name in pk:
                continue
            if any(fk["column"] == col_name for fk in fks):
                continue

            col_suppressed = column_is_suppressed(
                col_name, user_exclude_columns, []
            )
            col_suppression_reason: str | None = None
            if col_suppressed:
                if glob_match(col_name, user_exclude_columns):
                    col_suppression_reason = (
                        f"Per-domain config: column '{col_name}' matches "
                        f"exclude_columns pattern."
                    )
                else:
                    col_suppression_reason = (
                        f"Default Source C suppression: column "
                        f"'{col_name}' matches a noise filter pattern."
                    )
            # If the parent table is suppressed, the column inherits its
            # reason instead of any per-column reason (the audit shows
            # the root cause, not the leaf).
            final_suppressed = col_suppressed or table_suppressed
            final_reason = (
                table_suppression_reason if table_suppressed
                else col_suppression_reason
            )
            column_decisions[col_name] = (final_suppressed, final_reason)

            yield IntermediateCandidate(
                label=col_name,
                definition="",
                source_type="C",
                source_artifact=f"{source_path}#{tname}.{col_name}",
                raw_type=col_type,
                eid="",
                artifact_kind=ArtifactKind.ATTRIBUTE,
                strength=Strength.STRONG,
                promotion_reason=(
                    f"Source C: column '{tname}.{col_name}' (type {col_type})."
                ),
                suppression_reason=final_reason,
                suppressed=final_suppressed,
            )

            # NOT NULL on this column → required-rule candidate (AC1a),
            # carrying the same suppression decision as the attribute.
            col_constraints = constraints.get(col_name, {"nullable": True, "checks": []})
            if not col_constraints["nullable"]:
                payload = _build_required_rule_payload(tname, col_name, source_path)
                yield IntermediateCandidate(
                    label=canonical_rule_label(payload),
                    definition=f"{tname}.{col_name} must not be null.",
                    source_type="C",
                    source_artifact=f"{source_path}#{tname}.{col_name}",
                    raw_type="not_null_constraint",
                    eid="",
                    artifact_kind=ArtifactKind.RULE,
                    strength=Strength.STRONG,
                    promotion_reason=f"Source C: NOT NULL constraint on {tname}.{col_name}.",
                    suppression_reason=final_reason,
                    suppressed=final_suppressed,
                    rule_payload=payload,
                )

            # Per-column inline CHECK constraints (collected in pass 1).
            for check_expr in col_constraints["checks"]:
                seen_check_sql.add(check_expr.sql())
                payload, suppress_reason = _try_extract_simple_check(
                    check_expr, tname, source_path
                )
                if payload is not None:
                    yield IntermediateCandidate(
                        label=canonical_rule_label(payload),
                        definition=f"CHECK constraint on {tname}.{payload['subject_attribute']}",
                        source_type="C",
                        source_artifact=f"{source_path}#{tname}.{payload['subject_attribute']}",
                        raw_type="check_constraint",
                        eid="",
                        artifact_kind=ArtifactKind.RULE,
                        strength=Strength.STRONG,
                        promotion_reason=f"Source C: CHECK ({check_expr.sql()}) on {tname}.",
                        suppression_reason=final_reason,
                        suppressed=final_suppressed,
                        rule_payload=payload,
                    )
                else:
                    yield IntermediateCandidate(
                        label=f"complex check on {tname}: {check_expr.sql()[:80]}",
                        definition=f"Non-trivial CHECK constraint on {tname}",
                        source_type="C",
                        source_artifact=str(source_path),
                        raw_type="check_constraint",
                        eid="",
                        artifact_kind=ArtifactKind.RULE,
                        strength=Strength.WEAK,
                        promotion_reason=f"Source C: complex CHECK ({check_expr.sql()[:80]}) on {tname} — audit only.",
                        suppression_reason=suppress_reason,
                        suppressed=True,
                    )

        # Table-level CHECK constraints (not already seen as inline).
        # These appear as CheckColumnConstraint nodes directly inside the
        # Schema's expression list (not nested inside a ColumnDef).
        stmt = tdata["stmt"]
        schema = stmt.this
        table_level_checks = (
            e for e in (schema.expressions if isinstance(schema, exp.Schema) else [])
            if isinstance(e, exp.CheckColumnConstraint)
        )
        for check in table_level_checks:
            inner = check.this
            if inner is None or inner.sql() in seen_check_sql:
                continue
            payload, suppress_reason = _try_extract_simple_check(
                inner, tname, source_path
            )
            if payload is not None:
                # Inherit the subject column's suppression decision when known;
                # otherwise default to table-level decision.
                subj = payload["subject_attribute"]
                col_suppressed, col_reason = column_decisions.get(
                    subj, (table_suppressed, table_suppression_reason)
                )
                yield IntermediateCandidate(
                    label=canonical_rule_label(payload),
                    definition=f"CHECK constraint on {tname}.{subj}",
                    source_type="C",
                    source_artifact=f"{source_path}#{tname}.{subj}",
                    raw_type="check_constraint",
                    eid="",
                    artifact_kind=ArtifactKind.RULE,
                    strength=Strength.STRONG,
                    promotion_reason=f"Source C: CHECK ({inner.sql()}) on {tname}.",
                    suppression_reason=col_reason,
                    suppressed=col_suppressed,
                    rule_payload=payload,
                )
            else:
                yield IntermediateCandidate(
                    label=f"complex check on {tname}: {inner.sql()[:80]}",
                    definition=f"Non-trivial CHECK constraint on {tname}",
                    source_type="C",
                    source_artifact=str(source_path),
                    raw_type="check_constraint",
                    eid="",
                    artifact_kind=ArtifactKind.RULE,
                    strength=Strength.WEAK,
                    promotion_reason=f"Source C: complex CHECK ({inner.sql()[:80]}) on {tname} — audit only.",
                    suppression_reason=suppress_reason,
                    suppressed=True,
                )

        # FKs → relationships.
        for fk in fks:
            yield IntermediateCandidate(
                label=f"{tname}__{fk['column']}__{fk['ref_table']}",
                definition=(
                    f"Foreign key: {tname}.{fk['column']} -> "
                    f"{fk['ref_table']}.{fk['ref_column']}"
                ),
                source_type="C",
                source_artifact=f"{source_path}#{tname}.{fk['column']}",
                raw_type="foreign_key",
                eid="",
                artifact_kind=ArtifactKind.RELATIONSHIP,
                strength=Strength.MEDIUM,
                promotion_reason=(
                    f"Source C: FK from {tname}.{fk['column']} to "
                    f"{fk['ref_table']}.{fk['ref_column']}."
                ),
                suppression_reason=table_suppression_reason,
                suppressed=table_suppressed,
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
    def _extract_column_constraints(stmt: exp.Create) -> dict[str, dict]:
        """Return {col_name: {"nullable": bool, "checks": list[exp.Expression]}}.

        Mirrors the walk pattern used by _extract_pk_columns. Default
        nullable=True; flip to False when a NotNullColumnConstraint is
        present on the column. ``checks`` collects any
        CheckColumnConstraint expression nodes for the column for
        downstream rule emission (Task 4).
        """
        out: dict[str, dict] = {}
        this = stmt.this
        if not isinstance(this, exp.Schema):
            return out
        for expression in this.expressions or []:
            if not isinstance(expression, exp.ColumnDef):
                continue
            col_name = expression.name
            entry: dict = {"nullable": True, "checks": []}
            for constraint in expression.args.get("constraints") or []:
                kind = constraint.args.get("kind")
                if isinstance(kind, exp.NotNullColumnConstraint):
                    entry["nullable"] = False
                elif isinstance(kind, exp.CheckColumnConstraint):
                    entry["checks"].append(kind.this)
            out[col_name] = entry
        return out

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
