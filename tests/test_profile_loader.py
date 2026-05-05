"""Tests for the profile loader (Phase 1).

Loads the minimal test fixture under tests/fixtures/profiles/minimal/
plus a handful of malformed-on-purpose profiles built inline to verify
validation errors.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ontozense.core.profile import (
    EntityType,
    IdFormat,
    Predicate,
    Profile,
    ProfileError,
    load_profile,
)


MINIMAL_FIXTURE = (
    Path(__file__).parent / "fixtures" / "profiles" / "minimal"
)

ESG_REFERENCE = (
    Path(__file__).parent.parent / "docs" / "profile-examples" / "esg"
)


# ─── Loading the minimal fixture ─────────────────────────────────────────────


class TestLoadMinimalFixture:
    def test_loads_without_error(self):
        profile = load_profile(MINIMAL_FIXTURE)
        assert isinstance(profile, Profile)

    def test_metadata_populated(self):
        p = load_profile(MINIMAL_FIXTURE)
        assert p.profile_name == "minimal"
        assert p.profile_version == "1.0.0"
        assert "Tiny profile" in p.description

    def test_entity_types_parsed(self):
        p = load_profile(MINIMAL_FIXTURE)
        assert "Concept" in p.entity_types
        assert "Rule" in p.entity_types
        concept = p.entity_types["Concept"]
        assert concept.required_fields == ["definition"]
        assert concept.optional_fields == ["citation"]

    def test_predicates_parsed(self):
        p = load_profile(MINIMAL_FIXTURE)
        assert "AppliesTo" in p.predicates
        applies = p.predicates["AppliesTo"]
        assert applies.subject_types == ["Rule"]
        assert applies.object_types == ["Concept"]
        assert applies.cardinality == "N:N"

    def test_id_format_parsed(self):
        p = load_profile(MINIMAL_FIXTURE)
        assert p.id_format.strategy == "type_label_hash"
        assert p.id_format.hash_length == 6

    def test_alias_map_normalised_to_lowercase_keys(self):
        p = load_profile(MINIMAL_FIXTURE)
        assert p.alias_map["concept-1"] == "Concept One"
        assert p.alias_map["co1"] == "Concept One"

    def test_canonical_verbs_normalised_to_lowercase_keys(self):
        p = load_profile(MINIMAL_FIXTURE)
        assert p.canonical_verbs["applies to"] == "AppliesTo"
        assert p.canonical_verbs["governs"] == "AppliesTo"

    def test_source_path_recorded(self):
        p = load_profile(MINIMAL_FIXTURE)
        assert p.source_path == MINIMAL_FIXTURE


# ─── Profile convenience methods ────────────────────────────────────────────


class TestProfileMethods:
    @pytest.fixture
    def profile(self):
        return load_profile(MINIMAL_FIXTURE)

    def test_get_entity_type_by_name(self, profile):
        et = profile.get_entity_type("Concept")
        assert et is not None and et.name == "Concept"

    def test_get_entity_type_unknown_returns_none(self, profile):
        assert profile.get_entity_type("Unknown") is None

    def test_is_known_type(self, profile):
        assert profile.is_known_type("Concept")
        assert profile.is_known_type("Rule")
        assert not profile.is_known_type("Bogus")

    def test_is_known_predicate(self, profile):
        assert profile.is_known_predicate("AppliesTo")
        assert not profile.is_known_predicate("OrbitsAround")

    def test_canonicalise_verb_known(self, profile):
        assert profile.canonicalise_verb("applies to") == "AppliesTo"
        assert profile.canonicalise_verb("APPLIES TO") == "AppliesTo"
        assert profile.canonicalise_verb("governs") == "AppliesTo"

    def test_canonicalise_verb_unknown_returns_input(self, profile):
        assert profile.canonicalise_verb("orbits_around") == "orbits_around"

    def test_resolve_alias_known(self, profile):
        assert profile.resolve_alias("concept-1") == "Concept One"
        assert profile.resolve_alias("CO1") == "Concept One"

    def test_resolve_alias_unknown_returns_input(self, profile):
        assert profile.resolve_alias("unknown") == "unknown"


# ─── Subtype resolution ──────────────────────────────────────────────────────


class TestSubtypes:
    def test_subtype_resolves_to_parent(self, tmp_path):
        """A schema with subtypes lets is_known_type() accept the subtype name."""
        _write_profile(
            tmp_path,
            entity_types={
                "Metric": {
                    "required": ["unit"],
                    "subtypes": ["DirectMetric", "CalculatedMetric"],
                },
            },
            predicates={},
        )
        p = load_profile(tmp_path)
        assert p.is_known_type("Metric")
        assert p.is_known_type("DirectMetric")
        assert p.is_known_type("CalculatedMetric")
        # get_entity_type returns the parent for subtype lookups
        et = p.get_entity_type("DirectMetric")
        assert et is not None and et.name == "Metric"


# ─── Validation failure paths ────────────────────────────────────────────────


class TestValidationFailures:
    def test_missing_directory_raises(self, tmp_path):
        with pytest.raises(ProfileError, match="not found"):
            load_profile(tmp_path / "nonexistent")

    def test_path_is_a_file_raises(self, tmp_path):
        f = tmp_path / "file.txt"
        f.write_text("hi")
        with pytest.raises(ProfileError, match="not a directory"):
            load_profile(f)

    def test_missing_schema_json_raises(self, tmp_path):
        with pytest.raises(ProfileError, match="schema.json"):
            load_profile(tmp_path)

    def test_invalid_json_raises(self, tmp_path):
        (tmp_path / "schema.json").write_text("{ this is not json }")
        with pytest.raises(ProfileError, match="not valid JSON"):
            load_profile(tmp_path)

    def test_missing_required_top_level_keys(self, tmp_path):
        (tmp_path / "schema.json").write_text(
            json.dumps({"profile_name": "x"})
        )
        with pytest.raises(ProfileError, match="missing required keys"):
            load_profile(tmp_path)

    def test_empty_entity_types_rejected(self, tmp_path):
        _write_profile(tmp_path, entity_types={}, predicates={})
        with pytest.raises(ProfileError, match="non-empty"):
            load_profile(tmp_path)

    def test_predicate_references_unknown_type(self, tmp_path):
        _write_profile(
            tmp_path,
            entity_types={"Concept": {}},
            predicates={
                "Bogus": {
                    "subject_types": ["Concept"],
                    "object_types": ["Phantom"],
                    "cardinality": "N:N",
                }
            },
        )
        with pytest.raises(ProfileError, match="undeclared entity type"):
            load_profile(tmp_path)

    def test_invalid_cardinality_rejected(self, tmp_path):
        _write_profile(
            tmp_path,
            entity_types={"A": {}, "B": {}},
            predicates={
                "X": {
                    "subject_types": ["A"],
                    "object_types": ["B"],
                    "cardinality": "many-to-many",
                }
            },
        )
        with pytest.raises(ProfileError, match="cardinality"):
            load_profile(tmp_path)

    def test_unsupported_id_strategy_rejected(self, tmp_path):
        _write_profile(
            tmp_path,
            entity_types={"A": {}},
            predicates={},
            id_format={"strategy": "uuid_v4"},
        )
        with pytest.raises(ProfileError, match="not supported"):
            load_profile(tmp_path)

    def test_short_hash_length_rejected(self, tmp_path):
        _write_profile(
            tmp_path,
            entity_types={"A": {}},
            predicates={},
            id_format={"strategy": "type_label_hash", "hash_length": 2},
        )
        with pytest.raises(ProfileError, match="hash_length"):
            load_profile(tmp_path)

    def test_required_field_must_be_string(self, tmp_path):
        _write_profile(
            tmp_path,
            entity_types={"A": {"required": ["valid", 42]}},
            predicates={},
        )
        with pytest.raises(ProfileError, match="non-empty string"):
            load_profile(tmp_path)


# ─── Sidecar files ───────────────────────────────────────────────────────────


class TestShippedEsgReference:
    """The ESG reference profile in docs/profile-examples/esg/ must
    load cleanly — it's the canonical example users will copy from.
    Failures here mean the shipped artifact is broken."""

    def test_esg_reference_loads(self):
        if not ESG_REFERENCE.exists():
            pytest.skip("ESG reference profile not found")
        p = load_profile(ESG_REFERENCE)
        assert p.profile_name == "esg"
        assert p.profile_version  # any non-empty version

    def test_esg_reference_has_expected_types(self):
        if not ESG_REFERENCE.exists():
            pytest.skip("ESG reference profile not found")
        p = load_profile(ESG_REFERENCE)
        for expected in ["Industry", "ReportingFramework", "Category", "Metric", "Model"]:
            assert p.is_known_type(expected), (
                f"ESG reference must declare entity type {expected!r}"
            )

    def test_esg_reference_has_metric_subtypes(self):
        if not ESG_REFERENCE.exists():
            pytest.skip("ESG reference profile not found")
        p = load_profile(ESG_REFERENCE)
        for subtype in ["DirectMetric", "CalculatedMetric", "InputMetric"]:
            assert p.is_known_type(subtype), (
                f"ESG reference Metric must include subtype {subtype!r}"
            )

    def test_esg_reference_has_expected_predicates(self):
        if not ESG_REFERENCE.exists():
            pytest.skip("ESG reference profile not found")
        p = load_profile(ESG_REFERENCE)
        for pred in ["ReportUsing", "Include", "ConsistOf", "IsCalculatedBy", "RequiresInputFrom"]:
            assert p.is_known_predicate(pred), (
                f"ESG reference must declare predicate {pred!r}"
            )

    def test_esg_reference_prompt_fragment_loaded(self):
        if not ESG_REFERENCE.exists():
            pytest.skip("ESG reference profile not found")
        p = load_profile(ESG_REFERENCE)
        # Must contain the canonical predicate names so the LLM has
        # them in its prompt context
        for pred in ["ReportUsing", "Include", "ConsistOf", "IsCalculatedBy"]:
            assert pred in p.prompt_fragment, (
                f"ESG prompt fragment should reference predicate {pred!r}"
            )

    def test_esg_reference_alias_sidecar_loaded(self):
        if not ESG_REFERENCE.exists():
            pytest.skip("ESG reference profile not found")
        p = load_profile(ESG_REFERENCE)
        # Sidecar alias_map.json should overlay the schema's
        assert "co2 emissions" in p.alias_map
        # And schema-level aliases should still be there
        assert "carbon emissions" in p.alias_map


class TestSidecars:
    def test_alias_map_sidecar_overlays_schema(self, tmp_path):
        _write_profile(
            tmp_path,
            entity_types={"A": {}},
            predicates={},
            extra={
                "alias_map": {"foo": "Foo (from schema)"},
            },
        )
        # Sidecar overrides schema
        (tmp_path / "alias_map.json").write_text(
            json.dumps({
                "foo": "Foo (from sidecar)",
                "bar": "Bar (sidecar only)",
            })
        )
        p = load_profile(tmp_path)
        assert p.alias_map["foo"] == "Foo (from sidecar)"
        assert p.alias_map["bar"] == "Bar (sidecar only)"

    def test_prompt_fragment_loaded_when_present(self, tmp_path):
        _write_profile(tmp_path, entity_types={"A": {}}, predicates={})
        (tmp_path / "prompt_fragment.md").write_text(
            "# Test prompt\n\nExtract entities of type A.",
            encoding="utf-8",
        )
        p = load_profile(tmp_path)
        assert "Test prompt" in p.prompt_fragment
        assert "Extract entities" in p.prompt_fragment

    def test_no_prompt_fragment_means_empty_string(self, tmp_path):
        _write_profile(tmp_path, entity_types={"A": {}}, predicates={})
        p = load_profile(tmp_path)
        assert p.prompt_fragment == ""


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _write_profile(
    tmp_path: Path,
    *,
    entity_types: dict,
    predicates: dict,
    id_format: dict | None = None,
    extra: dict | None = None,
) -> None:
    """Write a schema.json into tmp_path with the given content."""
    schema = {
        "profile_name": "test",
        "profile_version": "1.0.0",
        "entity_types": entity_types,
        "predicates": predicates,
    }
    if id_format is not None:
        schema["id_format"] = id_format
    if extra:
        schema.update(extra)
    (tmp_path / "schema.json").write_text(json.dumps(schema), encoding="utf-8")
