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
