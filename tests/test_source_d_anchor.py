from ontozense.core.ingest.source_d.anchor import anchor_facts
from ontozense.core.ingest.source_d.ir import (
    AttributeFact,
    BehaviorFact,
    EntityFact,
    EvidenceSpan,
    RuleFact,
    VocabularyFact,
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


def test_anchor_keeps_ambiguous_multi_match_rule_unresolved():
    """When the rule's subject_attribute matches multiple AttributeFacts
    (different entities both have that field name), the rule is kept
    in anchored but subject_entity stays None — fusion-time may
    disambiguate via Source A/B/C attestation."""
    facts = [
        EntityFact(name="Loan", evidence_span=_span(), extractor_family="model"),
        EntityFact(name="Account", evidence_span=_span(), extractor_family="model"),
        AttributeFact(name="amount", subject_entity="Loan", evidence_span=_span(), extractor_family="model"),
        AttributeFact(name="amount", subject_entity="Account", evidence_span=_span(), extractor_family="model"),
        RuleFact(
            rule_kind="validation", subject_entity=None, subject_attribute="amount",
            predicate="gt", object_value=0, expression="amount > 0",
            evidence_span=_span(), code_context="", confidence=0.85, extractor_family="pipeline",
        ),
    ]
    anchored, suppressed = anchor_facts(facts)
    rule = [f for f in anchored if isinstance(f, RuleFact)][0]
    assert rule.subject_entity is None, (
        "ambiguous rule must stay unresolved (Loan vs Account both have 'amount')"
    )
    assert suppressed == [], "ambiguous rule must not be suppressed — fusion may resolve"


def test_anchor_ignores_attribute_facts_with_none_subject_entity():
    """AttributeFacts emitted by pipeline_extractor (`df["new"] = ...`)
    have subject_entity=None. They must NOT pollute attr_index — the
    rule lookup should treat them as if they didn't exist."""
    facts = [
        # Anchored model AttributeFact for "x" on Loan.
        AttributeFact(name="x", subject_entity="Loan", evidence_span=_span(), extractor_family="model"),
        # Unanchored pipeline AttributeFact for "x" (derived column).
        AttributeFact(name="x", subject_entity=None, evidence_span=_span(), extractor_family="pipeline"),
        RuleFact(
            rule_kind="validation", subject_entity=None, subject_attribute="x",
            predicate="gt", object_value=0, expression="x > 0",
            evidence_span=_span(), code_context="", confidence=0.85, extractor_family="pipeline",
        ),
    ]
    anchored, suppressed = anchor_facts(facts)
    rule = [f for f in anchored if isinstance(f, RuleFact)][0]
    # The unanchored AttributeFact didn't enter the index, so the
    # Loan-anchored one is the only candidate -> resolved.
    assert rule.subject_entity == "Loan", (
        f"unanchored AttributeFact should be ignored; got {rule.subject_entity}"
    )


def test_anchor_passes_through_all_non_rule_fact_kinds():
    """EntityFact, AttributeFact, VocabularyFact, BehaviorFact must
    appear unchanged in the anchored list."""
    span = _span()
    facts = [
        EntityFact(name="Loan", evidence_span=span, extractor_family="model"),
        AttributeFact(name="amount", subject_entity="Loan", evidence_span=span, extractor_family="model"),
        VocabularyFact(name="LoanStatus", members=["A", "B"], evidence_span=span, extractor_family="model"),
        BehaviorFact(name="approve", subject_entity="Loan", evidence_span=span, extractor_family="model"),
    ]
    anchored, suppressed = anchor_facts(facts)
    assert suppressed == []
    # Every input fact must appear in anchored, in some order.
    kinds = {type(f).__name__ for f in anchored}
    assert kinds == {"EntityFact", "AttributeFact", "VocabularyFact", "BehaviorFact"}
    assert len(anchored) == len(facts), "no facts may be silently dropped"
