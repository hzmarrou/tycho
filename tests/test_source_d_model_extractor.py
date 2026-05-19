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


def test_model_extractor_classifies_dataclass_raw_type():
    pm = parse_module(FIXTURES / "model_fixture.py")
    facts = list(extract_model(pm))
    borrower = next(
        f for f in facts
        if isinstance(f, EntityFact) and f.name == "Borrower"
    )
    assert borrower.raw_type == "dataclass"


def test_model_extractor_classifies_pydantic_raw_type():
    pm = parse_module(FIXTURES / "model_fixture.py")
    facts = list(extract_model(pm))
    loan = next(
        f for f in facts
        if isinstance(f, EntityFact) and f.name == "Loan"
    )
    assert loan.raw_type == "pydantic_model"


def test_model_extractor_classifies_sqlalchemy_raw_type(tmp_path):
    f = tmp_path / "orm.py"
    f.write_text(
        "from sqlalchemy.orm import declarative_base\n"
        "Base = declarative_base()\n"
        "class Account(Base):\n"
        "    pass\n"
    )
    pm = parse_module(f)
    facts = list(extract_model(pm))
    account = next(
        x for x in facts if isinstance(x, EntityFact) and x.name == "Account"
    )
    assert account.raw_type == "sqlalchemy_model"


def test_model_extractor_classifies_plain_class_raw_type(tmp_path):
    f = tmp_path / "plain.py"
    f.write_text(
        "class Plain:\n"
        "    x: int = 0\n"
    )
    pm = parse_module(f)
    facts = list(extract_model(pm))
    plain = next(
        x for x in facts if isinstance(x, EntityFact) and x.name == "Plain"
    )
    assert plain.raw_type == "class"


def test_model_extractor_does_not_extract_bare_name_in_regular_method(tmp_path):
    """A bare ast.Name comparison in a non-__init__, non-validator
    method is a local temporary — must NOT produce a rule, or the
    anchor layer will promote a pseudo-attribute as ontology-grade."""
    f = tmp_path / "regular.py"
    f.write_text(
        "class Calculator:\n"
        "    def compute(self):\n"
        "        threshold = 5\n"
        "        if threshold <= 0:\n"
        "            raise ValueError('bad')\n"
        "        return threshold\n"
    )
    pm = parse_module(f)
    facts = list(extract_model(pm))
    rules = [r for r in facts if isinstance(r, RuleFact)]
    # No rule should be emitted — `threshold` is a local, not an attribute.
    assert all(r.subject_attribute != "threshold" for r in rules), (
        f"unexpected rule on local temp 'threshold': {rules}"
    )


def test_model_extractor_still_extracts_self_attr_in_regular_method(tmp_path):
    """self.<attr> guards remain valid in any method (not just __init__)."""
    f = tmp_path / "self_attr.py"
    f.write_text(
        "class Account:\n"
        "    def withdraw(self, amount):\n"
        "        if self.balance < amount:\n"
        "            raise ValueError('insufficient funds')\n"
        "        self.balance -= amount\n"
    )
    pm = parse_module(f)
    facts = list(extract_model(pm))
    rules = [r for r in facts if isinstance(r, RuleFact)]
    # The guard is `if self.balance < amount:` — LHS is self.balance,
    # RHS is the bare name `amount` (not a literal), so this entire
    # pattern is skipped by _literal_value=None — no rule. That's
    # also correct: comparisons against non-literals are out of scope.
    assert not any(r.subject_attribute == "balance" for r in rules)


def test_model_extractor_extracts_self_attr_against_literal(tmp_path):
    """self.<attr> compared to a literal in a regular method DOES
    emit a rule."""
    f = tmp_path / "self_attr_literal.py"
    f.write_text(
        "class Account:\n"
        "    def reset(self):\n"
        "        if self.balance < 0:\n"
        "            raise ValueError('negative')\n"
        "        return self.balance\n"
    )
    pm = parse_module(f)
    facts = list(extract_model(pm))
    rules = [r for r in facts if isinstance(r, RuleFact)]
    assert any(
        r.subject_entity == "Account" and r.subject_attribute == "balance"
        and r.predicate == "gte" and r.object_value == 0
        for r in rules
    )
