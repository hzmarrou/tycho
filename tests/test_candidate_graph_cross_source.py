"""Cross-source corroboration: label normalisation + tier-boost merge logic.

Unit tests for the two new helpers introduced in Task 14
(``_resolve_alias_with_normalisation`` and
``_apply_corroboration_boost``) plus two ``_upsert``-level
integration tests that pin the singularize-and-merge behaviour
without depending on the orchestrator landing in Task 15.
"""

from ontozense.core.candidate_graph import (
    _CandidateIndex,
    _apply_corroboration_boost,
    _resolve_alias_with_normalisation,
    _upsert,
)


def test_resolve_alias_with_singularization():
    # Plural → singular.
    assert _resolve_alias_with_normalisation("customers", {}) == "customer"
    # Already singular, no change.
    assert _resolve_alias_with_normalisation("customer", {}) == "customer"
    # Table prefix stripped + singularized.
    assert _resolve_alias_with_normalisation("tbl_customers", {}) == "customer"
    assert _resolve_alias_with_normalisation("dim_customers", {}) == "customer"
    assert _resolve_alias_with_normalisation("fact_orders", {}) == "order"
    # Existing alias_map still wins.
    assert _resolve_alias_with_normalisation(
        "client", {"client": "Customer"}
    ) == "Customer"


def test_tier_boost_single_axis_returns_max_strength_no_boost():
    """Single axis: no boost; the result is simply the max strength."""
    assert _apply_corroboration_boost([("A", "medium")]) == "medium"
    assert _apply_corroboration_boost([("A", "weak")]) == "weak"
    assert _apply_corroboration_boost([("A", "strong")]) == "strong"


def test_tier_boost_two_axes_promotes_one_tier():
    """>=2 distinct axes -> +1 tier from the max, capped at strong."""
    assert _apply_corroboration_boost(
        [("A", "medium"), ("C", "medium")]
    ) == "strong"
    assert _apply_corroboration_boost(
        [("A", "weak"), ("D", "weak")]
    ) == "medium"


def test_tier_boost_capped_at_strong():
    """Cannot exceed strong, even with three axes or already-strong inputs."""
    assert _apply_corroboration_boost(
        [("A", "strong"), ("C", "strong")]
    ) == "strong"
    assert _apply_corroboration_boost(
        [("A", "medium"), ("C", "medium"), ("D", "medium")]
    ) == "strong"


def test_tier_boost_same_axis_twice_does_not_boost():
    """Two attestations on the SAME axis (e.g. A + B, both semantic)
    don't count as multi-axis corroboration."""
    assert _apply_corroboration_boost(
        [("A", "medium"), ("B", "medium")]
    ) == "medium"


def test_upsert_singularization_merges_plural_and_singular():
    """End-to-end through _upsert: 'customer' and 'customers' from
    different sources merge into a single candidate via the
    singularization in _resolve_alias_with_normalisation."""
    index = _CandidateIndex()
    _upsert(
        index,
        label="customer",
        definition="A bank client.",
        source_type="A",
        source_artifact="docs/policy.md",
        raw_type="Entity",
        eid="",
        artifact_kind="entity",
        strength="medium",
        promotion_reason="Source A.",
        suppression_reason=None,
        suppressed=False,
    )
    _upsert(
        index,
        label="customers",   # plural — should singularize-and-merge
        definition="The customers table.",
        source_type="C",
        source_artifact="schema.sql",
        raw_type="table",
        eid="",
        artifact_kind="entity",
        strength="strong",
        promotion_reason="Source C: table customers.",
        suppression_reason=None,
        suppressed=False,
    )
    candidates = index.values()
    assert len(candidates) == 1
    c = candidates[0]
    # Both source-presence bits set.
    assert c.source_presence["A"] is True
    assert c.source_presence["C"] is True
    # Multi-axis attestation -> boosted to strong (capped).
    assert c.strength == "strong"
    # The canonical (singularised) label survives.
    assert c.normalized_label == "customer"


def test_upsert_table_prefix_stripped_then_singularized_for_merge():
    """A C-side 'tbl_customers' merges with an A-side 'customer'
    through prefix-strip + singularize."""
    index = _CandidateIndex()
    _upsert(
        index,
        label="customer",
        definition="A bank client.",
        source_type="A",
        source_artifact="",
        raw_type="Entity",
        eid="",
        artifact_kind="entity",
        strength="medium",
        promotion_reason="",
        suppression_reason=None,
        suppressed=False,
    )
    _upsert(
        index,
        label="tbl_customers",
        definition="",
        source_type="C",
        source_artifact="schema.sql",
        raw_type="table",
        eid="",
        artifact_kind="entity",
        strength="strong",
        promotion_reason="",
        suppression_reason=None,
        suppressed=False,
    )
    candidates = index.values()
    assert len(candidates) == 1
    assert candidates[0].normalized_label == "customer"


def test_relationship_endpoints_resolve_through_singularization():
    """A Source A relationship whose subject/object is plural
    (e.g. 'customers') must resolve to a candidate merged under
    the singular 'customer'. Without this, the relationship is
    silently dropped and graph_degree is understated."""
    from ontozense.core.candidate_graph import build_candidate_graph

    source_a = {
        "concepts": [
            # 'customer' (singular) is the canonical merged candidate.
            {"name": "customer", "definition": "A bank client."},
            {"name": "loan", "definition": "Money borrowed."},
        ],
        # Relationship endpoint uses the plural form.
        "relationships": [
            {"subject": "loan", "predicate": "applies_to", "object": "customers"},
        ],
    }
    graph = build_candidate_graph(source_a=source_a)

    # The relationship must survive — endpoint 'customers' resolves
    # to the 'customer' candidate via singularization.
    assert len(graph.relationships) == 1
    rel = graph.relationships[0]
    assert rel.predicate == "applies_to"

    # Both candidates exist as one merged entry each.
    by_norm = {c.normalized_label: c for c in graph.concepts}
    assert "customer" in by_norm
    assert "loan" in by_norm

    # graph_degree should reflect the resolved edge.
    assert by_norm["customer"].graph_degree == 1
    assert by_norm["loan"].graph_degree == 1


def test_relationship_endpoints_resolve_through_prefix_stripping():
    """A Source A relationship whose endpoint uses a table-style
    prefix (e.g. 'tbl_customers') must resolve to a candidate
    merged under 'customer'."""
    from ontozense.core.candidate_graph import build_candidate_graph

    source_a = {
        "concepts": [
            {"name": "customer", "definition": "A bank client."},
            {"name": "loan", "definition": "Money borrowed."},
        ],
        "relationships": [
            {"subject": "loan", "predicate": "owned_by", "object": "tbl_customers"},
        ],
    }
    graph = build_candidate_graph(source_a=source_a)
    assert len(graph.relationships) == 1
    assert graph.relationships[0].predicate == "owned_by"
