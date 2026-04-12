"""Tests for the lint layer (Step 7).

Lint runs consistency checks on a fused knowledge base (FusionResult).
Four checks are tested:
  1. Contradictions — unresolved conflicts between sources
  2. Orphan terms — elements not referenced by any relationship
  3. Undefined but used — relationship endpoints with no matching element
  4. Coverage gaps — elements missing definition or citation
"""

from __future__ import annotations

import pytest

from ontozense.core.fusion import (
    FieldConflict,
    FieldProvenance,
    FusedElement,
    FusedRelationship,
    FusionResult,
)
from ontozense.core.lint import lint, LintFinding, LintReport


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _el(name, definition="", citation="", sources=None, conflicts=None):
    return FusedElement(
        element_name=name,
        definition=definition,
        citation=citation,
        sources=list(sources or ["A"]),
        conflicts=list(conflicts or []),
        confidence=0.8,
    )


def _rel(subject, predicate, obj, source="A"):
    return FusedRelationship(
        subject=subject,
        predicate=predicate,
        object=obj,
        source=source,
        confidence=0.9,
    )


def _conflict(field_name, winner_src, rejected_src, resolution="priority"):
    return FieldConflict(
        field_name=field_name,
        winner=FieldProvenance(winner_src, 0.9, "winner value"),
        rejected=[FieldProvenance(rejected_src, 0.8, "rejected value")],
        resolution=resolution,
    )


def _result(elements=None, relationships=None):
    return FusionResult(
        elements=list(elements or []),
        relationships=list(relationships or []),
        sources_used=["A"],
        fusion_timestamp="2026-04-12T00:00:00",
    )


# ─── Contradictions ─────────────────────────────────────────────────────────


class TestContradictions:
    def test_resolved_conflict_is_warning(self):
        el = _el("X", conflicts=[_conflict("definition", "A", "B", "priority")])
        report = lint(_result([el]))
        contras = report.by_category("contradiction")
        assert len(contras) == 1
        assert contras[0].severity == "warning"

    def test_unresolved_conflict_is_error(self):
        el = _el("X", conflicts=[_conflict("definition", "A", "B", "unresolved")])
        report = lint(_result([el]))
        contras = report.by_category("contradiction")
        assert len(contras) == 1
        assert contras[0].severity == "error"

    def test_no_conflicts_no_findings(self):
        report = lint(_result([_el("X", "def", "cite")]))
        assert report.by_category("contradiction") == []


# ─── Orphan terms ───────────────────────────────────────────────────────────


class TestOrphanTerms:
    def test_element_not_in_any_relationship_is_orphan(self):
        report = lint(_result(
            elements=[_el("A"), _el("B"), _el("C")],
            relationships=[_rel("A", "relates_to", "B")],
        ))
        orphans = report.by_category("orphan")
        names = [f.element_name for f in orphans]
        assert "C" in names
        assert "A" not in names
        assert "B" not in names

    def test_no_relationships_means_no_orphan_check(self):
        """If there are no relationships at all, we don't flag every
        element as an orphan — that would be noise."""
        report = lint(_result(elements=[_el("X"), _el("Y")]))
        assert report.by_category("orphan") == []

    def test_all_elements_referenced_no_orphans(self):
        report = lint(_result(
            elements=[_el("A"), _el("B")],
            relationships=[_rel("A", "relates_to", "B")],
        ))
        assert report.by_category("orphan") == []


# ─── Undefined but used ─────────────────────────────────────────────────────


class TestUndefinedUsed:
    def test_relationship_target_without_element_is_flagged(self):
        report = lint(_result(
            elements=[_el("A")],
            relationships=[_rel("A", "relates_to", "MISSING")],
        ))
        undef = report.by_category("undefined_used")
        assert len(undef) == 1
        assert undef[0].element_name == "MISSING"

    def test_both_endpoints_defined_no_finding(self):
        report = lint(_result(
            elements=[_el("A"), _el("B")],
            relationships=[_rel("A", "relates_to", "B")],
        ))
        assert report.by_category("undefined_used") == []

    def test_subject_undefined(self):
        report = lint(_result(
            elements=[_el("B")],
            relationships=[_rel("MISSING_SUBJECT", "relates_to", "B")],
        ))
        undef = report.by_category("undefined_used")
        assert any(f.element_name == "MISSING_SUBJECT" for f in undef)

    def test_duplicate_undefined_reported_once(self):
        report = lint(_result(
            elements=[_el("A")],
            relationships=[
                _rel("A", "rel1", "MISSING"),
                _rel("A", "rel2", "MISSING"),
            ],
        ))
        undef = report.by_category("undefined_used")
        assert len(undef) == 1  # MISSING reported only once


# ─── Coverage gaps ──────────────────────────────────────────────────────────


class TestCoverageGaps:
    def test_missing_definition_is_warning(self):
        report = lint(_result([_el("X", definition="", citation="ref")]))
        gaps = report.by_category("coverage_gap")
        assert len(gaps) == 1
        assert gaps[0].severity == "warning"
        assert "definition" in gaps[0].message

    def test_missing_citation_is_info(self):
        report = lint(_result([_el("X", definition="has def", citation="")]))
        gaps = report.by_category("coverage_gap")
        assert len(gaps) == 1
        assert gaps[0].severity == "info"
        assert "citation" in gaps[0].message

    def test_missing_both_is_warning(self):
        report = lint(_result([_el("X", definition="", citation="")]))
        gaps = report.by_category("coverage_gap")
        assert len(gaps) == 1
        assert "definition" in gaps[0].message
        assert "citation" in gaps[0].message

    def test_fully_populated_no_gap(self):
        report = lint(_result([_el("X", definition="def", citation="cite")]))
        assert report.by_category("coverage_gap") == []


# ─── Report properties ──────────────────────────────────────────────────────


class TestLintReport:
    def test_summary_counts_by_category(self):
        report = lint(_result(
            elements=[
                _el("A", definition="", citation=""),
                _el("B", definition="def", citation="cite",
                     conflicts=[_conflict("f", "A", "B")]),
            ],
            relationships=[_rel("A", "rel", "MISSING")],
        ))
        s = report.summary
        assert s.get("coverage_gap", 0) >= 1
        assert s.get("contradiction", 0) >= 1
        assert s.get("undefined_used", 0) >= 1

    def test_error_count(self):
        el = _el("X", conflicts=[_conflict("f", "A", "B", "unresolved")])
        report = lint(_result([el]))
        assert report.error_count == 1

    def test_by_element(self):
        report = lint(_result([
            _el("A", definition=""),
            _el("B", definition="def", citation="cite"),
        ]))
        findings_a = report.by_element("A")
        assert len(findings_a) >= 1
        assert all(f.element_name == "A" for f in findings_a)

    def test_empty_result_no_findings(self):
        report = lint(_result())
        assert report.findings == []
        assert report.error_count == 0
        assert report.warning_count == 0
