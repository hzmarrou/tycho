"""Tests for the fused.json → OWL exporter (semantic-layer redesign)."""

from __future__ import annotations

from rdflib import Graph, RDF, RDFS, OWL

from ontozense.core.fusion import FieldProvenance, FusedElement, FusionResult
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
