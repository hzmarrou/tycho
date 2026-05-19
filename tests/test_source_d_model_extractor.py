from pathlib import Path

from ontozense.core.ingest.source_d.ir import (
    AttributeFact,
    BehaviorFact,
    EntityFact,
    VocabularyFact,
)
from ontozense.core.ingest.source_d.model_extractor import extract_model
from ontozense.core.ingest.source_d.parse import parse_module

FIXTURES = Path(__file__).parent / "fixtures" / "source_d"


def test_model_extractor_emits_entities():
    pm = parse_module(FIXTURES / "model_fixture.py")
    facts = list(extract_model(pm))
    entities = [f for f in facts if isinstance(f, EntityFact)]
    assert {e.name for e in entities} >= {"Borrower", "Loan"}


def test_model_extractor_emits_enum_vocabularies():
    pm = parse_module(FIXTURES / "model_fixture.py")
    facts = list(extract_model(pm))
    vocabs = [f for f in facts if isinstance(f, VocabularyFact)]
    names = {v.name for v in vocabs}
    assert "LoanStatus" in names


def test_model_extractor_emits_attributes_anchored_to_entity():
    pm = parse_module(FIXTURES / "model_fixture.py")
    facts = list(extract_model(pm))
    attrs = [f for f in facts if isinstance(f, AttributeFact)]
    by_entity = {(a.subject_entity, a.name) for a in attrs}
    assert ("Borrower", "credit_score") in by_entity
    assert ("Loan", "amount") in by_entity


def test_model_extractor_emits_methods_as_behaviors():
    pm = parse_module(FIXTURES / "model_fixture.py")
    facts = list(extract_model(pm))
    behaviors = [f for f in facts if isinstance(f, BehaviorFact)]
    names = {b.name for b in behaviors}
    assert "amount_must_be_positive" in names
