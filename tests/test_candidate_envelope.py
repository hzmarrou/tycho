"""Round-trip tests for rule_payload on IntermediateCandidate and CandidateConcept."""
from ontozense.core.ingest.base import (
    ArtifactKind,
    IntermediateCandidate,
    Strength,
)
from ontozense.core.discovery_contracts import CandidateConcept


def _concept(**overrides):
    """Build a CandidateConcept with all required fields filled in."""
    base = dict(
        candidate_id="cid_1",
        label="Loan.amount gt 0",
        normalized_label="loan.amount gt 0",
        suggested_entity_type="Rule",
        classification="unknown",
        summary_definition="amount > 0",
        source_presence={"A": False, "B": False, "C": False, "D": True},
        source_counts={"A": 0, "B": 0, "C": 0, "D": 1},
        artifact_kind="rule",
        strength="strong",
    )
    base.update(overrides)
    return CandidateConcept(**base)


def test_intermediate_candidate_rule_payload_defaults_to_none():
    c = IntermediateCandidate(
        label="Loan.amount gt 0",
        definition="amount must be positive",
        source_type="D",
        source_artifact="loans.py:L12",
        raw_type="rule:validation",
        eid="",
        artifact_kind=ArtifactKind.RULE,
        strength=Strength.STRONG,
        promotion_reason="test",
    )
    assert c.rule_payload is None


def test_intermediate_candidate_accepts_rule_payload():
    payload = {
        "rule_kind": "validation",
        "subject_entity": "Loan",
        "subject_attribute": "amount",
        "predicate": "gt",
        "object_value": 0,
        "expression": "amount > 0",
        "evidence_span": {"file": "loans.py", "start_line": 12, "end_line": 14, "snippet": "if amount <= 0: raise"},
        "normalization_status": "deterministic",
    }
    c = IntermediateCandidate(
        label="Loan.amount gt 0",
        definition="amount must be positive",
        source_type="D",
        source_artifact="loans.py:L12",
        raw_type="rule:validation",
        eid="",
        artifact_kind=ArtifactKind.RULE,
        strength=Strength.STRONG,
        promotion_reason="test",
        rule_payload=payload,
    )
    assert c.rule_payload["predicate"] == "gt"


def test_candidate_concept_rule_payload_defaults_to_none():
    cc = _concept()
    assert cc.rule_payload is None


def test_candidate_concept_rule_payload_roundtrip():
    payload = {
        "rule_kind": "validation", "subject_entity": "Loan", "subject_attribute": "amount",
        "predicate": "gt", "object_value": 0,
        "expression": "amount > 0",
        "evidence_span": {"file": "loans.py", "start_line": 1, "end_line": 1, "snippet": ""},
        "normalization_status": "deterministic",
    }
    cc = _concept(rule_payload=payload)
    d = cc.to_dict()
    assert d["rule_payload"]["predicate"] == "gt"
    roundtripped = CandidateConcept.from_dict(d)
    assert roundtripped.rule_payload == payload


def test_rule_payloads_with_same_canonical_label_but_different_kind_do_not_collide():
    """A validation rule and a defaulting rule with the same surface
    label must remain distinct after merge."""
    from ontozense.core.candidate_graph import _CandidateIndex, _upsert

    payload_a = {
        "rule_kind": "validation", "subject_entity": "loan",
        "subject_attribute": "amount", "predicate": "gt", "object_value": 0,
        "condition": None, "expression": "amount > 0",
        "evidence_span": {"file": "a.py", "start_line": 1, "end_line": 1, "snippet": ""},
        "normalization_status": "deterministic",
    }
    payload_b = {
        "rule_kind": "defaulting", "subject_entity": "loan",
        "subject_attribute": "amount", "predicate": "gt", "object_value": 0,
        "condition": None, "expression": "amount > 0",
        "evidence_span": {"file": "b.py", "start_line": 1, "end_line": 1, "snippet": ""},
        "normalization_status": "deterministic",
    }

    index = _CandidateIndex()

    # Upsert both candidates with the same surface label but different rule_payloads.
    # The by_rule_key index should keep them distinct because merge_key(payload_a)
    # != merge_key(payload_b) (different rule_kind).
    _upsert(
        index,
        label="loan.amount gt 0",
        definition="amount > 0",
        source_type="D",
        source_artifact="a.py:L1",
        raw_type="rule:validation",
        artifact_kind="rule",
        strength="strong",
        promotion_reason="test",
        rule_payload=payload_a,
    )
    _upsert(
        index,
        label="loan.amount gt 0",
        definition="amount > 0",
        source_type="D",
        source_artifact="b.py:L1",
        raw_type="rule:defaulting",
        artifact_kind="rule",
        strength="strong",
        promotion_reason="test",
        rule_payload=payload_b,
    )

    # Two distinct CandidateConcepts must exist — one per rule_kind.
    rule_concepts = [
        c for c in index.values()
        if c.artifact_kind == "rule"
    ]
    assert len(rule_concepts) == 2, (
        f"Expected 2 distinct rule candidates, got {len(rule_concepts)}: "
        f"{[c.rule_payload.get('rule_kind') for c in rule_concepts]}"
    )
    rule_kinds = {c.rule_payload["rule_kind"] for c in rule_concepts}
    assert rule_kinds == {"validation", "defaulting"}
    assert len(index.by_rule_key) == 2, (
        f"by_rule_key should have two distinct entries; got {dict(index.by_rule_key)}"
    )


def test_rule_store_key_is_collision_safe_across_colons_in_components():
    """Two structurally distinct rule tuples must never produce the
    same store key, even when components contain ':' characters."""
    from ontozense.core.candidate_graph import _rule_store_key

    a = ("validation", "loan", "amount", "gt", 0, None)
    b = ("validation", "loan:amount", "gt:0", "", "", None)
    # Both have the same naive ':'.join(...) representation but are
    # structurally distinct. Their store keys must differ.
    assert _rule_store_key(a) != _rule_store_key(b)


def test_rule_candidates_with_same_eid_but_different_rule_keys_do_not_collide():
    """When two rule candidates share an eid but have distinct merge_keys
    (e.g. different rule_kind), both must remain as separate concepts.
    The store key is rule-derived; eid is only a secondary alias."""
    from ontozense.core.candidate_graph import _CandidateIndex, _upsert
    from ontozense.core.ingest.base import ArtifactKind, IntermediateCandidate, Strength

    def _payload(kind):
        return {
            "rule_kind": kind, "subject_entity": "loan",
            "subject_attribute": "amount", "predicate": "gt", "object_value": 0,
            "condition": None, "expression": "amount > 0",
            "evidence_span": {"file": "x.py", "start_line": 1, "end_line": 1, "snippet": ""},
            "normalization_status": "deterministic",
        }

    index = _CandidateIndex()
    # Both rule candidates share eid="loan-rule" but have distinct rule_kinds.
    for kind in ("validation", "defaulting"):
        _upsert(
            index,
            label="loan.amount gt 0",
            definition="amount > 0",
            source_type="D",
            source_artifact=f"{kind}.py:L1",
            raw_type=f"rule:{kind}",
            eid="loan-rule",
            artifact_kind="rule",
            strength="strong",
            promotion_reason="test",
            rule_payload=_payload(kind),
        )

    assert len(index.by_rule_key) == 2
    assert len(index.values()) == 2
    rule_kinds = {c.rule_payload["rule_kind"] for c in index.values()}
    assert rule_kinds == {"validation", "defaulting"}
