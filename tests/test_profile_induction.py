"""Tests for the induced-profile writer (profile induction
architecture, Phase 2 / Task 4).

Acceptance criterion 1 (AC1) for this task is the hard pin: the
schema.json that ``write_induced_profile`` emits must round-trip
through the existing ``load_profile`` loader without changes to
that loader.

Beyond AC1 the tests pin the architecture's documented contracts:

  - Candidates classified ``core_business`` are clustered as
    subtypes of ``Concept``; ``supporting_technical`` as subtypes
    of ``TechnicalArtifact`` (architecture §"Entity type induction"
    step 2).
  - ``noise`` candidates are excluded from the schema but surface
    in ``induction_report.json``'s ``rejected_examples``.
  - The report records both ``scoring_weights`` and
    ``scoring_thresholds`` so a reviewer can reproduce the
    classification (Phase 1 contract amendment for thresholds).
  - Sidecar files emitted: ``alias_map.json``, ``prompt_fragment.md``,
    ``induction_report.json``.
"""

from __future__ import annotations

import json
from pathlib import Path

from ontozense.core.discovery_contracts import CandidateConcept
from ontozense.core.profile import load_profile
from ontozense.core.profile_induction import write_induced_profile
from ontozense.core.relevance import DEFAULT_THRESHOLDS, DEFAULT_WEIGHTS


# ─── Helpers ────────────────────────────────────────────────────────────────


def _candidate(
    label: str,
    *,
    classification: str = "core_business",
    score: float = 0.8,
) -> CandidateConcept:
    """Build a CandidateConcept already at the post-scoring shape
    that write_induced_profile expects (classification + score
    populated)."""
    return CandidateConcept(
        candidate_id=f"cand_{label.lower().replace(' ', '_')}",
        label=label,
        normalized_label=label.lower(),
        suggested_entity_type="Concept",
        classification=classification,
        summary_definition=f"{label} definition.",
        source_presence={"A": True, "B": True, "C": False, "D": False},
        source_counts={"A": 2, "B": 1, "C": 0, "D": 0},
        authoritative_evidence_count=2,
        graph_degree=2,
        relevance_score=score,
        relevance_breakdown={"authoritative_frequency": 0.25},
    )


# ─── AC1: loader-compatible schema (plan tests + round-trip) ───────────────


class TestLoaderCompatibility:
    """The emitted schema.json must round-trip through load_profile
    without any loader changes. The plan calls these out as the two
    canonical Task 4 tests; the round-trip test below is the AC1
    pin."""

    def test_emits_loader_compatible_schema(self, tmp_path: Path):
        out_dir = tmp_path / "induced-profile"
        write_induced_profile(
            "demo", [_candidate("Customer")], out_dir,
        )
        profile = load_profile(out_dir)
        assert profile.profile_name == "demo"
        assert "Concept" in profile.entity_types

    def test_writes_induction_report(self, tmp_path: Path):
        out_dir = tmp_path / "induced-profile"
        write_induced_profile("demo", [], out_dir)
        raw = json.loads(
            (out_dir / "induction_report.json").read_text(encoding="utf-8")
        )
        assert raw["domain_name"] == "demo"

    def test_emitted_schema_round_trips_through_load_profile(
        self, tmp_path: Path,
    ):
        """AC1: a profile written by induction must load cleanly,
        every field intact, no ProfileError raised."""
        candidates = [
            _candidate("Customer", classification="core_business"),
            _candidate("Address", classification="core_business"),
            _candidate(
                "tmp_col_1",
                classification="supporting_technical",
                score=0.5,
            ),
        ]
        out_dir = tmp_path / "induced-profile"
        write_induced_profile("demo", candidates, out_dir)

        profile = load_profile(out_dir)
        assert profile.profile_name == "demo"
        # Both type buckets present because we have both bands.
        assert "Concept" in profile.entity_types
        assert "TechnicalArtifact" in profile.entity_types

    def test_minimum_loader_required_fields_are_present(
        self, tmp_path: Path,
    ):
        """schema.json must include the four keys load_profile
        validates as required."""
        out_dir = tmp_path / "induced-profile"
        write_induced_profile("demo", [_candidate("X")], out_dir)
        raw = json.loads(
            (out_dir / "schema.json").read_text(encoding="utf-8")
        )
        for key in ("profile_name", "profile_version",
                    "entity_types", "predicates"):
            assert key in raw, f"schema.json missing required key {key!r}"


# ─── Entity type induction (architecture §"Entity type induction") ────────


class TestEntityTypeClustering:

    def test_core_business_candidates_become_concept_subtypes(
        self, tmp_path: Path,
    ):
        candidates = [
            _candidate("Customer", classification="core_business"),
            _candidate("Order", classification="core_business"),
        ]
        out_dir = tmp_path / "induced-profile"
        write_induced_profile("demo", candidates, out_dir)
        profile = load_profile(out_dir)
        concept = profile.entity_types["Concept"]
        assert "Customer" in concept.subtypes
        assert "Order" in concept.subtypes

    def test_supporting_technical_candidates_become_technical_subtypes(
        self, tmp_path: Path,
    ):
        candidates = [
            _candidate(
                "tmp_col_1",
                classification="supporting_technical",
                score=0.5,
            ),
            _candidate(
                "internal_flag",
                classification="supporting_technical",
                score=0.5,
            ),
        ]
        out_dir = tmp_path / "induced-profile"
        write_induced_profile("demo", candidates, out_dir)
        profile = load_profile(out_dir)
        tech = profile.entity_types["TechnicalArtifact"]
        assert "tmp_col_1" in tech.subtypes
        assert "internal_flag" in tech.subtypes

    def test_no_supporting_candidates_omits_technical_type(
        self, tmp_path: Path,
    ):
        """If nothing classifies as supporting_technical, the schema
        omits the TechnicalArtifact bucket entirely — keeps the
        induced profile minimal."""
        candidates = [_candidate("Customer")]
        out_dir = tmp_path / "induced-profile"
        write_induced_profile("demo", candidates, out_dir)
        profile = load_profile(out_dir)
        assert "Concept" in profile.entity_types
        assert "TechnicalArtifact" not in profile.entity_types

    def test_empty_candidate_list_still_produces_loader_valid_schema(
        self, tmp_path: Path,
    ):
        """Edge case: zero candidates. Loader requires entity_types
        be non-empty, so we always emit at least the Concept bucket
        with no subtypes."""
        out_dir = tmp_path / "induced-profile"
        write_induced_profile("demo", [], out_dir)
        profile = load_profile(out_dir)
        assert "Concept" in profile.entity_types
        assert profile.entity_types["Concept"].subtypes == []

    def test_noise_candidates_excluded_from_schema_subtypes(
        self, tmp_path: Path,
    ):
        candidates = [
            _candidate("Customer", classification="core_business"),
            _candidate("garbage_x", classification="noise", score=0.1),
        ]
        out_dir = tmp_path / "induced-profile"
        write_induced_profile("demo", candidates, out_dir)
        profile = load_profile(out_dir)
        for et in profile.entity_types.values():
            assert "garbage_x" not in et.subtypes

    def test_duplicate_candidate_labels_are_deduplicated_in_subtypes(
        self, tmp_path: Path,
    ):
        """Two candidates kept separate by id-collision ambiguity can
        share a label. The schema's subtype list must dedupe so the
        loader doesn't see a malformed (duplicate) subtype."""
        candidates = [
            _candidate("Customer", classification="core_business"),
            _candidate("Customer", classification="core_business"),
        ]
        out_dir = tmp_path / "induced-profile"
        write_induced_profile("demo", candidates, out_dir)
        profile = load_profile(out_dir)
        subs = profile.entity_types["Concept"].subtypes
        assert subs.count("Customer") == 1

    def test_label_colliding_with_reserved_type_name_is_dropped(
        self, tmp_path: Path,
    ):
        """A candidate labelled exactly "Concept" or "TechnicalArtifact"
        would collide with a top-level type name and crash the
        loader's collision check. Such candidates must be dropped
        from the subtypes list and surfaced in review_notes."""
        candidates = [
            _candidate("Concept", classification="core_business"),
        ]
        out_dir = tmp_path / "induced-profile"
        write_induced_profile("demo", candidates, out_dir)
        # The loader must accept the result without raising.
        profile = load_profile(out_dir)
        assert "Concept" not in profile.entity_types["Concept"].subtypes
        report = json.loads(
            (out_dir / "induction_report.json").read_text(encoding="utf-8")
        )
        # The review_notes flag explains why it was dropped.
        notes = " ".join(report["review_notes"])
        assert "Concept" in notes

    def test_same_label_in_both_bands_does_not_cross_subtype_buckets(
        self, tmp_path: Path,
    ):
        """If a label appears in both core_business and
        supporting_technical (a rare ambiguity case), the loader's
        cross-parent collision check would reject the schema. The
        induction stage must drop the supporting one and log a
        review note."""
        candidates = [
            _candidate("Address", classification="core_business"),
            _candidate(
                "Address",
                classification="supporting_technical",
                score=0.5,
            ),
        ]
        out_dir = tmp_path / "induced-profile"
        write_induced_profile("demo", candidates, out_dir)
        # Loader must accept the schema.
        profile = load_profile(out_dir)
        # "Address" must appear in Concept's subtypes, not in
        # TechnicalArtifact's.
        assert "Address" in profile.entity_types["Concept"].subtypes
        if "TechnicalArtifact" in profile.entity_types:
            assert "Address" not in \
                profile.entity_types["TechnicalArtifact"].subtypes


# ─── Induction report contents ─────────────────────────────────────────────


class TestInductionReportContents:

    def test_report_counts_match_classification_bands(
        self, tmp_path: Path,
    ):
        candidates = [
            _candidate("A", classification="core_business"),
            _candidate("B", classification="core_business"),
            _candidate(
                "C", classification="supporting_technical", score=0.5,
            ),
            _candidate("D", classification="noise", score=0.1),
            _candidate("E", classification="noise", score=0.1),
        ]
        out_dir = tmp_path / "induced-profile"
        write_induced_profile("demo", candidates, out_dir)
        raw = json.loads(
            (out_dir / "induction_report.json").read_text(encoding="utf-8")
        )
        assert raw["candidate_count"] == 5
        assert raw["selected_core_count"] == 2
        assert raw["selected_supporting_count"] == 1
        assert raw["rejected_count"] == 2

    def test_rejected_examples_contain_noise_candidates(
        self, tmp_path: Path,
    ):
        candidates = [
            _candidate("Customer", classification="core_business"),
            _candidate("tmp_x", classification="noise", score=0.1),
        ]
        out_dir = tmp_path / "induced-profile"
        write_induced_profile("demo", candidates, out_dir)
        raw = json.loads(
            (out_dir / "induction_report.json").read_text(encoding="utf-8")
        )
        ids = [e["candidate_id"] for e in raw["rejected_examples"]]
        assert "cand_tmp_x" in ids
        assert "cand_customer" not in ids

    def test_top_candidates_sorted_by_score_descending(
        self, tmp_path: Path,
    ):
        candidates = [
            _candidate("Low", classification="core_business", score=0.71),
            _candidate("High", classification="core_business", score=0.95),
            _candidate("Mid", classification="core_business", score=0.85),
        ]
        out_dir = tmp_path / "induced-profile"
        write_induced_profile("demo", candidates, out_dir)
        raw = json.loads(
            (out_dir / "induction_report.json").read_text(encoding="utf-8")
        )
        scores = [e["score"] for e in raw["top_candidates"]]
        assert scores == sorted(scores, reverse=True)

    def test_report_records_scoring_weights_when_supplied(
        self, tmp_path: Path,
    ):
        custom_weights = dict(DEFAULT_WEIGHTS)
        custom_weights["authoritative_frequency"] = 0.50
        out_dir = tmp_path / "induced-profile"
        write_induced_profile(
            "demo", [_candidate("X")], out_dir, weights=custom_weights,
        )
        raw = json.loads(
            (out_dir / "induction_report.json").read_text(encoding="utf-8")
        )
        assert raw["scoring_weights"] == custom_weights

    def test_report_records_scoring_thresholds_when_supplied(
        self, tmp_path: Path,
    ):
        custom_thresholds = {
            "core_business": 0.80,
            "supporting_technical": 0.50,
        }
        out_dir = tmp_path / "induced-profile"
        write_induced_profile(
            "demo", [_candidate("X")], out_dir,
            thresholds=custom_thresholds,
        )
        raw = json.loads(
            (out_dir / "induction_report.json").read_text(encoding="utf-8")
        )
        assert raw["scoring_thresholds"] == custom_thresholds

    def test_default_weights_and_thresholds_recorded_when_omitted(
        self, tmp_path: Path,
    ):
        """If the caller doesn't pass weights / thresholds, the
        report records the documented defaults so a reviewer always
        sees the exact configuration used."""
        out_dir = tmp_path / "induced-profile"
        write_induced_profile("demo", [_candidate("X")], out_dir)
        raw = json.loads(
            (out_dir / "induction_report.json").read_text(encoding="utf-8")
        )
        assert raw["scoring_weights"] == dict(DEFAULT_WEIGHTS)
        assert raw["scoring_thresholds"] == dict(DEFAULT_THRESHOLDS)

    def test_required_field_suggestions_cover_each_emitted_type(
        self, tmp_path: Path,
    ):
        candidates = [
            _candidate("Customer", classification="core_business"),
            _candidate(
                "tmp_x", classification="supporting_technical", score=0.5,
            ),
        ]
        out_dir = tmp_path / "induced-profile"
        write_induced_profile("demo", candidates, out_dir)
        raw = json.loads(
            (out_dir / "induction_report.json").read_text(encoding="utf-8")
        )
        # Both emitted top-level types must have a required-field
        # suggestion entry.
        assert "Concept" in raw["required_field_suggestions"]
        assert "TechnicalArtifact" in raw["required_field_suggestions"]


# ─── Audit-trail reconciliation (round-1 reviewer finding) ─────────────────


class TestAuditTrailReconciliation:
    """Every candidate must be accounted for: the report's bucket
    counts must sum to candidate_count, and every candidate must
    appear in either top_candidates or rejected_examples. A previous
    implementation only counted explicit ``"noise"`` as rejected, so
    legacy ``"unknown"``-classified or any non-standard-band
    candidate would silently disappear from both the counts and the
    audit lists. These tests pin the reconciliation property."""

    def test_unknown_classification_candidate_appears_in_rejected_count(
        self, tmp_path: Path,
    ):
        candidates = [
            _candidate("Customer", classification="core_business"),
            # Default classification on the dataclass is "unknown" —
            # what a caller would see if they skipped score_candidates.
            _candidate("Orphan", classification="unknown", score=0.0),
        ]
        out_dir = tmp_path / "induced-profile"
        write_induced_profile("demo", candidates, out_dir)
        raw = json.loads(
            (out_dir / "induction_report.json").read_text(encoding="utf-8")
        )
        assert raw["rejected_count"] == 1

    def test_unknown_classification_candidate_appears_in_rejected_examples(
        self, tmp_path: Path,
    ):
        candidates = [
            _candidate("Orphan", classification="unknown", score=0.0),
        ]
        out_dir = tmp_path / "induced-profile"
        write_induced_profile("demo", candidates, out_dir)
        raw = json.loads(
            (out_dir / "induction_report.json").read_text(encoding="utf-8")
        )
        ids = [e["candidate_id"] for e in raw["rejected_examples"]]
        assert "cand_orphan" in ids

    def test_non_standard_classification_logged_in_review_notes(
        self, tmp_path: Path,
    ):
        candidates = [
            _candidate("Orphan", classification="unknown", score=0.0),
        ]
        out_dir = tmp_path / "induced-profile"
        write_induced_profile("demo", candidates, out_dir)
        raw = json.loads(
            (out_dir / "induction_report.json").read_text(encoding="utf-8")
        )
        notes = " ".join(raw["review_notes"])
        # The note must cite the actual non-standard classification
        # value so the reviewer can trace it back to the upstream
        # stage (typically a forgotten score_candidates() call).
        assert "unknown" in notes

    def test_only_noise_does_not_trigger_non_standard_review_note(
        self, tmp_path: Path,
    ):
        """If every rejected candidate is in the documented ``noise``
        band, the non-standard-classification note must *not* fire
        — it would be noise itself."""
        candidates = [
            _candidate("Customer", classification="core_business"),
            _candidate("garbage", classification="noise", score=0.1),
        ]
        out_dir = tmp_path / "induced-profile"
        write_induced_profile("demo", candidates, out_dir)
        raw = json.loads(
            (out_dir / "induction_report.json").read_text(encoding="utf-8")
        )
        notes = " ".join(raw["review_notes"])
        # The phrase "non-standard classification" must not appear.
        assert "non-standard" not in notes

    def test_arbitrary_classification_value_treated_as_rejected(
        self, tmp_path: Path,
    ):
        """Forward-compat: a hypothetical future band a caller
        invented (e.g. "experimental") must still be counted and
        appear in rejected_examples — never silently dropped."""
        candidates = [
            _candidate(
                "Maybe", classification="experimental", score=0.55,
            ),
        ]
        out_dir = tmp_path / "induced-profile"
        write_induced_profile("demo", candidates, out_dir)
        raw = json.loads(
            (out_dir / "induction_report.json").read_text(encoding="utf-8")
        )
        assert raw["rejected_count"] == 1
        ids = [e["candidate_id"] for e in raw["rejected_examples"]]
        assert "cand_maybe" in ids

    def test_counts_reconcile_under_mixed_bands(self, tmp_path: Path):
        """The full reconciliation invariant: counts sum to
        candidate_count, and every candidate appears in either
        top_candidates or rejected_examples."""
        candidates = [
            _candidate("A", classification="core_business"),
            _candidate("B", classification="core_business"),
            _candidate("C", classification="supporting_technical", score=0.5),
            _candidate("D", classification="noise", score=0.1),
            _candidate("E", classification="unknown", score=0.0),
            _candidate("F", classification="experimental", score=0.3),
        ]
        out_dir = tmp_path / "induced-profile"
        write_induced_profile("demo", candidates, out_dir)
        raw = json.loads(
            (out_dir / "induction_report.json").read_text(encoding="utf-8")
        )
        # The four counts reconcile.
        assert raw["candidate_count"] == 6
        total_buckets = (
            raw["selected_core_count"]
            + raw["selected_supporting_count"]
            + raw["rejected_count"]
        )
        assert total_buckets == raw["candidate_count"]
        # Every candidate appears in one of the two audit lists
        # (top_candidates limit is well above 6, so no truncation).
        in_top = {e["candidate_id"] for e in raw["top_candidates"]}
        in_rejected = {e["candidate_id"] for e in raw["rejected_examples"]}
        for candidate in candidates:
            assert (
                candidate.candidate_id in in_top
                or candidate.candidate_id in in_rejected
            ), (
                f"Candidate {candidate.candidate_id!r} "
                f"(classification={candidate.classification!r}) "
                f"missing from both audit lists"
            )


# ─── Empty / whitespace label handling (round-1 reviewer finding) ──────────


class TestEmptyLabelHandling:
    """Selected candidates whose labels are empty / whitespace-only
    are dropped from the schema (the loader rejects empty subtypes),
    but the drop must be surfaced in ``review_notes`` so the
    candidate doesn't disappear without explanation."""

    def test_empty_label_logged_in_review_notes(self, tmp_path: Path):
        candidates = [
            _candidate("Customer", classification="core_business"),
            # Construct directly so the helper's label-derived
            # candidate_id doesn't collapse to the empty string.
            CandidateConcept(
                candidate_id="cand_empty",
                label="",
                normalized_label="",
                suggested_entity_type="Concept",
                classification="core_business",
                summary_definition="",
                source_presence={"A": True, "B": False, "C": False, "D": False},
                source_counts={"A": 1, "B": 0, "C": 0, "D": 0},
                authoritative_evidence_count=1,
                graph_degree=0,
                relevance_score=0.75,
            ),
        ]
        out_dir = tmp_path / "induced-profile"
        write_induced_profile("demo", candidates, out_dir)
        raw = json.loads(
            (out_dir / "induction_report.json").read_text(encoding="utf-8")
        )
        notes = " ".join(raw["review_notes"])
        # The note must cite the candidate_id so the reviewer can
        # trace it back to the source row.
        assert "cand_empty" in notes

    def test_whitespace_only_label_logged_in_review_notes(
        self, tmp_path: Path,
    ):
        candidates = [
            CandidateConcept(
                candidate_id="cand_ws",
                label="   \t  ",
                normalized_label="",
                suggested_entity_type="Concept",
                classification="supporting_technical",
                summary_definition="",
                source_presence={"A": True, "B": False, "C": False, "D": False},
                source_counts={"A": 1, "B": 0, "C": 0, "D": 0},
                authoritative_evidence_count=1,
                graph_degree=0,
                relevance_score=0.55,
            ),
        ]
        out_dir = tmp_path / "induced-profile"
        write_induced_profile("demo", candidates, out_dir)
        raw = json.loads(
            (out_dir / "induction_report.json").read_text(encoding="utf-8")
        )
        notes = " ".join(raw["review_notes"])
        assert "cand_ws" in notes


# ─── Sidecar files ─────────────────────────────────────────────────────────


class TestSidecarFiles:

    def test_alias_map_json_written_as_empty_object(
        self, tmp_path: Path,
    ):
        """Alias induction is a follow-up step. v1 emits an empty
        but valid alias_map.json so the loader's optional-sidecar
        path is exercised cleanly."""
        out_dir = tmp_path / "induced-profile"
        write_induced_profile("demo", [_candidate("X")], out_dir)
        raw = json.loads(
            (out_dir / "alias_map.json").read_text(encoding="utf-8")
        )
        assert raw == {}

    def test_prompt_fragment_md_written_and_nonempty(
        self, tmp_path: Path,
    ):
        out_dir = tmp_path / "induced-profile"
        write_induced_profile("demo", [_candidate("X")], out_dir)
        text = (out_dir / "prompt_fragment.md").read_text(encoding="utf-8")
        assert text.strip()  # non-empty content

    def test_prompt_fragment_loaded_into_profile(self, tmp_path: Path):
        """load_profile reads prompt_fragment.md into Profile.prompt_fragment.
        Pin that the induced fragment survives that round-trip."""
        out_dir = tmp_path / "induced-profile"
        write_induced_profile("demo", [_candidate("X")], out_dir)
        profile = load_profile(out_dir)
        assert profile.prompt_fragment.strip()

    def test_write_returns_out_dir(self, tmp_path: Path):
        """Return value is the directory written, so the CLI can
        chain ``console.print(f"... {returned_path}")`` cleanly."""
        out_dir = tmp_path / "induced-profile"
        returned = write_induced_profile(
            "demo", [_candidate("X")], out_dir,
        )
        assert Path(returned) == out_dir
