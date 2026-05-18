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


def test_code_table_classified_as_vocabulary(tmp_path):
    """Table named *_lookup with code+name columns → vocabulary."""
    ddl = tmp_path / "schema.sql"
    ddl.write_text(
        """
        CREATE TABLE customers (
            customer_id INT PRIMARY KEY,
            name VARCHAR(100),
            country_code VARCHAR(2),
            FOREIGN KEY (country_code) REFERENCES country_lookup(code)
        );
        CREATE TABLE country_lookup (
            code VARCHAR(2) PRIMARY KEY,
            name VARCHAR(100)
        );
        """.strip(),
        encoding="utf-8",
    )
    cands = list(SourceCIngester().ingest({"files": [str(ddl)]}))
    by_label = {c.label: c for c in cands if c.artifact_kind in
                (ArtifactKind.ENTITY, ArtifactKind.VOCABULARY)}

    # customers stays an entity
    assert by_label["customers"].artifact_kind == ArtifactKind.ENTITY
    # country_lookup is reclassified as vocabulary
    assert by_label["country_lookup"].artifact_kind == ArtifactKind.VOCABULARY
    assert by_label["country_lookup"].strength == Strength.MEDIUM
    promo = by_label["country_lookup"].promotion_reason.lower()
    assert "code-table" in promo or "vocabulary" in promo


def test_bridge_table_yields_relationship_only(tmp_path):
    """A table with only FKs (no other domain columns) is a bridge
    table — emits as a relationship between its two referents, no
    entity candidate."""
    ddl = tmp_path / "schema.sql"
    ddl.write_text(
        """
        CREATE TABLE students (student_id INT PRIMARY KEY, name VARCHAR(100));
        CREATE TABLE courses (course_id INT PRIMARY KEY, title VARCHAR(200));
        CREATE TABLE enrolments (
            student_id INT,
            course_id INT,
            PRIMARY KEY (student_id, course_id),
            FOREIGN KEY (student_id) REFERENCES students(student_id),
            FOREIGN KEY (course_id) REFERENCES courses(course_id)
        );
        """.strip(),
        encoding="utf-8",
    )
    cands = list(SourceCIngester().ingest({"files": [str(ddl)]}))

    # No standalone 'enrolments' entity candidate
    entity_labels = {c.label for c in cands
                     if c.artifact_kind == ArtifactKind.ENTITY}
    assert "enrolments" not in entity_labels
    assert "students" in entity_labels
    assert "courses" in entity_labels

    # A relationship that mentions both endpoints (from the bridge)
    rels = [c for c in cands if c.artifact_kind == ArtifactKind.RELATIONSHIP]
    bridge_rels = [r for r in rels
                   if "students" in r.label.lower() and "courses" in r.label.lower()]
    assert len(bridge_rels) == 1
    assert bridge_rels[0].strength == Strength.MEDIUM


def test_small_table_without_code_naming_stays_entity(tmp_path):
    """A 2-column table without lookup/code naming and no FK-in pressure
    stays an entity (default classification)."""
    ddl = tmp_path / "schema.sql"
    ddl.write_text(
        "CREATE TABLE accounts (account_id INT PRIMARY KEY, balance DECIMAL);",
        encoding="utf-8",
    )
    cands = list(SourceCIngester().ingest({"files": [str(ddl)]}))
    entities = [c for c in cands if c.artifact_kind == ArtifactKind.ENTITY]
    assert any(c.label == "accounts" for c in entities)


def test_audit_table_suppressed(tmp_path):
    ddl = tmp_path / "schema.sql"
    ddl.write_text(
        """
        CREATE TABLE customers (customer_id INT PRIMARY KEY, name VARCHAR(100));
        CREATE TABLE customer_audit (
            audit_id INT PRIMARY KEY,
            event VARCHAR(50),
            occurred_at TIMESTAMP
        );
        """.strip(),
        encoding="utf-8",
    )
    cands = list(SourceCIngester().ingest({"files": [str(ddl)]}))
    by_label = {c.label: c for c in cands}
    assert "customer_audit" in by_label
    assert by_label["customer_audit"].suppressed is True
    assert "audit" in (by_label["customer_audit"].suppression_reason or "").lower()


def test_created_at_column_suppressed_birth_date_kept(tmp_path):
    ddl = tmp_path / "schema.sql"
    ddl.write_text(
        """
        CREATE TABLE customers (
            customer_id INT PRIMARY KEY,
            name VARCHAR(100),
            birth_date DATE,
            created_at TIMESTAMP,
            updated_at TIMESTAMP
        );
        """.strip(),
        encoding="utf-8",
    )
    cands = list(SourceCIngester().ingest({"files": [str(ddl)]}))
    by_label = {c.label: c for c in cands
                if c.artifact_kind == ArtifactKind.ATTRIBUTE}

    assert by_label["birth_date"].suppressed is False
    assert by_label["created_at"].suppressed is True
    assert by_label["updated_at"].suppressed is True


def test_user_exclude_tables_overrides_default_keep(tmp_path):
    ddl = tmp_path / "schema.sql"
    ddl.write_text(
        "CREATE TABLE legacy_loans (id INT PRIMARY KEY, x VARCHAR(100));",
        encoding="utf-8",
    )
    cfg = {"exclude_tables": ["legacy_*"]}
    cands = list(SourceCIngester(config=cfg).ingest({"files": [str(ddl)]}))
    by_label = {c.label: c for c in cands}
    assert by_label["legacy_loans"].suppressed is True
    assert "legacy_*" in (by_label["legacy_loans"].suppression_reason or "")


def test_user_include_tables_overrides_default_suppress(tmp_path):
    """A default-suppressed table (e.g. *_audit) can be brought back
    via include_tables."""
    ddl = tmp_path / "schema.sql"
    ddl.write_text(
        "CREATE TABLE customer_audit (id INT PRIMARY KEY, event VARCHAR(50));",
        encoding="utf-8",
    )
    cfg = {"include_tables": ["customer_audit"]}
    cands = list(SourceCIngester(config=cfg).ingest({"files": [str(ddl)]}))
    by_label = {c.label: c for c in cands}
    assert by_label["customer_audit"].suppressed is False


def test_user_force_vocabulary_overrides_default_entity(tmp_path):
    ddl = tmp_path / "schema.sql"
    ddl.write_text(
        """
        CREATE TABLE status (id INT PRIMARY KEY, name VARCHAR(50),
                             description VARCHAR(200), priority INT);
        """.strip(),
        encoding="utf-8",
    )
    cfg = {"force_vocabulary": ["status"]}
    cands = list(SourceCIngester(config=cfg).ingest({"files": [str(ddl)]}))
    status = next(c for c in cands if c.label == "status")
    assert status.artifact_kind == ArtifactKind.VOCABULARY


def test_user_force_entity_overrides_default_vocabulary(tmp_path):
    ddl = tmp_path / "schema.sql"
    ddl.write_text(
        """
        CREATE TABLE country_lookup (code VARCHAR(2) PRIMARY KEY, name VARCHAR(100));
        CREATE TABLE customers (
            id INT PRIMARY KEY,
            country_code VARCHAR(2),
            FOREIGN KEY (country_code) REFERENCES country_lookup(code)
        );
        CREATE TABLE other (
            id INT PRIMARY KEY,
            country_code VARCHAR(2),
            FOREIGN KEY (country_code) REFERENCES country_lookup(code)
        );
        """.strip(),
        encoding="utf-8",
    )
    cfg = {"force_entity": ["country_lookup"]}
    cands = list(SourceCIngester(config=cfg).ingest({"files": [str(ddl)]}))
    cl = next(c for c in cands if c.label == "country_lookup"
              and c.artifact_kind in (ArtifactKind.ENTITY, ArtifactKind.VOCABULARY))
    assert cl.artifact_kind == ArtifactKind.ENTITY


def test_user_force_vocabulary_supports_glob(tmp_path):
    """force_vocabulary: ['*_lookup'] reclassifies country_lookup
    despite the *_lookup pattern (not exact-match)."""
    ddl = tmp_path / "schema.sql"
    ddl.write_text(
        """
        CREATE TABLE country_lookup (
            id INT PRIMARY KEY,
            name VARCHAR(100),
            iso_alpha_3 VARCHAR(3),
            currency_code VARCHAR(3)
        );
        """.strip(),
        encoding="utf-8",
    )
    cfg = {"force_vocabulary": ["*_lookup"]}
    cands = list(SourceCIngester(config=cfg).ingest({"files": [str(ddl)]}))
    cl = next(c for c in cands if c.label == "country_lookup")
    assert cl.artifact_kind == ArtifactKind.VOCABULARY
    # The promotion_reason should cite the matched pattern
    assert "*_lookup" in cl.promotion_reason or "lookup" in cl.promotion_reason.lower()


def test_user_force_entity_is_case_insensitive(tmp_path):
    """force_entity: ['COUNTRY_LOOKUP'] (upper-case) reclassifies the
    lower-case 'country_lookup' table — globbing is case-insensitive
    per spec §6.5."""
    ddl = tmp_path / "schema.sql"
    ddl.write_text(
        """
        CREATE TABLE country_lookup (code VARCHAR(2) PRIMARY KEY, name VARCHAR(100));
        CREATE TABLE customers (
            id INT PRIMARY KEY,
            country_code VARCHAR(2),
            FOREIGN KEY (country_code) REFERENCES country_lookup(code)
        );
        CREATE TABLE other (
            id INT PRIMARY KEY,
            country_code VARCHAR(2),
            FOREIGN KEY (country_code) REFERENCES country_lookup(code)
        );
        """.strip(),
        encoding="utf-8",
    )
    # Note: UPPER-CASE force_entity entry
    cfg = {"force_entity": ["COUNTRY_LOOKUP"]}
    cands = list(SourceCIngester(config=cfg).ingest({"files": [str(ddl)]}))
    cl = next(c for c in cands if c.label == "country_lookup"
              and c.artifact_kind in (ArtifactKind.ENTITY, ArtifactKind.VOCABULARY))
    assert cl.artifact_kind == ArtifactKind.ENTITY


def test_user_force_vocabulary_glob_does_not_match_unrelated(tmp_path):
    """Sanity check: force_vocabulary: ['*_lookup'] does NOT reclassify
    'customers' even though it's a regular entity."""
    ddl = tmp_path / "schema.sql"
    ddl.write_text(
        """
        CREATE TABLE customers (id INT PRIMARY KEY, name VARCHAR(100), email VARCHAR(200));
        CREATE TABLE status_lookup (id INT PRIMARY KEY, name VARCHAR(50), description VARCHAR(200));
        """.strip(),
        encoding="utf-8",
    )
    cfg = {"force_vocabulary": ["*_lookup"]}
    cands = list(SourceCIngester(config=cfg).ingest({"files": [str(ddl)]}))
    customers = next(c for c in cands if c.label == "customers"
                     and c.artifact_kind in (ArtifactKind.ENTITY, ArtifactKind.VOCABULARY))
    status_lookup = next(c for c in cands if c.label == "status_lookup"
                         and c.artifact_kind in (ArtifactKind.ENTITY, ArtifactKind.VOCABULARY))
    assert customers.artifact_kind == ArtifactKind.ENTITY
    assert status_lookup.artifact_kind == ArtifactKind.VOCABULARY
