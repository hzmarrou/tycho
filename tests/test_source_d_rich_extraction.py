"""Unit tests for v1.2.1 rich-extraction helpers."""
import ast

from ontozense.core.ingest.source_d.procedural_extractor import _resolve_subject


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


from ontozense.core.ingest.source_d.parse import parse_module
from ontozense.core.ingest.source_d.procedural_extractor import (
    _UNRESOLVED,
    _collect_module_constants,
    _resolve_constant,
)


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
