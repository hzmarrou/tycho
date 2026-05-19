from ontozense.core.ingest.base import ArtifactKind, Strength
from ontozense.core.ingest.source_d.emit import emit_candidates
from ontozense.core.ingest.source_d.ir import (
    AttributeFact,
    EntityFact,
    EvidenceSpan,
    RuleFact,
    VocabularyFact,
)


def _span():
    return EvidenceSpan(file="f.py", start_line=1, end_line=1, snippet="")


def test_emit_entity_to_strong_candidate():
    cands = list(emit_candidates([EntityFact(name="Loan", evidence_span=_span(), extractor_family="model")], suppressed=[]))
    assert any(c.artifact_kind == ArtifactKind.ENTITY and c.label == "Loan" and c.strength == Strength.STRONG for c in cands)


def test_emit_rule_populates_rule_payload():
    rule = RuleFact(
        rule_kind="validation", subject_entity="Loan", subject_attribute="amount",
        predicate="gt", object_value=0, expression="amount > 0",
        evidence_span=_span(), code_context="class Loan", confidence=0.9, extractor_family="model",
    )
    cands = list(emit_candidates([rule], suppressed=[]))
    rule_cands = [c for c in cands if c.artifact_kind == ArtifactKind.RULE]
    assert len(rule_cands) == 1
    assert rule_cands[0].rule_payload["predicate"] == "gt"
    assert rule_cands[0].strength == Strength.STRONG


def test_emit_suppressed_rule_is_audit_only():
    rule = RuleFact(
        rule_kind="validation", subject_entity=None, subject_attribute=None,
        predicate="required", object_value="validate_score", expression="validate_score",
        evidence_span=_span(), code_context="def validate_score", confidence=0.4, extractor_family="procedural",
    )
    cands = list(emit_candidates([], suppressed=[(rule, "unanchored:reason")]))
    audit = [c for c in cands if c.suppressed]
    assert len(audit) == 1
    assert audit[0].suppression_reason == "unanchored:reason"
    assert audit[0].rule_payload is not None


def test_emit_attribute_to_strong_candidate():
    attr = AttributeFact(
        name="amount",
        subject_entity="Loan",
        evidence_span=_span(),
        extractor_family="model",
        annotation="float",
    )
    cands = list(emit_candidates([attr], suppressed=[]))
    assert len(cands) == 1
    c = cands[0]
    assert c.artifact_kind == ArtifactKind.ATTRIBUTE
    assert c.label == "Loan.amount"
    assert c.strength == Strength.STRONG
    assert c.raw_type == "attribute"


def test_emit_vocabulary_to_medium_candidate():
    vocab = VocabularyFact(
        name="LoanStatus",
        members=["PERFORMING", "NON_PERFORMING"],
        evidence_span=_span(),
        extractor_family="model",
    )
    cands = list(emit_candidates([vocab], suppressed=[]))
    assert len(cands) == 1
    c = cands[0]
    assert c.artifact_kind == ArtifactKind.VOCABULARY
    assert c.label == "LoanStatus"
    assert c.strength == Strength.MEDIUM
    assert "model" in c.promotion_reason  # extractor_family used


def test_emit_behavior_to_weak_candidate():
    from ontozense.core.ingest.source_d.ir import BehaviorFact
    behavior = BehaviorFact(
        name="approve",
        subject_entity="Loan",
        evidence_span=_span(),
        extractor_family="model",
    )
    cands = list(emit_candidates([behavior], suppressed=[]))
    assert len(cands) == 1
    c = cands[0]
    assert c.artifact_kind == ArtifactKind.BEHAVIOR
    assert c.label == "Loan.approve"
    assert c.strength == Strength.WEAK


def test_emit_rule_strength_at_boundaries():
    """_rule_strength uses >=0.85 for STRONG and >=0.6 for MEDIUM.
    Pin the boundary behavior."""
    base_kwargs = dict(
        rule_kind="validation",
        subject_entity="Loan",
        subject_attribute="amount",
        predicate="gt",
        object_value=0,
        expression="amount > 0",
        evidence_span=_span(),
        code_context="",
        extractor_family="model",
    )

    # Exactly 0.85 -> STRONG (inclusive boundary).
    r_strong = RuleFact(confidence=0.85, **base_kwargs)
    c_strong = list(emit_candidates([r_strong], suppressed=[]))[0]
    assert c_strong.strength == Strength.STRONG

    # Just under 0.85 (0.84) -> MEDIUM.
    r_medium_top = RuleFact(confidence=0.84, **base_kwargs)
    c_medium_top = list(emit_candidates([r_medium_top], suppressed=[]))[0]
    assert c_medium_top.strength == Strength.MEDIUM

    # Exactly 0.6 -> MEDIUM (inclusive boundary).
    r_medium_low = RuleFact(confidence=0.6, **base_kwargs)
    c_medium_low = list(emit_candidates([r_medium_low], suppressed=[]))[0]
    assert c_medium_low.strength == Strength.MEDIUM

    # Just under 0.6 (0.59) -> WEAK.
    r_weak = RuleFact(confidence=0.59, **base_kwargs)
    c_weak = list(emit_candidates([r_weak], suppressed=[]))[0]
    assert c_weak.strength == Strength.WEAK


def test_emit_orchestrator_yields_facts_before_suppressed():
    """emit_candidates must yield facts in order, then suppressed
    candidates after — downstream consumers can rely on this."""
    entity = EntityFact(name="Loan", evidence_span=_span(), extractor_family="model")
    suppressed_rule = RuleFact(
        rule_kind="validation",
        subject_entity=None,
        subject_attribute=None,
        predicate="required",
        object_value="x",
        expression="x",
        evidence_span=_span(),
        code_context="",
        confidence=0.4,
        extractor_family="procedural",
    )
    out = list(emit_candidates([entity], suppressed=[(suppressed_rule, "unanchored:reason")]))
    assert len(out) == 2
    # Entity (fact) before suppressed audit candidate.
    assert out[0].artifact_kind == ArtifactKind.ENTITY
    assert out[0].suppressed is False
    assert out[1].artifact_kind == ArtifactKind.RULE
    assert out[1].suppressed is True


def test_emit_raises_on_unknown_fact_type():
    """Future IR additions must surface immediately, not be silently
    dropped."""
    class _NewFact:
        pass

    import pytest
    with pytest.raises(TypeError, match="unknown IR fact type"):
        list(emit_candidates([_NewFact()], suppressed=[]))
