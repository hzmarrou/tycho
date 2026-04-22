"""Lint — periodic consistency check on the fused knowledge base.

Per ``docs/PLAYBOOK.md`` §9, lint is the gap report generalised to
operate on the **fused** knowledge base, not on a single extraction.

Four checks are implemented (MVP):

  1. **Contradictions** — unresolved conflicts between sources
  2. **Orphan terms** — elements not referenced by any relationship
  3. **Undefined but used** — relationship endpoints without a matching element
  4. **Coverage gaps** — elements where important fields are empty

Two checks are deferred:

  - **Stale claims** — requires persistent state across extraction runs
  - **Missing cross-references** — requires domain semantics
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .fusion import FusedElement, FusionResult, normalise_name


# ─── Dataclasses ─────────────────────────────────────────────────────────────


@dataclass
class LintFinding:
    """One issue found by the lint checker."""
    category: str      # "contradiction", "orphan", "undefined_used", "coverage_gap"
    severity: str      # "error", "warning", "info"
    element_name: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class LintReport:
    """The result of running lint on a fused knowledge base."""
    findings: list[LintFinding] = field(default_factory=list)
    timestamp: str = ""

    @property
    def summary(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for f in self.findings:
            counts[f.category] = counts.get(f.category, 0) + 1
        return counts

    @property
    def error_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "warning")

    def by_category(self, category: str) -> list[LintFinding]:
        return [f for f in self.findings if f.category == category]

    def by_element(self, name: str) -> list[LintFinding]:
        target = normalise_name(name)
        return [
            f for f in self.findings
            if normalise_name(f.element_name) == target
        ]


# ─── Core fields that coverage-gap checks against ───────────────────────────

# These are the fields we consider "important" for coverage purposes.
# An element missing one of these gets a coverage_gap finding.
CORE_FIELDS = ["definition", "citation"]


# ─── Lint engine ─────────────────────────────────────────────────────────────


# Default caps to keep lint output actionable on large ontologies.
# When the concept graph is heavily fragmented (many small communities),
# the O(n^2) community-pair check can produce hundreds of structural
# gap findings. We report only the worst ones (lowest density, largest
# community size) up to these limits, and emit a summary finding
# telling the user how many more exist.
DEFAULT_MAX_GAPS = 10
DEFAULT_MAX_BRIDGES = 10


def lint(
    result: FusionResult,
    *,
    max_gaps: int = DEFAULT_MAX_GAPS,
    max_bridges: int = DEFAULT_MAX_BRIDGES,
) -> LintReport:
    """Run all lint checks on a fused knowledge base.

    Structural gap reporting is capped by ``max_gaps`` (worst holes
    first, by density) and ``max_bridges`` (highest-centrality bridges
    first) to keep output actionable on large ontologies.
    """
    report = LintReport(timestamp=datetime.utcnow().isoformat())

    _check_contradictions(result, report)
    _check_orphan_terms(result, report)
    _check_undefined_used(result, report)
    _check_coverage_gaps(result, report)
    _check_structural_gaps(
        result, report, max_gaps=max_gaps, max_bridges=max_bridges,
    )

    return report


def _check_contradictions(result: FusionResult, report: LintReport) -> None:
    """Flag elements with unresolved conflicts between sources."""
    for el in result.elements:
        for conflict in el.conflicts:
            severity = "error" if conflict.resolution == "unresolved" else "warning"
            report.findings.append(
                LintFinding(
                    category="contradiction",
                    severity=severity,
                    element_name=el.element_name,
                    message=(
                        f"Field '{conflict.field_name}': "
                        f"{conflict.winner.source} ({conflict.winner.original_value!r}) "
                        f"vs {', '.join(r.source for r in conflict.rejected)} "
                        f"({', '.join(repr(r.original_value) for r in conflict.rejected)}). "
                        f"Resolved by {conflict.resolution}."
                    ),
                    details={
                        "field": conflict.field_name,
                        "winner_source": conflict.winner.source,
                        "resolution": conflict.resolution,
                    },
                )
            )


def _check_orphan_terms(result: FusionResult, report: LintReport) -> None:
    """Flag elements not mentioned in any relationship (as subject or object)."""
    # Collect all names referenced in relationships
    referenced: set[str] = set()
    for rel in result.relationships:
        referenced.add(normalise_name(rel.subject))
        referenced.add(normalise_name(rel.object))

    for el in result.elements:
        key = normalise_name(el.element_name)
        if key not in referenced and len(result.relationships) > 0:
            report.findings.append(
                LintFinding(
                    category="orphan",
                    severity="info",
                    element_name=el.element_name,
                    message=(
                        f"'{el.element_name}' is not referenced by any "
                        f"relationship (neither as subject nor object)."
                    ),
                )
            )


def _check_undefined_used(result: FusionResult, report: LintReport) -> None:
    """Flag relationship endpoints that have no matching element."""
    element_keys: set[str] = {
        normalise_name(el.element_name) for el in result.elements
    }

    seen: set[str] = set()
    for rel in result.relationships:
        for endpoint_name, role in [
            (rel.subject, "subject"),
            (rel.object, "object"),
        ]:
            key = normalise_name(endpoint_name)
            if key not in element_keys and key not in seen:
                seen.add(key)
                report.findings.append(
                    LintFinding(
                        category="undefined_used",
                        severity="warning",
                        element_name=endpoint_name,
                        message=(
                            f"'{endpoint_name}' appears as a relationship "
                            f"{role} but has no matching element in the "
                            f"fused dictionary."
                        ),
                        details={"role": role},
                    )
                )


def _check_coverage_gaps(result: FusionResult, report: LintReport) -> None:
    """Flag elements missing important fields (definition, citation)."""
    for el in result.elements:
        missing = []
        if not el.definition.strip():
            missing.append("definition")
        if not el.citation.strip():
            missing.append("citation")

        if missing:
            report.findings.append(
                LintFinding(
                    category="coverage_gap",
                    severity="warning" if "definition" in missing else "info",
                    element_name=el.element_name,
                    message=(
                        f"'{el.element_name}' is missing: "
                        f"{', '.join(missing)}. "
                        f"Sources: {'+'.join(el.sources) or 'none'}."
                    ),
                    details={"missing_fields": missing},
                )
            )


# ─── Structural gap analysis (networkx) ─────────────────────────────────────


def _build_concept_graph(result: FusionResult):
    """Build an undirected weighted graph from fused relationships.

    Nodes = element names (normalised). Edges = relationships, weighted
    by confidence. Element definitions are stored as node attributes
    so the downstream bridging module can include them in LLM prompts.

    Returns a networkx.Graph. Imported lazily to avoid paying the import
    cost when the graph check isn't needed.
    """
    import networkx as nx

    G = nx.Graph()

    # Add all elements as nodes (ensures orphans appear in the graph)
    for el in result.elements:
        key = normalise_name(el.element_name)
        G.add_node(key, label=el.element_name, definition=el.definition)

    # Add edges from relationships
    for rel in result.relationships:
        src = normalise_name(rel.subject)
        tgt = normalise_name(rel.object)
        if src in G and tgt in G and src != tgt:
            G.add_edge(src, tgt, weight=rel.confidence, predicate=rel.predicate)

    return G


def _find_structural_holes(
    G,
    communities: list,
    hole_threshold: float = 0.05,
) -> list[tuple[list[str], list[str], int, float]]:
    """Find pairs of communities with weak or no cross-connections.

    A structural hole exists when the ratio of actual cross-edges to
    possible cross-edges between two communities is below the threshold.

    Returns a list of (community_a_labels, community_b_labels,
    cross_edge_count, density) tuples. Labels are the original
    (non-normalised) element names read from node attributes.
    """
    holes = []
    community_list = [set(c) for c in communities]

    for i in range(len(community_list)):
        for j in range(i + 1, len(community_list)):
            ci, cj = community_list[i], community_list[j]
            cross = sum(
                1 for u in ci for v in cj if G.has_edge(u, v)
            )
            possible = len(ci) * len(cj)
            density = cross / possible if possible > 0 else 0.0

            if density < hole_threshold:
                labels_i = sorted(G.nodes[n].get("label", n) for n in ci)
                labels_j = sorted(G.nodes[n].get("label", n) for n in cj)
                holes.append((labels_i, labels_j, cross, density))

    return holes


def _check_structural_gaps(
    result: FusionResult,
    report: LintReport,
    *,
    min_communities: int = 2,
    hole_threshold: float = 0.05,
    max_gaps: int = DEFAULT_MAX_GAPS,
    max_bridges: int = DEFAULT_MAX_BRIDGES,
) -> None:
    """Detect structural gaps using graph community detection.

    Builds a concept graph from relationships, runs community detection,
    computes betweenness centrality for bridge concepts, and identifies
    structural holes between weakly-connected communities.

    The ``max_gaps`` and ``max_bridges`` caps keep the output actionable
    on large or fragmented ontologies. Results are sorted by severity
    (lowest density / highest centrality first); anything beyond the
    cap is summarised as a single info finding.
    """
    import networkx as nx
    from networkx.algorithms.community import greedy_modularity_communities

    # Need enough structure for meaningful analysis
    if len(result.relationships) == 0:
        return
    G = _build_concept_graph(result)
    if len(G.nodes) < 3:
        return

    # Community detection
    communities = list(greedy_modularity_communities(G))
    if len(communities) < min_communities:
        return

    # Structural holes — sort by severity (worst first):
    #   1. Lowest density (0.0 = fully disconnected)
    #   2. Largest community size (impacts more concepts)
    # max_gaps=0 means "disable the hole check entirely" — no warnings
    # and no overflow summary.
    if max_gaps > 0:
        holes = _find_structural_holes(G, communities, hole_threshold)
        holes_sorted = sorted(
            holes,
            key=lambda h: (h[3], -(len(h[0]) + len(h[1]))),  # density asc, size desc
        )

        total_holes = len(holes_sorted)
        reported_holes = holes_sorted[:max_gaps]

        for labels_a, labels_b, cross, density in reported_holes:
            a_str = ", ".join(labels_a[:5])
            b_str = ", ".join(labels_b[:5])
            if len(labels_a) > 5:
                a_str += f" (+{len(labels_a) - 5} more)"
            if len(labels_b) > 5:
                b_str += f" (+{len(labels_b) - 5} more)"

            report.findings.append(
                LintFinding(
                    category="structural_gap",
                    severity="warning",
                    element_name="",
                    message=(
                        f"Communities {{{a_str}}} and {{{b_str}}} have "
                        f"{'no' if cross == 0 else f'only {cross}'} "
                        f"cross-connection(s) (density {density:.2f}). "
                        f"Consider adding bridging relationships."
                    ),
                    details={
                        "community_a": labels_a,
                        "community_b": labels_b,
                        "cross_edges": cross,
                        "density": density,
                    },
                )
            )

        if total_holes > max_gaps:
            report.findings.append(
                LintFinding(
                    category="structural_gap",
                    severity="info",
                    element_name="",
                    message=(
                        f"{total_holes - max_gaps} additional structural "
                        f"gap(s) not shown (showing worst {max_gaps} of "
                        f"{total_holes}). Re-run with --max-gaps N to see more."
                    ),
                    details={
                        "total_holes": total_holes,
                        "shown": max_gaps,
                    },
                )
            )

    # Bridge concepts (high betweenness centrality) — cap similarly.
    # max_bridges=0 disables the bridge-concept scan entirely.
    if len(G.edges) > 0 and max_bridges > 0:
        centrality = nx.betweenness_centrality(G, weight="weight")
        threshold = 1.0 / max(len(G.nodes) - 1, 1)
        bridges = [
            (node, score) for node, score in centrality.items()
            if score > threshold
        ]
        bridges.sort(key=lambda x: -x[1])

        total_bridges = len(bridges)
        for node, score in bridges[:max_bridges]:
            label = G.nodes[node].get("label", node)
            report.findings.append(
                LintFinding(
                    category="structural_gap",
                    severity="info",
                    element_name=label,
                    message=(
                        f"'{label}' is a bridge concept "
                        f"(betweenness centrality {score:.2f}). "
                        f"It connects otherwise separate concept clusters."
                    ),
                    details={
                        "centrality": round(score, 3),
                    },
                )
            )

        if total_bridges > max_bridges:
            report.findings.append(
                LintFinding(
                    category="structural_gap",
                    severity="info",
                    element_name="",
                    message=(
                        f"{total_bridges - max_bridges} additional bridge "
                        f"concept(s) not shown (showing top {max_bridges} "
                        f"of {total_bridges})."
                    ),
                    details={
                        "total_bridges": total_bridges,
                        "shown": max_bridges,
                    },
                )
            )
