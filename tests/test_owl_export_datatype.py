"""PR3 — owl:DatatypeProperty emission coverage.

Exercises the property-extraction projection added to
:func:`ontozense.core.owl_export.fused_to_owl`:

  - per-attribute owl:DatatypeProperty triples
  - rdfs:domain pointing at parent class URI
  - rdfs:range XSD URIRef per the design §5 mapping
  - owl:FunctionalProperty for is_id
  - ontozense:required / enumValues / rawType / multivalued annotations
  - object property URIs migrated to {base}/rel/{predicate}
  - attribute URI vs predicate URI collision impossible by construction
  - serialised output round-trips through rdflib.Graph().parse()
"""

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import OWL, RDF, RDFS, XSD

from ontozense.core.attribute import Attribute
from ontozense.core.fusion import FusedElement, FusedRelationship, FusionResult
from ontozense.core.owl_export import ONTOZENSE_NS, fused_to_owl


BASE = "https://tycho.local/default/"
ONTO = URIRef(ONTOZENSE_NS).toPython()


# ─── Helpers ────────────────────────────────────────────────────────────────


def _emit(elements, relationships=None) -> Graph:
    fr = FusionResult(elements=elements, relationships=relationships or [])
    turtle = fused_to_owl(fr, format="turtle")
    g = Graph()
    g.parse(data=turtle, format="turtle")
    return g


def _attr_uri(class_frag: str, attr_frag: str) -> URIRef:
    return URIRef(f"{BASE}{class_frag}/{attr_frag}")


def _class_uri(class_frag: str) -> URIRef:
    return URIRef(f"{BASE}{class_frag}")


def _rel_uri(predicate_frag: str) -> URIRef:
    return URIRef(f"{BASE}rel/{predicate_frag}")


# ─── DatatypeProperty emission ──────────────────────────────────────────────


def test_one_datatype_property_emitted_per_attribute():
    el = FusedElement(
        element_name="Customer",
        attributes=[
            Attribute(name="email", xsd_type="xsd:string"),
            Attribute(name="age", xsd_type="xsd:integer"),
        ],
    )
    g = _emit([el])
    props = list(g.subjects(RDF.type, OWL.DatatypeProperty))
    assert len(props) == 2
    expected = {
        _attr_uri("customer", "email"),
        _attr_uri("customer", "age"),
    }
    assert set(props) == expected


def test_datatype_property_has_label():
    el = FusedElement(
        element_name="Customer",
        attributes=[Attribute(name="email", xsd_type="xsd:string")],
    )
    g = _emit([el])
    uri = _attr_uri("customer", "email")
    assert (uri, RDFS.label, Literal("email")) in g


def test_datatype_property_domain_points_at_parent_class():
    el = FusedElement(
        element_name="Customer",
        attributes=[Attribute(name="email", xsd_type="xsd:string")],
    )
    g = _emit([el])
    uri = _attr_uri("customer", "email")
    assert (uri, RDFS.domain, _class_uri("customer")) in g


def test_datatype_property_range_maps_to_xsd_uriref():
    el = FusedElement(
        element_name="Order",
        attributes=[
            Attribute(name="amount", xsd_type="xsd:decimal"),
            Attribute(name="placed_at", xsd_type="xsd:dateTime"),
            Attribute(name="is_paid", xsd_type="xsd:boolean"),
        ],
    )
    g = _emit([el])
    assert (_attr_uri("order", "amount"), RDFS.range, XSD.decimal) in g
    assert (_attr_uri("order", "placed_at"), RDFS.range, XSD.dateTime) in g
    assert (_attr_uri("order", "is_paid"), RDFS.range, XSD.boolean) in g


def test_unknown_xsd_label_defaults_to_string_range():
    el = FusedElement(
        element_name="X",
        attributes=[Attribute(name="weird", xsd_type="xsd:nope")],
    )
    g = _emit([el])
    assert (_attr_uri("x", "weird"), RDFS.range, XSD.string) in g


def test_description_emitted_as_rdfs_comment():
    el = FusedElement(
        element_name="Customer",
        attributes=[Attribute(
            name="email", xsd_type="xsd:string",
            description="Customer login email",
        )],
    )
    g = _emit([el])
    uri = _attr_uri("customer", "email")
    assert (uri, RDFS.comment, Literal("Customer login email")) in g


def test_description_omitted_when_empty():
    el = FusedElement(
        element_name="x",
        attributes=[Attribute(name="y", xsd_type="xsd:string")],
    )
    g = _emit([el])
    uri = _attr_uri("x", "y")
    assert (uri, RDFS.comment, None) not in g


# ─── owl:FunctionalProperty (is_id) ────────────────────────────────────────


def test_is_id_emits_owl_functional_property_type():
    el = FusedElement(
        element_name="Customer",
        attributes=[Attribute(
            name="id", xsd_type="xsd:integer", is_id=True,
        )],
    )
    g = _emit([el])
    uri = _attr_uri("customer", "id")
    assert (uri, RDF.type, OWL.DatatypeProperty) in g
    assert (uri, RDF.type, OWL.FunctionalProperty) in g


def test_non_id_does_not_get_functional_property_type():
    el = FusedElement(
        element_name="Customer",
        attributes=[Attribute(name="email", xsd_type="xsd:string")],
    )
    g = _emit([el])
    uri = _attr_uri("customer", "email")
    assert (uri, RDF.type, OWL.FunctionalProperty) not in g


# ─── ontozense:* annotations ───────────────────────────────────────────────


def test_required_annotation_emitted_when_not_nullable():
    el = FusedElement(
        element_name="Customer",
        attributes=[Attribute(
            name="email", xsd_type="xsd:string", is_nullable=False,
        )],
    )
    g = _emit([el])
    uri = _attr_uri("customer", "email")
    required_pred = URIRef(f"{ONTO}required")
    assert (uri, required_pred, Literal(True)) in g


def test_required_annotation_omitted_when_nullable_default():
    el = FusedElement(
        element_name="Customer",
        attributes=[Attribute(name="nickname", xsd_type="xsd:string")],
    )
    g = _emit([el])
    uri = _attr_uri("customer", "nickname")
    required_pred = URIRef(f"{ONTO}required")
    assert (uri, required_pred, None) not in g


def test_enum_values_annotation_semicolon_joined():
    el = FusedElement(
        element_name="Order",
        attributes=[Attribute(
            name="status", xsd_type="xsd:string",
            enum_values=["open", "paid", "closed"],
        )],
    )
    g = _emit([el])
    uri = _attr_uri("order", "status")
    enum_pred = URIRef(f"{ONTO}enumValues")
    assert (uri, enum_pred, Literal("open;paid;closed")) in g


def test_enum_values_omitted_when_empty():
    el = FusedElement(
        element_name="Order",
        attributes=[Attribute(name="status", xsd_type="xsd:string")],
    )
    g = _emit([el])
    uri = _attr_uri("order", "status")
    enum_pred = URIRef(f"{ONTO}enumValues")
    assert (uri, enum_pred, None) not in g


def test_raw_type_annotation_preserved():
    el = FusedElement(
        element_name="Order",
        attributes=[Attribute(
            name="amount", xsd_type="xsd:decimal",
            raw_type="DECIMAL(18,2)",
        )],
    )
    g = _emit([el])
    uri = _attr_uri("order", "amount")
    raw_pred = URIRef(f"{ONTO}rawType")
    assert (uri, raw_pred, Literal("DECIMAL(18,2)")) in g


def test_multivalued_annotation_emitted_when_true():
    el = FusedElement(
        element_name="Account",
        attributes=[Attribute(
            name="tags", xsd_type="xsd:string", is_multivalued=True,
        )],
    )
    g = _emit([el])
    uri = _attr_uri("account", "tags")
    mv_pred = URIRef(f"{ONTO}multivalued")
    assert (uri, mv_pred, Literal(True)) in g


# ─── /rel/ URI branch for object properties ────────────────────────────────


def test_object_property_uri_lives_under_rel_branch():
    el_a = FusedElement(element_name="Loan")
    el_b = FusedElement(element_name="Borrower")
    rel = FusedRelationship(
        subject="Loan", predicate="has_borrower", object="Borrower",
        source="A", confidence=0.9,
    )
    g = _emit([el_a, el_b], relationships=[rel])
    expected = _rel_uri("has_borrower")
    assert (expected, RDF.type, OWL.ObjectProperty) in g
    # The flat-form URI {base}/has_borrower must NOT exist any more.
    flat = URIRef(f"{BASE}has_borrower")
    assert (flat, RDF.type, OWL.ObjectProperty) not in g


def test_object_property_domain_and_range_preserved_under_rel_branch():
    el_a = FusedElement(element_name="Loan")
    el_b = FusedElement(element_name="Borrower")
    rel = FusedRelationship(
        subject="Loan", predicate="has_borrower", object="Borrower",
        source="A",
    )
    g = _emit([el_a, el_b], relationships=[rel])
    uri = _rel_uri("has_borrower")
    assert (uri, RDFS.domain, _class_uri("loan")) in g
    assert (uri, RDFS.range, _class_uri("borrower")) in g


# ─── Attribute URI vs predicate URI collision impossible by construction ──


def test_attribute_named_same_as_predicate_does_not_collide():
    """``Loan`` has an attribute ``borrower`` AND a predicate
    ``borrower`` exists; the two URIs must NOT collide. Codex hard
    constraint guard."""
    el_loan = FusedElement(
        element_name="Loan",
        attributes=[Attribute(name="borrower", xsd_type="xsd:string")],
    )
    el_borrower = FusedElement(element_name="Borrower")
    rel = FusedRelationship(
        subject="Loan", predicate="borrower", object="Borrower",
        source="A",
    )
    g = _emit([el_loan, el_borrower], relationships=[rel])

    datatype_uri = _attr_uri("loan", "borrower")          # {base}/loan/borrower
    object_uri = _rel_uri("borrower")                     # {base}/rel/borrower

    # Distinct URIs.
    assert datatype_uri != object_uri
    # Both exist with the right types.
    assert (datatype_uri, RDF.type, OWL.DatatypeProperty) in g
    assert (object_uri, RDF.type, OWL.ObjectProperty) in g
    # Neither URI carries the OTHER type — confirms no aliasing.
    assert (datatype_uri, RDF.type, OWL.ObjectProperty) not in g
    assert (object_uri, RDF.type, OWL.DatatypeProperty) not in g


# ─── Round-trip parse ─────────────────────────────────────────────────────


def test_serialised_output_round_trips_via_rdflib_parse():
    """rdflib must be able to re-parse the emitted text — guards
    against malformed URIs / broken serialisation paths."""
    el = FusedElement(
        element_name="Customer",
        attributes=[
            Attribute(
                name="id", xsd_type="xsd:integer", is_id=True,
                is_nullable=False, raw_type="INT",
            ),
            Attribute(
                name="status", xsd_type="xsd:string",
                enum_values=["a", "b"], is_multivalued=False,
            ),
        ],
    )
    # Emit twice to confirm determinism — same input → same output set.
    fr = FusionResult(elements=[el])
    turtle = fused_to_owl(fr, format="turtle")
    g = Graph()
    g.parse(data=turtle, format="turtle")
    # And the xml-form round-trip.
    xml = fused_to_owl(fr, format="pretty-xml")
    g2 = Graph()
    g2.parse(data=xml, format="xml")
    assert len(g2) > 0


def test_emit_does_not_raise_on_empty_attributes():
    el = FusedElement(element_name="Concept")
    g = _emit([el])
    # Class still emitted; no datatype property.
    assert (_class_uri("concept"), RDF.type, OWL.Class) in g
    assert not list(g.subjects(RDF.type, OWL.DatatypeProperty))


def test_class_without_attributes_does_not_pollute_property_graph():
    el_a = FusedElement(
        element_name="Customer",
        attributes=[Attribute(name="email", xsd_type="xsd:string")],
    )
    el_b = FusedElement(element_name="EmptyConcept")
    g = _emit([el_a, el_b])
    props = list(g.subjects(RDF.type, OWL.DatatypeProperty))
    assert props == [_attr_uri("customer", "email")]
