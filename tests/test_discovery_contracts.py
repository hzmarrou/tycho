"""Tests for the discovery-side typed contracts (profile induction
architecture, Phase 1 / Task 1).

These dataclasses are pure data carriers — no behaviour beyond
round-trip JSON serialisation. The tests verify the shape, defaults,
and dict round-trip for each.
"""

from __future__ import annotations

from ontozense.core.discovery_contracts import (
    CandidateConcept,
    CandidateRelationship,
    EvidenceEntry,
    InductionReport,
)


# ─── EvidenceEntry ──────────────────────────────────────────────────────────


class TestEvidenceEntry:
    def test_defaults(self):
        e = EvidenceEntry(source_type="A", source_artifact="docs/x.md")
        assert e.snippet == ""
        assert e.raw_label == ""
        assert e.raw_type == ""
        assert e.confidence == 0.0
        assert e.anchor is None

    def test_round_trip_dict(self):
        original = EvidenceEntry(
            source_type="A",
            source_artifact="docs/x.md",
            anchor={"line": 42, "page": 3},
            snippet="A customer is...",
            raw_label="customer",
            raw_type="Concept",
            confidence=0.91,
        )
        raw = original.to_dict()
        assert EvidenceEntry.from_dict(raw) == original


# ─── CandidateConcept ──────────────────────────────────────────────────────


class TestCandidateConcept:
    def test_required_fields_minimal_construction(self):
        c = CandidateConcept(
            candidate_id="cand_x",
            label="X",
            normalized_label="x",
            suggested_entity_type="Concept",
            classification="unknown",
            summary_definition="",
            source_presence={"A": False, "B": False, "C": False, "D": False},
            source_counts={"A": 0, "B": 0, "C": 0, "D": 0},
        )
        # Defaults
        assert c.schema_links == []
        assert c.code_links == []
        assert c.governance_links == []
        assert c.authoritative_evidence_count == 0
        assert c.graph_degree == 0
        assert c.relevance_score == 0.0
        assert c.relevance_breakdown == {}
        assert c.provenance == []
        assert c.aliases == []
        assert c.status == "candidate"

    def test_round_trip_dict(self):
        concept = CandidateConcept(
            candidate_id="cand_customer",
            label="Customer",
            normalized_label="customer",
            suggested_entity_type="Concept",
            classification="core_business",
            summary_definition="A person or organization receiving a service.",
            source_presence={"A": True, "B": True, "C": False, "D": True},
            source_counts={"A": 2, "B": 1, "C": 0, "D": 3},
            schema_links=[],
            code_links=[],
            governance_links=[],
            authoritative_evidence_count=2,
            graph_degree=4,
            relevance_score=0.84,
            relevance_breakdown={"authoritative_frequency": 0.25},
            provenance=[
                EvidenceEntry(
                    source_type="A",
                    source_artifact="docs/reg.md",
                    snippet="Customer means...",
                    confidence=0.92,
                ),
            ],
            aliases=["Customers", "Client"],
            status="candidate",
        )
        raw = concept.to_dict()
        # Nested provenance round-trips as a list of dicts
        assert isinstance(raw["provenance"], list)
        assert raw["provenance"][0]["source_type"] == "A"
        assert CandidateConcept.from_dict(raw) == concept


# ─── CandidateRelationship ─────────────────────────────────────────────────


class TestCandidateRelationship:
    def test_defaults(self):
        r = CandidateRelationship(
            subject_candidate_id="cand_a",
            predicate="has",
            object_candidate_id="cand_b",
        )
        assert r.canonical_predicate == ""
        assert r.source_presence == {}
        assert r.relevance_score == 0.0
        assert r.provenance == []

    def test_round_trip_dict(self):
        original = CandidateRelationship(
            subject_candidate_id="cand_a",
            predicate="has",
            object_candidate_id="cand_b",
            canonical_predicate="HasA",
            source_presence={"A": True, "B": False},
            relevance_score=0.7,
            provenance=[
                EvidenceEntry(
                    source_type="A",
                    source_artifact="docs/y.md",
                    confidence=0.85,
                ),
            ],
        )
        assert CandidateRelationship.from_dict(original.to_dict()) == original


# ─── InductionReport ───────────────────────────────────────────────────────


class TestInductionReport:
    def test_round_trip_dict(self):
        report = InductionReport(
            domain_name="npl",
            generated_at="2026-05-13T10:00:00",
            candidate_count=10,
            selected_core_count=4,
            selected_supporting_count=3,
            rejected_count=3,
            scoring_weights={"authoritative_frequency": 0.25},
            top_candidates=[{"candidate_id": "cand_customer", "score": 0.9}],
            rejected_examples=[{"candidate_id": "cand_tmp_col_1", "score": 0.1}],
            predicate_suggestions=[{"predicate": "AppliesTo", "support": 3}],
            required_field_suggestions={"Concept": ["definition"]},
            review_notes=["Review aliases before production use."],
        )
        assert InductionReport.from_dict(report.to_dict()) == report

    def test_scoring_thresholds_defaults_to_empty_dict(self):
        # Backward-compatibility pin: callers that construct an
        # InductionReport without explicitly setting scoring_thresholds
        # (e.g. existing tests, existing serialised reports) must
        # still work — the field gets a default-factory empty dict.
        report = InductionReport(
            domain_name="demo",
            generated_at="2026-05-13T10:00:00",
            candidate_count=0,
            selected_core_count=0,
            selected_supporting_count=0,
            rejected_count=0,
            scoring_weights={},
            top_candidates=[],
            rejected_examples=[],
            predicate_suggestions=[],
            required_field_suggestions={},
            review_notes=[],
        )
        assert report.scoring_thresholds == {}

    def test_round_trip_with_scoring_thresholds(self):
        report = InductionReport(
            domain_name="demo",
            generated_at="2026-05-13T10:00:00",
            candidate_count=5,
            selected_core_count=2,
            selected_supporting_count=1,
            rejected_count=2,
            scoring_weights={
                "authoritative_frequency": 0.25,
                "governance_presence": 0.20,
            },
            top_candidates=[],
            rejected_examples=[],
            predicate_suggestions=[],
            required_field_suggestions={},
            review_notes=[],
            scoring_thresholds={
                "core_business": 0.70,
                "supporting_technical": 0.40,
            },
        )
        raw = report.to_dict()
        # Serialised JSON must carry both maps explicitly so a
        # reviewer can see which thresholds the induction used.
        assert raw["scoring_thresholds"] == {
            "core_business": 0.70,
            "supporting_technical": 0.40,
        }
        assert InductionReport.from_dict(raw) == report

    def test_from_dict_handles_legacy_json_without_thresholds_key(self):
        # An InductionReport JSON file emitted *before* the
        # scoring_thresholds field was added must still load. The
        # dataclass's default_factory fills in the missing key as an
        # empty dict.
        legacy = {
            "domain_name": "demo",
            "generated_at": "2026-05-13T10:00:00",
            "candidate_count": 0,
            "selected_core_count": 0,
            "selected_supporting_count": 0,
            "rejected_count": 0,
            "scoring_weights": {},
            "top_candidates": [],
            "rejected_examples": [],
            "predicate_suggestions": [],
            "required_field_suggestions": {},
            "review_notes": [],
            # scoring_thresholds intentionally absent
        }
        loaded = InductionReport.from_dict(legacy)
        assert loaded.scoring_thresholds == {}
