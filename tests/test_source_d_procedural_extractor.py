from pathlib import Path

from ontozense.core.ingest.source_d.ir import RuleFact
from ontozense.core.ingest.source_d.parse import parse_module
from ontozense.core.ingest.source_d.procedural_extractor import extract_procedural

FIXTURES = Path(__file__).parent / "fixtures" / "source_d"


def test_procedural_extracts_validation_rule():
    pm = parse_module(FIXTURES / "procedural_fixture.py")
    facts = list(extract_procedural(pm))
    rules = [f for f in facts if isinstance(f, RuleFact) and f.rule_kind == "validation"]
    assert any(
        r.subject_attribute == "amount" and r.predicate in {"gt", "gte"} and r.object_value == 0
        for r in rules
    )


def test_procedural_extracts_defaulting_rule():
    pm = parse_module(FIXTURES / "procedural_fixture.py")
    facts = list(extract_procedural(pm))
    rules = [f for f in facts if isinstance(f, RuleFact) and f.rule_kind == "defaulting"]
    assert any(
        r.subject_attribute == "currency" and r.object_value == "EUR"
        for r in rules
    )


def test_procedural_validate_function_yields_at_least_weak_rule(tmp_path):
    f = tmp_path / "v.py"
    f.write_text(
        "def validate_score(score):\n"
        "    return True\n"
    )
    pm = parse_module(f)
    facts = list(extract_procedural(pm))
    rules = [r for r in facts if isinstance(r, RuleFact)]
    assert rules, "expected at least one rule from a validate_* function"
