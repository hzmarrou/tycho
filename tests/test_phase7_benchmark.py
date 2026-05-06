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
