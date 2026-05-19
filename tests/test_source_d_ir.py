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
