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
