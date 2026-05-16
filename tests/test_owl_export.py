"""Tests for the fused.json → OWL exporter (semantic-layer redesign)."""

from __future__ import annotations

from rdflib import Graph, RDF, RDFS, OWL
from rdflib.namespace import DC

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


class TestAnnotations:
    def test_definition_becomes_rdfs_comment(self):
        # _el() helper already wires definition into field_provenance.
        result = _result(elements=[
            _el("Borrower", definition="A party that receives a service."),
        ])
        ttl = fused_to_owl(result, format="turtle")
        g = Graph()
        g.parse(data=ttl, format="turtle")
        comments = {str(o) for o in g.objects(predicate=RDFS.comment)}
        assert "A party that receives a service." in comments

    def test_citation_becomes_dc_source(self):
        el = _el("Borrower")
        # Mutate the field_provenance dict to add a citation. The plan's
        # draft used el.provenance["citation"] = FieldProvenance(value=...),
        # adapted here to the real FusedElement.field_provenance + the real
        # FieldProvenance(source, confidence, original_value) signature.
        el.field_provenance["citation"] = FieldProvenance(
            source="A", confidence=0.9, original_value="Basel D403, section 3.2",
        )
        result = _result(elements=[el])
        ttl = fused_to_owl(result, format="turtle")
        g = Graph()
        g.parse(data=ttl, format="turtle")
        sources = {str(o) for o in g.objects(predicate=DC.source)}
        assert "Basel D403, section 3.2" in sources


class TestSerialisationFormats:
    def test_turtle_default(self):
        result = _result(elements=[_el("Borrower")])
        out = fused_to_owl(result)  # default format
        assert "Borrower" in out
        # Turtle starts with "@prefix" or a triple
        assert "@prefix" in out or "Borrower" in out

    def test_jsonld_format(self):
        result = _result(elements=[_el("Borrower")])
        out = fused_to_owl(result, format="json-ld")
        # JSON-LD is JSON; should parse
        import json
        json.loads(out)  # raises if not valid JSON

    def test_owl_xml_format(self):
        result = _result(elements=[_el("Borrower")])
        out = fused_to_owl(result, format="xml")  # rdflib's "xml" == RDF/XML
        assert "<?xml" in out


class TestEmptyAnnotations:
    def test_element_with_no_definition_emits_no_comment(self):
        result = _result(elements=[_el("Borrower")])  # no definition
        ttl = fused_to_owl(result, format="turtle")
        g = Graph()
        g.parse(data=ttl, format="turtle")
        comments = list(g.objects(predicate=RDFS.comment))
        assert len(comments) == 0

    def test_element_with_no_citation_emits_no_dc_source(self):
        # Symmetric negative pin for citation: an element with no
        # citation in field_provenance must not emit a dc:source
        # triple. Closes the test-coverage gap flagged in Task 3
        # round-1 code review.
        result = _result(elements=[_el("Borrower")])  # no citation
        ttl = fused_to_owl(result, format="turtle")
        g = Graph()
        g.parse(data=ttl, format="turtle")
        sources = list(g.objects(predicate=DC.source))
        assert len(sources) == 0
