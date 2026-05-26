"""Fixture: one BusinessRule per CodeExtractor rule_type.

Phase D PR D1 tests use this to assert L1 annotation triples for
every rule_type the projector supports. Mirrors the seven types
emitted today by ``src/ontozense/extractors/code_extractor.py``.
"""

from __future__ import annotations

from ontozense.core.fusion import BusinessRule, FieldAnchor


def _anchor(line: int, segment: str = "ledger.py") -> FieldAnchor:
    return FieldAnchor(line=line, segment_id=segment)


def make_constant_rule() -> BusinessRule:
    return BusinessRule(
        rule_type="constant",
        name="NPE_DPD_THRESHOLD",
        expression="NPE_DPD_THRESHOLD = 90",
        description="Days-past-due threshold for non-performing exposures.",
        value=90,
        referenced_symbols=["days_past_due"],
        citations=["Basel D403 §1.2"],
        docstring="",
        confidence=0.95,
        anchor=_anchor(12, "classifier.py"),
    )


def make_conditional_rule() -> BusinessRule:
    return BusinessRule(
        rule_type="conditional",
        name="stage_npe",
        expression='if days_past_due > 90: stage = "NPE"',
        description="Stage = NPE when DPD > 90.",
        value=None,
        referenced_symbols=["days_past_due", "stage"],
        citations=[],
        docstring="",
        confidence=0.9,
        anchor=_anchor(34, "classifier.py"),
    )


def make_function_rule() -> BusinessRule:
    return BusinessRule(
        rule_type="function",
        name="is_npe",
        expression="def is_npe(loan): ...",
        description="is_npe() — return True when the loan qualifies as NPE.",
        value=None,
        referenced_symbols=["loan"],
        citations=["IFRS 9 §5.5"],
        docstring="Return True when the loan qualifies as NPE.\n\nLong-form rationale here.",
        confidence=0.85,
        anchor=_anchor(50, "classifier.py"),
    )


def make_sql_check_rule() -> BusinessRule:
    return BusinessRule(
        rule_type="sql_check",
        name="status_in",
        expression="status IN ('performing','non_performing')",
        description="status must be in {performing, non_performing}.",
        value=None,
        referenced_symbols=["status"],
        citations=[],
        docstring="",
        confidence=0.95,
        anchor=_anchor(8, "loan_constraints.sql"),
    )


def make_sql_where_rule() -> BusinessRule:
    return BusinessRule(
        rule_type="sql_where",
        name="finrep_filter",
        expression="WHERE status = 'non_performing'",
        description="FINREP filter: only NPE rows.",
        value=None,
        referenced_symbols=["status"],
        citations=["FINREP F18"],
        docstring="",
        confidence=0.92,
        anchor=_anchor(14, "finrep_npl_query.sql"),
    )


def make_sql_view_rule() -> BusinessRule:
    return BusinessRule(
        rule_type="sql_view",
        name="vw_npe",
        expression="CREATE VIEW vw_npe AS SELECT * FROM loans WHERE status = 'non_performing'",
        description="View of all non-performing loans.",
        value=None,
        referenced_symbols=["loans", "status"],
        citations=[],
        docstring="",
        confidence=0.9,
        anchor=_anchor(2, "finrep_views.sql"),
    )


def make_comment_citation_rule() -> BusinessRule:
    return BusinessRule(
        rule_type="comment_citation",
        name="basel_ref",
        expression="# See Basel D403 §1.2 for the DPD threshold rationale",
        description="Regulatory citation: Basel D403 §1.2.",
        value=None,
        referenced_symbols=[],
        citations=["Basel D403 §1.2", "IFRS 9 §5.5"],
        docstring="",
        confidence=0.8,
        anchor=_anchor(5, "classifier.py"),
    )


def all_rule_types() -> list[BusinessRule]:
    """Convenience: one rule per CodeExtractor rule_type, in canonical
    iteration order. Used by parametrised tests."""
    return [
        make_constant_rule(),
        make_conditional_rule(),
        make_function_rule(),
        make_sql_check_rule(),
        make_sql_where_rule(),
        make_sql_view_rule(),
        make_comment_citation_rule(),
    ]
