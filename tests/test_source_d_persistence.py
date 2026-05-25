"""PR1b — Source D Python AST → SourceDResult persistence coverage.

Exercises ``build_source_d_from_files()`` against the PR1a fixture so
the AttributeFact metadata extended in PR1a survives projection into
the typed ``SourceDResult`` contract. Also covers the dump/load
round-trip and silent fallbacks (non-.py files, parse errors).
"""

from pathlib import Path

import pytest

from ontozense.core.source_d import (
    SourceDAttribute,
    SourceDContractError,
    SourceDEntity,
    SourceDResult,
    build_source_d_from_files,
    dump_source_d_json,
    load_source_d_json,
)

# Re-use the PR1a fixture — it already exercises every populated
# AttributeFact field across Pydantic / dataclass / SQLAlchemy 2.0.
FIXTURE = Path(__file__).parent / "fixtures" / "source_d" / "property_metadata_fixture.py"


@pytest.fixture(scope="module")
def sd_result() -> SourceDResult:
    return build_source_d_from_files([FIXTURE])


def _get_entity(result: SourceDResult, name: str) -> SourceDEntity:
    e = result.get_entity(name)
    assert e is not None, f"expected entity {name!r}"
    return e


def _get_attr(entity: SourceDEntity, name: str) -> SourceDAttribute:
    matches = [a for a in entity.attributes if a.name == name]
    assert len(matches) == 1, f"expected exactly one attr {name!r} on {entity.name}"
    return matches[0]


# ─── build_source_d_from_files ─────────────────────────────────────────────


def test_all_expected_entities_emitted(sd_result):
    names = {e.name for e in sd_result.entities}
    # Priority is an Enum (becomes VocabularyFact, not EntityFact) and
    # ``Base`` is the SQLAlchemy declarative base. Both are intentionally
    # absent from the SourceDResult entity list.
    assert {"Account", "Order", "Customer", "Wrapped", "WrappedColumn"} <= names


def test_entity_raw_type_classification_preserved(sd_result):
    assert _get_entity(sd_result, "Account").raw_type in ("pydantic_model", "class")
    assert _get_entity(sd_result, "Order").raw_type == "dataclass"
    assert _get_entity(sd_result, "Customer").raw_type == "sqlalchemy_model"


def test_attribute_description_carried_from_pydantic_field(sd_result):
    a = _get_attr(_get_entity(sd_result, "Account"), "account_id")
    assert a.description == "Unique account identifier"


def test_attribute_description_carried_from_dataclass_metadata(sd_result):
    a = _get_attr(_get_entity(sd_result, "Order"), "order_id")
    assert a.description == "Order primary key"


def test_attribute_description_carried_from_sqlalchemy_comment(sd_result):
    a = _get_attr(_get_entity(sd_result, "Customer"), "id")
    assert a.description == "PK"


def test_attribute_is_pk_persisted(sd_result):
    a = _get_attr(_get_entity(sd_result, "Customer"), "id")
    assert a.is_pk is True


def test_attribute_is_nullable_false_persisted_from_sqla(sd_result):
    a = _get_attr(_get_entity(sd_result, "Customer"), "email")
    assert a.is_nullable is False


def test_attribute_is_multivalued_persisted(sd_result):
    a = _get_attr(_get_entity(sd_result, "Account"), "tags")
    assert a.is_multivalued is True


def test_attribute_default_factory_captured(sd_result):
    a = _get_attr(_get_entity(sd_result, "Account"), "tags")
    assert a.default_factory == "list"


def test_attribute_enum_values_from_literal(sd_result):
    a = _get_attr(_get_entity(sd_result, "Account"), "status")
    assert a.enum_values == ["open", "closed"]


def test_attribute_enum_values_from_enum_class_reference(sd_result):
    a = _get_attr(_get_entity(sd_result, "Order"), "priority")
    assert a.enum_values == ["LOW", "HIGH"]


def test_attribute_raw_type_preserves_verbatim_annotation(sd_result):
    a = _get_attr(_get_entity(sd_result, "Account"), "tags")
    assert a.raw_type == "list[str]"


def test_wrapped_optional_enum_propagates_to_persistence(sd_result):
    """Codex r1 walker fix must survive projection into SourceDAttribute."""
    a = _get_attr(_get_entity(sd_result, "Wrapped"), "opt_enum")
    assert a.is_nullable is True
    assert a.enum_values == ["LOW", "HIGH"]


def test_mapped_literal_propagates_to_persistence(sd_result):
    a = _get_attr(_get_entity(sd_result, "WrappedColumn"), "mapped_literal")
    assert a.enum_values == ["open", "closed"]


# ─── Fallbacks ─────────────────────────────────────────────────────────────


def test_non_py_files_silently_skipped(tmp_path):
    text = tmp_path / "notes.txt"
    text.write_text("not python")
    py = tmp_path / "a.py"
    py.write_text("class A:\n    x: int = 0\n")
    result = build_source_d_from_files([text, py])
    assert {e.name for e in result.entities} == {"A"}


def test_unparseable_python_silently_skipped(tmp_path):
    broken = tmp_path / "broken.py"
    broken.write_text("def syntax error :::")
    good = tmp_path / "good.py"
    good.write_text("class Good:\n    x: int = 0\n")
    result = build_source_d_from_files([broken, good])
    assert {e.name for e in result.entities} == {"Good"}


def test_empty_input_returns_empty_result():
    result = build_source_d_from_files([])
    assert result.entities == []
    assert result.source_files == []


# ─── dump/load round-trip ─────────────────────────────────────────────────


def test_source_d_round_trip_via_disk(tmp_path, sd_result):
    path = tmp_path / "discovery" / "source-d.json"
    dump_source_d_json(sd_result, path)
    assert path.exists()

    reloaded = load_source_d_json(path)
    assert {e.name for e in reloaded.entities} == {e.name for e in sd_result.entities}
    # Spot-check one rich entity.
    new_account = _get_entity(reloaded, "Account")
    assert {a.name for a in new_account.attributes} >= {"account_id", "tags", "status"}
    new_status = _get_attr(new_account, "status")
    assert new_status.enum_values == ["open", "closed"]
    new_customer = _get_entity(reloaded, "Customer")
    new_id = _get_attr(new_customer, "id")
    assert new_id.is_pk is True


def test_load_source_d_json_rejects_unsupported_major_version(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text('{"schema_version": "9.0", "entities": []}', encoding="utf-8")
    with pytest.raises(SourceDContractError) as excinfo:
        load_source_d_json(bad)
    assert "9.0" in str(excinfo.value)


def test_load_source_d_json_rejects_missing_entities_key(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text('{"schema_version": "1.0"}', encoding="utf-8")
    with pytest.raises(SourceDContractError) as excinfo:
        load_source_d_json(bad)
    assert "entities" in str(excinfo.value)


# ─── Nested-shape validation (umbrella cleanup — Codex finding 1) ──────────
#
# load_source_d_json previously only checked the root + entities-list
# type, then delegated to from_json_dict() which crashes with raw
# AttributeError on nested malformed payloads. That bypassed draft's
# catch-and-warn path. These tests guard the now-promised behaviour:
# any nested type violation raises SourceDContractError so draft can
# log a yellow warning and continue.


def test_load_rejects_non_dict_entity(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(
        '{"schema_version": "1.0", "entities": [123]}',
        encoding="utf-8",
    )
    with pytest.raises(SourceDContractError) as excinfo:
        load_source_d_json(bad)
    assert "entities[0]" in str(excinfo.value)
    assert "object" in str(excinfo.value) or "dict" in str(excinfo.value).lower()


def test_load_rejects_non_dict_entity_in_middle_of_list(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(
        '{"schema_version": "1.0", "entities": ['
        '{"name": "ok", "attributes": []}, "string", '
        '{"name": "also_ok", "attributes": []}'
        ']}',
        encoding="utf-8",
    )
    with pytest.raises(SourceDContractError) as excinfo:
        load_source_d_json(bad)
    assert "entities[1]" in str(excinfo.value)


def test_load_rejects_non_list_attributes(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(
        '{"schema_version": "1.0", "entities": ['
        '{"name": "Bad", "attributes": "not-a-list"}'
        ']}',
        encoding="utf-8",
    )
    with pytest.raises(SourceDContractError) as excinfo:
        load_source_d_json(bad)
    assert "entities[0].attributes" in str(excinfo.value)


def test_load_rejects_non_dict_attribute(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(
        '{"schema_version": "1.0", "entities": ['
        '{"name": "Bad", "attributes": [42]}'
        ']}',
        encoding="utf-8",
    )
    with pytest.raises(SourceDContractError) as excinfo:
        load_source_d_json(bad)
    assert "entities[0].attributes[0]" in str(excinfo.value)


def test_load_rejects_null_attribute(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(
        '{"schema_version": "1.0", "entities": ['
        '{"name": "Bad", "attributes": [null]}'
        ']}',
        encoding="utf-8",
    )
    with pytest.raises(SourceDContractError) as excinfo:
        load_source_d_json(bad)
    assert "entities[0].attributes[0]" in str(excinfo.value)


def test_load_tolerates_missing_attributes_key(tmp_path):
    """Entity without an ``attributes`` key is valid — the writer
    elides empty lists. Reload must default to empty."""
    good = tmp_path / "good.json"
    good.write_text(
        '{"schema_version": "1.0", "entities": ['
        '{"name": "MinimalEntity"}'
        ']}',
        encoding="utf-8",
    )
    result = load_source_d_json(good)
    assert len(result.entities) == 1
    assert result.entities[0].name == "MinimalEntity"
    assert result.entities[0].attributes == []


# ─── Suppression parity (PR1b r1 — Codex blocker 2) ────────────────────────
#
# The persistence builder must mirror SourceDIngester's file-level
# filtering so discovery/source-d.json cannot resurrect entities from
# files candidate-graph suppressed. If parity drifts, PR2's fusion
# step would attach Attribute records from generated / test / vendor
# files the user meant to exclude.


def _py(tmp_path: Path, name: str, body: str) -> Path:
    p = tmp_path / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return p


def test_user_exclude_paths_drops_matching_files(tmp_path):
    keep = _py(tmp_path, "keep.py", "class Kept:\n    x: int = 0\n")
    legacy = _py(
        tmp_path, "legacy_dir/old.py",
        "class Legacy:\n    x: int = 0\n",
    )
    result = build_source_d_from_files(
        [keep, legacy], config={"exclude_paths": ["legacy_dir/**"]},
    )
    assert {e.name for e in result.entities} == {"Kept"}


def test_default_path_suppression_drops_tests_dir(tmp_path):
    keep = _py(tmp_path, "src/keep.py", "class Kept:\n    x: int = 0\n")
    in_tests = _py(
        tmp_path, "tests/sample.py",
        "class TestSubject:\n    x: int = 0\n",
    )
    result = build_source_d_from_files([keep, in_tests])
    assert {e.name for e in result.entities} == {"Kept"}


def test_default_path_suppression_drops_conftest(tmp_path):
    keep = _py(tmp_path, "src/keep.py", "class Kept:\n    x: int = 0\n")
    conftest = _py(
        tmp_path, "src/conftest.py",
        "class Helper:\n    x: int = 0\n",
    )
    result = build_source_d_from_files([keep, conftest])
    assert {e.name for e in result.entities} == {"Kept"}


def test_default_path_suppression_drops_migrations_and_fixtures(tmp_path):
    keep = _py(tmp_path, "app/models.py", "class Real:\n    x: int = 0\n")
    migration = _py(
        tmp_path, "migrations/0001_init.py",
        "class Mig:\n    x: int = 0\n",
    )
    fixture = _py(
        tmp_path, "fixtures/payload.py",
        "class FixPayload:\n    x: int = 0\n",
    )
    result = build_source_d_from_files([keep, migration, fixture])
    assert {e.name for e in result.entities} == {"Real"}


def test_generated_marker_suppresses_file(tmp_path):
    keep = _py(tmp_path, "keep.py", "class Kept:\n    x: int = 0\n")
    generated = _py(
        tmp_path, "generated.py",
        "# DO NOT EDIT\n"
        "# Generated by codegen v1.2\n"
        "\n"
        "class Generated:\n"
        "    x: int = 0\n",
    )
    autogen = _py(
        tmp_path, "autogen.py",
        "# AUTOGENERATED FILE\n"
        "class Autogen:\n"
        "    x: int = 0\n",
    )
    result = build_source_d_from_files([keep, generated, autogen])
    assert {e.name for e in result.entities} == {"Kept"}


def test_generated_marker_check_limited_to_first_five_lines(tmp_path):
    """A ``# DO NOT EDIT`` comment on line 10+ does NOT suppress —
    matches SourceDIngester behaviour."""
    body = (
        "\n" * 6
        + "# DO NOT EDIT this section by hand\n"
        + "class NotSuppressed:\n"
        + "    x: int = 0\n"
    )
    f = _py(tmp_path, "late_marker.py", body)
    result = build_source_d_from_files([f])
    assert {e.name for e in result.entities} == {"NotSuppressed"}


def test_user_exclude_paths_combined_with_default(tmp_path):
    """User exclude AND default suppression both apply together."""
    keep = _py(tmp_path, "src/keep.py", "class Kept:\n    x: int = 0\n")
    in_tests = _py(
        tmp_path, "tests/sample.py",
        "class FromTests:\n    x: int = 0\n",
    )
    vendor = _py(
        tmp_path, "vendor/lib.py",
        "class Vendor:\n    x: int = 0\n",
    )
    user_excluded = _py(
        tmp_path, "internal/private.py",
        "class Internal:\n    x: int = 0\n",
    )
    result = build_source_d_from_files(
        [keep, in_tests, vendor, user_excluded],
        config={"exclude_paths": ["internal/**"]},
    )
    assert {e.name for e in result.entities} == {"Kept"}
