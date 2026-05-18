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
