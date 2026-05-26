"""PR D1 — end-to-end rule annotation emission in draft.owl.

Exercises ``ontozense.core.owl_export.fused_to_owl`` with the
``emit_rules`` parameter. Confirms:

  - Default emit_rules="annotations" adds ontozense:businessRule
    triples for every BusinessRule on every FusedElement.
  - emit_rules="none" produces a graph isomorphic to a fused result
    that has no business_rules at all (pre-Phase-D byte-identity
    regression guard).
  - The annotation triples land on the correct parent class URIs.
  - Phase A DatatypeProperty emission (PR3) is not affected by
    Phase D — adding rules to a fused element does not change its
    attribute output.
"""

from __future__ import annotations

import pytest
from rdflib import Graph, Literal, URIRef
from rdflib.compare import isomorphic
from rdflib.namespace import OWL, RDF

from ontozense.core.fusion import FusedElement, FusionResult
from ontozense.core.owl_export import ONTOZENSE_NS, fused_to_owl

from tests.fixtures.synthetic_business_rules import (
    all_rule_types,
    make_constant_rule,
    make_conditional_rule,
)


BASE = "https://tycho.local/default/"
ONTO = URIRef(ONTOZENSE_NS).toPython()


def _emit(fused: FusionResult, *, emit_rules: str = "annotations") -> Graph:
    turtle = fused_to_owl(fused, format="turtle", emit_rules=emit_rules)
    g = Graph()
    g.parse(data=turtle, format="turtle")
    return g


def _class_uri(class_frag: str) -> URIRef:
    return URIRef(f"{BASE}{class_frag}")


# ─── Default emit_rules=annotations ────────────────────────────────────────


def test_annotations_default_emits_business_rule_per_rule():
    fused = FusionResult(elements=[
        FusedElement(element_name="Loan", business_rules=all_rule_types()),
    ])
    g = _emit(fused)
    rule_triples = list(g.triples((
        _class_uri("loan"), URIRef(f"{ONTO}businessRule"), None,
    )))
    assert len(rule_triples) == len(all_rule_types())


def test_annotations_default_emits_rule_type_per_rule():
    fused = FusionResult(elements=[
        FusedElement(element_name="Loan", business_rules=all_rule_types()),
    ])
    g = _emit(fused)
    type_triples = list(g.triples((
        _class_uri("loan"), URIRef(f"{ONTO}ruleType"), None,
    )))
    emitted_types = {str(o) for _, _, o in type_triples}
    expected_types = {r.rule_type for r in all_rule_types()}
    assert emitted_types == expected_types


def test_constant_rule_value_lands_on_parent_class():
    rule = make_constant_rule()  # value=90
    fused = FusionResult(elements=[
        FusedElement(element_name="Loan", business_rules=[rule]),
    ])
    g = _emit(fused)
    assert (
        _class_uri("loan"),
        URIRef(f"{ONTO}ruleValue"),
        Literal(repr(90)),
    ) in g


def test_no_rules_no_business_rule_annotations():
    fused = FusionResult(elements=[FusedElement(element_name="Loan")])
    g = _emit(fused)
    assert not list(g.triples((None, URIRef(f"{ONTO}businessRule"), None)))


# ─── emit_rules="none" — byte-identity regression guard ────────────────────


def test_emit_rules_none_matches_empty_business_rules_graph():
    """A fused result with business_rules + emit_rules="none" must
    yield a graph isomorphic to the same result with business_rules
    stripped (which is what pre-Phase-D would have emitted). Uses
    rdflib.compare.isomorphic for the comparison since literal text
    serialisation order is not deterministic across rdflib versions.
    """
    with_rules = FusionResult(elements=[
        FusedElement(element_name="Loan", business_rules=all_rule_types()),
    ])
    without_rules = FusionResult(elements=[FusedElement(element_name="Loan")])

    g_with_none = _emit(with_rules, emit_rules="none")
    g_without = _emit(without_rules)

    assert isomorphic(g_with_none, g_without)


def test_emit_rules_none_strips_all_phase_d_triples():
    """The ``ontozense:businessRule`` / ``ruleType`` / etc.
    predicates must not appear when emit_rules="none"."""
    fused = FusionResult(elements=[
        FusedElement(element_name="Loan", business_rules=[make_constant_rule()]),
    ])
    g = _emit(fused, emit_rules="none")
    phase_d_predicates = {
        URIRef(f"{ONTO}businessRule"),
        URIRef(f"{ONTO}ruleType"),
        URIRef(f"{ONTO}ruleAnchor"),
        URIRef(f"{ONTO}ruleConfidence"),
        URIRef(f"{ONTO}ruleValue"),
        URIRef(f"{ONTO}ruleReferencedSymbols"),
    }
    for pred in phase_d_predicates:
        assert not list(g.triples((None, pred, None))), (
            f"emit_rules=none should suppress {pred}"
        )


# ─── Multi-element binding ─────────────────────────────────────────────────


def test_annotations_attach_to_correct_parent_classes():
    fused = FusionResult(elements=[
        FusedElement(element_name="Loan", business_rules=[make_constant_rule()]),
        FusedElement(element_name="Borrower", business_rules=[make_conditional_rule()]),
    ])
    g = _emit(fused)
    loan_rules = list(g.triples((
        _class_uri("loan"), URIRef(f"{ONTO}businessRule"), None,
    )))
    borrower_rules = list(g.triples((
        _class_uri("borrower"), URIRef(f"{ONTO}businessRule"), None,
    )))
    assert len(loan_rules) == 1
    assert len(borrower_rules) == 1
    # Cross-attachment must NOT happen.
    cross = list(g.triples((
        _class_uri("loan"), URIRef(f"{ONTO}businessRule"),
        Literal(make_conditional_rule().expression),
    )))
    assert cross == []


# ─── Phase A regression guard ──────────────────────────────────────────────


def test_phase_a_class_and_datatype_emission_unchanged_by_rules():
    """Adding rules to a fused element must not affect Phase A's
    class + DatatypeProperty emission."""
    from ontozense.core.attribute import Attribute

    fused = FusionResult(elements=[
        FusedElement(
            element_name="Loan",
            business_rules=[make_constant_rule()],
            attributes=[Attribute(name="amount", xsd_type="xsd:decimal")],
        ),
    ])
    g = _emit(fused)
    # Class still emitted.
    assert (_class_uri("loan"), RDF.type, OWL.Class) in g
    # DatatypeProperty still emitted.
    dt_props = list(g.subjects(RDF.type, OWL.DatatypeProperty))
    assert len(dt_props) == 1


def test_dc_source_citations_emitted_for_rule():
    """Phase D dc:source emission per citation; verifies the
    dc:source predicate (matching the existing class-level
    citation emission convention)."""
    from rdflib.namespace import DC

    rule = make_constant_rule()  # citations=["Basel D403 §1.2"]
    fused = FusionResult(elements=[
        FusedElement(element_name="Loan", business_rules=[rule]),
    ])
    g = _emit(fused)
    assert (
        _class_uri("loan"),
        DC.source,
        Literal("Basel D403 §1.2"),
    ) in g


# ─── Exporter-side emit_rules validation (Codex r1 minor) ──────────────────
#
# Programmatic callers of fused_to_owl skip the CLI's validation
# layer. Without exporter-side validation a typo like
# emit_rules="annotaions" would silently degrade to the default
# behaviour. r1 adds explicit validation so the failure surface is
# symmetric to the CLI.


def test_fused_to_owl_rejects_phase_e_reserved_restrictions():
    fused = FusionResult(elements=[FusedElement(element_name="Loan")])
    with pytest.raises(ValueError) as exc:
        fused_to_owl(fused, emit_rules="restrictions")
    assert "queued for Phase E" in str(exc.value)
    assert "restrictions" in str(exc.value)


def test_fused_to_owl_rejects_phase_e_reserved_swrl():
    fused = FusionResult(elements=[FusedElement(element_name="Loan")])
    with pytest.raises(ValueError) as exc:
        fused_to_owl(fused, emit_rules="swrl")
    assert "queued for Phase E" in str(exc.value)


def test_fused_to_owl_rejects_phase_e_reserved_all():
    fused = FusionResult(elements=[FusedElement(element_name="Loan")])
    with pytest.raises(ValueError) as exc:
        fused_to_owl(fused, emit_rules="all")
    assert "queued for Phase E" in str(exc.value)


def test_fused_to_owl_rejects_unknown_emit_rules():
    """Typos must not silently degrade to default — caller gets a
    list of the five recognised values."""
    fused = FusionResult(elements=[FusedElement(element_name="Loan")])
    with pytest.raises(ValueError) as exc:
        fused_to_owl(fused, emit_rules="annotaions")  # deliberate typo
    msg = str(exc.value)
    assert "annotaions" in msg
    for mode in ("annotations", "none", "restrictions", "swrl", "all"):
        assert mode in msg


def test_fused_to_owl_accepts_annotations():
    fused = FusionResult(elements=[FusedElement(element_name="Loan")])
    # No raise.
    fused_to_owl(fused, emit_rules="annotations")


def test_fused_to_owl_accepts_none():
    fused = FusionResult(elements=[FusedElement(element_name="Loan")])
    # No raise.
    fused_to_owl(fused, emit_rules="none")
