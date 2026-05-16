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
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from rdflib import Graph, Literal, Namespace, RDF, RDFS, OWL
from rdflib.namespace import DC

if TYPE_CHECKING:
    from .fusion import FusionResult
    from .profile import Profile


def fused_to_owl(
    fused: "FusionResult",
    profile: "Profile | None" = None,
    domain_namespace: str = "https://tycho.local",
    format: str = "turtle",
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
    """
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
    g.bind("", ns)
    g.bind("owl", OWL)
    g.bind("rdfs", RDFS)
    g.bind("dc", DC)

    for element in fused.elements:
        uri = ns[_id_fragment(element.element_name)]
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

    # One ObjectProperty per distinct predicate. Predicates often
    # repeat across relationships (e.g. "HasLoan" used by many
    # borrowers); we deduplicate by predicate name and let the
    # subject/object endpoints contribute to the domain / range.
    predicates: dict[str, dict[str, set]] = {}
    for rel in fused.relationships:
        entry = predicates.setdefault(
            rel.predicate, {"domains": set(), "ranges": set()},
        )
        entry["domains"].add(_id_fragment(rel.subject))
        entry["ranges"].add(_id_fragment(rel.object))

    for predicate_name, endpoints in predicates.items():
        uri = ns[_id_fragment(predicate_name)]
        g.add((uri, RDF.type, OWL.ObjectProperty))
        g.add((uri, RDFS.label, Literal(predicate_name)))
        for domain in endpoints["domains"]:
            g.add((uri, RDFS.domain, ns[domain]))
        for rng in endpoints["ranges"]:
            g.add((uri, RDFS.range, ns[rng]))

    return g.serialize(format=format)


def _id_fragment(label: str) -> str:
    """Generate a URI fragment for an element name."""
    return label.strip().lower().replace(" ", "_").replace("/", "_")


def _first_element_domain(elements) -> str:
    """Return the first non-empty ``domain_name`` across elements, or ``""``."""
    for el in elements:
        if getattr(el, "domain_name", ""):
            return el.domain_name
    return ""
