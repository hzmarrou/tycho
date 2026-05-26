"""PR D1 — per-rule_type L1 annotation projection coverage.

Exercises ``ontozense.core.rule_projection`` against the synthetic
business-rule fixture. Each CodeExtractor rule_type gets a
parametrised test covering the expected triple set, plus dedicated
tests for the truncation guard, value coercion, citations expansion,
referenced-symbols join, and the project_annotations entry-point
behaviour (binding rules to parent classes, ignoring unmatched
rules).
"""

from __future__ import annotations

import pytest
from rdflib import Literal, Namespace, URIRef
from rdflib.namespace import DC

from ontozense.core.fusion import (
    BusinessRule,
    FieldAnchor,
    FusedElement,
    FusionResult,
)
from ontozense.core.rule_projection import (
    MAX_RULE_EXPRESSION_LITERAL,
    RuleAnnotation,
    project_annotations,
)

from tests.fixtures.synthetic_business_rules import (
    all_rule_types,
    make_comment_citation_rule,
    make_conditional_rule,
    make_constant_rule,
    make_sql_check_rule,
)


NS = Namespace("https://tycho.local/test/")
ONTOZENSE_NS = Namespace("https://tycho.local/ns/ontozense#")


def _fused_with_rules(element_name: str, rules: list[BusinessRule]) -> FusionResult:
    return FusionResult(
        elements=[FusedElement(element_name=element_name, business_rules=list(rules))],
    )


def _project_one_rule(rule: BusinessRule, element_name: str = "Loan") -> RuleAnnotation:
    fused = _fused_with_rules(element_name, [rule])
    out = project_annotations(fused, ns=NS, ontozense_ns=ONTOZENSE_NS)
    assert len(out) == 1
    return out[0]


def _triples_by_predicate(ann: RuleAnnotation) -> dict[URIRef, list]:
    """Index triples by predicate URI for assertion convenience."""
    by_pred: dict[URIRef, list] = {}
    for s, p, o in ann.triples:
        by_pred.setdefault(p, []).append((s, o))
    return by_pred


# ─── project_annotations entry point ───────────────────────────────────────


def test_project_annotations_returns_one_per_rule_per_element():
    fused = FusionResult(elements=[
        FusedElement(
            element_name="Loan",
            business_rules=[make_constant_rule(), make_conditional_rule()],
        ),
        FusedElement(
            element_name="Borrower",
            business_rules=[make_sql_check_rule()],
        ),
    ])
    annotations = project_annotations(fused, ns=NS, ontozense_ns=ONTOZENSE_NS)
    assert len(annotations) == 3


def test_project_annotations_ignores_unmatched_rules():
    """Rules on ``unmatched_code_rules`` have no parent class. They
    must not contribute annotations."""
    fused = FusionResult(
        elements=[FusedElement(element_name="Loan", business_rules=[make_constant_rule()])],
    )
    # Simulate an unmatched rule the fusion couldn't bind.
    fused.unmatched_code_rules = [object()]  # type: ignore[assignment]
    annotations = project_annotations(fused, ns=NS, ontozense_ns=ONTOZENSE_NS)
    assert len(annotations) == 1  # only the matched constant rule


def test_project_annotations_attaches_to_parent_class_uri():
    ann = _project_one_rule(make_constant_rule(), element_name="Loan")
    expected_uri = URIRef(str(NS) + "loan")
    assert ann.parent_class_uri == expected_uri
    assert all(s == expected_uri for s, _, _ in ann.triples)


def test_project_annotations_normalises_element_name_for_uri():
    """Element name "Non-Performing Exposure" → URI fragment
    "non-performing_exposure". Matches the _id_fragment helper used
    by the rest of the OWL export."""
    ann = _project_one_rule(
        make_constant_rule(), element_name="Non Performing Exposure",
    )
    assert "non_performing_exposure" in str(ann.parent_class_uri)


def test_empty_business_rules_yields_no_annotations():
    fused = _fused_with_rules("Loan", [])
    assert project_annotations(fused, ns=NS, ontozense_ns=ONTOZENSE_NS) == []


# ─── Per-rule_type L1 triple shape ─────────────────────────────────────────


@pytest.mark.parametrize("rule", all_rule_types())
def test_every_rule_type_emits_business_rule_annotation(rule):
    ann = _project_one_rule(rule)
    by_pred = _triples_by_predicate(ann)
    assert ONTOZENSE_NS.businessRule in by_pred, (
        f"rule_type {rule.rule_type!r} missing ontozense:businessRule"
    )


@pytest.mark.parametrize("rule", all_rule_types())
def test_every_rule_type_emits_rule_type_annotation(rule):
    ann = _project_one_rule(rule)
    by_pred = _triples_by_predicate(ann)
    assert ONTOZENSE_NS.ruleType in by_pred
    assert by_pred[ONTOZENSE_NS.ruleType][0][1] == Literal(rule.rule_type)


@pytest.mark.parametrize("rule", all_rule_types())
def test_every_rule_type_emits_confidence(rule):
    ann = _project_one_rule(rule)
    by_pred = _triples_by_predicate(ann)
    assert ONTOZENSE_NS.ruleConfidence in by_pred
    assert by_pred[ONTOZENSE_NS.ruleConfidence][0][1] == Literal(rule.confidence)


@pytest.mark.parametrize("rule", all_rule_types())
def test_every_rule_type_emits_anchor_when_present(rule):
    ann = _project_one_rule(rule)
    by_pred = _triples_by_predicate(ann)
    # All fixture rules have anchors with both segment_id and line set.
    assert ONTOZENSE_NS.ruleAnchor in by_pred


# ─── constant — value coercion ─────────────────────────────────────────────


def test_constant_rule_emits_rule_value_via_repr():
    rule = make_constant_rule()  # value=90
    ann = _project_one_rule(rule)
    by_pred = _triples_by_predicate(ann)
    assert ONTOZENSE_NS.ruleValue in by_pred
    assert by_pred[ONTOZENSE_NS.ruleValue][0][1] == Literal(repr(90))


def test_constant_rule_with_string_value_uses_repr():
    rule = BusinessRule(
        rule_type="constant", name="X", expression="X = 'y'",
        description="", value="y", confidence=0.95,
    )
    ann = _project_one_rule(rule)
    by_pred = _triples_by_predicate(ann)
    assert by_pred[ONTOZENSE_NS.ruleValue][0][1] == Literal("'y'")


def test_constant_rule_with_none_value_skips_rule_value():
    rule = BusinessRule(
        rule_type="constant", name="X", expression="X = None",
        description="", value=None, confidence=0.95,
    )
    ann = _project_one_rule(rule)
    by_pred = _triples_by_predicate(ann)
    assert ONTOZENSE_NS.ruleValue not in by_pred


def test_non_constant_rule_never_emits_rule_value():
    rule = make_conditional_rule()  # rule_type=conditional, value=None
    ann = _project_one_rule(rule)
    by_pred = _triples_by_predicate(ann)
    assert ONTOZENSE_NS.ruleValue not in by_pred


def test_non_constant_with_value_still_skips_rule_value():
    """ruleValue is constant-specific by design — even a function
    rule with a value field set must not surface it as ruleValue."""
    rule = BusinessRule(
        rule_type="function", name="f", expression="", description="",
        value=42, confidence=0.9,
    )
    ann = _project_one_rule(rule)
    by_pred = _triples_by_predicate(ann)
    assert ONTOZENSE_NS.ruleValue not in by_pred


# ─── Truncation guard ─────────────────────────────────────────────────────


def test_long_expression_truncates_at_max_literal():
    long_expr = "x = 1\n" * 1000  # 6000 chars
    rule = BusinessRule(
        rule_type="constant", name="x", expression=long_expr,
        description="", value=1, confidence=0.95,
    )
    ann = _project_one_rule(rule)
    by_pred = _triples_by_predicate(ann)
    emitted_text = str(by_pred[ONTOZENSE_NS.businessRule][0][1])
    assert len(emitted_text) <= MAX_RULE_EXPRESSION_LITERAL
    assert emitted_text.endswith("...")


def test_expression_at_exact_limit_is_not_truncated():
    expr = "a" * MAX_RULE_EXPRESSION_LITERAL
    rule = BusinessRule(
        rule_type="constant", name="x", expression=expr,
        description="", value=1, confidence=0.95,
    )
    ann = _project_one_rule(rule)
    by_pred = _triples_by_predicate(ann)
    emitted_text = str(by_pred[ONTOZENSE_NS.businessRule][0][1])
    assert emitted_text == expr  # no truncation, no ellipsis


def test_short_expression_passes_through_unchanged():
    rule = make_conditional_rule()
    ann = _project_one_rule(rule)
    by_pred = _triples_by_predicate(ann)
    emitted_text = str(by_pred[ONTOZENSE_NS.businessRule][0][1])
    assert emitted_text == rule.expression


def test_falls_back_to_description_when_expression_empty():
    rule = BusinessRule(
        rule_type="function", name="f", expression="",
        description="Stub function — body intentionally omitted.",
        confidence=0.9,
    )
    ann = _project_one_rule(rule)
    by_pred = _triples_by_predicate(ann)
    assert str(by_pred[ONTOZENSE_NS.businessRule][0][1]) == rule.description


# ─── Citations (dc:source per entry) ──────────────────────────────────────


def test_empty_citations_emits_no_dc_source():
    rule = make_conditional_rule()  # citations=[]
    ann = _project_one_rule(rule)
    by_pred = _triples_by_predicate(ann)
    assert DC.source not in by_pred


def test_single_citation_emits_one_dc_source():
    rule = make_constant_rule()  # citations=["Basel D403 §1.2"]
    ann = _project_one_rule(rule)
    by_pred = _triples_by_predicate(ann)
    assert DC.source in by_pred
    assert len(by_pred[DC.source]) == 1
    assert by_pred[DC.source][0][1] == Literal("Basel D403 §1.2")


def test_multiple_citations_emit_one_dc_source_each():
    rule = make_comment_citation_rule()  # 2 citations
    ann = _project_one_rule(rule)
    by_pred = _triples_by_predicate(ann)
    assert len(by_pred[DC.source]) == 2
    values = {str(o) for _, o in by_pred[DC.source]}
    assert values == {"Basel D403 §1.2", "IFRS 9 §5.5"}


def test_empty_string_citations_are_skipped():
    rule = BusinessRule(
        rule_type="constant", name="x", expression="x = 1",
        description="", value=1, citations=["", "real cite", ""],
        confidence=0.95,
    )
    ann = _project_one_rule(rule)
    by_pred = _triples_by_predicate(ann)
    assert len(by_pred.get(DC.source, [])) == 1
    assert by_pred[DC.source][0][1] == Literal("real cite")


# ─── Referenced symbols ────────────────────────────────────────────────────


def test_referenced_symbols_emitted_as_semicolon_joined():
    rule = make_conditional_rule()  # referenced_symbols=["days_past_due","stage"]
    ann = _project_one_rule(rule)
    by_pred = _triples_by_predicate(ann)
    assert ONTOZENSE_NS.ruleReferencedSymbols in by_pred
    text = str(by_pred[ONTOZENSE_NS.ruleReferencedSymbols][0][1])
    assert text == "days_past_due;stage"


def test_empty_referenced_symbols_emits_nothing():
    rule = make_comment_citation_rule()  # referenced_symbols=[]
    ann = _project_one_rule(rule)
    by_pred = _triples_by_predicate(ann)
    assert ONTOZENSE_NS.ruleReferencedSymbols not in by_pred


# ─── Anchor formatting ────────────────────────────────────────────────────


def test_anchor_without_line_emits_nothing():
    rule = BusinessRule(
        rule_type="constant", name="x", expression="x = 1",
        description="", value=1, confidence=0.95,
        anchor=FieldAnchor(),  # all defaults, is_empty() returns True
    )
    ann = _project_one_rule(rule)
    by_pred = _triples_by_predicate(ann)
    assert ONTOZENSE_NS.ruleAnchor not in by_pred


def test_anchor_with_segment_and_line_renders_as_file_colon_line():
    rule = make_constant_rule()  # segment_id="classifier.py", line=12
    ann = _project_one_rule(rule)
    by_pred = _triples_by_predicate(ann)
    assert by_pred[ONTOZENSE_NS.ruleAnchor][0][1] == Literal("classifier.py:12")


def test_anchor_with_line_only_renders_as_line_n():
    rule = BusinessRule(
        rule_type="conditional", name="x", expression="if x: pass",
        description="", confidence=0.9,
        anchor=FieldAnchor(line=42),  # no segment_id
    )
    ann = _project_one_rule(rule)
    by_pred = _triples_by_predicate(ann)
    assert by_pred[ONTOZENSE_NS.ruleAnchor][0][1] == Literal("line 42")
