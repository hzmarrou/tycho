"""Tests for Phase 4: validation stage.

Covers the 6 structural rules (VR001-VR006), both modes (flag/filter),
cascade filtering, and the CLI integration.

Backward compat: validation only runs in profile mode. Without a
profile, no FusionResult acquires validation metadata. The Phase 4
code is purely additive.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ontozense.core.fusion import (
    FieldConflict,
    FieldProvenance,
    FusedElement,
    FusedRelationship,
    FusionResult,
)
from ontozense.core.profile import load_profile
from ontozense.core.validation import (
    VALID_MODES,
    ValidationFinding,
    ValidationResult,
    validate,
)


MINIMAL_PROFILE_DIR = (
    Path(__file__).parent / "fixtures" / "profiles" / "minimal"
)


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _el(
    name: str,
    *,
    eid: str = "",
    entity_type: str = "",
    definition: str = "",
    citation: str = "",
    extras: dict | None = None,
) -> FusedElement:
    """Construct a FusedElement with profile-aware extras.

    Profile-mode ``id`` and ``entity_type`` live in ``extra_fields``
    so backward compat with unconstrained pipelines is preserved.
    """
    extra = dict(extras or {})
    if eid:
        extra["id"] = eid
    if entity_type:
        extra["entity_type"] = entity_type
    return FusedElement(
        element_name=name,
        definition=definition,
        citation=citation,
        sources=["A"],
        confidence=0.9,
        extra_fields=extra,
    )


def _rel(subject: str, predicate: str, obj: str) -> FusedRelationship:
    return FusedRelationship(
        subject=subject,
        predicate=predicate,
        object=obj,
        source="A",
        confidence=0.9,
    )


def _result(elements, relationships=None) -> FusionResult:
    return FusionResult(
        elements=list(elements),
        relationships=list(relationships or []),
        sources_used=["A"],
        fusion_timestamp="2026-05-06T00:00:00",
    )


# ─── Mode handling ──────────────────────────────────────────────────────────


class TestModes:
    def test_invalid_mode_raises(self):
        profile = load_profile(MINIMAL_PROFILE_DIR)
        with pytest.raises(ValueError, match="mode"):
            validate(_result([]), profile, mode="invalid")

    def test_valid_modes_constant(self):
        assert "flag" in VALID_MODES
        assert "filter" in VALID_MODES

    def test_default_mode_is_flag(self):
        profile = load_profile(MINIMAL_PROFILE_DIR)
        r = validate(_result([]), profile)
        assert r.mode == "flag"


# ─── VR001: Entity uniqueness ───────────────────────────────────────────────


class TestVr001Uniqueness:
    def test_no_duplicates_no_finding(self):
        profile = load_profile(MINIMAL_PROFILE_DIR)
        r = validate(
            _result([
                _el("A", eid="concept_a_111111", entity_type="Concept", definition="x"),
                _el("B", eid="concept_b_222222", entity_type="Concept", definition="y"),
            ]),
            profile,
        )
        assert r.by_rule("VR001") == []

    def test_duplicate_id_produces_error(self):
        profile = load_profile(MINIMAL_PROFILE_DIR)
        r = validate(
            _result([
                _el("A", eid="concept_a_111111", entity_type="Concept", definition="x"),
                _el("A copy", eid="concept_a_111111", entity_type="Concept", definition="y"),
            ]),
            profile,
        )
        findings = r.by_rule("VR001")
        assert len(findings) == 1
        assert findings[0].severity == "error"
        assert "concept_a_111111" in findings[0].target_id

    def test_filter_mode_drops_duplicates(self):
        profile = load_profile(MINIMAL_PROFILE_DIR)
        r = validate(
            _result([
                _el("A", eid="concept_a_111111", entity_type="Concept", definition="x"),
                _el("A2", eid="concept_a_111111", entity_type="Concept", definition="y"),
                _el("B", eid="concept_b_222222", entity_type="Concept", definition="z"),
            ]),
            profile,
            mode="filter",
        )
        assert len(r.elements) == 2
        # First occurrence kept
        assert r.elements[0].element_name == "A"
        assert r.cascade_filtered_entities >= 1

    def test_flag_mode_keeps_duplicates(self):
        profile = load_profile(MINIMAL_PROFILE_DIR)
        r = validate(
            _result([
                _el("A", eid="concept_a_111111", entity_type="Concept", definition="x"),
                _el("A2", eid="concept_a_111111", entity_type="Concept", definition="y"),
            ]),
            profile,
            mode="flag",
        )
        assert len(r.elements) == 2
        assert r.cascade_filtered_entities == 0


# ─── VR002: Type membership ─────────────────────────────────────────────────


class TestVr002TypeMembership:
    def test_known_type_no_finding(self):
        profile = load_profile(MINIMAL_PROFILE_DIR)
        r = validate(
            _result([
                _el("X", eid="concept_x_111111", entity_type="Concept", definition="d"),
            ]),
            profile,
        )
        assert r.by_rule("VR002") == []

    def test_empty_type_produces_error(self):
        profile = load_profile(MINIMAL_PROFILE_DIR)
        # No entity_type extra_fields entry
        r = validate(
            _result([
                _el("X", eid="concept_x_111111", definition="d"),
            ]),
            profile,
        )
        findings = r.by_rule("VR002")
        assert len(findings) == 1
        assert findings[0].severity == "error"
        assert "no entity_type" in findings[0].message

    def test_unknown_type_produces_error(self):
        profile = load_profile(MINIMAL_PROFILE_DIR)
        r = validate(
            _result([
                _el("X", eid="bogus_x_111111", entity_type="Bogus", definition="d"),
            ]),
            profile,
        )
        findings = r.by_rule("VR002")
        assert len(findings) == 1
        assert "unknown" in findings[0].message.lower()
        assert "Bogus" in findings[0].message

    def test_filter_mode_drops_unknown_types(self):
        profile = load_profile(MINIMAL_PROFILE_DIR)
        r = validate(
            _result([
                _el("X", eid="concept_x_111111", entity_type="Concept", definition="d"),
                _el("Y", eid="bogus_y_222222", entity_type="Bogus"),
            ]),
            profile,
            mode="filter",
        )
        assert len(r.elements) == 1
        assert r.elements[0].element_name == "X"
        assert r.cascade_filtered_entities >= 1

    def test_subtype_matches_parent(self, tmp_path):
        """If profile declares Metric with subtypes [DirectMetric, ...],
        an element with entity_type 'DirectMetric' is valid."""
        profile_dir = tmp_path / "subtype_profile"
        profile_dir.mkdir()
        (profile_dir / "schema.json").write_text(
            json.dumps({
                "profile_name": "subtype_test",
                "profile_version": "1.0.0",
                "entity_types": {
                    "Metric": {
                        "required": ["unit"],
                        "subtypes": ["DirectMetric", "CalculatedMetric"],
                    },
                },
                "predicates": {},
            }),
            encoding="utf-8",
        )
        profile = load_profile(profile_dir)
        r = validate(
            _result([
                _el(
                    "GHG Emissions",
                    eid="metric_ghg_111111",
                    entity_type="DirectMetric",
                    extras={"unit": "tCO2e"},
                ),
            ]),
            profile,
        )
        assert r.by_rule("VR002") == []


# ─── VR003: Required fields ─────────────────────────────────────────────────


class TestVr003RequiredFields:
    def test_missing_required_field_produces_warning(self):
        # Minimal profile: Concept requires "definition"
        profile = load_profile(MINIMAL_PROFILE_DIR)
        r = validate(
            _result([
                _el(
                    "Untyped",
                    eid="concept_x_111111",
                    entity_type="Concept",
                    definition="",  # missing!
                ),
            ]),
            profile,
        )
        findings = r.by_rule("VR003")
        assert len(findings) == 1
        assert findings[0].severity == "warning"
        assert "definition" in findings[0].message

    def test_all_required_present_no_finding(self):
        profile = load_profile(MINIMAL_PROFILE_DIR)
        r = validate(
            _result([
                _el(
                    "X",
                    eid="concept_x_111111",
                    entity_type="Concept",
                    definition="A real definition.",
                ),
            ]),
            profile,
        )
        assert r.by_rule("VR003") == []

    def test_required_field_in_extra_fields(self, tmp_path):
        """Required fields can also be looked up in extra_fields, not
        just typed FusedElement attributes."""
        profile_dir = tmp_path / "extra_required_profile"
        profile_dir.mkdir()
        (profile_dir / "schema.json").write_text(
            json.dumps({
                "profile_name": "extras_test",
                "profile_version": "1.0.0",
                "entity_types": {
                    "Metric": {"required": ["unit", "code"]},
                },
                "predicates": {},
            }),
            encoding="utf-8",
        )
        profile = load_profile(profile_dir)

        # All required fields provided via extra_fields
        r = validate(
            _result([
                _el(
                    "GHG",
                    eid="metric_ghg_111111",
                    entity_type="Metric",
                    extras={"unit": "tCO2e", "code": "FN-CB-110a.1"},
                ),
            ]),
            profile,
        )
        assert r.by_rule("VR003") == []

        # Missing one required
        r = validate(
            _result([
                _el(
                    "GHG",
                    eid="metric_ghg_111111",
                    entity_type="Metric",
                    extras={"unit": "tCO2e"},  # missing code
                ),
            ]),
            profile,
        )
        findings = r.by_rule("VR003")
        assert len(findings) == 1
        assert "code" in findings[0].message


# ─── VR004: Predicate vocabulary ────────────────────────────────────────────


class TestVr004PredicateVocabulary:
    def test_known_predicate_no_finding(self):
        profile = load_profile(MINIMAL_PROFILE_DIR)
        r = validate(
            _result(
                [
                    _el("A", eid="rule_a_111111", entity_type="Rule", extras={"expression": "x"}),
                    _el("B", eid="concept_b_222222", entity_type="Concept", definition="d"),
                ],
                [_rel("A", "AppliesTo", "B")],
            ),
            profile,
        )
        assert r.by_rule("VR004") == []

    def test_unknown_predicate_produces_error(self):
        profile = load_profile(MINIMAL_PROFILE_DIR)
        r = validate(
            _result(
                [
                    _el("A", eid="rule_a_111111", entity_type="Rule", extras={"expression": "x"}),
                    _el("B", eid="concept_b_222222", entity_type="Concept", definition="d"),
                ],
                [_rel("A", "Bogus", "B")],
            ),
            profile,
        )
        findings = r.by_rule("VR004")
        assert len(findings) == 1
        assert findings[0].severity == "error"
        assert "Bogus" in findings[0].message

    def test_filter_mode_drops_unknown_predicate_relationship(self):
        profile = load_profile(MINIMAL_PROFILE_DIR)
        r = validate(
            _result(
                [
                    _el("A", eid="rule_a_111111", entity_type="Rule", extras={"expression": "x"}),
                    _el("B", eid="concept_b_222222", entity_type="Concept", definition="d"),
                ],
                [
                    _rel("A", "AppliesTo", "B"),
                    _rel("A", "Bogus", "B"),
                ],
            ),
            profile,
            mode="filter",
        )
        assert len(r.relationships) == 1
        assert r.relationships[0].predicate == "AppliesTo"


# ─── VR005: Predicate domains ───────────────────────────────────────────────


class TestVr005PredicateDomains:
    def test_correct_domain_types_no_finding(self):
        profile = load_profile(MINIMAL_PROFILE_DIR)
        # AppliesTo: subject_types=["Rule"], object_types=["Concept"]
        r = validate(
            _result(
                [
                    _el("A", eid="rule_a_111111", entity_type="Rule", extras={"expression": "x"}),
                    _el("B", eid="concept_b_222222", entity_type="Concept", definition="d"),
                ],
                [_rel("A", "AppliesTo", "B")],
            ),
            profile,
        )
        assert r.by_rule("VR005") == []

    def test_wrong_subject_type_produces_warning(self):
        profile = load_profile(MINIMAL_PROFILE_DIR)
        # AppliesTo expects Rule -> Concept; we give Concept -> Concept
        r = validate(
            _result(
                [
                    _el("A", eid="concept_a_111111", entity_type="Concept", definition="d1"),
                    _el("B", eid="concept_b_222222", entity_type="Concept", definition="d2"),
                ],
                [_rel("A", "AppliesTo", "B")],
            ),
            profile,
        )
        findings = r.by_rule("VR005")
        assert len(findings) >= 1
        assert findings[0].severity == "warning"


# ─── VR006: Cardinality ─────────────────────────────────────────────────────


class TestVr006Cardinality:
    def test_one_to_one_violation_subject_side(self, tmp_path):
        """1:1 predicate where one subject maps to multiple objects."""
        profile_dir = tmp_path / "card_profile"
        profile_dir.mkdir()
        (profile_dir / "schema.json").write_text(
            json.dumps({
                "profile_name": "card_test",
                "profile_version": "1.0.0",
                "entity_types": {
                    "A": {"required": []},
                    "B": {"required": []},
                },
                "predicates": {
                    "MapsTo": {
                        "subject_types": ["A"],
                        "object_types": ["B"],
                        "cardinality": "1:1",
                    },
                },
            }),
            encoding="utf-8",
        )
        profile = load_profile(profile_dir)
        r = validate(
            _result(
                [
                    _el("a1", eid="a_a1_111111", entity_type="A"),
                    _el("b1", eid="b_b1_222222", entity_type="B"),
                    _el("b2", eid="b_b2_333333", entity_type="B"),
                ],
                [
                    _rel("a1", "MapsTo", "b1"),
                    _rel("a1", "MapsTo", "b2"),
                ],
            ),
            profile,
        )
        findings = r.by_rule("VR006")
        assert len(findings) >= 1
        assert "a1" in findings[0].target_id

    def test_n_to_n_no_violation(self, tmp_path):
        """N:N never produces cardinality findings — they're allowed."""
        profile = load_profile(MINIMAL_PROFILE_DIR)
        # AppliesTo is N:N in the minimal profile
        r = validate(
            _result(
                [
                    _el("rule1", eid="rule_r1_111111", entity_type="Rule", extras={"expression": "x"}),
                    _el("c1", eid="concept_c1_222222", entity_type="Concept", definition="d"),
                    _el("c2", eid="concept_c2_333333", entity_type="Concept", definition="d"),
                ],
                [
                    _rel("rule1", "AppliesTo", "c1"),
                    _rel("rule1", "AppliesTo", "c2"),
                ],
            ),
            profile,
        )
        assert r.by_rule("VR006") == []


# ─── Cascade filter ─────────────────────────────────────────────────────────


class TestCascadeFiltering:
    def test_filter_mode_drops_dangling_relationships(self):
        """Filter mode: when an entity is dropped (VR002 unknown type),
        relationships referencing it are also dropped."""
        profile = load_profile(MINIMAL_PROFILE_DIR)
        r = validate(
            _result(
                [
                    _el("A", eid="rule_a_111111", entity_type="Rule", extras={"expression": "x"}),
                    _el("B", eid="bogus_b_222222", entity_type="Bogus"),
                ],
                [_rel("A", "AppliesTo", "B")],
            ),
            profile,
            mode="filter",
        )
        # B was dropped (unknown type), the relationship referencing
        # it should be cascade-dropped too
        assert len(r.elements) == 1
        assert len(r.relationships) == 0
        assert r.cascade_filtered_relationships >= 1

    def test_flag_mode_no_cascade(self):
        """Flag mode: dangling relationships kept, cascade count is 0."""
        profile = load_profile(MINIMAL_PROFILE_DIR)
        r = validate(
            _result(
                [
                    _el("A", eid="rule_a_111111", entity_type="Rule", extras={"expression": "x"}),
                    _el("B", eid="bogus_b_222222", entity_type="Bogus"),
                ],
                [_rel("A", "AppliesTo", "B")],
            ),
            profile,
            mode="flag",
        )
        assert len(r.elements) == 2
        assert len(r.relationships) == 1
        assert r.cascade_filtered_relationships == 0


# ─── ValidationResult API ───────────────────────────────────────────────────


class TestValidationResult:
    def test_summary_aggregates_by_rule(self):
        profile = load_profile(MINIMAL_PROFILE_DIR)
        r = validate(
            _result([
                _el("X", eid="bogus_x_111111", entity_type="Bogus"),
                _el("Y", eid="another_y_222222", entity_type="AlsoUnknown"),
            ]),
            profile,
        )
        s = r.summary
        assert s.get("VR002") == 2

    def test_error_and_warning_counts(self):
        profile = load_profile(MINIMAL_PROFILE_DIR)
        r = validate(
            _result([
                _el("X", eid="bogus_x_111111", entity_type="Bogus"),  # VR002 error
                _el("Y", eid="concept_y_222222", entity_type="Concept", definition=""),  # VR003 warning
            ]),
            profile,
        )
        assert r.error_count >= 1
        assert r.warning_count >= 1


# ─── CLI integration ────────────────────────────────────────────────────────


class TestCli:
    def _write_fused_json(self, tmp_path: Path, elements, relationships=None) -> Path:
        """Write a minimal fused JSON shape that the CLI can read."""
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

    def test_validate_requires_profile(self, tmp_path):
        from typer.testing import CliRunner
        from ontozense import cli

        runner = CliRunner()
        f = self._write_fused_json(tmp_path, [])

        # No --profile flag
        r = runner.invoke(cli.app, ["validate", str(f)])
        # Typer exits with usage error for missing required option
        assert r.exit_code != 0

    def test_validate_clean_data_exits_zero(self, tmp_path):
        from typer.testing import CliRunner
        from ontozense import cli

        runner = CliRunner()
        f = self._write_fused_json(
            tmp_path,
            [
                {
                    "element_name": "X",
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
                    "extra_fields": {"entity_type": "Concept"},
                },
            ],
        )

        r = runner.invoke(
            cli.app,
            ["validate", str(f), "--profile", str(MINIMAL_PROFILE_DIR)],
        )
        assert r.exit_code == 0
        flat = " ".join(r.output.split())
        assert "No findings" in flat or "0 errors" in flat

    def test_validate_with_errors_exits_three(self, tmp_path):
        from typer.testing import CliRunner
        from ontozense import cli

        runner = CliRunner()
        f = self._write_fused_json(
            tmp_path,
            [
                {
                    "element_name": "Bad",
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
                    "extra_fields": {"entity_type": "Bogus"},  # unknown
                },
            ],
        )

        r = runner.invoke(
            cli.app,
            ["validate", str(f), "--profile", str(MINIMAL_PROFILE_DIR)],
        )
        # VR002 error -> exit code 3
        assert r.exit_code == 3
        flat = " ".join(r.output.split())
        assert "VR002" in flat or "Type membership" in flat

    def test_validate_writes_output_when_requested(self, tmp_path):
        from typer.testing import CliRunner
        from ontozense import cli

        runner = CliRunner()
        f = self._write_fused_json(
            tmp_path,
            [
                {
                    "element_name": "X",
                    "definition": "A test.",
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
                    "extra_fields": {"entity_type": "Concept"},
                },
            ],
        )
        out = tmp_path / "validated.json"
        r = runner.invoke(
            cli.app,
            [
                "validate", str(f),
                "--profile", str(MINIMAL_PROFILE_DIR),
                "--output", str(out),
            ],
        )
        assert r.exit_code == 0
        assert out.exists()
        data = json.loads(out.read_text(encoding="utf-8"))
        assert "validation_summary" in data
        assert data["validation_summary"]["profile_name"] == "minimal"
        assert data["validation_summary"]["error_count"] == 0

    def test_validate_invalid_mode_value_clean_error(self, tmp_path):
        from typer.testing import CliRunner
        from ontozense import cli

        runner = CliRunner()
        f = self._write_fused_json(tmp_path, [])
        r = runner.invoke(
            cli.app,
            [
                "validate", str(f),
                "--profile", str(MINIMAL_PROFILE_DIR),
                "--mode", "invalid_mode",
            ],
        )
        assert r.exit_code == 1
        flat = " ".join(r.output.split())
        assert "Invalid --mode" in flat
        assert "Traceback" not in r.output
