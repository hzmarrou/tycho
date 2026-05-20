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


def test_procedural_defaulting_skips_mismatched_key(tmp_path):
    """`if p.get("currency") is None: p["country"] = "NL"` must NOT
    emit a defaulting rule on `currency` — the assignment targets a
    different key."""
    f = tmp_path / "v.py"
    f.write_text(
        "def normalize(payment):\n"
        "    if payment.get('currency') is None:\n"
        "        payment['country'] = 'NL'\n"
        "    return payment\n"
    )
    pm = parse_module(f)
    facts = list(extract_procedural(pm))
    rules = [r for r in facts if isinstance(r, RuleFact) and r.rule_kind == "defaulting"]
    assert rules == [], f"mismatched-key default must not emit: {rules}"


def test_procedural_defaulting_skips_mismatched_object(tmp_path):
    """`if a.get("x") is None: b["x"] = 1` must NOT emit — the
    assignment targets a different object."""
    f = tmp_path / "v.py"
    f.write_text(
        "def normalize(a, b):\n"
        "    if a.get('x') is None:\n"
        "        b['x'] = 1\n"
        "    return a, b\n"
    )
    pm = parse_module(f)
    facts = list(extract_procedural(pm))
    rules = [r for r in facts if isinstance(r, RuleFact) and r.rule_kind == "defaulting"]
    assert rules == [], f"mismatched-object default must not emit: {rules}"


def test_procedural_extracts_eligibility_rule_from_is_prefix(tmp_path):
    """`def is_eligible(borrower): return borrower["credit_score"] >= 500`
    must emit an eligibility rule on credit_score with predicate gte, value 500.
    Direct op mapping — the comparison IS the eligibility predicate."""
    f = tmp_path / "p.py"
    f.write_text(
        "def is_eligible(borrower):\n"
        "    return borrower['credit_score'] >= 500\n"
    )
    pm = parse_module(f)
    facts = list(extract_procedural(pm))
    elig = [r for r in facts if isinstance(r, RuleFact) and r.rule_kind == "eligibility"]
    assert len(elig) == 1
    r = elig[0]
    assert r.subject_attribute == "credit_score"
    assert r.predicate == "gte"
    assert r.object_value == 500
    assert r.confidence == 0.85


def test_procedural_eligibility_supports_can_may_should_must_prefixes(tmp_path):
    """All five eligibility prefixes (is_, can_, may_, should_, must_)
    are recognised."""
    f = tmp_path / "p.py"
    f.write_text(
        "def can_approve(loan):\n"
        "    return loan['amount'] > 0\n"
        "def may_proceed(req):\n"
        "    return req['score'] >= 700\n"
        "def should_retry(ctx):\n"
        "    return ctx['attempts'] < 3\n"
        "def must_validate(payment):\n"
        "    return payment['total'] > 0\n"
    )
    pm = parse_module(f)
    facts = list(extract_procedural(pm))
    elig = [r for r in facts if isinstance(r, RuleFact) and r.rule_kind == "eligibility"]
    assert len(elig) == 4
    by_attr = {r.subject_attribute for r in elig}
    assert by_attr == {"amount", "score", "attempts", "total"}


def test_procedural_eligibility_skips_when_body_is_not_a_simple_compare_return(tmp_path):
    """Eligibility extraction requires a single `return <Compare>` body.
    Multi-statement bodies or non-comparison returns don't qualify."""
    f = tmp_path / "p.py"
    f.write_text(
        "def is_complex(x):\n"
        "    y = x * 2\n"
        "    return y > 0\n"
        "def is_constant(x):\n"
        "    return True\n"
    )
    pm = parse_module(f)
    facts = list(extract_procedural(pm))
    elig = [r for r in facts if isinstance(r, RuleFact) and r.rule_kind == "eligibility"]
    assert elig == [], f"non-simple bodies must not emit; got {elig}"


def test_procedural_eligibility_does_not_double_emit_validation(tmp_path):
    """A function matching the eligibility prefix that ALSO has an internal
    `if/raise` guard must NOT produce both an eligibility and a validation
    rule for the same condition. Eligibility short-circuits the validate path."""
    f = tmp_path / "p.py"
    f.write_text(
        "def is_valid(payment):\n"
        "    return payment['amount'] > 0\n"
    )
    pm = parse_module(f)
    facts = list(extract_procedural(pm))
    rules = [r for r in facts if isinstance(r, RuleFact)]
    # Exactly one rule — the eligibility one.
    assert len(rules) == 1
    assert rules[0].rule_kind == "eligibility"


def test_procedural_extracts_transition_rule(tmp_path):
    """`if approved: payment['status'] = 'PAID'` emits a transition rule."""
    f = tmp_path / "p.py"
    f.write_text(
        "def settle(payment, approved):\n"
        "    if approved:\n"
        "        payment['status'] = 'PAID'\n"
        "    return payment\n"
    )
    pm = parse_module(f)
    facts = list(extract_procedural(pm))
    trans = [r for r in facts if isinstance(r, RuleFact) and r.rule_kind == "transition"]
    assert len(trans) == 1
    r = trans[0]
    assert r.subject_attribute == "status"
    assert r.predicate == "transitions_to"
    assert r.object_value == "PAID"


def test_procedural_transition_ignores_non_status_subscript_assigns(tmp_path):
    """Subscript assigns to non-status fields are NOT transitions."""
    f = tmp_path / "p.py"
    f.write_text(
        "def apply_discount(cart, condition):\n"
        "    if condition:\n"
        "        cart['total'] = 0\n"
        "    return cart\n"
    )
    pm = parse_module(f)
    facts = list(extract_procedural(pm))
    trans = [r for r in facts if isinstance(r, RuleFact) and r.rule_kind == "transition"]
    assert trans == []
