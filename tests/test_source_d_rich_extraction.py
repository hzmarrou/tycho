"""Unit tests for v1.2.1 rich-extraction helpers."""
import ast

from ontozense.core.ingest.source_d.ir import RuleFact
from ontozense.core.ingest.source_d.parse import parse_module
from ontozense.core.ingest.source_d.procedural_extractor import (
    _UNRESOLVED,
    _collect_module_constants,
    _resolve_constant,
    _resolve_subject,
    extract_procedural,
)


def _expr(src: str) -> ast.expr:
    """Parse a single expression string into its ast.expr."""
    module = ast.parse(src, mode="eval")
    return module.body


def test_resolve_subject_param_attribute_access():
    expr = _expr("loan.is_non_performing")
    assert _resolve_subject(expr, {"loan"}) == "is_non_performing"


def test_resolve_subject_param_string_subscript():
    expr = _expr("payment['amount']")
    assert _resolve_subject(expr, {"payment"}) == "amount"


def test_resolve_subject_bare_param():
    expr = _expr("has_active_forbearance")
    assert _resolve_subject(expr, {"has_active_forbearance"}) == "has_active_forbearance"


def test_resolve_subject_rejects_module_level_name():
    expr = _expr("THRESHOLDS")
    assert _resolve_subject(expr, {"loan"}) is None


def test_resolve_subject_rejects_method_call():
    expr = _expr("payment_history.continuous_repayments()")
    assert _resolve_subject(expr, {"payment_history"}) is None


def test_resolve_subject_rejects_chained_attribute():
    expr = _expr("self.config.threshold")
    assert _resolve_subject(expr, {"self"}) is None


def test_resolve_subject_rejects_non_string_subscript():
    expr = _expr("loan[0]")
    assert _resolve_subject(expr, {"loan"}) is None


def test_resolve_subject_rejects_subscript_on_non_param():
    expr = _expr("CONFIG['key']")
    assert _resolve_subject(expr, {"loan"}) is None


def test_collect_module_constants_picks_up_simple_assigns(tmp_path):
    src = tmp_path / "m.py"
    src.write_text(
        "NPE_DPD_THRESHOLD = 90\n"
        "MATERIALITY = 100\n"
        "IFRS_STAGE_IMPAIRED = 'ifrs_stage_3_impaired'\n"
    )
    pm = parse_module(src)
    constants = _collect_module_constants(pm)
    assert constants["NPE_DPD_THRESHOLD"] == 90
    assert constants["MATERIALITY"] == 100
    assert constants["IFRS_STAGE_IMPAIRED"] == "ifrs_stage_3_impaired"


def test_collect_module_constants_ignores_non_constant_values(tmp_path):
    src = tmp_path / "m.py"
    src.write_text(
        "FOO = some_func()\n"
        "BAR = 1 + 2\n"
        "OK = 5\n"
    )
    pm = parse_module(src)
    constants = _collect_module_constants(pm)
    assert "FOO" not in constants
    assert "BAR" not in constants
    assert constants["OK"] == 5


def test_collect_module_constants_ignores_tuple_unpacking(tmp_path):
    src = tmp_path / "m.py"
    src.write_text("A, B = 1, 2\nC = 3\n")
    pm = parse_module(src)
    constants = _collect_module_constants(pm)
    assert "A" not in constants
    assert "B" not in constants
    assert constants["C"] == 3


def test_resolve_constant_returns_literal_value_for_ast_constant():
    node = ast.parse("42", mode="eval").body
    assert _resolve_constant(node, {}) == 42


def test_resolve_constant_resolves_name_from_constants_map():
    node = ast.parse("NPE_DPD_THRESHOLD", mode="eval").body
    assert _resolve_constant(node, {"NPE_DPD_THRESHOLD": 90}) == 90


def test_resolve_constant_returns_unresolved_for_unknown_name():
    node = ast.parse("UNKNOWN", mode="eval").body
    assert _resolve_constant(node, {"OTHER": 1}) is _UNRESOLVED


def test_resolve_constant_returns_unresolved_for_other_shapes():
    node = ast.parse("some_func()", mode="eval").body
    assert _resolve_constant(node, {}) is _UNRESOLVED


def test_pattern_d_resolves_module_constant_rhs_in_existing_extractor(tmp_path):
    """An `if x['amount'] <= THRESHOLD: raise` rule must resolve
    THRESHOLD against the module-level constant."""
    src = tmp_path / "m.py"
    src.write_text(
        "THRESHOLD = 100\n"
        "def validate_payment(payment):\n"
        "    if payment['amount'] <= THRESHOLD:\n"
        "        raise ValueError('too low')\n"
    )
    pm = parse_module(src)
    facts = list(extract_procedural(pm))
    rules = [r for r in facts if isinstance(r, RuleFact) and r.subject_attribute == "amount"]
    assert len(rules) == 1
    assert rules[0].object_value == 100
    assert rules[0].predicate == "gt"  # inverted from <=


def test_pattern_d_skips_when_constant_unknown(tmp_path):
    """An unresolved Name RHS still skips emission (the v1.2 behavior)."""
    src = tmp_path / "m.py"
    src.write_text(
        "def validate_payment(payment):\n"
        "    if payment['amount'] <= UNKNOWN_THRESHOLD:\n"
        "        raise ValueError\n"
    )
    pm = parse_module(src)
    facts = list(extract_procedural(pm))
    rules = [r for r in facts if isinstance(r, RuleFact)]
    # No structured rule; only the weak validate_* fallback fires.
    structured = [r for r in rules if r.subject_attribute == "amount"]
    assert structured == []


# ---------------------------------------------------------------------------
# Task 4 — Pattern A (multi-condition eligibility, conjunction)
# ---------------------------------------------------------------------------


def test_pattern_a_emits_eligibility_per_required_condition(tmp_path):
    """`if not X: return False` chain → one eligibility rule per condition
    with (required, True) polarity."""
    src = tmp_path / "m.py"
    src.write_text(
        "def is_forbearance(loan_modification, counterparty_status):\n"
        "    if not counterparty_status.is_in_financial_difficulty:\n"
        "        return False\n"
        "    if not loan_modification.is_concessionary:\n"
        "        return False\n"
        "    return True\n"
    )
    pm = parse_module(src)
    facts = list(extract_procedural(pm))
    elig = [r for r in facts if isinstance(r, RuleFact) and r.rule_kind == "eligibility"]
    assert len(elig) == 2
    subjects = {(r.subject_attribute, r.predicate, r.object_value) for r in elig}
    assert ("is_in_financial_difficulty", "required", True) in subjects
    assert ("is_concessionary", "required", True) in subjects


def test_pattern_a_bare_param_truthiness_polarity(tmp_path):
    """`if has_X: return False` (no `not`) → bare-param subject with
    (required, False) polarity."""
    src = tmp_path / "m.py"
    src.write_text(
        "def can_upgrade(loan, has_active_forbearance):\n"
        "    if has_active_forbearance:\n"
        "        return False\n"
        "    if not loan.is_non_performing:\n"
        "        return False\n"
        "    return True\n"
    )
    pm = parse_module(src)
    facts = list(extract_procedural(pm))
    elig = [r for r in facts if isinstance(r, RuleFact) and r.rule_kind == "eligibility"]
    triples = {(r.subject_attribute, r.predicate, r.object_value) for r in elig}
    assert ("has_active_forbearance", "required", False) in triples
    assert ("is_non_performing", "required", True) in triples


def test_pattern_a_skips_nested_ifs(tmp_path):
    """Nested `if/if return False` patterns must NOT contribute rules
    — outer-guard context can't be serialised faithfully."""
    src = tmp_path / "m.py"
    src.write_text(
        "def is_eligible(loan):\n"
        "    if loan.flag_a:\n"
        "        if loan.flag_b:\n"
        "            return False\n"
        "    return True\n"
    )
    pm = parse_module(src)
    facts = list(extract_procedural(pm))
    elig = [r for r in facts if isinstance(r, RuleFact) and r.rule_kind == "eligibility"]
    # The OUTER if doesn't have `return False` directly; its body has
    # only a nested if. Neither layer should emit a standalone rule.
    assert elig == []


def test_pattern_a_skips_when_lhs_is_method_call(tmp_path):
    """`if not payment_history.continuous_repayments(): return False`
    must be skipped — method call LHS is not a subject-bearing
    reference."""
    src = tmp_path / "m.py"
    src.write_text(
        "def can_upgrade(loan, payment_history):\n"
        "    if not payment_history.continuous_repayments():\n"
        "        return False\n"
        "    return True\n"
    )
    pm = parse_module(src)
    facts = list(extract_procedural(pm))
    elig = [r for r in facts if isinstance(r, RuleFact) and r.rule_kind == "eligibility"]
    assert elig == []


def test_pattern_a_skips_when_rhs_is_local_variable(tmp_path):
    """`if loan.dpd < threshold: return False` where `threshold` is a
    local must be skipped — dataflow is out of scope."""
    src = tmp_path / "m.py"
    src.write_text(
        "def can_upgrade(loan):\n"
        "    threshold = 90\n"
        "    if loan.dpd < threshold:\n"
        "        return False\n"
        "    return True\n"
    )
    pm = parse_module(src)
    facts = list(extract_procedural(pm))
    elig = [r for r in facts if isinstance(r, RuleFact) and r.rule_kind == "eligibility"]
    assert elig == []


# ---------------------------------------------------------------------------
# Task 4 — Pattern B (multi-condition classification, disjunction)
# ---------------------------------------------------------------------------


def test_pattern_b_emits_eligibility_per_sufficient_trigger(tmp_path):
    """`if X: return True; ...; return False` → one eligibility rule
    per trigger with direct (not inverted) polarity."""
    src = tmp_path / "m.py"
    src.write_text(
        "def classify_loan_as_npe(loan):\n"
        "    if loan.ifrs_stage == 'ifrs_stage_3_impaired':\n"
        "        return True\n"
        "    if loan.is_defaulted:\n"
        "        return True\n"
        "    return False\n"
    )
    pm = parse_module(src)
    facts = list(extract_procedural(pm))
    elig = [r for r in facts if isinstance(r, RuleFact) and r.rule_kind == "eligibility"]
    triples = {(r.subject_attribute, r.predicate, r.object_value) for r in elig}
    assert ("ifrs_stage", "eq", "ifrs_stage_3_impaired") in triples
    assert ("is_defaulted", "required", True) in triples


def test_pattern_b_resolves_constant_rhs(tmp_path):
    """Pattern B + Pattern D: `if X == IFRS_STAGE_IMPAIRED` resolves
    the constant to its literal value."""
    src = tmp_path / "m.py"
    src.write_text(
        "IFRS_STAGE_IMPAIRED = 'ifrs_stage_3_impaired'\n"
        "def classify_loan(loan):\n"
        "    if loan.ifrs_stage == IFRS_STAGE_IMPAIRED:\n"
        "        return True\n"
        "    return False\n"
    )
    pm = parse_module(src)
    facts = list(extract_procedural(pm))
    elig = [r for r in facts if isinstance(r, RuleFact) and r.rule_kind == "eligibility"]
    assert len(elig) == 1
    assert elig[0].object_value == "ifrs_stage_3_impaired"


def test_pattern_b_only_fires_on_extended_prefix_set(tmp_path):
    """`classify_*`, `determine_*`, etc. trigger Pattern B; plain
    function names don't."""
    src = tmp_path / "m.py"
    src.write_text(
        "def helper(loan):\n"  # not a recognised prefix
        "    if loan.is_defaulted:\n"
        "        return True\n"
        "    return False\n"
    )
    pm = parse_module(src)
    facts = list(extract_procedural(pm))
    elig = [r for r in facts if isinstance(r, RuleFact) and r.rule_kind == "eligibility"]
    assert elig == []


def test_pattern_a_skips_negated_comparison(tmp_path):
    """`if not (X <op> lit): return False` is documented as a rare
    pattern deferred to a future patch. The helper must return None
    (no rule emitted) for this shape, not crash or emit a wrong rule."""
    src = tmp_path / "m.py"
    src.write_text(
        "def is_eligible(loan):\n"
        "    if not (loan.amount > 0):\n"
        "        return False\n"
        "    return True\n"
    )
    pm = parse_module(src)
    facts = list(extract_procedural(pm))
    elig = [r for r in facts if isinstance(r, RuleFact) and r.rule_kind == "eligibility"]
    assert elig == []


def test_pattern_b_negated_bare_name_polarity(tmp_path):
    """`if not X: return True` (Pattern B, negated) maps to
    (required, False) — X being falsy is the sufficient trigger."""
    src = tmp_path / "m.py"
    src.write_text(
        "def classify_loan(loan):\n"
        "    if not loan.is_active:\n"
        "        return True\n"
        "    return False\n"
    )
    pm = parse_module(src)
    facts = list(extract_procedural(pm))
    elig = [r for r in facts if isinstance(r, RuleFact) and r.rule_kind == "eligibility"]
    assert len(elig) == 1
    r = elig[0]
    assert r.subject_attribute == "is_active"
    assert r.predicate == "required"
    assert r.object_value is False
