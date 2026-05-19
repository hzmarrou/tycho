from ontozense.core.ingest.source_d.anchor import anchor_facts
from ontozense.core.ingest.source_d.ir import (
    AttributeFact,
    EntityFact,
    EvidenceSpan,
    RuleFact,
)


def _span():
    return EvidenceSpan(file="f.py", start_line=1, end_line=1, snippet="")


def test_anchor_resolves_subject_entity_via_attribute():
    facts = [
        EntityFact(name="Loan", evidence_span=_span(), extractor_family="model"),
        AttributeFact(name="amount", subject_entity="Loan", evidence_span=_span(), extractor_family="model"),
        RuleFact(
            rule_kind="validation", subject_entity=None, subject_attribute="amount",
            predicate="gt", object_value=0, expression="amount > 0",
            evidence_span=_span(), code_context="", confidence=0.9, extractor_family="pipeline",
        ),
    ]
    anchored, suppressed = anchor_facts(facts)
    rule = [f for f in anchored if isinstance(f, RuleFact)][0]
    assert rule.subject_entity == "Loan"
    assert suppressed == []


def test_anchor_keeps_unresolved_rule_with_attribute_only():
    facts = [
        RuleFact(
            rule_kind="validation", subject_entity=None, subject_attribute="amount",
            predicate="gt", object_value=0, expression="amount > 0",
            evidence_span=_span(), code_context="", confidence=0.9, extractor_family="pipeline",
        ),
    ]
    anchored, suppressed = anchor_facts(facts)
    assert [r for r in anchored if isinstance(r, RuleFact)]
    assert suppressed == []


def test_anchor_suppresses_when_both_subject_fields_missing():
    facts = [
        RuleFact(
            rule_kind="validation", subject_entity=None, subject_attribute=None,
            predicate="required", object_value="validate_score", expression="validate_score",
            evidence_span=_span(), code_context="def validate_score", confidence=0.4, extractor_family="procedural",
        ),
    ]
    anchored, suppressed = anchor_facts(facts)
    assert not [r for r in anchored if isinstance(r, RuleFact)]
    assert suppressed and "unanchored" in suppressed[0][1]
