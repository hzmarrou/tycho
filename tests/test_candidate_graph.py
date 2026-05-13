"""Tests for the candidate graph builder (profile induction
architecture, Phase 1 / Task 2).

The builder ingests source outputs (raw dicts that mirror the
existing Source A/B/C/D JSON shapes) and produces a merged graph of
``CandidateConcept`` objects keyed conservatively by normalised
label. Merge logic must:

  - Combine evidence across sources for the same normalised label.
  - Track ``source_presence`` and ``source_counts`` per candidate.
  - Keep ambiguous / distinct labels separate (don't over-merge).
  - Preserve provenance / aliases.
"""

from __future__ import annotations

from ontozense.core.candidate_graph import build_candidate_graph


# ─── Cross-source merging by normalised label ──────────────────────────────


class TestSourceMerging:
    def test_same_normalized_label_across_a_and_b_merges_to_one_candidate(self):
        source_a = {
            "concepts": [
                {
                    "name": "Customer",
                    "definition": "A client.",
                    "provenance": {"source_document": "a.md"},
                }
            ],
            "relationships": [],
        }
        source_b = {
            "records": [
                {"element_name": "customer", "definition": "Governed customer record."}
            ]
        }
        graph = build_candidate_graph(source_a=source_a, source_b=source_b)
        assert len(graph.concepts) == 1
        c = graph.concepts[0]
        # Cross-source presence both flipped on
        assert c.source_presence["A"] is True
        assert c.source_presence["B"] is True
        # Counts tally per source
        assert c.source_counts["A"] == 1
        assert c.source_counts["B"] == 1
        # Authoritative-evidence count rises only for Source A
        assert c.authoritative_evidence_count == 1
        # Provenance accumulates one entry per source contribution
        assert len(c.provenance) == 2
        sources_in_prov = {p.source_type for p in c.provenance}
        assert sources_in_prov == {"A", "B"}

    def test_distinct_labels_kept_separate(self):
        source_a = {
            "concepts": [
                {"name": "Default", "definition": "Loan default."},
                {"name": "Default Rate", "definition": "Frequency of default."},
            ],
            "relationships": [],
        }
        graph = build_candidate_graph(source_a=source_a)
        assert len(graph.concepts) == 2
        labels = {c.label for c in graph.concepts}
        assert labels == {"Default", "Default Rate"}

    def test_case_variants_merge(self):
        """``CUSTOMER`` and ``customer`` normalise to the same label."""
        source_a = {
            "concepts": [
                {"name": "CUSTOMER", "definition": "All caps."},
                {"name": "customer", "definition": "lowercase."},
            ],
            "relationships": [],
        }
        graph = build_candidate_graph(source_a=source_a)
        assert len(graph.concepts) == 1
        c = graph.concepts[0]
        # Both surface forms tracked as aliases
        assert "CUSTOMER" in c.aliases
        assert "customer" in c.aliases


# ─── Defaults and edge cases ───────────────────────────────────────────────


class TestEmptyAndDefaults:
    def test_no_sources_yields_empty_graph(self):
        graph = build_candidate_graph()
        assert graph.concepts == []
        assert graph.relationships == []

    def test_empty_label_skipped(self):
        source_a = {
            "concepts": [
                {"name": "", "definition": "no name"},
                {"name": "RealName", "definition": "actual"},
            ],
            "relationships": [],
        }
        graph = build_candidate_graph(source_a=source_a)
        assert len(graph.concepts) == 1
        assert graph.concepts[0].label == "RealName"

    def test_candidate_id_derived_from_normalised_label(self):
        source_a = {
            "concepts": [{"name": "Customer Identifier", "definition": "id"}],
            "relationships": [],
        }
        graph = build_candidate_graph(source_a=source_a)
        c = graph.concepts[0]
        # ID is deterministic from the normalised label
        assert c.candidate_id.startswith("cand_")
        assert "customer" in c.candidate_id.lower()


# ─── JSON serialisation ────────────────────────────────────────────────────


class TestSerialisation:
    def test_graph_to_dict_round_trippable(self):
        source_a = {
            "concepts": [{"name": "X", "definition": "x def"}],
            "relationships": [],
        }
        graph = build_candidate_graph(source_a=source_a)
        raw = graph.to_dict()
        assert "concepts" in raw and isinstance(raw["concepts"], list)
        assert "relationships" in raw and isinstance(raw["relationships"], list)
        # Each concept is a JSON-friendly dict
        assert raw["concepts"][0]["label"] == "X"
        assert raw["concepts"][0]["source_presence"]["A"] is True
