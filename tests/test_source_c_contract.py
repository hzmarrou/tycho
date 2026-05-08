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


# ─── 4. Schema version + structural validation (review finding #1) ────────


class TestLoaderContractValidation:
    """Pin the Source C loader's strict-validation behaviour. The
    pre-fix loader silently accepted any JSON, even with an
    unsupported schema_version or missing models, producing a
    seemingly-successful run with 0 models. Now those failure modes
    raise ``SourceCContractError``."""

    def _write_json(self, tmp_path, payload) -> Path:
        import json as _json
        f = tmp_path / "source-c.json"
        f.write_text(_json.dumps(payload), encoding="utf-8")
        return f

    def test_unsupported_major_version_raises(self, tmp_path):
        from ontozense.core.source_c import SourceCContractError
        f = self._write_json(tmp_path, {
            "schema_version": "999.0",
            "models": [],
        })
        with pytest.raises(SourceCContractError, match="Unsupported"):
            load_source_c_json(f)

    def test_missing_models_key_raises(self, tmp_path):
        from ontozense.core.source_c import SourceCContractError
        f = self._write_json(tmp_path, {"schema_version": "1.0"})
        with pytest.raises(SourceCContractError, match="missing required key 'models'"):
            load_source_c_json(f)

    def test_models_must_be_list(self, tmp_path):
        from ontozense.core.source_c import SourceCContractError
        f = self._write_json(tmp_path, {
            "schema_version": "1.0",
            "models": "not a list",
        })
        with pytest.raises(SourceCContractError, match="'models' must be a list"):
            load_source_c_json(f)

    def test_root_must_be_object(self, tmp_path):
        from ontozense.core.source_c import SourceCContractError
        f = self._write_json(tmp_path, ["not", "an", "object"])
        with pytest.raises(SourceCContractError, match="root must be an object"):
            load_source_c_json(f)

    def test_missing_schema_version_tolerated_as_1_0(self, tmp_path):
        """A pre-versioning JSON file (no schema_version key) loads
        cleanly with the implicit 1.0 default — backward compat for
        any adapter output written before the field existed."""
        f = self._write_json(tmp_path, {"models": []})
        result = load_source_c_json(f)
        assert result.models == []

    def test_minor_version_within_supported_major_loads(self, tmp_path):
        """1.7 is in major 1 → supported."""
        f = self._write_json(tmp_path, {
            "schema_version": "1.7",
            "models": [],
        })
        result = load_source_c_json(f)
        assert result.models == []


# ─── 5. CLI integration: --source-c (review findings #2 + #4) ─────────────


class TestCliSourceC:
    def _basic_source_a_json(self, tmp_path: Path) -> Path:
        """A minimal Source A JSON the fuse command will accept."""
        import json as _json
        f = tmp_path / "source-a.json"
        f.write_text(_json.dumps({
            "domain_name": "test",
            "concepts": [{
                "name": "Customer",
                "definition": "A buyer.",
                "citation": "",
                "id": "",
                "entity_type": "",
                "confidence": [{"field_name": "name", "score": 0.9, "reason": "v"}],
                "provenance": {"source_document": "doc.md"},
            }],
            "relationships": [],
            "source_documents": ["doc.md"],
            "extraction_timestamp": "2026-05-08T00:00:00",
        }), encoding="utf-8")
        return f

    def test_directory_input_prints_migration_hint(self, tmp_path):
        """Pre-1.0 users passed a directory to --source-c. The CLI
        now refuses but prints the inline migration command."""
        from typer.testing import CliRunner
        from ontozense import cli

        models_dir = tmp_path / "myapp"
        models_dir.mkdir()
        sa = self._basic_source_a_json(tmp_path)

        runner = CliRunner()
        r = runner.invoke(cli.app, [
            "fuse",
            "--source-a", str(sa),
            "--source-c", str(models_dir),
            "--output", str(tmp_path / "fused.json"),
        ])
        assert r.exit_code == 1
        flat = " ".join(r.output.split())
        assert "Source C is now a JSON file" in flat
        assert "django_to_json" in flat
        assert "Traceback" not in r.output

    def test_unsupported_schema_version_clean_error(self, tmp_path):
        """Reviewer's blocker repro: a JSON with an unsupported
        schema_version must error loudly, not silently produce 0
        models."""
        from typer.testing import CliRunner
        from ontozense import cli
        import json as _json

        sa = self._basic_source_a_json(tmp_path)
        sc = tmp_path / "source-c.json"
        sc.write_text(_json.dumps({
            "schema_version": "999.0",
            "models": [],
        }), encoding="utf-8")

        runner = CliRunner()
        r = runner.invoke(cli.app, [
            "fuse",
            "--source-a", str(sa),
            "--source-c", str(sc),
            "--output", str(tmp_path / "fused.json"),
        ])
        assert r.exit_code == 1
        flat = " ".join(r.output.split())
        assert "Source C JSON contract error" in flat
        assert "Unsupported" in flat
        assert "Traceback" not in r.output


# ─── 6. End-to-end: adapter CLI → SchemaResult JSON → fuse (review #3) ────


class TestEndToEndAdapterToFuse:
    """Pin the migration path the reviewer flagged: an adapter writes
    a SchemaResult JSON, fuse consumes it. Without this test the
    contract isn't actually exercised by CI — only its halves."""

    def test_synthetic_schemaresult_dump_then_fuse_consumes(self, tmp_path):
        """Use the dataclass dump helper to produce a SchemaResult
        JSON (proxying for what an adapter would do), then run
        fuse --source-c on it and assert the schema field bubbled
        through into the fused output."""
        from typer.testing import CliRunner
        from ontozense import cli
        import json as _json

        # Build a minimal SchemaResult that "Customer.name" exists
        result = SchemaResult(
            source_dir="/synthetic",
            models=[
                SchemaModel(
                    name="Customer",
                    fields=[
                        SchemaField(
                            name="name",
                            field_type="CharField",
                            playground_type="string",
                            max_length=100,
                        ),
                    ],
                ),
            ],
        )
        sc_path = tmp_path / "source-c.json"
        from ontozense.core.source_c import dump_source_c_json
        dump_source_c_json(result, sc_path)

        # Confirm the file conforms before fuse touches it
        loaded = load_source_c_json(sc_path)
        assert len(loaded.models) == 1

        # Build a Source A that mentions 'name' so fusion has
        # something to enrich with the schema's data_type
        sa = tmp_path / "source-a.json"
        sa.write_text(_json.dumps({
            "domain_name": "t",
            "concepts": [{
                "name": "name",
                "definition": "the customer's full legal name",
                "citation": "",
                "id": "",
                "entity_type": "",
                "confidence": [{"field_name": "name", "score": 0.9, "reason": "v"}],
                "provenance": {"source_document": "doc.md"},
            }],
            "relationships": [],
            "source_documents": ["doc.md"],
            "extraction_timestamp": "2026-05-08T00:00:00",
        }), encoding="utf-8")

        out = tmp_path / "fused.json"
        runner = CliRunner()
        r = runner.invoke(cli.app, [
            "fuse",
            "--source-a", str(sa),
            "--source-c", str(sc_path),
            "--output", str(out),
        ])
        assert r.exit_code == 0, r.output
        assert out.exists()
        data = _json.loads(out.read_text(encoding="utf-8"))
        # Source C contributed the data_type
        names = {el["element_name"] for el in data["elements"]}
        assert "name" in names
        the_el = next(el for el in data["elements"] if el["element_name"] == "name")
        assert the_el["data_type"] == "string"


# ─── 7. Compatibility shim for old DjangoSchemaParser import path ─────────


class TestDjangoSchemaParserImportShim:
    """Pin the targeted ImportError that replaces the old
    ``from ontozense.extractors import DjangoSchemaParser`` path.
    The shim fails loudly with migration instructions instead of
    a vanilla ImportError that doesn't tell the user what to do."""

    def test_old_import_path_raises_with_migration_guidance(self):
        with pytest.raises(ImportError, match="moved to adapters/django"):
            from ontozense.extractors import DjangoSchemaParser  # noqa: F401

    def test_other_unknown_attrs_raise_attribute_error(self):
        """The __getattr__ shim only intercepts DjangoSchemaParser.
        Other unknown attribute access on the module still raises
        AttributeError as Python expects."""
        import ontozense.extractors as exts
        with pytest.raises(AttributeError, match="no attribute 'NonExistent'"):
            _ = exts.NonExistent
