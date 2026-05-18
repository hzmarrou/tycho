"""Tests for Source C ingestion (SQL DDL via sqlglot)."""

from pathlib import Path

import pytest

from ontozense.core.ingest.base import ArtifactKind, Strength
from ontozense.core.ingest.ingest_c import SourceCIngester


def test_single_table_yields_one_entity(tmp_path):
    ddl = tmp_path / "schema.sql"
    ddl.write_text(
        """
        CREATE TABLE customers (
            customer_id INT PRIMARY KEY,
            name VARCHAR(100),
            email VARCHAR(200),
            credit_score INT
        );
        """.strip(),
        encoding="utf-8",
    )
    cands = list(SourceCIngester().ingest({"files": [str(ddl)]}))
    entities = [c for c in cands if c.artifact_kind == ArtifactKind.ENTITY]
    assert len(entities) == 1

    c = entities[0]
    assert c.label == "customers"
    assert c.source_type == "C"
    assert c.raw_type == "table"
    assert c.strength == Strength.STRONG
    assert "table" in c.promotion_reason.lower()
    assert str(ddl) in c.source_artifact


def test_unparseable_ddl_raises_clear_error(tmp_path):
    """Unparseable DDL is silently skipped (with a logged warning),
    not propagated as an exception. v1.1 convention: graceful skip."""
    ddl = tmp_path / "bad.sql"
    ddl.write_text("this is not SQL at all !!!!", encoding="utf-8")

    cands = list(SourceCIngester().ingest({"files": [str(ddl)]}))
    assert cands == []  # nothing parseable


def test_no_files_yields_nothing():
    assert list(SourceCIngester().ingest({"files": []})) == []
    assert list(SourceCIngester().ingest({})) == []


def test_handles_non_dict_input_safely():
    """Non-dict raw_input is treated as empty — no exception."""
    ingester = SourceCIngester()
    assert list(ingester.ingest(None)) == []
    assert list(ingester.ingest([])) == []
    assert list(ingester.ingest("not a dict")) == []


def test_columns_yield_attribute_candidates(tmp_path):
    ddl = tmp_path / "schema.sql"
    ddl.write_text(
        """
        CREATE TABLE customers (
            customer_id INT PRIMARY KEY,
            name VARCHAR(100),
            email VARCHAR(200),
            credit_score INT
        );
        """.strip(),
        encoding="utf-8",
    )
    cands = list(SourceCIngester().ingest({"files": [str(ddl)]}))
    attrs = [c for c in cands if c.artifact_kind == ArtifactKind.ATTRIBUTE]

    labels = sorted(c.label for c in attrs)
    # PK column 'customer_id' is demoted (not emitted as standalone)
    assert labels == ["credit_score", "email", "name"]


def test_pk_column_is_demoted_not_emitted(tmp_path):
    ddl = tmp_path / "schema.sql"
    ddl.write_text(
        "CREATE TABLE customers (customer_id INT PRIMARY KEY, name VARCHAR(100));",
        encoding="utf-8",
    )
    cands = list(SourceCIngester().ingest({"files": [str(ddl)]}))
    labels = {c.label for c in cands}
    assert "customer_id" not in labels
    assert "customers" in labels  # the entity still surfaces


def test_column_raw_type_carries_sql_datatype(tmp_path):
    ddl = tmp_path / "schema.sql"
    ddl.write_text(
        "CREATE TABLE x (a VARCHAR(100), b INT, c DATE);",
        encoding="utf-8",
    )
    cands = list(SourceCIngester().ingest({"files": [str(ddl)]}))
    by_label = {c.label: c for c in cands if c.artifact_kind == ArtifactKind.ATTRIBUTE}
    # raw_type carries the SQL type — case may vary by sqlglot
    assert "varchar" in by_label["a"].raw_type.lower()
    assert "int" in by_label["b"].raw_type.lower()
    assert "date" in by_label["c"].raw_type.lower()


def test_foreign_key_yields_relationship_candidate(tmp_path):
    ddl = tmp_path / "schema.sql"
    ddl.write_text(
        """
        CREATE TABLE customers (customer_id INT PRIMARY KEY, name VARCHAR(100));
        CREATE TABLE loans (
            loan_id INT PRIMARY KEY,
            customer_id INT,
            amount DECIMAL(10,2),
            FOREIGN KEY (customer_id) REFERENCES customers(customer_id)
        );
        """.strip(),
        encoding="utf-8",
    )
    cands = list(SourceCIngester().ingest({"files": [str(ddl)]}))
    rels = [c for c in cands if c.artifact_kind == ArtifactKind.RELATIONSHIP]
    assert len(rels) == 1

    r = rels[0]
    # The FK relationship label is "<source-table>__<col>__<ref-table>"
    # or similar — the test just pins that it includes both endpoints.
    assert "customer" in r.label.lower()
    assert r.raw_type == "foreign_key"
    assert r.strength == Strength.MEDIUM
