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
