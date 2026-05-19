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


def test_procedural_no_rule_when_rhs_is_variable(tmp_path):
    """A guard whose RHS is a name (not a literal) is not a structured
    rule. Confirms the `isinstance(rhs, ast.Constant)` guard pins."""
    f = tmp_path / "v.py"
    f.write_text(
        "def check_amount(payload, threshold):\n"
        "    if payload['amount'] <= threshold:\n"
        "        raise ValueError('too small')\n"
    )
    pm = parse_module(f)
    facts = list(extract_procedural(pm))
    rules = [r for r in facts if isinstance(r, RuleFact)]
    # check_amount matches the validate-prefix family (check_*), so the
    # weak fallback still fires — but no STRUCTURED validation rule
    # should be emitted (rhs is not a literal).
    structured = [
        r for r in rules
        if r.rule_kind == "validation"
        and r.subject_attribute == "amount"
        and r.predicate in {"gt", "gte"}
    ]
    assert structured == [], f"unexpected structured rule on amount: {structured}"


def test_procedural_truthiness_does_not_fire_defaulting(tmp_path):
    """`.get(x):` (truthiness) is NOT `.get(x) is None`. The defaulting
    extractor must distinguish them."""
    f = tmp_path / "v.py"
    f.write_text(
        "def normalize(p):\n"
        "    if p.get('currency'):\n"
        "        p['currency'] = p['currency'].upper()\n"
        "    return p\n"
    )
    pm = parse_module(f)
    facts = list(extract_procedural(pm))
    rules = [r for r in facts if isinstance(r, RuleFact) and r.rule_kind == "defaulting"]
    assert rules == [], f"truthiness check should not produce defaulting rule: {rules}"


def test_procedural_non_validate_function_with_no_body_yields_no_rule(tmp_path):
    """A function whose body matches no extraction pattern AND whose
    name does not match validate_/check_/assert_ prefixes must produce
    zero rules."""
    f = tmp_path / "v.py"
    f.write_text(
        "def process(x):\n"
        "    return x * 2\n"
        "\n"
        "def helper(p):\n"
        "    return p['amount'] + 1\n"
    )
    pm = parse_module(f)
    facts = list(extract_procedural(pm))
    rules = [r for r in facts if isinstance(r, RuleFact)]
    assert rules == [], f"expected zero rules from non-validate functions: {rules}"
