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
    # The function now returns (canonical, alias_fired) tuple.
    # Plural → singular (alias_fired=False: only singularisation ran).
    canonical, fired = _resolve_alias_with_normalisation("customers", {})
    assert canonical == "customer"
    assert fired is False
    # Already singular, no change.
    canonical, fired = _resolve_alias_with_normalisation("customer", {})
    assert canonical == "customer"
    assert fired is False
    # Table prefix stripped + singularized (alias_fired=False).
    canonical, fired = _resolve_alias_with_normalisation("tbl_customers", {})
    assert canonical == "customer"
    assert fired is False
    canonical, fired = _resolve_alias_with_normalisation("dim_customers", {})
    assert canonical == "customer"
    assert fired is False
    canonical, fired = _resolve_alias_with_normalisation("fact_orders", {})
    assert canonical == "order"
    assert fired is False
    # Existing alias_map wins (alias_fired=True).
    canonical, fired = _resolve_alias_with_normalisation(
        "client", {"client": "Customer"}
    )
    assert canonical == "Customer"
    assert fired is True


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


def test_cross_kind_collision_keeps_both_candidates_and_logs_conflict():
    """Spec §8 point 2: when an entity (e.g. Source C table 'customer')
    and an attribute (e.g. Source A 'customer' as a property) share the
    same normalised label, BOTH must survive as separate candidates
    with their distinct artifact_kinds. The conflict is surfaced via
    an audit entry."""
    from ontozense.core.candidate_graph import _CandidateIndex, _upsert

    index = _CandidateIndex()
    _upsert(
        index,
        label="customer",
        definition="A bank client.",
        source_type="A",
        source_artifact="docs.md",
        raw_type="property",
        eid="",
        artifact_kind="attribute",
        strength="medium",
        promotion_reason="Source A attribute.",
        suppression_reason=None,
        suppressed=False,
    )
    _upsert(
        index,
        label="customer",
        definition="The customers table.",
        source_type="C",
        source_artifact="schema.sql",
        raw_type="table",
        eid="",
        artifact_kind="entity",
        strength="strong",
        promotion_reason="Source C entity.",
        suppression_reason=None,
        suppressed=False,
    )
    candidates = index.values()
    # Both survive as SEPARATE candidates with distinct kinds.
    kinds = {c.artifact_kind for c in candidates}
    assert kinds == {"attribute", "entity"}, (
        f"expected both attribute and entity to survive; got {kinds}"
    )
    assert len(candidates) == 2

    # Both share the same normalized label.
    norms = {c.normalized_label for c in candidates}
    assert norms == {"customer"}


def test_a_b_only_run_preserves_original_plural_label():
    """AC1 backward-compat (per spec §17): for an A+B-only run, the
    existing CandidateConcept.label value carries the same content
    as today. v1.1 must NOT singularize 'customers' to 'customer'
    in the surface label — only normalized_label is canonicalised."""
    from ontozense.core.candidate_graph import build_candidate_graph

    source_a = {
        "concepts": [
            {"name": "customers", "definition": "Bank clients (plural)."},
        ],
        "relationships": [],
    }
    graph = build_candidate_graph(source_a=source_a)
    assert len(graph.concepts) == 1
    c = graph.concepts[0]
    # AC1: original surface label preserved.
    assert c.label == "customers"
    # But the merge key IS canonicalised so cross-source merge still works.
    assert c.normalized_label == "customer"


def test_alias_map_still_changes_surface_label():
    """An explicit alias_map entry IS authoritative for the surface
    label (this preserves the pre-v1.1 alias-resolution behaviour).
    Only the singularisation/prefix-strip steps leave label alone."""
    from ontozense.core.candidate_graph import build_candidate_graph

    source_a = {
        "concepts": [{"name": "client"}],
        "relationships": [],
    }
    graph = build_candidate_graph(
        source_a=source_a,
        alias_map={"client": "Customer"},
    )
    assert len(graph.concepts) == 1
    c = graph.concepts[0]
    # alias_map fired: 'client' -> 'Customer'. Surface label changes.
    assert c.label == "Customer"


def test_alias_map_relabels_existing_candidate_on_merge():
    """Per spec: 'alias_map is authoritative for the surface label'.
    The order-dependent variant: ingest 'customers' FIRST (surface
    preserved as 'customers'), THEN ingest 'client' with alias_map
    {'client': 'Customer'}. The alias_map should win — the final
    candidate's label is 'Customer'. The previous surface forms
    should be preserved in aliases."""
    from ontozense.core.candidate_graph import _CandidateIndex, _upsert

    index = _CandidateIndex()

    # First upsert: no alias fires; surface 'customers' preserved.
    _upsert(
        index,
        label="customers",
        definition="Bank clients.",
        source_type="A",
        source_artifact="docs.md",
        raw_type="Entity",
        eid="",
        artifact_kind="entity",
        strength="medium",
        promotion_reason="Source A.",
        suppression_reason=None,
        suppressed=False,
    )
    assert len(index.values()) == 1
    assert index.values()[0].label == "customers"

    # Second upsert: alias_map fires on 'client' -> 'Customer'.
    # Both inputs share the normalised form 'customer', so they
    # merge into the same candidate.
    _upsert(
        index,
        label="client",
        definition="A bank client.",
        source_type="B",
        source_artifact="glossary.json",
        raw_type="Entity",
        eid="",
        artifact_kind="entity",
        strength="medium",
        promotion_reason="Source B.",
        suppression_reason=None,
        suppressed=False,
        alias_map={"client": "Customer"},
    )

    # Still one merged candidate.
    candidates = index.values()
    assert len(candidates) == 1
    c = candidates[0]

    # alias_map fired on the second upsert: surface label flipped
    # to 'Customer' (authoritative per spec).
    assert c.label == "Customer", (
        f"expected label='Customer' after alias_map fire on merge; "
        f"got label={c.label!r}"
    )

    # Both source-presence bits set (merge happened correctly).
    assert c.source_presence["A"] is True
    assert c.source_presence["B"] is True

    # Original surface forms preserved in aliases.
    assert "customers" in c.aliases or "client" in c.aliases


def test_normalisation_keeps_compound_us_suffix_words():
    """v1.1.1 follow-up #94: inflect mangles 'loan_status' to
    'loan_statu' and 'CustomerStatus' to 'CustomerStatu'. The
    round-trip guard didn't catch these (the s->s round-trip is
    reversible). Forward suffix-denylist for 'us'/'ss'/'is'
    closes the gap."""
    from ontozense.core.candidate_graph import _resolve_alias_with_normalisation

    # Underscore-compound -us suffix
    canon, fired = _resolve_alias_with_normalisation("loan_status", {})
    assert canon == "loan_status", f"got {canon!r}"
    assert fired is False

    # Camel-case <word>Status
    canon, fired = _resolve_alias_with_normalisation("CustomerStatus", {})
    assert canon == "CustomerStatus", f"got {canon!r}"
    assert fired is False

    # -ss suffix (was already guarded by round-trip; pin it explicitly)
    canon, fired = _resolve_alias_with_normalisation("Address", {})
    assert canon == "Address", f"got {canon!r}"
    assert fired is False

    # -is suffix (analysis, basis, …)
    canon, fired = _resolve_alias_with_normalisation("analysis", {})
    assert canon == "analysis", f"got {canon!r}"
    assert fired is False


def test_normalisation_still_singularises_clean_plurals():
    """The denylist must NOT regress clean plural cases."""
    from ontozense.core.candidate_graph import _resolve_alias_with_normalisation

    canon, fired = _resolve_alias_with_normalisation("customers", {})
    assert canon == "customer"
    assert fired is False

    canon, fired = _resolve_alias_with_normalisation("countries", {})
    assert canon == "country"

    canon, fired = _resolve_alias_with_normalisation("addresses", {})
    assert canon == "address"

    canon, fired = _resolve_alias_with_normalisation("orders", {})
    assert canon == "order"

    # Singular forms already correct — pass through unchanged.
    canon, fired = _resolve_alias_with_normalisation("customer", {})
    assert canon == "customer"


def test_synthetic_fk_label_bypasses_canonicalisation_only_for_source_c():
    """v1.1.1 follow-up #95 (corrected): the synthetic FK bypass
    applies ONLY when source_type=='C'. A non-Source-C label that
    happens to contain '__' twice (e.g. iso__20022__message from a
    governance source) must still flow through alias_map and
    singularisation."""
    from ontozense.core.candidate_graph import _resolve_alias_with_normalisation

    # Source C synthetic FK label: bypass applies.
    canon, fired = _resolve_alias_with_normalisation(
        "customers__country_code__countries", {}, source_type="C",
    )
    assert canon == "customers__country_code__countries"
    assert fired is False

    # Mixed-case Source C label: bypass applies.
    canon, fired = _resolve_alias_with_normalisation(
        "loan__customer_id__customers", {}, source_type="C",
    )
    assert canon == "loan__customer_id__customers"

    # Source C synthetic FK with alias_map: bypass still applies.
    # Source C ingester emits these as synthetic IDs, never as
    # user-facing labels, so alias_map must not fire for them.
    canon, fired = _resolve_alias_with_normalisation(
        "customers__country_code__countries",
        {"customers__country_code__countries": "Something Else"},
        source_type="C",
    )
    assert canon == "customers__country_code__countries"
    assert fired is False


def test_double_underscore_label_from_non_c_source_canonicalises():
    """A label with the '__' shape from any source OTHER than C
    must flow through normalisation normally. iso__20022__message
    (a real ISO 20022 identifier shape that a governance term might
    legitimately use) must still respect alias_map and the rest of
    the pipeline."""
    from ontozense.core.candidate_graph import _resolve_alias_with_normalisation

    # Source A/B/D with double-underscores: NO bypass. alias_map fires.
    canon, fired = _resolve_alias_with_normalisation(
        "iso__20022__message",
        {"iso__20022__message": "ISO 20022 Message"},
        source_type="B",
    )
    assert canon == "ISO 20022 Message"
    assert fired is True

    # Source D: no bypass either.
    canon, fired = _resolve_alias_with_normalisation(
        "iso__20022__message",
        {"iso__20022__message": "ISO 20022 Message"},
        source_type="D",
    )
    assert canon == "ISO 20022 Message"
    assert fired is True

    # Empty source_type (back-compat default): NO bypass.
    # Non-C callers like _resolve_endpoint_to_candidate_id (which
    # doesn't know the source of the endpoint label) pass empty.
    canon, fired = _resolve_alias_with_normalisation(
        "iso__20022__message", {},
    )
    # Without source_type="C", the double-underscore shape carries
    # no special meaning. Falls through normal canonicalisation.
    # 'iso__20022__message' has no plural-suffix issue, no alias map
    # match, no prefix -> returned as-is.
    assert canon == "iso__20022__message"
    assert fired is False


def test_non_synthetic_labels_still_canonicalise_normally():
    """Sanity check: the FK-bypass must NOT regress regular labels
    that happen to contain a single double-underscore (rare but
    possible, e.g. Python's __init__ — though that won't appear at
    this layer in practice)."""
    from ontozense.core.candidate_graph import _resolve_alias_with_normalisation

    # Regular plural with no synthetic FK shape.
    canon, _ = _resolve_alias_with_normalisation("customers", {})
    assert canon == "customer"
