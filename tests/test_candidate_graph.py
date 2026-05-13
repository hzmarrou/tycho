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


# ─── Id-first merge contract (architecture §"Candidate merge rules") ───────


class TestIdFirstMergeContract:
    """The architecture requires merge-key priority:
      1. existing profile-mode id
      2. normalised canonical label
      3. alias-expanded label
      4. source-specific fallback
    and: ambiguous cases must stay split.
    These tests pin the four resulting cases."""

    def test_same_id_different_labels_merge(self):
        """Profile-mode same canonical entity from two sources via
        identical deterministic ids — surface labels differ but the
        candidates must collapse to one."""
        source_a = {
            "concepts": [
                {"name": "Customer Identifier", "id": "concept_cust_111111",
                 "entity_type": "Concept", "definition": "Source A wording."},
            ],
            "relationships": [],
        }
        source_b = {
            "records": [
                {"element_name": "customer-id", "id": "concept_cust_111111",
                 "entity_type": "Concept", "definition": "Governance wording."},
            ],
        }
        graph = build_candidate_graph(source_a=source_a, source_b=source_b)
        assert len(graph.concepts) == 1
        c = graph.concepts[0]
        assert c.source_presence["A"] is True
        assert c.source_presence["B"] is True
        # Two surface forms tracked as aliases despite different labels
        assert "Customer Identifier" in c.aliases
        assert "customer-id" in c.aliases

    def test_same_name_different_ids_stay_separate(self):
        """Ambiguity: two profile-mode concepts that share a normalised
        label but carry distinct ids must NOT merge — they're
        genuinely different entities of the same surface name."""
        source_a = {
            "concepts": [
                {"name": "Default", "id": "rule_default_aaaaaa",
                 "entity_type": "Rule", "definition": "A code rule."},
                {"name": "Default", "id": "concept_default_bbbbbb",
                 "entity_type": "Concept", "definition": "A loan default state."},
            ],
            "relationships": [],
        }
        graph = build_candidate_graph(source_a=source_a)
        assert len(graph.concepts) == 2
        # Both ids surface in candidate ids
        cand_ids = {c.candidate_id for c in graph.concepts}
        assert "cand_id_rule_default_aaaaaa" in cand_ids
        assert "cand_id_concept_default_bbbbbb" in cand_ids

    def test_existing_has_no_id_incoming_has_id_promotes(self):
        """When an existing candidate (from an earlier source) lacks
        an id and a later source contributes the same normalised
        label WITH an id, the existing is promoted to claim the id
        — mixed-mode tolerance."""
        source_a = {
            "concepts": [
                {"name": "Customer", "definition": "Unconstrained wording."},
            ],
            "relationships": [],
        }
        source_b = {
            "records": [
                {"element_name": "Customer", "id": "concept_cust_999999",
                 "entity_type": "Concept", "definition": "Governance wording."},
            ],
        }
        graph = build_candidate_graph(source_a=source_a, source_b=source_b)
        assert len(graph.concepts) == 1
        c = graph.concepts[0]
        # The candidate now references the promoted id
        assert c.candidate_id == "cand_id_concept_cust_999999"
        assert c.source_presence["A"] is True
        assert c.source_presence["B"] is True

    def test_neither_has_id_falls_back_to_name(self):
        """Plain unconstrained mode: no ids on either side, merge by
        normalised label (the existing Phase 1 baseline)."""
        source_a = {
            "concepts": [{"name": "Customer", "definition": "A."}],
            "relationships": [],
        }
        source_b = {
            "records": [{"element_name": "customer", "definition": "B."}],
        }
        graph = build_candidate_graph(source_a=source_a, source_b=source_b)
        assert len(graph.concepts) == 1


# ─── Relationship ingestion + graph_degree (architecture §"Graph features") ─


class TestRelationshipIngestion:
    def test_source_a_relationships_become_candidate_relationships(self):
        """Source A's subject-predicate-object triples are materialised
        as CandidateRelationship objects referencing candidate IDs."""
        source_a = {
            "concepts": [
                {"name": "Loan", "definition": "L."},
                {"name": "Borrower", "definition": "B."},
            ],
            "relationships": [
                {"subject": "Loan", "predicate": "HasBorrower", "object": "Borrower"},
            ],
        }
        graph = build_candidate_graph(source_a=source_a)
        assert len(graph.relationships) == 1
        rel = graph.relationships[0]
        assert rel.predicate == "HasBorrower"
        # Endpoints are resolved to candidate IDs, not raw labels
        cand_loan = next(c for c in graph.concepts if c.label == "Loan")
        cand_borrower = next(c for c in graph.concepts if c.label == "Borrower")
        assert rel.subject_candidate_id == cand_loan.candidate_id
        assert rel.object_candidate_id == cand_borrower.candidate_id

    def test_graph_degree_increments_from_relationships(self):
        """graph_degree is the distinct-neighbour count per candidate."""
        source_a = {
            "concepts": [
                {"name": "Loan", "definition": "L."},
                {"name": "Borrower", "definition": "B."},
                {"name": "Collateral", "definition": "C."},
            ],
            "relationships": [
                {"subject": "Loan", "predicate": "HasBorrower", "object": "Borrower"},
                {"subject": "Loan", "predicate": "SecuredBy", "object": "Collateral"},
            ],
        }
        graph = build_candidate_graph(source_a=source_a)
        loan = next(c for c in graph.concepts if c.label == "Loan")
        borrower = next(c for c in graph.concepts if c.label == "Borrower")
        collateral = next(c for c in graph.concepts if c.label == "Collateral")
        # Loan has two distinct neighbours
        assert loan.graph_degree == 2
        # Borrower and Collateral each have one (Loan)
        assert borrower.graph_degree == 1
        assert collateral.graph_degree == 1

    def test_relationships_with_unresolved_endpoints_are_skipped(self):
        """If a relationship references an entity that wasn't
        extracted as a concept, skip it. The lint stage downstream
        catches dangling references."""
        source_a = {
            "concepts": [{"name": "Loan", "definition": "L."}],
            "relationships": [
                {"subject": "Loan", "predicate": "HasBorrower",
                 "object": "NeverExtracted"},
            ],
        }
        graph = build_candidate_graph(source_a=source_a)
        assert len(graph.relationships) == 0
        assert graph.concepts[0].graph_degree == 0

    def test_zero_graph_degree_when_no_relationships(self):
        """Sanity check the default."""
        source_a = {
            "concepts": [{"name": "X", "definition": "x"}],
            "relationships": [],
        }
        graph = build_candidate_graph(source_a=source_a)
        assert graph.concepts[0].graph_degree == 0
