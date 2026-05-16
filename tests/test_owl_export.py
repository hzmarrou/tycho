"""Tests for the fused.json → OWL exporter (semantic-layer redesign)."""

from __future__ import annotations

from rdflib import Graph, RDF, RDFS, OWL

from ontozense.core.fusion import (
    FieldProvenance,
    FusedElement,
    FusedRelationship,
    FusionResult,
)
from ontozense.core.owl_export import fused_to_owl


def _el(name: str, *, definition: str = "", entity_type: str = "Concept") -> FusedElement:
    prov: dict = {}
    if definition:
        prov["definition"] = FieldProvenance(
            source="A", confidence=0.9, original_value=definition,
        )
    return FusedElement(
        element_name=name,
        field_provenance=prov,
        extra_fields={"entity_type": entity_type} if entity_type else {},
    )


def _result(elements=(), relationships=()) -> FusionResult:
    return FusionResult(
        elements=list(elements),
        relationships=list(relationships),
        fusion_timestamp="2026-05-16T00:00:00",
    )


def _rel(subject: str, predicate: str, obj: str) -> FusedRelationship:
    """Build a minimal FusedRelationship for testing.

    Real FusedRelationship signature is
    ``(subject, predicate, object, source, confidence=0.0)`` —
    ``object`` is the actual attribute name (not a reserved one),
    and ``source`` is required.
    """
    return FusedRelationship(
        subject=subject,
        predicate=predicate,
        object=obj,
        source="A",
        confidence=0.9,
    )


class TestEntityToClass:
    def test_each_element_becomes_an_owl_class(self):
        result = _result(elements=[_el("Borrower"), _el("Loan")])
        ttl = fused_to_owl(result, format="turtle")
        g = Graph()
        g.parse(data=ttl, format="turtle")
        classes = list(g.subjects(RDF.type, OWL.Class))
        assert len(classes) == 2

    def test_element_name_becomes_rdfs_label(self):
        result = _result(elements=[_el("Borrower")])
        ttl = fused_to_owl(result, format="turtle")
        g = Graph()
        g.parse(data=ttl, format="turtle")
        labels = {str(o) for o in g.objects(predicate=RDFS.label)}
        assert "Borrower" in labels

    def test_empty_result_yields_a_valid_owl_graph(self):
        ttl = fused_to_owl(_result(), format="turtle")
        g = Graph()
        g.parse(data=ttl, format="turtle")
        # No classes, but the graph parses cleanly — that's the contract.
        assert len(list(g.subjects(RDF.type, OWL.Class))) == 0


class TestRelationshipToProperty:
    def test_each_relationship_becomes_an_object_property(self):
        result = _result(
            elements=[_el("Borrower"), _el("Loan")],
            relationships=[_rel("Borrower", "HasLoan", "Loan")],
        )
        ttl = fused_to_owl(result, format="turtle")
        g = Graph()
        g.parse(data=ttl, format="turtle")
        props = list(g.subjects(RDF.type, OWL.ObjectProperty))
        assert len(props) == 1

    def test_relationship_has_domain_and_range(self):
        result = _result(
            elements=[_el("Borrower"), _el("Loan")],
            relationships=[_rel("Borrower", "HasLoan", "Loan")],
        )
        ttl = fused_to_owl(result, format="turtle")
        g = Graph()
        g.parse(data=ttl, format="turtle")
        props = list(g.subjects(RDF.type, OWL.ObjectProperty))
        assert len(props) == 1
        domains = list(g.objects(subject=props[0], predicate=RDFS.domain))
        ranges = list(g.objects(subject=props[0], predicate=RDFS.range))
        assert len(domains) == 1 and len(ranges) == 1

    def test_duplicate_relationship_predicate_emits_one_property(self):
        # Two relationships sharing the same predicate name should map
        # to a single ObjectProperty (predicate is the property; the
        # endpoints are the usage, not extra properties).
        result = _result(
            elements=[_el("Borrower"), _el("Loan"), _el("Collateral")],
            relationships=[
                _rel("Borrower", "Has", "Loan"),
                _rel("Borrower", "Has", "Collateral"),
            ],
        )
        ttl = fused_to_owl(result, format="turtle")
        g = Graph()
        g.parse(data=ttl, format="turtle")
        props = list(g.subjects(RDF.type, OWL.ObjectProperty))
        assert len(props) == 1  # one "Has" property
