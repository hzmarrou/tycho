"""Project Source D business rules onto the OWL output as annotations.

Phase D (L1) — annotation-layer rule projection. Each
:class:`ontozense.core.fusion.BusinessRule` already attached to a
:class:`ontozense.core.fusion.FusedElement` becomes one
``ontozense:businessRule`` annotation on the parent class, plus
structured sibling annotations (``ontozense:ruleType``,
``ontozense:ruleAnchor``, ``ontozense:ruleConfidence``,
``ontozense:ruleValue`` when the rule is a constant,
``ontozense:ruleReferencedSymbols`` when non-empty, and one
``dc:source`` triple per entry in ``rule.citations``).

L2 OWL restrictions and L3 SWRL Horn-clause rules are out of scope
for Phase D. See
``docs/PROPERTY_EXTRACTION_DESIGN.md §4 Phase D`` for the contract
constraint that drove the L1-only scope and the deferred Phase E
roadmap.

Rule-to-class binding policy (per design §5 / §9 D7): we trust the
fusion-layer resolution. Each ``BusinessRule`` lives on exactly one
``FusedElement`` (the one ``_merge_source_d`` attached it to), and
the annotation lands on that element's class URI. Rules that fusion
couldn't bind live on ``FusionResult.unmatched_code_rules`` and are
NOT projected by Phase D (they have no parent class to attach to).

Truncation guard (per design §6 Q7): ``ontozense:businessRule``
literal capped at :data:`MAX_RULE_EXPRESSION_LITERAL` characters
(2000). Longer expressions truncate with trailing ``"..."``; the
full text remains addressable via ``ontozense:ruleAnchor``
(``"file:line"`` click-through).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from rdflib import Literal, Namespace, URIRef
from rdflib.namespace import DC

if TYPE_CHECKING:
    from .fusion import BusinessRule, FusionResult


# Hard cap on the ``ontozense:businessRule`` literal length. Long SQL
# views and function bodies can run to thousands of characters;
# emitting the full text inline bloats the OWL output without adding
# value (the curator clicks through via the anchor for the full
# source). 2000 chars covers the vast majority of CodeExtractor
# outputs we've seen on real domains.
MAX_RULE_EXPRESSION_LITERAL = 2000


# CodeExtractor's actual rule_type vocabulary (per
# src/ontozense/extractors/code_extractor.py:77). Phase D supports
# exactly these seven. Unknown rule_types still get the L1 annotation
# cluster (defensive default — never silently drop a rule).
KNOWN_RULE_TYPES: frozenset[str] = frozenset({
    "constant",
    "conditional",
    "function",
    "sql_check",
    "sql_where",
    "sql_view",
    "comment_citation",
})


@dataclass
class RuleAnnotation:
    """One rule's annotation cluster, ready to merge into a graph.

    Pure data carrier. The caller (``owl_export.fused_to_owl``)
    iterates the ``triples`` list and adds each ``(s, p, o)`` to the
    rdflib graph. Keeping the data shape separate from emission lets
    tests assert the triple set without needing a real graph.
    """

    parent_class_uri: URIRef
    rule: "BusinessRule"
    triples: list[tuple] = field(default_factory=list)


def project_annotations(
    fused: "FusionResult",
    *,
    ns,                          # rdflib Namespace for the per-domain base URI
    ontozense_ns: Namespace,
) -> list[RuleAnnotation]:
    """Return one ``RuleAnnotation`` per ``BusinessRule`` on every
    ``FusedElement`` in ``fused``.

    Parameters
    ----------
    fused
        The fusion result whose elements carry the rules.
    ns
        The per-domain base namespace (e.g.
        ``Namespace("https://tycho.local/<domain>/")``). Used to
        construct each parent class URI the annotation triples
        attach to.
    ontozense_ns
        The ``ontozense:`` annotation namespace. Caller binds it on
        the graph; this module emits triples against it.

    Unmatched rules (``fused.unmatched_code_rules``) are not
    projected — they have no parent class. They remain accessible to
    consumers via the existing ``fused.json`` field.
    """
    # Late import to avoid circular: fusion imports from many
    # core.* modules at load time.
    from .fusion import FusedElement  # noqa: F401  (TYPE_CHECKING already imports it)

    annotations: list[RuleAnnotation] = []
    for element in fused.elements:
        class_fragment = _id_fragment(element.element_name)
        class_uri = ns[class_fragment]
        for rule in element.business_rules:
            ann = _project_one(rule, class_uri, ontozense_ns)
            annotations.append(ann)
    return annotations


# ─── Per-rule projection ────────────────────────────────────────────────────


def _project_one(
    rule: "BusinessRule",
    parent_class_uri: URIRef,
    ontozense_ns: Namespace,
) -> RuleAnnotation:
    """Build the annotation triple cluster for a single ``BusinessRule``.

    The output set is uniform across rule_types — every rule gets the
    same core annotations (``businessRule``, ``ruleType``,
    ``ruleAnchor``, ``ruleConfidence``). Constants additionally get
    ``ruleValue``. Any rule with ``referenced_symbols`` gets
    ``ruleReferencedSymbols``. Any rule with ``citations`` gets one
    ``dc:source`` per citation.

    This uniformity is intentional: Phase D's job is to surface the
    rule to the curator, not to interpret it. Per-rule_type semantic
    projection (L2 restrictions, L3 SWRL) is Phase E.
    """
    triples: list[tuple] = []

    # ── ontozense:businessRule — verbatim rule text, truncated ────
    expression = rule.expression or rule.description or ""
    literal_text = _truncate(expression, MAX_RULE_EXPRESSION_LITERAL)
    triples.append(
        (parent_class_uri, ontozense_ns.businessRule, Literal(literal_text)),
    )

    # ── ontozense:ruleType ─────────────────────────────────────────
    if rule.rule_type:
        triples.append(
            (parent_class_uri, ontozense_ns.ruleType, Literal(rule.rule_type)),
        )

    # ── ontozense:ruleAnchor — "file:line" click-through ──────────
    if rule.anchor is not None and not rule.anchor.is_empty():
        anchor_text = _format_anchor(rule.anchor)
        if anchor_text:
            triples.append(
                (parent_class_uri, ontozense_ns.ruleAnchor, Literal(anchor_text)),
            )

    # ── ontozense:ruleConfidence ──────────────────────────────────
    triples.append(
        (parent_class_uri, ontozense_ns.ruleConfidence, Literal(rule.confidence)),
    )

    # ── ontozense:ruleValue — only for constants with a non-None value
    # Stays at one OWL literal (curator-visible text) per design §6 Q8.
    # value=None on non-constant rules contributes nothing.
    if rule.rule_type == "constant" and rule.value is not None:
        triples.append(
            (parent_class_uri, ontozense_ns.ruleValue, Literal(repr(rule.value))),
        )

    # ── ontozense:ruleReferencedSymbols ───────────────────────────
    if rule.referenced_symbols:
        triples.append((
            parent_class_uri,
            ontozense_ns.ruleReferencedSymbols,
            Literal(";".join(str(s) for s in rule.referenced_symbols)),
        ))

    # ── dc:source per citation ────────────────────────────────────
    # Per design §9 D5 (closed r2): use dc:source for consistency with
    # the existing class-level emission at owl_export.py:114.
    for citation in rule.citations or []:
        if citation:
            triples.append(
                (parent_class_uri, DC.source, Literal(str(citation))),
            )

    return RuleAnnotation(
        parent_class_uri=parent_class_uri,
        rule=rule,
        triples=triples,
    )


# ─── Helpers ────────────────────────────────────────────────────────────────


def _truncate(text: str, limit: int) -> str:
    """Cap ``text`` at ``limit`` chars; append ``"..."`` when truncated."""
    if len(text) <= limit:
        return text
    # Reserve 3 chars for the ellipsis so the literal stays under the
    # cap including the trailing marker.
    return text[: limit - 3] + "..."


def _format_anchor(anchor) -> str:
    """Render a ``FieldAnchor`` as ``"file:line"`` for click-through.

    Empty file or line=0 → "" so the caller can skip the triple.
    Multi-line spans use the start line only; end_line is implicit in
    the snippet which the curator can pull from ``fused.json`` if
    they need it.
    """
    snippet_file = getattr(anchor, "segment_id", "") or ""
    # FieldAnchor's "file" lives on the rule's evidence_span. The
    # FieldAnchor dataclass itself doesn't have a file field — we
    # build "file:line" from whatever the upstream extractor put on
    # the BusinessRule. In practice CodeRule provenance lives on the
    # rule itself; for now, we surface line + segment when available.
    line = getattr(anchor, "line", 0) or 0
    if not line:
        return snippet_file or ""
    if snippet_file:
        return f"{snippet_file}:{line}"
    return f"line {line}"


def _id_fragment(label: str) -> str:
    """Generate a URI fragment for an element name. Mirrors the
    helper in :mod:`ontozense.core.owl_export` — kept local so the
    rule projector doesn't depend on owl_export's internals."""
    return label.strip().lower().replace(" ", "_").replace("/", "_")
