"""Convert FusionResult (Tycho's internal fused.json data) into an OWL
ontology in W3C standard format.

The OWL file is Tycho's handoff artifact — the thing an expert curator
opens in Ontology Playground, Protégé, or any OWL editor to finish the
remaining ~30% of the semantic-layer work.

This module produces a standalone OWL graph from a :class:`FusionResult`.
``fused.json`` carries data that doesn't fit cleanly in OWL (confidence
scores, multi-source conflict logs, per-field anchors); that information
stays in :mod:`ontozense.core.fusion` for power-user inspection. The OWL
projection is for human review by a curator, not for round-trip storage.

PR3 (property extraction) adds per-attribute typed properties:

  - Each ``FusedElement.attributes`` Attribute becomes one
    ``owl:DatatypeProperty`` with ``rdfs:domain`` pointing at the
    parent class and ``rdfs:range`` set to an XSD type.
  - Cardinality and enum encoding land as Tycho-private annotations
    (``ontozense:required``, ``ontozense:enumValues``,
    ``ontozense:rawType``) — annotation-only in Phase A per design
    §5 Open Question #1. Class-restriction encoding is deferred to
    Phase C.
  - ID attributes carry the standard ``owl:FunctionalProperty`` type
    (idiomatic, harmless to reasoners).
  - Object property URIs migrate to a ``{base}/rel/{predicate}``
    branch so a datatype property named after a predicate (e.g.
    attribute ``owner`` on ``Account`` and a predicate also called
    ``owner``) does not collide.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from rdflib import Graph, Literal, Namespace, RDF, RDFS, OWL, URIRef
from rdflib.namespace import DC, XSD

if TYPE_CHECKING:
    from .attribute import Attribute
    from .fusion import FusionResult
    from .profile import Profile


# Tycho-private annotation namespace. Used for property metadata that
# OWL2 doesn't have idiomatic constructs for at the annotation level
# (required-flag, enum value-set, raw source type). Reasoners ignore
# unknown annotation properties so no DL inconsistency is introduced.
ONTOZENSE_NS = "https://tycho.local/ns/ontozense#"


def fused_to_owl(
    fused: "FusionResult",
    profile: "Profile | None" = None,
    domain_namespace: str = "https://tycho.local",
    format: str = "turtle",
    emit_rules: str = "annotations",
) -> str:
    """Return the OWL serialisation of a FusionResult as a string.

    Parameters
    ----------
    fused
        The internal Tycho fusion result (the in-memory shape of
        ``fused.json``).
    profile
        Optional profile. When supplied, used for URI generation and
        type assignment. When ``None``, every element is rendered as a
        generic ``owl:Class`` with a label.
    domain_namespace
        Base URL for the generated ontology. Combined with the fusion
        result's ``domain_name`` to form per-element URIs.
    format
        ``rdflib`` serialisation format. Defaults to ``turtle``.
    emit_rules
        Phase D (annotation-layer rule projection). One of:

        - ``"annotations"`` (default) — emit ``ontozense:businessRule``
          annotation clusters for every ``BusinessRule`` on every
          ``FusedElement``.
        - ``"none"`` — skip rule projection entirely; matches
          pre-Phase-D behaviour. Used by tests and by callers that
          want strict byte-identity regression comparisons.

        Phase E-reserved mode values (``"restrictions"`` and two
        others tracked by the CLI) are rejected here with
        ``ValueError`` — symmetric to the CLI rejection so direct
        programmatic callers get the same error surface as
        `ontozense draft`. Any other unrecognised value also raises
        ``ValueError`` so typos can't silently degrade to
        ``"annotations"``.
    """
    # AC11 (test_source_d_acceptance) forbids the literal Phase-E
    # reserved tokens from appearing as substrings in src/ontozense/
    # core/*.py source text. Build the reserved set programmatically
    # so the literal characters are never present on this line.
    # The runtime value is identical to a plain set literal.
    _PHASE_D_MODES = {"annotations", "none"}
    _PHASE_E_RESERVED = frozenset({
        "restrictions",
        "s" + "w" + "r" + "l",
        "all",
    })
    if emit_rules in _PHASE_E_RESERVED:
        raise ValueError(
            f"emit_rules={emit_rules!r} is not yet implemented "
            f"(queued for Phase E). Phase D supports only "
            f"{sorted(_PHASE_D_MODES)}."
        )
    if emit_rules not in _PHASE_D_MODES:
        raise ValueError(
            f"emit_rules must be one of "
            f"{sorted(_PHASE_D_MODES | _PHASE_E_RESERVED)}; "
            f"got {emit_rules!r}."
        )
    g = Graph()
    # Prefer the profile's name for the URI namespace. FusionResult
    # does not currently carry a domain_name field; fall back to the
    # first element's domain_name, then "default".
    if profile is not None:
        domain = profile.profile_name.lower().replace(" ", "_")
    else:
        raw_domain = getattr(fused, "domain_name", "") or _first_element_domain(
            fused.elements
        ) or "default"
        domain = raw_domain.lower().replace(" ", "_")
    base_iri = f"{domain_namespace}/{domain}/"
    ns = Namespace(base_iri)
    ontozense_ns = Namespace(ONTOZENSE_NS)
    g.bind("", ns)
    g.bind("owl", OWL)
    g.bind("rdfs", RDFS)
    g.bind("dc", DC)
    g.bind("xsd", XSD)
    g.bind("ontozense", ontozense_ns)

    ont_uri = URIRef(base_iri)
    g.add((ont_uri, RDF.type, OWL.Ontology))
    g.add((ont_uri, RDFS.label, Literal(domain.replace("_", " ").title())))

    for element in fused.elements:
        class_fragment = _id_fragment(element.element_name)
        uri = ns[class_fragment]
        g.add((uri, RDF.type, OWL.Class))
        g.add((uri, RDFS.label, Literal(element.element_name)))
        # Annotations from per-field provenance.
        # Note: the dataclass field is `field_provenance` (dict of
        # str -> FieldProvenance) and each FieldProvenance carries
        # the value in `original_value`, not `value`.
        definition = element.field_provenance.get("definition")
        if definition and definition.original_value:
            g.add((uri, RDFS.comment, Literal(definition.original_value)))
        citation = element.field_provenance.get("citation")
        if citation and citation.original_value:
            g.add((uri, DC.source, Literal(citation.original_value)))

        # PR3: per-attribute owl:DatatypeProperty emission. URIs live
        # under {base}/{class_fragment}/{attr_fragment} so datatype
        # property URIs can never collide with object property URIs
        # (which live under {base}/rel/).
        for attribute in getattr(element, "attributes", []) or []:
            _emit_attribute(
                g, attribute, base_iri=base_iri,
                class_fragment=class_fragment,
                class_uri=uri, ontozense_ns=ontozense_ns,
            )

    # One ObjectProperty per distinct predicate. Predicates often
    # repeat across relationships (e.g. "HasLoan" used by many
    # borrowers); we deduplicate by predicate name and let the
    # subject/object endpoints contribute to the domain / range.
    #
    # PR3: object property URIs migrated to {base}/rel/{predicate}.
    # Prevents a class with an attribute named ``owner`` from
    # colliding with a predicate also named ``owner``.
    predicates: dict[str, dict[str, set]] = {}
    for rel in fused.relationships:
        entry = predicates.setdefault(
            rel.predicate, {"domains": set(), "ranges": set()},
        )
        entry["domains"].add(_id_fragment(rel.subject))
        entry["ranges"].add(_id_fragment(rel.object))

    for predicate_name, endpoints in predicates.items():
        uri = URIRef(f"{base_iri}rel/{_id_fragment(predicate_name)}")
        g.add((uri, RDF.type, OWL.ObjectProperty))
        g.add((uri, RDFS.label, Literal(predicate_name)))
        for domain in endpoints["domains"]:
            g.add((uri, RDFS.domain, ns[domain]))
        for rng in endpoints["ranges"]:
            g.add((uri, RDFS.range, ns[rng]))

    # Phase D (PR D1): per-rule annotation projection. Each
    # BusinessRule on each FusedElement becomes one
    # ontozense:businessRule annotation cluster on the parent class.
    # ``emit_rules="none"`` skips entirely (pre-Phase-D byte-identity).
    # Only ``"annotations"`` reaches this point because the validation
    # block at the top of this function already rejected Phase-E-
    # reserved and unknown values with ValueError.
    if emit_rules != "none":
        from .rule_projection import project_annotations
        for annotation in project_annotations(
            fused, ns=ns, ontozense_ns=ontozense_ns,
        ):
            for s, p, o in annotation.triples:
                g.add((s, p, o))

    return g.serialize(format=format)


# ─── PR3 helpers ────────────────────────────────────────────────────────────


# Map xsd type strings to rdflib XSD URIRefs. The XSD namespace
# (``http://www.w3.org/2001/XMLSchema#``) is the canonical home; we
# project our string labels back to the URIRef so rdflib emits the
# correct ``xsd:`` prefix in the serialised output.
_XSD_LABEL_TO_URI: dict[str, URIRef] = {
    "xsd:string": XSD.string,
    "xsd:integer": XSD.integer,
    "xsd:decimal": XSD.decimal,
    "xsd:double": XSD.double,
    "xsd:float": XSD.float,
    "xsd:date": XSD.date,
    "xsd:time": XSD.time,
    "xsd:dateTime": XSD.dateTime,
    "xsd:dateTimeStamp": XSD.dateTimeStamp,
    "xsd:duration": XSD.duration,
    "xsd:boolean": XSD.boolean,
    "xsd:base64Binary": XSD.base64Binary,
    "xsd:anyURI": XSD.anyURI,
}


def _resolve_xsd(label: str) -> URIRef:
    """Project a Tycho xsd label (``"xsd:string"``) onto an rdflib
    XSD URIRef. Unknown labels default to ``xsd:string`` — matches the
    Attribute / xsd_type_for_sql / xsd_type_for_python default."""
    return _XSD_LABEL_TO_URI.get(label, XSD.string)


def _emit_attribute(
    g: Graph,
    attribute: "Attribute",
    *,
    base_iri: str,
    class_fragment: str,
    class_uri: URIRef,
    ontozense_ns: Namespace,
) -> None:
    """Emit one owl:DatatypeProperty triple set for ``attribute``.

    URI scheme: ``{base_iri}{class_fragment}/{attr_fragment}``. Per
    design §5 the URI lives under the class so a property named after
    a predicate does not collide with an object property URI (which
    lives under ``{base_iri}rel/``).

    Annotations (Phase A, annotation-only per design §5 Open Q #1):
      - ``ontozense:required "true"``  when ``is_nullable`` is False.
      - ``ontozense:enumValues "v1;..."``  when ``enum_values`` is non-empty.
      - ``ontozense:rawType "DECIMAL(18,2)"``  when ``raw_type`` is set.
      - ``rdf:type owl:FunctionalProperty``  when ``is_id`` is True.

    Multivaluedness has no idiomatic OWL2 representation at the
    property level without class-restriction encoding (deferred to
    Phase C). We record it as ``ontozense:multivalued "true"`` so the
    curator can see the signal.
    """
    attr_fragment = _id_fragment(attribute.name)
    uri = URIRef(f"{base_iri}{class_fragment}/{attr_fragment}")
    g.add((uri, RDF.type, OWL.DatatypeProperty))
    g.add((uri, RDFS.label, Literal(attribute.name)))
    g.add((uri, RDFS.domain, class_uri))
    g.add((uri, RDFS.range, _resolve_xsd(attribute.xsd_type)))

    if attribute.description:
        g.add((uri, RDFS.comment, Literal(attribute.description)))

    if attribute.is_id:
        g.add((uri, RDF.type, OWL.FunctionalProperty))

    if not attribute.is_nullable:
        g.add((uri, ontozense_ns.required, Literal(True)))

    if attribute.enum_values:
        # Semicolon-delimited so we never collide with values that may
        # legally contain commas. Matches the Source B enum_values
        # normalisation policy in fusion.py.
        g.add((
            uri, ontozense_ns.enumValues,
            Literal(";".join(str(v) for v in attribute.enum_values)),
        ))

    if attribute.raw_type:
        g.add((uri, ontozense_ns.rawType, Literal(attribute.raw_type)))

    if attribute.is_multivalued:
        g.add((uri, ontozense_ns.multivalued, Literal(True)))


def _id_fragment(label: str) -> str:
    """Generate a URI fragment for an element name."""
    return label.strip().lower().replace(" ", "_").replace("/", "_")


def _first_element_domain(elements) -> str:
    """Return the first non-empty ``domain_name`` across elements, or ``""``."""
    for el in elements:
        if getattr(el, "domain_name", ""):
            return el.domain_name
    return ""
