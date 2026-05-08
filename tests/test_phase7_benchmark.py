"""Tests for Phase 7: benchmark metrics + reporting.

Covers the six benchmark sections (element counts, confidence,
conflicts, anchors, corroboration, profile coverage), the markdown
renderer, the CLI ``ontozense report`` command, and AC1 (the report
is read-only on the fused output).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ontozense.core.benchmark import (
    AnchorCoverage,
    BenchmarkReport,
    ConfidenceStats,
    ConflictStats,
    CorroborationStats,
    ElementCounts,
    ProfileCoverage,
    compute_benchmark,
    render_markdown,
)
from ontozense.core.fusion import (
    FieldAnchor,
    FieldConflict,
    FieldProvenance,
    FusedElement,
    FusedRelationship,
    FusionResult,
)
from ontozense.core.profile import load_profile


MINIMAL_PROFILE_DIR = (
    Path(__file__).parent / "fixtures" / "profiles" / "minimal"
)


# ─── Helpers ────────────────────────────────────────────────────────────────


def _el(
    name: str,
    *,
    confidence: float = 0.9,
    sources: list[str] | None = None,
    governance_validated: bool = False,
    conflicts: list[FieldConflict] | None = None,
    field_provenance: dict[str, FieldProvenance] | None = None,
    extra_fields: dict | None = None,
    entity_type: str = "",
    eid: str = "",
) -> FusedElement:
    extra = dict(extra_fields or {})
    if entity_type:
        extra["entity_type"] = entity_type
    if eid:
        extra["id"] = eid
    return FusedElement(
        element_name=name,
        confidence=confidence,
        sources=sources or ["A"],
        governance_validated=governance_validated,
        conflicts=conflicts or [],
        field_provenance=field_provenance or {},
        extra_fields=extra,
    )


def _result(
    elements: list[FusedElement],
    relationships: list[FusedRelationship] | None = None,
    sources_used: list[str] | None = None,
) -> FusionResult:
    return FusionResult(
        elements=elements,
        relationships=relationships or [],
        sources_used=sources_used or ["A"],
        fusion_timestamp="2026-05-06T00:00:00",
    )


# ─── 1. Element counts ─────────────────────────────────────────────────────


class TestElementCounts:
    def test_empty_result(self):
        r = compute_benchmark(_result([]))
        assert r.elements.total == 0
        assert r.elements.governance_validated == 0
        assert r.elements.multi_source == 0
        assert r.elements.by_source_combination == {}

    def test_governance_validated_count(self):
        r = compute_benchmark(_result([
            _el("X", governance_validated=True),
            _el("Y", governance_validated=True),
            _el("Z", governance_validated=False),
        ]))
        assert r.elements.total == 3
        assert r.elements.governance_validated == 2

    def test_multi_source_count(self):
        r = compute_benchmark(_result([
            _el("X", sources=["A"]),
            _el("Y", sources=["A", "B"]),
            _el("Z", sources=["A", "B", "C"]),
        ]))
        assert r.elements.multi_source == 2

    def test_source_combination_breakdown(self):
        r = compute_benchmark(_result([
            _el("A1", sources=["A"]),
            _el("A2", sources=["A"]),
            _el("AB", sources=["A", "B"]),
            _el("BC", sources=["B", "C"]),
        ]))
        # Sources are stable-sorted in the key
        assert r.elements.by_source_combination["A"] == 2
        assert r.elements.by_source_combination["A+B"] == 1
        assert r.elements.by_source_combination["B+C"] == 1


# ─── 2. Confidence ──────────────────────────────────────────────────────────


class TestConfidenceStats:
    def test_empty_result(self):
        r = compute_benchmark(_result([]))
        assert r.confidence.min == 0.0
        assert r.confidence.max == 0.0
        assert r.confidence.mean == 0.0

    def test_min_max_mean_median(self):
        r = compute_benchmark(_result([
            _el("X", confidence=0.5),
            _el("Y", confidence=0.7),
            _el("Z", confidence=0.9),
        ]))
        assert r.confidence.min == 0.5
        assert r.confidence.max == 0.9
        assert r.confidence.mean == 0.7
        assert r.confidence.median == 0.7

    def test_buckets(self):
        r = compute_benchmark(_result([
            _el("a", confidence=0.3),
            _el("b", confidence=0.6),
            _el("c", confidence=0.8),
            _el("d", confidence=0.95),
            _el("e", confidence=0.97),
        ]))
        assert r.confidence.buckets == {
            "0.0-0.5": 1,
            "0.5-0.7": 1,
            "0.7-0.9": 1,
            "0.9-1.0": 2,
        }


# ─── 3. Conflicts ───────────────────────────────────────────────────────────


class TestConflictStats:
    def _conflict(self, resolution: str) -> FieldConflict:
        w = FieldProvenance(source="A", confidence=0.9, original_value="a")
        l = FieldProvenance(source="B", confidence=0.8, original_value="b")
        return FieldConflict(
            field_name="definition",
            winner=w, rejected=[l], resolution=resolution,
        )

    def test_no_conflicts(self):
        r = compute_benchmark(_result([_el("X")]))
        assert r.conflicts.total_conflicts == 0
        assert r.conflicts.elements_with_conflicts == 0

    def test_resolution_breakdown(self):
        r = compute_benchmark(_result([
            _el("X", conflicts=[
                self._conflict("priority"),
                self._conflict("priority"),
            ]),
            _el("Y", conflicts=[self._conflict("confidence")]),
            _el("Z"),
        ]))
        assert r.conflicts.total_conflicts == 3
        assert r.conflicts.elements_with_conflicts == 2
        assert r.conflicts.by_resolution["priority"] == 2
        assert r.conflicts.by_resolution["confidence"] == 1


# ─── 4. Anchor coverage ────────────────────────────────────────────────────


class TestAnchorCoverage:
    def test_no_anchors(self):
        fp = FieldProvenance(source="A", confidence=0.9, original_value="x")
        r = compute_benchmark(_result([
            _el("X", field_provenance={"definition": fp}),
        ]))
        assert r.anchors.total_field_provenance == 1
        assert r.anchors.with_anchor == 0
        assert r.anchors.with_non_empty_anchor == 0
        assert r.anchors.by_field["definition"]["with_anchor"] == 0
        assert r.anchors.by_field["definition"]["without_anchor"] == 1

    def test_mixed_anchors(self):
        fp_anchored = FieldProvenance(
            source="A", confidence=0.9, original_value="d",
            anchor=FieldAnchor(segment_id="3.2"),
        )
        fp_empty_anchor = FieldProvenance(
            source="A", confidence=0.9, original_value="c",
            anchor=FieldAnchor(),
        )
        fp_no_anchor = FieldProvenance(source="A", confidence=0.9, original_value="n")
        r = compute_benchmark(_result([
            _el("X", field_provenance={
                "definition": fp_anchored,
                "citation": fp_empty_anchor,
                "domain_name": fp_no_anchor,
            }),
        ]))
        assert r.anchors.total_field_provenance == 3
        # Both definition and citation have an anchor object
        assert r.anchors.with_anchor == 2
        # Only definition's anchor is non-empty
        assert r.anchors.with_non_empty_anchor == 1


# ─── 5. Corroboration ──────────────────────────────────────────────────────


class TestCorroborationStats:
    def test_no_tracking(self):
        r = compute_benchmark(_result([_el("X")]))
        assert r.corroboration.elements_tracked == 0

    def test_distribution_buckets(self):
        r = compute_benchmark(_result([
            _el("a", extra_fields={"corroborating_doc_count": 1}),
            _el("b", extra_fields={"corroborating_doc_count": 2}),
            _el("c", extra_fields={"corroborating_doc_count": 2}),
            _el("d", extra_fields={"corroborating_doc_count": 3}),
            _el("e", extra_fields={"corroborating_doc_count": 7}),
        ]))
        assert r.corroboration.elements_tracked == 5
        assert r.corroboration.distribution["1_doc"] == 1
        assert r.corroboration.distribution["2_docs"] == 2
        assert r.corroboration.distribution["3+_docs"] == 2

    def test_non_positive_counts_are_skipped(self):
        """Regression for Phase 7 review minor: a hand-edited fused
        JSON with ``corroborating_doc_count`` of 0 or negative values
        was previously mis-bucketed as ``3+_docs`` via the else
        branch. Now those anomalous values are skipped entirely:
        not tracked, not bucketed."""
        r = compute_benchmark(_result([
            _el("zero", extra_fields={"corroborating_doc_count": 0}),
            _el("neg", extra_fields={"corroborating_doc_count": -1}),
            _el("ok", extra_fields={"corroborating_doc_count": 2}),
            _el("untracked"),  # no key at all
        ]))
        # Only "ok" is tracked
        assert r.corroboration.elements_tracked == 1
        assert r.corroboration.distribution == {
            "1_doc": 0, "2_docs": 1, "3+_docs": 0,
        }

    def test_non_int_counts_are_skipped(self):
        """Defensive: a non-integer value (string, float, list)
        in corroborating_doc_count is treated as anomalous and
        skipped, not crashed-on or bucketed."""
        r = compute_benchmark(_result([
            _el("str", extra_fields={"corroborating_doc_count": "two"}),
            _el("float", extra_fields={"corroborating_doc_count": 2.5}),
            _el("ok", extra_fields={"corroborating_doc_count": 1}),
        ]))
        assert r.corroboration.elements_tracked == 1
        assert r.corroboration.distribution["1_doc"] == 1


# ─── 6. Profile coverage (when profile supplied) ───────────────────────────


class TestProfileCoverage:
    def test_no_profile_means_section_is_none(self):
        r = compute_benchmark(_result([_el("X")]))
        assert r.profile_coverage is None

    def test_zero_coverage(self):
        profile = load_profile(MINIMAL_PROFILE_DIR)
        r = compute_benchmark(_result([_el("X")]), profile=profile)
        pc = r.profile_coverage
        assert pc is not None
        assert pc.entity_types_total > 0
        assert pc.entity_types_covered == 0
        assert pc.predicates_covered == 0
        assert "Concept" in pc.entity_types_unused

    def test_partial_coverage(self):
        profile = load_profile(MINIMAL_PROFILE_DIR)
        r = compute_benchmark(
            _result(
                [_el("X", entity_type="Concept", eid="concept_x_111111")],
                relationships=[FusedRelationship(
                    subject="X", predicate="AppliesTo", object="Y", source="A",
                )],
            ),
            profile=profile,
        )
        pc = r.profile_coverage
        assert pc is not None
        assert pc.entity_types_covered >= 1
        assert "Concept" not in pc.entity_types_unused
        assert pc.predicates_covered >= 1
        assert "AppliesTo" not in pc.predicates_unused

    def test_predicate_match_is_case_insensitive(self):
        profile = load_profile(MINIMAL_PROFILE_DIR)
        r = compute_benchmark(
            _result(
                [_el("X", entity_type="Concept")],
                relationships=[FusedRelationship(
                    # Profile declares "AppliesTo"; relationship uses lowercase
                    subject="X", predicate="appliesto", object="Y", source="A",
                )],
            ),
            profile=profile,
        )
        pc = r.profile_coverage
        assert pc.predicates_covered >= 1

    def test_subtypes_total_zero_for_no_subtype_profile(self):
        """The minimal profile declares two flat entity types with no
        subtypes — subtype counts must be zero across the board."""
        profile = load_profile(MINIMAL_PROFILE_DIR)
        r = compute_benchmark(_result([_el("X")]), profile=profile)
        pc = r.profile_coverage
        assert pc.subtypes_total == 0
        assert pc.subtypes_covered == 0
        assert pc.subtypes_unused == []

    def test_subtype_coverage_with_subtyped_profile(self, tmp_path):
        """Profile with one parent type Metric having three subtypes;
        only DirectMetric is used in the fused output. Subtype
        coverage must report 1/3 with the two unused dotted-named."""
        profile_dir = tmp_path / "subtype_profile"
        profile_dir.mkdir()
        (profile_dir / "schema.json").write_text(
            json.dumps({
                "profile_name": "subtype_test",
                "profile_version": "1.0.0",
                "entity_types": {
                    "Metric": {
                        "required": [],
                        "subtypes": [
                            "DirectMetric",
                            "CalculatedMetric",
                            "InputMetric",
                        ],
                    },
                },
                "predicates": {},
            }),
            encoding="utf-8",
        )
        profile = load_profile(profile_dir)
        r = compute_benchmark(
            _result([_el("X", entity_type="DirectMetric")]),
            profile=profile,
        )
        pc = r.profile_coverage
        assert pc.subtypes_total == 3
        assert pc.subtypes_covered == 1
        # Unused list is sorted, parent-prefixed
        assert pc.subtypes_unused == [
            "Metric.CalculatedMetric",
            "Metric.InputMetric",
        ]
        # Parent type Metric is reported as covered (subtype usage
        # bubbles up — Phase 4 behaviour)
        assert "Metric" not in pc.entity_types_unused

    def test_subtype_zero_coverage_lists_all(self, tmp_path):
        """Profile with subtypes, none used → all unused, none covered."""
        profile_dir = tmp_path / "subtype_unused"
        profile_dir.mkdir()
        (profile_dir / "schema.json").write_text(
            json.dumps({
                "profile_name": "test",
                "profile_version": "1.0.0",
                "entity_types": {
                    "Metric": {
                        "required": [],
                        "subtypes": ["DirectMetric", "CalculatedMetric"],
                    },
                },
                "predicates": {},
            }),
            encoding="utf-8",
        )
        profile = load_profile(profile_dir)
        # No elements with entity_type
        r = compute_benchmark(_result([_el("X")]), profile=profile)
        pc = r.profile_coverage
        assert pc.subtypes_total == 2
        assert pc.subtypes_covered == 0
        assert pc.subtypes_unused == [
            "Metric.CalculatedMetric",
            "Metric.DirectMetric",
        ]


# ─── 7. Markdown rendering ─────────────────────────────────────────────────


class TestMarkdownRender:
    def test_render_does_not_crash_on_empty(self):
        r = compute_benchmark(_result([]))
        md = render_markdown(r)
        assert "Ontozense Benchmark Report" in md
        assert "Total: **0**" in md

    def test_render_includes_all_sections(self):
        r = compute_benchmark(_result([
            _el("X", confidence=0.95, governance_validated=True),
        ]))
        md = render_markdown(r)
        assert "## Elements" in md
        assert "## Confidence" in md
        assert "## Conflicts" in md
        assert "## Provenance anchors" in md
        assert "## Multi-doc corroboration" in md
        # No profile supplied → no profile-coverage section
        assert "## Profile coverage" not in md

    def test_render_includes_profile_section_when_supplied(self):
        profile = load_profile(MINIMAL_PROFILE_DIR)
        r = compute_benchmark(_result([_el("X")]), profile=profile)
        md = render_markdown(r)
        assert "## Profile coverage" in md
        assert "Entity types covered:" in md

    def test_render_omits_subtype_line_for_no_subtype_profile(self):
        """Minimal profile has no subtypes → render must not include
        a 'Subtypes covered' line, keeping the report tidy."""
        profile = load_profile(MINIMAL_PROFILE_DIR)
        r = compute_benchmark(_result([_el("X")]), profile=profile)
        md = render_markdown(r)
        assert "Subtypes covered:" not in md

    def test_render_includes_subtype_line_for_subtyped_profile(self, tmp_path):
        """Profile with subtypes → render shows the subtype coverage
        line and lists unused with parent-dotted names."""
        profile_dir = tmp_path / "subtype_render"
        profile_dir.mkdir()
        (profile_dir / "schema.json").write_text(
            json.dumps({
                "profile_name": "test",
                "profile_version": "1.0.0",
                "entity_types": {
                    "Metric": {
                        "required": [],
                        "subtypes": ["DirectMetric", "CalculatedMetric"],
                    },
                },
                "predicates": {},
            }),
            encoding="utf-8",
        )
        profile = load_profile(profile_dir)
        r = compute_benchmark(
            _result([_el("X", entity_type="DirectMetric")]),
            profile=profile,
        )
        md = render_markdown(r)
        assert "Subtypes covered: 1/2" in md
        assert "Metric.CalculatedMetric" in md


# ─── 8. AC1: report is read-only on the fused result ───────────────────────


class TestReportIsReadOnly:
    def test_compute_does_not_mutate_input(self):
        """compute_benchmark must not change the FusionResult or
        anything inside it. AC1: running report on a fused output
        leaves the fused output exactly as it was."""
        original = _result([
            _el("X", confidence=0.9, governance_validated=True),
        ])
        before_extra = dict(original.elements[0].extra_fields)
        before_conf = original.elements[0].confidence
        before_sources = list(original.elements[0].sources)

        compute_benchmark(original)

        assert original.elements[0].extra_fields == before_extra
        assert original.elements[0].confidence == before_conf
        assert original.elements[0].sources == before_sources


# ─── 9. CLI smoke ──────────────────────────────────────────────────────────


class TestCli:
    def _write_fused_json(self, tmp_path: Path, elements: list[dict],
                          relationships: list[dict] | None = None) -> Path:
        f = tmp_path / "fused.json"
        f.write_text(
            json.dumps({
                "fusion_timestamp": "2026-05-06T00:00:00",
                "sources_used": ["A"],
                "summary": {},
                "elements": elements,
                "relationships": relationships or [],
            }),
            encoding="utf-8",
        )
        return f

    def _basic_element(self, name: str, **overrides) -> dict:
        base = {
            "element_name": name,
            "definition": "A test concept.",
            "is_critical": False,
            "citation": "",
            "data_type": "",
            "enum_values": [],
            "business_rules": [],
            "governance_validated": False,
            "confidence": 0.9,
            "sources": ["A"],
            "needs_review": False,
            "conflicts": [],
            "extra_fields": {},
        }
        base.update(overrides)
        return base

    def test_report_prints_markdown_to_stdout(self, tmp_path):
        from typer.testing import CliRunner
        from ontozense import cli

        runner = CliRunner()
        f = self._write_fused_json(tmp_path, [self._basic_element("X")])
        r = runner.invoke(cli.app, ["report", str(f)])
        assert r.exit_code == 0, r.output
        flat = " ".join(r.output.split())
        assert "Ontozense Benchmark Report" in flat
        assert "Elements" in flat

    def test_report_writes_json_snapshot(self, tmp_path):
        from typer.testing import CliRunner
        from ontozense import cli

        runner = CliRunner()
        f = self._write_fused_json(tmp_path, [self._basic_element("X")])
        out_json = tmp_path / "report.json"
        r = runner.invoke(
            cli.app, ["report", str(f), "--output", str(out_json)],
        )
        assert r.exit_code == 0, r.output
        assert out_json.exists()
        data = json.loads(out_json.read_text(encoding="utf-8"))
        assert "elements" in data
        assert data["elements"]["total"] == 1
        assert "anchors" in data
        assert "corroboration" in data

    def test_report_writes_markdown_to_file(self, tmp_path):
        from typer.testing import CliRunner
        from ontozense import cli

        runner = CliRunner()
        f = self._write_fused_json(tmp_path, [self._basic_element("X")])
        out_md = tmp_path / "report.md"
        r = runner.invoke(
            cli.app, ["report", str(f), "--markdown", str(out_md)],
        )
        assert r.exit_code == 0, r.output
        assert out_md.exists()
        assert "Ontozense Benchmark Report" in out_md.read_text(encoding="utf-8")

    def test_report_with_profile_includes_coverage(self, tmp_path):
        from typer.testing import CliRunner
        from ontozense import cli

        runner = CliRunner()
        f = self._write_fused_json(tmp_path, [
            self._basic_element("X", extra_fields={"entity_type": "Concept"}),
        ])
        out_json = tmp_path / "r.json"
        r = runner.invoke(
            cli.app,
            [
                "report", str(f),
                "--profile", str(MINIMAL_PROFILE_DIR),
                "--output", str(out_json),
            ],
        )
        assert r.exit_code == 0, r.output
        data = json.loads(out_json.read_text(encoding="utf-8"))
        assert data["profile_coverage"] is not None
        assert data["profile_name"] == "minimal"

    def test_report_missing_file_clean_error(self, tmp_path):
        from typer.testing import CliRunner
        from ontozense import cli

        runner = CliRunner()
        r = runner.invoke(
            cli.app, ["report", str(tmp_path / "missing.json")],
        )
        assert r.exit_code == 1
        assert "Traceback" not in r.output


# ─── 10. Reference comparison (wrap-up #3) ─────────────────────────────────


class TestReferenceComparison:
    """Pin the reference-benchmark mode: compute_benchmark gets an
    optional ``reference`` FusionResult, returns a populated
    ``BenchmarkReport.reference_comparison`` with element- and
    relationship-level precision/recall/F1."""

    def test_no_reference_means_section_is_none(self):
        """AC1: report without --reference produces None for the
        section, byte-identical to pre-wrap-up output."""
        r = compute_benchmark(_result([_el("X")]))
        assert r.reference_comparison is None

    def test_perfect_match_yields_p_r_f1_one(self):
        """fused == reference (same elements, same relationships)
        → P=R=F1=1.0."""
        elements = [_el("A"), _el("B"), _el("C")]
        rels = [
            FusedRelationship(subject="A", predicate="rel", object="B", source="A"),
        ]
        fused = _result(elements, rels)
        ref = _result([_el("A"), _el("B"), _el("C")], [
            FusedRelationship(subject="A", predicate="rel", object="B", source="A"),
        ])
        r = compute_benchmark(fused, reference=ref)
        rc = r.reference_comparison
        assert rc is not None
        assert rc.elements_precision == 1.0
        assert rc.elements_recall == 1.0
        assert rc.elements_f1 == 1.0
        assert rc.relationships_precision == 1.0
        assert rc.relationships_recall == 1.0
        assert rc.missing_elements == []
        assert rc.extra_elements == []

    def test_partial_match_metrics(self):
        """Fused has 3 elements (A, B, C); reference has (A, B, D).
        TP=2 (A, B), FP=1 (C), FN=1 (D).
        Precision = 2/3, Recall = 2/3, F1 = 2/3."""
        fused = _result([_el("A"), _el("B"), _el("C")])
        ref = _result([_el("A"), _el("B"), _el("D")])
        r = compute_benchmark(fused, reference=ref)
        rc = r.reference_comparison
        assert rc.elements_true_positive == 2
        assert rc.elements_false_positive == 1
        assert rc.elements_false_negative == 1
        assert abs(rc.elements_precision - 0.667) < 0.01
        assert abs(rc.elements_recall - 0.667) < 0.01
        assert abs(rc.elements_f1 - 0.667) < 0.01
        assert rc.missing_elements == ["D"]
        assert rc.extra_elements == ["C"]

    def test_empty_fused_against_nonempty_reference(self):
        """Recall = 0 (we missed everything); precision is 0/0 → 0
        (no division by zero)."""
        fused = _result([])
        ref = _result([_el("A"), _el("B")])
        r = compute_benchmark(fused, reference=ref)
        rc = r.reference_comparison
        assert rc.elements_precision == 0.0
        assert rc.elements_recall == 0.0
        assert rc.elements_f1 == 0.0
        assert rc.missing_elements == ["A", "B"]

    def test_id_match_wins_over_name_match(self):
        """In profile mode, two elements with the same ID but
        different surface names match. Pinned because this is the
        cross-source ID alignment contract from Phases 1–5 applied
        to reference comparison."""
        fused = _result([
            _el("CustomerID", entity_type="Concept", eid="concept_x_111"),
        ])
        # Reference uses a different surface name but same ID
        ref = _result([
            _el("customer-identifier", entity_type="Concept", eid="concept_x_111"),
        ])
        r = compute_benchmark(fused, reference=ref)
        rc = r.reference_comparison
        # Match by ID → 1 TP, no FP, no FN
        assert rc.elements_true_positive == 1
        assert rc.elements_false_positive == 0
        assert rc.elements_false_negative == 0
        assert rc.elements_f1 == 1.0

    def test_relationship_predicate_match_is_case_insensitive(self):
        """Match relationships on (normalised subj, lowercased pred,
        normalised obj). Trivially case-insensitive, mirrors fusion
        and benchmark predicate-coverage policy."""
        fused = _result(
            [_el("A"), _el("B")],
            [FusedRelationship(
                subject="A", predicate="AppliesTo", object="B", source="A",
            )],
        )
        ref = _result(
            [_el("A"), _el("B")],
            [FusedRelationship(
                subject="A", predicate="appliesto", object="B", source="A",
            )],
        )
        r = compute_benchmark(fused, reference=ref)
        rc = r.reference_comparison
        assert rc.relationships_true_positive == 1
        assert rc.relationships_f1 == 1.0

    def test_markdown_includes_reference_section_when_supplied(self):
        ref = _result([_el("A")])
        r = compute_benchmark(_result([_el("A")]), reference=ref)
        md = render_markdown(r)
        assert "## Reference comparison" in md
        assert "Precision" in md
        assert "F1" in md

    def test_markdown_omits_reference_section_without_reference(self):
        r = compute_benchmark(_result([_el("A")]))
        md = render_markdown(r)
        assert "Reference comparison" not in md


class TestCliReferenceFlag:
    def _write_fused_json(self, tmp_path: Path, elements: list[dict]) -> Path:
        f = tmp_path / "f.json"
        f.write_text(
            json.dumps({
                "fusion_timestamp": "2026-05-08T00:00:00",
                "sources_used": ["A"],
                "summary": {},
                "elements": elements,
                "relationships": [],
            }),
            encoding="utf-8",
        )
        return f

    def _basic_element(self, name: str, **overrides) -> dict:
        base = {
            "element_name": name,
            "definition": "",
            "is_critical": False,
            "citation": "",
            "data_type": "",
            "enum_values": [],
            "business_rules": [],
            "governance_validated": False,
            "confidence": 0.9,
            "sources": ["A"],
            "needs_review": False,
            "conflicts": [],
            "extra_fields": {},
        }
        base.update(overrides)
        return base

    def test_reference_flag_includes_section_in_output(self, tmp_path):
        from typer.testing import CliRunner
        from ontozense import cli

        runner = CliRunner()
        fused = self._write_fused_json(tmp_path, [
            self._basic_element("A"), self._basic_element("B"),
        ])
        ref_path = tmp_path / "ref.json"
        ref_path.write_text(json.dumps({
            "fusion_timestamp": "", "sources_used": [], "summary": {},
            "elements": [self._basic_element("A"), self._basic_element("B"),
                         self._basic_element("C")],
            "relationships": [],
        }), encoding="utf-8")

        out = tmp_path / "report.json"
        r = runner.invoke(cli.app, [
            "report", str(fused),
            "--reference", str(ref_path),
            "--output", str(out),
        ])
        assert r.exit_code == 0, r.output
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["reference_comparison"] is not None
        rc = data["reference_comparison"]
        assert rc["elements_true_positive"] == 2
        assert rc["elements_false_negative"] == 1
        assert rc["missing_elements"] == ["C"]

    def test_missing_reference_clean_error(self, tmp_path):
        from typer.testing import CliRunner
        from ontozense import cli

        runner = CliRunner()
        fused = self._write_fused_json(tmp_path, [self._basic_element("X")])
        r = runner.invoke(cli.app, [
            "report", str(fused),
            "--reference", str(tmp_path / "missing.json"),
        ])
        assert r.exit_code == 1
        assert "Reference file not found" in r.output
        assert "Traceback" not in r.output

    def test_malformed_reference_clean_error(self, tmp_path):
        from typer.testing import CliRunner
        from ontozense import cli

        runner = CliRunner()
        fused = self._write_fused_json(tmp_path, [self._basic_element("X")])
        bad = tmp_path / "bad.json"
        bad.write_text("{not valid json", encoding="utf-8")
        r = runner.invoke(cli.app, [
            "report", str(fused),
            "--reference", str(bad),
        ])
        assert r.exit_code == 1
        assert "Reference JSON parse error" in r.output
        assert "Traceback" not in r.output

    def test_structurally_malformed_reference_clean_error(self, tmp_path):
        """Round-4 review: a syntactically-valid JSON with the wrong
        shape (e.g. ``{"elements": [123]}``) used to crash with
        AttributeError during reconstruction. Now it raises
        ReferenceContractError and the CLI prints a clean message."""
        from typer.testing import CliRunner
        from ontozense import cli

        runner = CliRunner()
        fused = self._write_fused_json(tmp_path, [self._basic_element("X")])
        bad = tmp_path / "bad_shape.json"
        bad.write_text(
            json.dumps({"elements": [123], "relationships": []}),
            encoding="utf-8",
        )
        r = runner.invoke(cli.app, [
            "report", str(fused),
            "--reference", str(bad),
        ])
        assert r.exit_code == 1
        flat = " ".join(r.output.split())
        assert "Reference JSON contract error" in flat
        assert "elements[0] must be an object" in flat
        assert "Traceback" not in r.output


# ─── 11. Round-4 review regression tests ───────────────────────────────────


class TestRound4ReviewRegressions:
    """Pin the three failure modes the round-4 reviewer reproduced
    against commit 8103235:

      * Element matching with no IDs falsely conflates two entities
        of different types that share a normalised name.
      * Relationship matching ignored profile-mode IDs, so the same
        triple over IDs vs over names counted as zero matches.
      * Structurally malformed (but syntactically valid) reference
        JSON crashed the loader instead of raising a clean error.
    """

    def test_element_match_distinguishes_by_entity_type(self):
        """Repro: a fused Rule named "Default" should NOT match a
        reference Concept named "Default" — different types, same
        name, no IDs. Pre-fix this counted as TP=1; post-fix
        TP=0, FP=1, FN=1."""
        fused = _result([_el("Default", entity_type="Rule")])
        ref = _result([_el("Default", entity_type="Concept")])
        r = compute_benchmark(fused, reference=ref)
        rc = r.reference_comparison
        assert rc.elements_true_positive == 0
        assert rc.elements_false_positive == 1
        assert rc.elements_false_negative == 1

    def test_element_match_typeless_legacy_still_works(self):
        """When neither side declares entity_type (truly typeless
        legacy payloads), name-only matching still functions —
        the type guard only kicks in when at least one side has a
        type."""
        fused = _result([_el("Default")])
        ref = _result([_el("Default")])
        r = compute_benchmark(fused, reference=ref)
        rc = r.reference_comparison
        assert rc.elements_true_positive == 1

    def test_relationship_match_uses_endpoint_ids(self):
        """Repro: fused has elements with IDs and a relationship
        ``Customer -> Order``; reference has the same IDs but
        different surface names (CustomerOne -> OrderOne) and the
        same relationship. Pre-fix the relationship scored as
        TP=0; post-fix it should be TP=1 because endpoint IDs
        align."""
        fused = _result(
            [
                _el("Customer", entity_type="Concept", eid="concept_c_111"),
                _el("Order", entity_type="Concept", eid="concept_o_222"),
            ],
            [FusedRelationship(
                subject="Customer", predicate="rel", object="Order", source="A",
            )],
        )
        ref = _result(
            [
                _el("CustomerOne", entity_type="Concept", eid="concept_c_111"),
                _el("OrderOne", entity_type="Concept", eid="concept_o_222"),
            ],
            [FusedRelationship(
                subject="CustomerOne", predicate="rel", object="OrderOne",
                source="A",
            )],
        )
        r = compute_benchmark(fused, reference=ref)
        rc = r.reference_comparison
        # Elements matched by ID
        assert rc.elements_true_positive == 2
        # Relationship: endpoints resolve to the same ID-keys on both
        # sides, predicate matches case-insensitively → TP=1
        assert rc.relationships_true_positive == 1
        assert rc.relationships_false_positive == 0
        assert rc.relationships_false_negative == 0
        assert rc.relationships_f1 == 1.0

    def test_relationship_match_falls_back_to_name_when_no_ids(self):
        """Without IDs, relationship matching falls back to
        normalised-name endpoints — the pre-fix behaviour for fully
        unconstrained pipelines stays intact."""
        fused = _result(
            [_el("A"), _el("B")],
            [FusedRelationship(
                subject="A", predicate="rel", object="B", source="A",
            )],
        )
        ref = _result(
            [_el("A"), _el("B")],
            [FusedRelationship(
                subject="A", predicate="rel", object="B", source="A",
            )],
        )
        r = compute_benchmark(fused, reference=ref)
        rc = r.reference_comparison
        assert rc.relationships_true_positive == 1
        assert rc.relationships_f1 == 1.0

    def test_structural_validation_at_load_time(self):
        """Repro: ``{"elements": [123]}`` previously crashed at
        ``_reconstruct_fusion_result`` with AttributeError. Now
        ``validate_reference_shape`` raises
        ReferenceContractError before reconstruction is attempted."""
        from ontozense.core.benchmark import (
            ReferenceContractError, validate_reference_shape,
        )
        with pytest.raises(ReferenceContractError, match="elements\\[0\\] must be an object"):
            validate_reference_shape({"elements": [123]})

    def test_structural_validation_missing_elements_key(self):
        from ontozense.core.benchmark import (
            ReferenceContractError, validate_reference_shape,
        )
        with pytest.raises(ReferenceContractError, match="missing required key 'elements'"):
            validate_reference_shape({"relationships": []})

    def test_structural_validation_root_must_be_object(self):
        from ontozense.core.benchmark import (
            ReferenceContractError, validate_reference_shape,
        )
        with pytest.raises(ReferenceContractError, match="root must be an object"):
            validate_reference_shape(["not", "an", "object"])

    def test_structural_validation_relationships_must_be_list(self):
        from ontozense.core.benchmark import (
            ReferenceContractError, validate_reference_shape,
        )
        with pytest.raises(ReferenceContractError, match="'relationships' must be a list"):
            validate_reference_shape({"elements": [], "relationships": "bad"})
