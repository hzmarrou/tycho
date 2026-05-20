"""Unit tests for v1.2.1 rich-extraction helpers."""
import ast

from ontozense.core.ingest.source_d.parse import parse_module
from ontozense.core.ingest.source_d.procedural_extractor import (
    _UNRESOLVED,
    _collect_module_constants,
    _resolve_constant,
    _resolve_subject,
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


from ontozense.core.ingest.source_d.ir import RuleFact
from ontozense.core.ingest.source_d.procedural_extractor import extract_procedural


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
