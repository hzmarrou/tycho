"""End-to-end test: DDL-only survey produces useful candidate graph.

Validates the v1.1 motivating case: a domain with NO docs and NO
governance still produces useful, classified, and provenance-rich
candidate-graph output from DDL alone. This is the headline value
proposition for data-led domains (banking, insurance, healthcare).
"""

from pathlib import Path

from ontozense.core.candidate_graph import build_candidate_graph


FIXTURE = Path(__file__).parent / "fixtures" / "data_only_minimal"


def _build():
    return build_candidate_graph(
        source_c={"files": [str(FIXTURE / "source-c.sql")]},
    )


def test_tables_become_entity_candidates():
    """customers and orders tables surface as entity candidates,
    each attested only on the C (structural) axis."""
    graph = _build()
    by_norm = {c.normalized_label: c for c in graph.concepts}

    assert "customer" in by_norm   # singularised from 'customers'
    assert by_norm["customer"].artifact_kind == "entity"
    assert by_norm["customer"].source_presence["C"] is True
    assert by_norm["customer"].source_presence["A"] is False
    assert by_norm["customer"].source_presence["B"] is False

    assert "order" in by_norm      # singularised from 'orders'
    assert by_norm["order"].artifact_kind == "entity"


def test_single_axis_attestation_means_no_boost():
    """C-only attestation: no corroboration boost. The default
    strength for a Source C table is STRONG already (deterministic
    schema attestation), so it stays STRONG without needing a boost."""
    graph = _build()
    by_norm = {c.normalized_label: c for c in graph.concepts}
    # Source C alone -> single axis -> no tier boost applied.
    # Default Source C strength for a table is STRONG (per Task 8).
    assert by_norm["customer"].strength == "strong"


def test_countries_table_classifies_as_entity_in_v1_1():
    """countries has shape (code + name = 2 cols) but doesn't match
    the naming heuristic and has only 1 inbound FK — only 1 of 3
    code-table triggers fires (the 2-of-3 threshold). v1.1 default
    classifies it as entity, NOT vocabulary.

    Domain-specific use can override with `force_vocabulary` in
    source-c.yaml. Widening the default naming heuristic to include
    table names like 'countries' is explicitly deferred per Codex's
    Task 18 review: would over-classify ordinary entity tables in
    real schemas.
    """
    graph = _build()
    by_norm = {c.normalized_label: c for c in graph.concepts}
    country = by_norm.get("country") or by_norm.get("countries")
    assert country is not None
    assert country.artifact_kind == "entity"


def test_domain_bearing_date_kept():
    """birth_date is a TIMESTAMP-style column but has a
    domain-bearing prefix ('birth') — the column-suppression rule
    keeps it as an attribute candidate, not suppressed."""
    graph = _build()
    attr_labels = {
        c.label for c in graph.concepts
        if c.artifact_kind == "attribute"
    }
    assert "birth_date" in attr_labels


def test_audit_block_lists_timestamp_without_domain_prefix():
    """placed_at is a TIMESTAMP column with no domain-bearing
    prefix — the default Source C column-suppression rule routes
    it to the audit block."""
    graph = _build()
    audit_labels = {a["label"] for a in graph.audit}
    assert "placed_at" in audit_labels

    audit_entry = next(a for a in graph.audit if a["label"] == "placed_at")
    assert audit_entry["suppressed"] is True
    assert audit_entry["suppression_reason"]
    # Source C column-level reason format
    assert "noise filter" in audit_entry["suppression_reason"].lower() \
        or "timestamp" in audit_entry["suppression_reason"].lower() \
        or "_at" in audit_entry["suppression_reason"].lower()


def test_foreign_key_relationships_emitted():
    """The two FKs in the DDL (customers->countries, orders->customers)
    emit as relationship candidates with raw_type='foreign_key'.
    Synthetic FK labels follow '<src>__<col>__<ref>' with BOTH
    endpoints preserved as-is (no partial singularisation), per
    v1.1.1 follow-up #95.
    """
    graph = _build()
    relationships = [
        c for c in graph.concepts
        if c.artifact_kind == "relationship"
    ]
    # Two FKs in the fixture -> two relationship candidates.
    assert len(relationships) >= 2

    rel_labels = {c.label for c in relationships}
    # Both source AND ref segments preserved exactly (no singularisation).
    assert "customers__country_code__countries" in rel_labels
    assert "orders__customer_id__customers" in rel_labels

    # Each carries raw_type='foreign_key' via its EvidenceEntry provenance.
    for r in relationships:
        assert any(
            e.raw_type == "foreign_key" for e in r.provenance
        ), f"expected 'foreign_key' in provenance for {r.label!r}"
