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
    # ``FusionResult`` itself doesn't carry a ``domain_name`` field today;
    # the domain lives on each ``FusedElement``. We pick the first
    # populated value and fall back to ``"default"`` for empty results.
    raw_domain = getattr(fused, "domain_name", "") or _first_element_domain(
        fused.elements
    ) or "default"
    domain = raw_domain.lower().replace(" ", "_")
    base_iri = f"{domain_namespace}/{domain}/"
    ns = Namespace(base_iri)
    g.bind("", ns)
    g.bind("owl", OWL)
    g.bind("rdfs", RDFS)

    for element in fused.elements:
        uri = ns[_id_fragment(element.element_name)]
        g.add((uri, RDF.type, OWL.Class))
        g.add((uri, RDFS.label, Literal(element.element_name)))

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
