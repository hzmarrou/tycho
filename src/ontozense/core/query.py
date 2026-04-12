"""Query — look up elements in the fused knowledge base.

Per ``docs/PLAYBOOK.md`` §9 (Query operation): an analyst asks a
question against the accumulated knowledge, the result is rendered as
markdown, and optionally **filed back** as a derived artifact under
``<domain>/derived/analyses/``.

Two query modes:

  1. **Element lookup** — show everything we know about a single element
     (all fields, all sources, conflicts, business rules, relationships).
  2. **Search** — find all elements matching a term (substring or exact).

The output is always markdown so it can be filed back directly.
"""

from __future__ import annotations

from .fusion import FusedElement, FusionResult, normalise_name


def query_element(result: FusionResult, name: str) -> str | None:
    """Look up a single element by name. Returns a markdown report or None."""
    el = result.get_element(name)
    if el is None:
        return None
    return _render_element(el, result)


def search_elements(result: FusionResult, term: str) -> list[FusedElement]:
    """Find all elements whose name contains the search term."""
    norm = normalise_name(term)
    return [
        el for el in result.elements
        if norm in normalise_name(el.element_name)
    ]


def render_search_results(
    results: list[FusedElement], term: str, fusion: FusionResult
) -> str:
    """Render search results as markdown."""
    if not results:
        return f"No elements found matching '{term}'.\n"

    lines = [f"# Search: '{term}' ({len(results)} match{'es' if len(results) != 1 else ''})\n"]

    for el in results:
        lines.append(f"## {el.element_name}\n")
        lines.append(_render_element(el, fusion))
        lines.append("")

    return "\n".join(lines)


def _render_element(el: FusedElement, result: FusionResult) -> str:
    """Render a single element as a markdown block."""
    lines: list[str] = []

    # Header
    lines.append(f"### {el.element_name}")
    lines.append("")

    # Core fields
    lines.append("| Field | Value | Source |")
    lines.append("|---|---|---|")

    prov = el.field_provenance

    _row(lines, "domain_name", el.domain_name, prov)
    _row(lines, "definition", el.definition, prov)
    _row(lines, "is_critical", str(el.is_critical) if el.is_critical else "", prov)
    _row(lines, "citation", el.citation, prov)
    _row(lines, "data_type", el.data_type, prov)
    if el.enum_values:
        _row(lines, "enum_values", ", ".join(el.enum_values), prov)

    lines.append("")

    # Governance validation
    if el.governance_validated:
        lines.append("**Governance validated**")
        lines.append("")

    # Business rules
    if el.business_rules:
        lines.append(f"**Business rules ({len(el.business_rules)}):**")
        for rule in el.business_rules:
            lines.append(f"- {rule}")
        lines.append("")

    # Relationships involving this element
    norm = normalise_name(el.element_name)
    rels = [
        r for r in result.relationships
        if normalise_name(r.subject) == norm or normalise_name(r.object) == norm
    ]
    if rels:
        lines.append(f"**Relationships ({len(rels)}):**")
        for r in rels:
            lines.append(f"- {r.subject} --[{r.predicate}]--> {r.object} (source: {r.source})")
        lines.append("")

    # Conflicts
    if el.conflicts:
        lines.append(f"**Conflicts ({len(el.conflicts)}):**")
        for c in el.conflicts:
            rejected_str = ", ".join(
                f"{r.source}: {r.original_value!r}" for r in c.rejected
            )
            lines.append(
                f"- `{c.field_name}`: winner={c.winner.source} "
                f"({c.winner.original_value!r}), "
                f"rejected=[{rejected_str}], "
                f"resolved by {c.resolution}"
            )
        lines.append("")

    # Extra fields
    if el.extra_fields:
        lines.append("**Extra fields:**")
        for k, v in el.extra_fields.items():
            lines.append(f"- {k}: {v}")
        lines.append("")

    # Confidence + sources
    lines.append(
        f"*Confidence: {el.confidence:.2f} | "
        f"Sources: {'+'.join(el.sources)} | "
        f"Needs review: {'yes' if el.needs_review() else 'no'}*"
    )
    lines.append("")

    return "\n".join(lines)


def _row(
    lines: list[str],
    field_name: str,
    value: str,
    prov: dict,
) -> None:
    """Add a table row if the value is non-empty."""
    if not value:
        return
    source = ""
    if field_name in prov:
        source = prov[field_name].source
    lines.append(f"| {field_name} | {value} | {source} |")
