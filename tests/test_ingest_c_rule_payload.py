"""Tests for the rule_payload contract on Source C output (AC1a)."""
from pathlib import Path

from ontozense.core.ingest.base import ArtifactKind
from ontozense.core.ingest.ingest_c import SourceCIngester


def _ingest(sql: Path):
    return list(SourceCIngester().ingest({"files": [str(sql)]}))


def test_not_null_column_emits_rule_candidate(tmp_path: Path):
    sql = tmp_path / "loans.sql"
    sql.write_text(
        "CREATE TABLE loan (\n"
        "  loan_id VARCHAR(32) PRIMARY KEY,\n"
        "  amount NUMERIC NOT NULL\n"
        ");\n",
        encoding="utf-8",
    )
    cands = _ingest(sql)

    rule_cands = [c for c in cands if c.artifact_kind == ArtifactKind.RULE]
    assert len(rule_cands) == 1, [c.label for c in rule_cands]
    rp = rule_cands[0].rule_payload
    assert rp["rule_kind"] == "validation"
    assert rp["subject_entity"] == "loan"
    assert rp["subject_attribute"] == "amount"
    assert rp["predicate"] == "required"
    assert rp["normalization_status"] == "deterministic"
    # Canonical label drives the merge identity.
    assert rule_cands[0].label == "loan.amount required True"
    assert rp["extractor_family"] == "source_c_ddl"
    assert set(rp["evidence_span"].keys()) == {"file", "start_line", "end_line", "snippet"}
    assert rp["evidence_span"]["snippet"] == "amount NOT NULL"


def test_nullable_column_emits_no_rule(tmp_path: Path):
    sql = tmp_path / "loans.sql"
    sql.write_text(
        "CREATE TABLE loan (\n"
        "  loan_id VARCHAR(32) PRIMARY KEY,\n"
        "  notes TEXT\n"
        ");\n",
        encoding="utf-8",
    )
    cands = _ingest(sql)
    rule_cands = [c for c in cands if c.artifact_kind == ArtifactKind.RULE]
    assert rule_cands == []


def test_primary_key_column_is_implicitly_not_null_but_does_not_double_emit(tmp_path: Path):
    """PK columns are skipped by the existing attribute emission loop; the
    NOT NULL rule emission must follow the same skip rule so we don't get
    a phantom required-rule for the PK."""
    sql = tmp_path / "loans.sql"
    sql.write_text(
        "CREATE TABLE loan (\n"
        "  loan_id VARCHAR(32) PRIMARY KEY,\n"
        "  amount NUMERIC NOT NULL\n"
        ");\n",
        encoding="utf-8",
    )
    cands = _ingest(sql)
    rule_cands = [c for c in cands if c.artifact_kind == ArtifactKind.RULE]
    assert {rp.rule_payload["subject_attribute"] for rp in rule_cands} == {"amount"}


def test_excluded_column_suppresses_both_attribute_and_rule(tmp_path: Path):
    """When a NOT NULL column matches user exclude_columns, both the
    attribute candidate AND the required-rule candidate must be
    suppressed with the same reason. The rule loop must not bypass
    column-level suppression that the attribute loop honored."""
    sql = tmp_path / "loans.sql"
    sql.write_text(
        "CREATE TABLE loan (\n"
        "  loan_id VARCHAR(32) PRIMARY KEY,\n"
        "  amount NUMERIC NOT NULL,\n"
        "  created_at TIMESTAMP NOT NULL\n"
        ");\n",
        encoding="utf-8",
    )
    cands = list(
        SourceCIngester(config={"exclude_columns": ["created_at"]})
        .ingest({"files": [str(sql)]})
    )

    # The created_at attribute is emitted but suppressed.
    created_attrs = [
        c for c in cands
        if c.artifact_kind == ArtifactKind.ATTRIBUTE and c.label == "created_at"
    ]
    assert len(created_attrs) == 1
    assert created_attrs[0].suppressed is True
    assert "exclude_columns" in (created_attrs[0].suppression_reason or "")

    # The created_at rule is emitted but ALSO suppressed (the fix).
    created_rules = [
        c for c in cands
        if c.artifact_kind == ArtifactKind.RULE
        and c.rule_payload
        and c.rule_payload["subject_attribute"] == "created_at"
    ]
    assert len(created_rules) == 1
    assert created_rules[0].suppressed is True
    assert "exclude_columns" in (created_rules[0].suppression_reason or "")

    # The non-excluded amount rule is still emitted and not suppressed.
    amount_rules = [
        c for c in cands
        if c.artifact_kind == ArtifactKind.RULE
        and c.rule_payload
        and c.rule_payload["subject_attribute"] == "amount"
    ]
    assert len(amount_rules) == 1
    assert amount_rules[0].suppressed is False
