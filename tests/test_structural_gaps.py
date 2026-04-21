"""Tests for structural gap analysis in the lint layer.

Uses networkx community detection and betweenness centrality to find
disconnected concept clusters and bridge concepts in the fused
knowledge graph.
"""

from __future__ import annotations

import pytest

from ontozense.core.fusion import (
    FusedElement,
    FusedRelationship,
    FusionResult,
)
from ontozense.core.lint import lint


def _el(name, definition=""):
    return FusedElement(
        element_name=name,
        definition=definition,
        sources=["A"],
        confidence=0.8,
    )


def _rel(subject, obj, predicate="relates_to"):
    return FusedRelationship(
        subject=subject,
        predicate=predicate,
        object=obj,
        source="A",
        confidence=0.9,
    )


def _result(elements, relationships):
    return FusionResult(
        elements=list(elements),
        relationships=list(relationships),
        sources_used=["A"],
    )


class TestDisconnectedClusters:
    def test_two_disconnected_clusters_produce_finding(self):
        """Two groups of concepts with no cross-edges → structural gap."""
        result = _result(
            elements=[
                _el("A"), _el("B"), _el("C"),  # cluster 1
                _el("X"), _el("Y"), _el("Z"),  # cluster 2
            ],
            relationships=[
                _rel("A", "B"), _rel("B", "C"),  # cluster 1 edges
                _rel("X", "Y"), _rel("Y", "Z"),  # cluster 2 edges
            ],
        )
        report = lint(result)
        gaps = report.by_category("structural_gap")
        warnings = [f for f in gaps if f.severity == "warning"]
        assert len(warnings) >= 1, (
            f"Expected at least 1 structural_gap warning, got {len(warnings)}: "
            f"{[f.message for f in gaps]}"
        )
        # Verify the details contain community info
        assert warnings[0].details.get("community_a")
        assert warnings[0].details.get("community_b")
        assert warnings[0].details.get("cross_edges") == 0

    def test_fully_connected_graph_no_findings(self):
        """All nodes in one community → no structural gaps."""
        result = _result(
            elements=[_el("A"), _el("B"), _el("C"), _el("D")],
            relationships=[
                _rel("A", "B"), _rel("B", "C"),
                _rel("C", "D"), _rel("A", "D"),
                _rel("A", "C"), _rel("B", "D"),
            ],
        )
        report = lint(result)
        gaps = [
            f for f in report.by_category("structural_gap")
            if f.severity == "warning"
        ]
        assert len(gaps) == 0


class TestWeakConnections:
    def test_weakly_connected_clusters_produce_finding(self):
        """Two clusters connected by only 1 edge out of many possible
        → density below threshold → structural gap.
        """
        result = _result(
            elements=[
                _el("A"), _el("B"), _el("C"), _el("D"), _el("E"),  # cluster 1
                _el("V"), _el("W"), _el("X"), _el("Y"), _el("Z"),  # cluster 2
            ],
            relationships=[
                # Dense within cluster 1
                _rel("A", "B"), _rel("B", "C"), _rel("C", "D"),
                _rel("D", "E"), _rel("A", "E"),
                # Dense within cluster 2
                _rel("V", "W"), _rel("W", "X"), _rel("X", "Y"),
                _rel("Y", "Z"), _rel("V", "Z"),
                # Single weak cross-connection
                _rel("E", "V"),
            ],
        )
        report = lint(result)
        gaps = [
            f for f in report.by_category("structural_gap")
            if f.severity == "warning"
        ]
        # Density = 1 / (5*5) = 0.04 < 0.05 threshold
        assert len(gaps) >= 1


class TestBridgeConcepts:
    def test_bridge_concept_reported_as_info(self):
        """A node connecting two clusters should have high betweenness
        and be reported as an info-level finding.
        """
        result = _result(
            elements=[
                _el("A"), _el("B"),      # cluster 1
                _el("Bridge"),           # the bridge
                _el("X"), _el("Y"),      # cluster 2
            ],
            relationships=[
                _rel("A", "B"),
                _rel("A", "Bridge"),
                _rel("Bridge", "X"),
                _rel("X", "Y"),
            ],
        )
        report = lint(result)
        infos = [
            f for f in report.by_category("structural_gap")
            if f.severity == "info"
        ]
        bridge_names = [f.element_name for f in infos]
        assert "Bridge" in bridge_names, (
            f"Expected 'Bridge' in info findings, got {bridge_names}"
        )


class TestEdgeCases:
    def test_fewer_than_3_nodes_no_findings(self):
        """Trivial graphs shouldn't produce structural analysis noise."""
        result = _result(
            elements=[_el("A"), _el("B")],
            relationships=[_rel("A", "B")],
        )
        report = lint(result)
        gaps = report.by_category("structural_gap")
        assert len(gaps) == 0

    def test_no_relationships_no_findings(self):
        """No relationships = no graph to analyse."""
        result = _result(
            elements=[_el("A"), _el("B"), _el("C"), _el("D")],
            relationships=[],
        )
        report = lint(result)
        gaps = report.by_category("structural_gap")
        assert len(gaps) == 0


class TestOutputCapping:
    """The max_gaps / max_bridges kwargs prevent noise on fragmented graphs."""

    def _build_fragmented_result(self, n_clusters=15):
        """Build a graph with many small disconnected clusters.

        Each cluster is 2 nodes with 1 internal edge; no cross-edges
        between clusters. Produces n_clusters*(n_clusters-1)/2
        community pairs, all with density 0.
        """
        elements = []
        relationships = []
        for i in range(n_clusters):
            a, b = f"A{i}", f"B{i}"
            elements.append(_el(a))
            elements.append(_el(b))
            relationships.append(_rel(a, b))
        return _result(elements, relationships)

    def test_default_cap_limits_warnings_to_10(self):
        """Default max_gaps=10 → at most 10 structural_gap warnings
        plus 1 info summarising the overflow."""
        result = self._build_fragmented_result(n_clusters=15)
        report = lint(result)
        gaps = report.by_category("structural_gap")
        warnings = [f for f in gaps if f.severity == "warning"]
        assert len(warnings) <= 10, (
            f"Default cap should limit warnings to 10, got {len(warnings)}"
        )

    def test_overflow_summary_emitted(self):
        """When gaps > max_gaps, an info finding reports the overflow."""
        result = self._build_fragmented_result(n_clusters=15)
        # 15 clusters → C(15,2) = 105 community pairs, all density 0
        report = lint(result, max_gaps=5)
        infos = [
            f for f in report.by_category("structural_gap")
            if f.severity == "info" and "not shown" in f.message
        ]
        assert len(infos) == 1
        assert "additional structural gap" in infos[0].message
        assert infos[0].details.get("shown") == 5

    def test_custom_max_gaps_honoured(self):
        """lint(max_gaps=3) reports at most 3 warnings."""
        result = self._build_fragmented_result(n_clusters=10)
        report = lint(result, max_gaps=3)
        warnings = [
            f for f in report.by_category("structural_gap")
            if f.severity == "warning"
        ]
        assert len(warnings) <= 3

    def test_worst_gaps_reported_first(self):
        """Gaps with density 0.0 should be reported before denser ones."""
        # Three clusters: {A,B} fully disconnected from {C,D}, but
        # {E,F} has one cross-edge to {A,B} (lower severity).
        result = _result(
            elements=[_el(n) for n in ["A", "B", "C", "D", "E", "F", "G", "H"]],
            relationships=[
                _rel("A", "B"), _rel("C", "D"),
                _rel("E", "F"), _rel("G", "H"),
                _rel("A", "E"),  # weak bridge — lowers severity of that pair
            ],
        )
        report = lint(result, max_gaps=1)
        warnings = [
            f for f in report.by_category("structural_gap")
            if f.severity == "warning"
        ]
        # The single reported warning should be the worst (density 0.0)
        if warnings:
            assert warnings[0].details["density"] == 0.0

    def test_no_overflow_summary_when_under_cap(self):
        """If gaps <= max_gaps, no overflow info is emitted."""
        result = self._build_fragmented_result(n_clusters=3)
        # 3 clusters → C(3,2) = 3 pairs; under default cap of 10
        report = lint(result)
        overflow_infos = [
            f for f in report.by_category("structural_gap")
            if f.severity == "info" and "not shown" in f.message
        ]
        assert len(overflow_infos) == 0
