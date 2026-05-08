"""Tests for Source C — the typed contract and JSON round-trip.

These tests cover the **core** module ``ontozense.core.source_c``:

  - JSON serialise / deserialise round-trip (the contract any
    adapter must conform to)
  - Profile application against a synthetic ``SchemaResult``
    (no Django involved — the parser is in adapters/django/)
  - Backward-compatibility on the no-profile path

Adapter-specific behaviour (e.g. DjangoSchemaParser parsing AST
correctly) lives in ``adapters/django/tests/``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ontozense.core.profile import load_profile
from ontozense.core.source_c import (
    SCHEMA_VERSION,
    SchemaField,
    SchemaModel,
    SchemaRelationship,
    SchemaResult,
    apply_profile_to_schema,
    dump_source_c_json,
    load_source_c_json,
)


MINIMAL_PROFILE_DIR = (
    Path(__file__).parent / "fixtures" / "profiles" / "minimal"
)


# ─── 1. Dataclass shape ────────────────────────────────────────────────────


class TestShape:
    def test_schema_result_default_empty(self):
        r = SchemaResult()
        assert r.models == []
        assert r.source_dir == ""

    def test_schema_field_defaults_no_profile_metadata(self):
        f = SchemaField(name="x", field_type="CharField", playground_type="string")
        assert f.id == ""
        assert f.entity_type == ""
        assert f.choices_values == []
        assert f.max_length is None


# ─── 2. JSON round-trip ────────────────────────────────────────────────────


class TestJsonRoundTrip:
    def _sample_result(self) -> SchemaResult:
        return SchemaResult(
            source_dir="/tmp/myapp",
            models=[
                SchemaModel(
                    name="Customer",
                    doc="A customer entity.",
                    fields=[
                        SchemaField(
                            name="id",
                            field_type="AutoField",
                            playground_type="integer",
                            is_primary_key=True,
                        ),
                        SchemaField(
                            name="status",
                            field_type="CharField",
                            playground_type="enum",
                            choices_var="STATUS_CHOICES",
                            choices_values=["active", "paid"],
                            max_length=20,
                        ),
                    ],
                    relationships=[
                        SchemaRelationship(
                            field_name="account",
                            from_model="Customer",
                            to_model="Account",
                        ),
                    ],
                    source_file="customer.py",
                ),
            ],
        )

    def test_round_trip_no_profile(self, tmp_path):
        original = self._sample_result()
        out = tmp_path / "schema.json"
        dump_source_c_json(original, out)

        # The serialised JSON includes schema_version
        raw = json.loads(out.read_text(encoding="utf-8"))
        assert raw["schema_version"] == SCHEMA_VERSION

        loaded = load_source_c_json(out)
        assert len(loaded.models) == 1
        m = loaded.models[0]
        assert m.name == "Customer"
        assert m.doc == "A customer entity."
        assert len(m.fields) == 2
        assert m.fields[1].choices_values == ["active", "paid"]
        assert m.fields[1].max_length == 20
        assert len(m.relationships) == 1
        assert m.relationships[0].to_model == "Account"

    def test_no_profile_fields_omitted_from_json(self, tmp_path):
        """When id/entity_type are empty (unconstrained mode), the
        serialised JSON omits those keys entirely. Keeps the JSON
        tidy and round-trips cleanly."""
        f = SchemaField(name="x", field_type="CharField", playground_type="string")
        out = f.to_json_dict()
        assert "id" not in out
        assert "entity_type" not in out

    def test_profile_fields_present_when_set(self):
        f = SchemaField(
            name="x", field_type="CharField", playground_type="string",
            id="concept_x_111111", entity_type="Concept",
        )
        out = f.to_json_dict()
        assert out["id"] == "concept_x_111111"
        assert out["entity_type"] == "Concept"

    def test_load_tolerates_missing_profile_keys(self):
        """A pre-1.0 JSON file written before profile fields existed
        loads cleanly with empty id/entity_type."""
        raw = {
            "name": "Customer",
            "fields": [{
                "name": "x",
                "field_type": "CharField",
                "playground_type": "string",
            }],
            "relationships": [],
        }
        m = SchemaModel.from_json_dict(raw)
        assert m.id == ""
        assert m.entity_type == ""
        assert m.fields[0].id == ""

    def test_get_model_lookup(self):
        r = self._sample_result()
        m = r.get_model("customer")  # case-insensitive
        assert m is not None
        assert m.name == "Customer"
        assert r.get_model("missing") is None


# ─── 3. Profile application against the typed contract ────────────────────


class TestApplyProfile:
    def test_known_type_gets_id_and_entity_type(self):
        """A SchemaModel whose name matches a profile entity_type
        gets its id and entity_type populated."""
        result = SchemaResult(models=[
            SchemaModel(
                name="Concept",
                fields=[
                    SchemaField(name="x", field_type="CharField", playground_type="string"),
                ],
            ),
        ])
        profile = load_profile(MINIMAL_PROFILE_DIR)
        apply_profile_to_schema(result, profile)

        m = result.models[0]
        assert m.entity_type == "Concept"
        assert m.id.startswith("concept_")
        # Field inherits parent's entity_type
        assert m.fields[0].entity_type == "Concept"
        assert m.fields[0].id != ""
        assert m.fields[0].id != m.id

    def test_unknown_type_leaves_entity_type_empty_but_still_assigns_id(self):
        """Phase 3 quarantine semantics: unknown model name still gets
        an ID (so cross-source consolidation works) but entity_type
        stays empty for validation to flag."""
        result = SchemaResult(models=[
            SchemaModel(
                name="Mystery",
                fields=[
                    SchemaField(name="x", field_type="CharField", playground_type="string"),
                ],
            ),
        ])
        profile = load_profile(MINIMAL_PROFILE_DIR)
        apply_profile_to_schema(result, profile)

        m = result.models[0]
        assert m.entity_type == ""
        assert m.id != ""

    def test_field_ids_unique_within_a_model(self):
        result = SchemaResult(models=[
            SchemaModel(
                name="Concept",
                fields=[
                    SchemaField(name="a", field_type="CharField", playground_type="string"),
                    SchemaField(name="b", field_type="CharField", playground_type="string"),
                    SchemaField(name="c", field_type="CharField", playground_type="string"),
                ],
            ),
        ])
        profile = load_profile(MINIMAL_PROFILE_DIR)
        apply_profile_to_schema(result, profile)

        ids = [f.id for f in result.models[0].fields]
        assert len(set(ids)) == len(ids), "Field IDs must be unique"

    def test_unconstrained_no_profile_unchanged(self):
        """Without a profile, no fields are modified — apply is a no-op
        you wouldn't call. But the dataclasses themselves never carry
        profile metadata in the unconstrained path."""
        result = SchemaResult(models=[
            SchemaModel(
                name="Concept",
                fields=[SchemaField(name="x", field_type="CharField", playground_type="string")],
            ),
        ])
        # Don't call apply_profile_to_schema
        assert result.models[0].id == ""
        assert result.models[0].entity_type == ""
