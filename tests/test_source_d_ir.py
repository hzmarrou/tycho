import pytest

from ontozense.core.ingest.source_d.ir import (
    AttributeFact,
    BehaviorFact,
    EntityFact,
    EvidenceSpan,
    RuleFact,
    VocabularyFact,
)


def test_evidence_span_required_fields():
    e = EvidenceSpan(file="x.py", start_line=10, end_line=12, snippet="raise X")
    assert e.start_line == 10


def test_rule_fact_defaults():
    r = RuleFact(
        rule_kind="validation",
        subject_entity="Loan",
        subject_attribute="amount",
        predicate="gt",
        object_value=0,
        expression="amount > 0",
        evidence_span=EvidenceSpan(file="f.py", start_line=1, end_line=1, snippet=""),
        code_context="class Loan",
        confidence=0.9,
        extractor_family="model",
    )
    assert r.condition is None
    assert r.depends_on == []


def test_entity_fact_defaults():
    e = EntityFact(name="Loan", evidence_span=EvidenceSpan(file="f.py", start_line=1, end_line=1, snippet=""), extractor_family="model")
    assert e.docstring is None
    assert e.bases == []


def test_rule_fact_to_payload_roundtrip():
    r = RuleFact(
        rule_kind="validation",
        subject_entity="Loan",
        subject_attribute="amount",
        predicate="gt",
        object_value=0,
        condition=None,
        depends_on=["amount"],
        expression="amount > 0",
        evidence_span=EvidenceSpan(file="f.py", start_line=1, end_line=1, snippet="x"),
        code_context="class Loan",
        confidence=0.9,
        extractor_family="model",
    )
    p = r.to_payload()
    assert p["rule_kind"] == "validation"
    assert p["subject_attribute"] == "amount"
    assert p["evidence_span"]["file"] == "f.py"
    assert p["normalization_status"] == "deterministic"


def test_attribute_fact_constructs_with_minimal_args():
    a = AttributeFact(
        name="amount",
        evidence_span=EvidenceSpan(file="f.py", start_line=1, end_line=1, snippet=""),
        extractor_family="model",
    )
    assert a.subject_entity is None
    assert a.annotation is None
    assert a.has_default is False


def test_behavior_fact_constructs_with_minimal_args():
    b = BehaviorFact(
        name="amount_must_be_positive",
        evidence_span=EvidenceSpan(file="f.py", start_line=1, end_line=1, snippet=""),
        extractor_family="model",
    )
    assert b.subject_entity is None


def test_vocabulary_fact_constructs():
    v = VocabularyFact(
        name="LoanStatus",
        members=["performing", "non_performing"],
        evidence_span=EvidenceSpan(file="f.py", start_line=1, end_line=1, snippet=""),
        extractor_family="model",
    )
    assert v.members == ["performing", "non_performing"]


def test_rule_fact_is_mutable_for_post_extraction_anchoring():
    """Task 13's anchor layer mutates RuleFact.subject_entity after the
    extractor returns. Pin the mutable contract so a future
    frozen=True regression fails loudly."""
    r = RuleFact(
        rule_kind="validation", subject_entity=None, subject_attribute="amount",
        predicate="gt", object_value=0, expression="amount > 0",
        evidence_span=EvidenceSpan(file="f.py", start_line=1, end_line=1, snippet=""),
        code_context="def validate_amount", confidence=0.85, extractor_family="procedural",
    )
    r.subject_entity = "Loan"
    assert r.subject_entity == "Loan"
