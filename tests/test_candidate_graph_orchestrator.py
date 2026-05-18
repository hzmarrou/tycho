"""Orchestrator integration: build_candidate_graph routes through ingesters."""

import json

from ontozense.core.candidate_graph import build_candidate_graph


def test_a_only_run_is_backward_compatible():
    """Existing fields and values match the v1.0 baseline.
    New additive fields are present at defaults."""
    source_a = {
        "concepts": [
            {"name": "Customer", "definition": "A bank client.",
             "entity_type": "Entity"},
        ],
        "relationships": [],
    }
    graph = build_candidate_graph(source_a=source_a)

    assert len(graph.concepts) == 1
    c = graph.concepts[0]
    assert c.label == "Customer"
    assert c.normalized_label
    assert c.source_presence == {"A": True, "B": False, "C": False, "D": False}
    # New additive fields populated from Source A ingester defaults
    assert c.artifact_kind == "entity"
    # strength comes from Source A's default (medium); no corroboration yet
    assert c.strength == "medium"
    assert c.suppressed is False


def test_b_only_run_works():
    """Same backward-compat for Source B-only."""
    source_b = {
        "records": [
            {"element_name": "Customer", "entity_type": "Entity",
             "definition": "..."},
        ],
    }
    graph = build_candidate_graph(source_b=source_b)
    assert len(graph.concepts) == 1
    assert graph.concepts[0].source_presence["B"] is True


def test_source_c_run_produces_candidates(tmp_path):
    """A run with only Source C DDL produces candidates."""
    ddl = tmp_path / "schema.sql"
    ddl.write_text(
        """
        CREATE TABLE customers (
            customer_id INT PRIMARY KEY,
            name VARCHAR(100),
            credit_score INT
        );
        """.strip(),
        encoding="utf-8",
    )
    graph = build_candidate_graph(source_c={"files": [str(ddl)]})

    norm_labels = {c.normalized_label for c in graph.concepts}
    assert "customer" in norm_labels   # singularised from 'customers'

    customer = next(c for c in graph.concepts
                    if c.normalized_label == "customer")
    assert customer.source_presence["C"] is True
    assert customer.artifact_kind == "entity"


def test_a_and_c_corroborate_to_strong(tmp_path):
    """Source A 'customer' + Source C 'customers' table → tier boosted to strong."""
    source_a = {"concepts": [{"name": "customer"}], "relationships": []}
    ddl = tmp_path / "schema.sql"
    ddl.write_text(
        """
        CREATE TABLE customers (
            customer_id INT PRIMARY KEY,
            name VARCHAR(100),
            credit_score INT
        );
        """.strip(),
        encoding="utf-8",
    )
    graph = build_candidate_graph(
        source_a=source_a,
        source_c={"files": [str(ddl)]},
    )

    customer = next(c for c in graph.concepts
                    if c.normalized_label == "customer")
    assert customer.source_presence["A"] is True
    assert customer.source_presence["C"] is True
    # Multi-axis attestation (semantic + structural) -> boosted to strong
    assert customer.strength == "strong"


def test_audit_block_lists_suppressed_candidates(tmp_path):
    """Suppressed candidates appear in graph.to_dict()['audit'],
    not in the main concepts list."""
    ddl = tmp_path / "schema.sql"
    ddl.write_text(
        """
        CREATE TABLE customers (customer_id INT PRIMARY KEY, name VARCHAR(100));
        CREATE TABLE customer_audit (
            audit_id INT PRIMARY KEY, event VARCHAR(50)
        );
        """.strip(),
        encoding="utf-8",
    )
    graph = build_candidate_graph(source_c={"files": [str(ddl)]})

    # customer_audit is suppressed (matches *_audit) — NOT in concepts
    concept_labels = {c.label for c in graph.concepts}
    assert "customer_audit" not in concept_labels
    # "customers" is singularised to "customer" by the ingester's normalisation
    assert any(lbl in ("customers", "customer") for lbl in concept_labels)

    # audit list contains the suppressed entry
    raw = graph.to_dict()
    assert "audit" in raw
    assert isinstance(raw["audit"], list)
    audit_labels = {entry["label"] for entry in raw["audit"]}
    assert "customer_audit" in audit_labels

    # Each audit entry has the documented fields
    audit_entry = next(e for e in raw["audit"] if e["label"] == "customer_audit")
    assert audit_entry["source_type"] == "C"
    assert audit_entry["artifact_kind"] in ("entity", "vocabulary", "relationship")
    assert audit_entry["suppression_reason"]


def test_data_only_run_useful_output(tmp_path):
    """A DDL-only run (no A, no B) still produces a useful candidate graph
    — this is the v1.1 motivating case for data-led domains."""
    ddl = tmp_path / "schema.sql"
    ddl.write_text(
        """
        CREATE TABLE customers (
            customer_id INT PRIMARY KEY,
            name VARCHAR(100),
            email VARCHAR(200)
        );
        CREATE TABLE loans (
            loan_id INT PRIMARY KEY,
            customer_id INT,
            amount DECIMAL(10,2),
            FOREIGN KEY (customer_id) REFERENCES customers(customer_id)
        );
        """.strip(),
        encoding="utf-8",
    )
    graph = build_candidate_graph(source_c={"files": [str(ddl)]})

    norm_labels = {c.normalized_label for c in graph.concepts}
    assert "customer" in norm_labels
    assert "loan" in norm_labels


def test_source_d_run_produces_candidates(tmp_path):
    """A run with only Source D Python AST input produces entity
    candidates."""
    code_file = tmp_path / "models.py"
    code_file.write_text(
        "from dataclasses import dataclass\n"
        "\n"
        "@dataclass\n"
        "class Customer:\n"
        "    name: str\n"
        "    email: str\n",
        encoding="utf-8",
    )
    graph = build_candidate_graph(source_d={"files": [str(code_file)]})

    norm_labels = {c.normalized_label for c in graph.concepts}
    assert "customer" in norm_labels
    customer = next(c for c in graph.concepts
                    if c.normalized_label == "customer")
    assert customer.source_presence["D"] is True
    assert customer.artifact_kind == "entity"


def test_per_domain_source_c_config_passed_through(tmp_path):
    """source_c_config kwarg flows to SourceCIngester and overrides
    its classification."""
    ddl = tmp_path / "schema.sql"
    ddl.write_text(
        """
        CREATE TABLE status (
            id INT PRIMARY KEY,
            name VARCHAR(50),
            description VARCHAR(200),
            priority INT
        );
        """.strip(),
        encoding="utf-8",
    )
    graph = build_candidate_graph(
        source_c={"files": [str(ddl)]},
        source_c_config={"force_vocabulary": ["status"]},
    )
    status = next(c for c in graph.concepts if c.label == "status")
    assert status.artifact_kind == "vocabulary"
