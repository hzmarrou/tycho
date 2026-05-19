from pathlib import Path

from ontozense.core.ingest.source_d.ir import (
    AttributeFact,
    BehaviorFact,
    EntityFact,
    RuleFact,
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


def test_model_extractor_extracts_pydantic_validator_rule():
    pm = parse_module(FIXTURES / "model_fixture.py")
    facts = list(extract_model(pm))
    rules = [f for f in facts if isinstance(f, RuleFact)]
    amount_rules = [r for r in rules if r.subject_attribute == "amount"]
    assert amount_rules, "expected at least one rule for Loan.amount"
    r = amount_rules[0]
    assert r.subject_entity == "Loan"
    assert r.predicate in {"gt", "gte"}  # synthesised from `if v <= 0: raise`
    assert r.object_value == 0
    assert r.rule_kind == "validation"


def test_model_extractor_extracts_init_guard(tmp_path):
    f = tmp_path / "f.py"
    f.write_text(
        "class Account:\n"
        "    def __init__(self, balance):\n"
        "        if balance < 0:\n"
        "            raise ValueError('negative balance')\n"
        "        self.balance = balance\n"
    )
    pm = parse_module(f)
    facts = list(extract_model(pm))
    rules = [r for r in facts if isinstance(r, RuleFact)]
    assert any(
        r.subject_entity == "Account" and r.subject_attribute == "balance"
        and r.predicate == "gte" and r.object_value == 0
        for r in rules
    )
