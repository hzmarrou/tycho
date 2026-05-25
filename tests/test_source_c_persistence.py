"""PR1b — Source C SQL → SchemaResult persistence coverage.

Exercises ``build_schema_from_sql_files()`` against the synthetic
fixture: every PK / FK / NOT NULL / CHECK IN enum / VARCHAR length
recognition path. Also covers the dump/load round-trip via
``dump_source_c_json`` / ``load_source_c_json``.
"""

from pathlib import Path

import pytest

from ontozense.core.source_c import (
    SchemaField,
    SchemaModel,
    SchemaResult,
    SourceCContractError,
    build_schema_from_sql_files,
    dump_source_c_json,
    load_source_c_json,
)

FIXTURE = Path(__file__).parent / "fixtures" / "synthetic_props.sql"


@pytest.fixture(scope="module")
def schema_result() -> SchemaResult:
    return build_schema_from_sql_files([FIXTURE], source_dir=str(FIXTURE.parent))


def _get_model(result: SchemaResult, name: str) -> SchemaModel:
    m = result.get_model(name)
    assert m is not None, f"expected model {name!r} in result"
    return m


def _get_field(model: SchemaModel, name: str) -> SchemaField:
    matches = [f for f in model.fields if f.name == name]
    assert len(matches) == 1, f"expected exactly one field {name!r} on {model.name}"
    return matches[0]


# ─── build_schema_from_sql_files ───────────────────────────────────────────


def test_all_four_tables_discovered(schema_result):
    names = {m.name for m in schema_result.models}
    assert names == {"customer", "order_record", "product", "order_item"}


def test_simple_columns_get_xsd_typed_playground(schema_result):
    c = _get_model(schema_result, "customer")
    email = _get_field(c, "email")
    assert email.field_type == "VARCHAR(255)"
    assert email.playground_type == "string"
    assert email.is_nullable is False
    assert email.max_length == 255


def test_inline_primary_key_is_recognised(schema_result):
    c = _get_model(schema_result, "customer")
    pk_id = _get_field(c, "id")
    assert pk_id.is_primary_key is True


def test_not_null_columns_have_is_nullable_false(schema_result):
    o = _get_model(schema_result, "order_record")
    amount = _get_field(o, "amount")
    assert amount.is_nullable is False
    assert amount.playground_type == "decimal"
    assert amount.field_type.upper().startswith("DECIMAL")


def test_nullable_columns_have_is_nullable_true(schema_result):
    c = _get_model(schema_result, "customer")
    nickname = _get_field(c, "nickname")
    assert nickname.is_nullable is True


def test_check_in_constraint_populates_choices_values(schema_result):
    o = _get_model(schema_result, "order_record")
    status = _get_field(o, "status")
    assert status.choices_values == ["open", "paid", "closed"]
    assert status.is_nullable is False


def test_foreign_key_emits_relationship(schema_result):
    o = _get_model(schema_result, "order_record")
    fk_rels = [r for r in o.relationships if r.field_name == "customer_id"]
    assert len(fk_rels) == 1
    assert fk_rels[0].from_model == "order_record"
    assert fk_rels[0].to_model == "customer"


def test_varchar_max_length_extracted(schema_result):
    p = _get_model(schema_result, "product")
    sku = _get_field(p, "sku")
    assert sku.max_length == 32
    assert sku.is_primary_key is True


def test_table_level_composite_primary_key_applies_to_columns(schema_result):
    item = _get_model(schema_result, "order_item")
    order_id = _get_field(item, "order_id")
    product_sku = _get_field(item, "product_sku")
    qty = _get_field(item, "qty")
    assert order_id.is_primary_key is True
    assert product_sku.is_primary_key is True
    assert qty.is_primary_key is False


def test_junction_table_has_two_foreign_keys(schema_result):
    item = _get_model(schema_result, "order_item")
    targets = {r.to_model for r in item.relationships}
    assert targets == {"order_record", "product"}


def test_non_sql_files_silently_skipped(tmp_path):
    text_file = tmp_path / "notes.txt"
    text_file.write_text("not sql")
    sql_file = tmp_path / "a.sql"
    sql_file.write_text("CREATE TABLE x (id INT PRIMARY KEY);")
    result = build_schema_from_sql_files([text_file, sql_file])
    assert {m.name for m in result.models} == {"x"}


def test_invalid_sql_silently_skipped(tmp_path):
    bad = tmp_path / "bad.sql"
    bad.write_text("THIS IS NOT VALID SQL @@@")
    good = tmp_path / "good.sql"
    good.write_text("CREATE TABLE good_table (id INT PRIMARY KEY);")
    result = build_schema_from_sql_files([bad, good])
    assert {m.name for m in result.models} == {"good_table"}


# ─── dump_source_c_json / load_source_c_json round-trip ────────────────────


def test_round_trip_via_disk(tmp_path, schema_result):
    path = tmp_path / "source-c.json"
    dump_source_c_json(schema_result, path)
    assert path.exists()

    reloaded = load_source_c_json(path)
    # Same model name set.
    assert {m.name for m in reloaded.models} == {m.name for m in schema_result.models}
    # Same field count per model.
    for m in schema_result.models:
        r = reloaded.get_model(m.name)
        assert r is not None
        assert len(r.fields) == len(m.fields)
        assert len(r.relationships) == len(m.relationships)
    # Pick one and assert full field equality.
    orig = _get_model(schema_result, "order_record")
    new = _get_model(reloaded, "order_record")
    assert _get_field(new, "status").choices_values == ["open", "paid", "closed"]
    assert _get_field(new, "amount").is_nullable is False
    assert _get_field(new, "customer_id").field_type == orig.fields[1].field_type


def test_load_source_c_json_rejects_unsupported_major_version(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text('{"schema_version": "9.0", "models": []}', encoding="utf-8")
    with pytest.raises(SourceCContractError) as excinfo:
        load_source_c_json(bad)
    assert "9.0" in str(excinfo.value)


def test_load_source_c_json_rejects_missing_models_key(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text('{"schema_version": "1.0"}', encoding="utf-8")
    with pytest.raises(SourceCContractError) as excinfo:
        load_source_c_json(bad)
    assert "models" in str(excinfo.value)


def test_source_c_json_written_under_discovery_dir(tmp_path):
    """Verifies the public file shape one level up — exactly what the
    survey orchestrator writes to ``<domain-dir>/discovery/source-c.json``."""
    result = SchemaResult(
        models=[
            SchemaModel(
                name="t",
                fields=[SchemaField(
                    name="id", field_type="INT", playground_type="integer",
                    is_primary_key=True, is_nullable=False,
                )],
            ),
        ],
        source_dir="domains/x/sources",
    )
    discovery = tmp_path / "discovery"
    out = discovery / "source-c.json"
    dump_source_c_json(result, out)
    assert out.exists()
    reloaded = load_source_c_json(out)
    assert reloaded.source_dir == "domains/x/sources"
    assert reloaded.get_model("t") is not None


# ─── Suppression parity (PR1b r1 — Codex blocker 1) ────────────────────────
#
# The persistence builder must mirror SourceCIngester's filtering so
# discovery/source-c.json cannot resurrect tables / columns the
# candidate-graph build suppressed. If parity drifts, PR2's fusion
# step would attach Attribute records to FusedElements the user
# meant to exclude.


def _sql(tmp_path: Path, name: str, body: str) -> Path:
    p = tmp_path / name
    p.write_text(body, encoding="utf-8")
    return p


def test_user_exclude_tables_drops_matching_tables(tmp_path):
    sql = _sql(tmp_path, "schema.sql",
        "CREATE TABLE legacy_orders (id INT PRIMARY KEY);\n"
        "CREATE TABLE customer (id INT PRIMARY KEY);\n"
    )
    result = build_schema_from_sql_files(
        [sql], config={"exclude_tables": ["legacy_*"]},
    )
    assert {m.name for m in result.models} == {"customer"}


def test_default_table_suppression_drops_audit_history_tables(tmp_path):
    sql = _sql(tmp_path, "schema.sql",
        "CREATE TABLE customer_audit (id INT PRIMARY KEY);\n"
        "CREATE TABLE order_history (id INT PRIMARY KEY);\n"
        "CREATE TABLE tmp_data (id INT PRIMARY KEY);\n"
        "CREATE TABLE customer (id INT PRIMARY KEY);\n"
    )
    result = build_schema_from_sql_files([sql])
    assert {m.name for m in result.models} == {"customer"}


def test_user_include_tables_overrides_default_suppression(tmp_path):
    sql = _sql(tmp_path, "schema.sql",
        "CREATE TABLE customer_audit (id INT PRIMARY KEY);\n"
        "CREATE TABLE customer (id INT PRIMARY KEY);\n"
    )
    result = build_schema_from_sql_files(
        [sql], config={"include_tables": ["customer_audit"]},
    )
    assert {m.name for m in result.models} == {"customer_audit", "customer"}


def test_user_exclude_tables_wins_over_include_tables(tmp_path):
    sql = _sql(tmp_path, "schema.sql",
        "CREATE TABLE legacy (id INT PRIMARY KEY);\n"
    )
    result = build_schema_from_sql_files(
        [sql],
        config={"exclude_tables": ["legacy"], "include_tables": ["legacy"]},
    )
    assert {m.name for m in result.models} == set()


def test_default_column_suppression_drops_audit_timestamps(tmp_path):
    sql = _sql(tmp_path, "schema.sql",
        "CREATE TABLE customer ("
        "id INT PRIMARY KEY, "
        "email VARCHAR(255), "
        "created_at TIMESTAMP, "
        "updated_at TIMESTAMP, "
        "etag VARCHAR(64)"
        ");\n"
    )
    result = build_schema_from_sql_files([sql])
    customer = result.get_model("customer")
    assert customer is not None
    cols = {f.name for f in customer.fields}
    assert cols == {"id", "email"}


def test_domain_bearing_prefix_exempts_column_from_default_suppression(tmp_path):
    """birth_date / expiry_at survive even though ``*_at`` is suppressed
    by default (column_is_suppressed has the domain-bearing-prefix
    exemption)."""
    sql = _sql(tmp_path, "schema.sql",
        "CREATE TABLE customer ("
        "id INT PRIMARY KEY, "
        "birth_date DATE, "
        "expiry_at TIMESTAMP, "
        "created_at TIMESTAMP"
        ");\n"
    )
    result = build_schema_from_sql_files([sql])
    customer = result.get_model("customer")
    assert customer is not None
    cols = {f.name for f in customer.fields}
    assert "birth_date" in cols
    assert "expiry_at" in cols
    assert "created_at" not in cols


def test_user_exclude_columns_drops_matching_columns(tmp_path):
    sql = _sql(tmp_path, "schema.sql",
        "CREATE TABLE customer ("
        "id INT PRIMARY KEY, "
        "email VARCHAR(255), "
        "internal_notes TEXT"
        ");\n"
    )
    result = build_schema_from_sql_files(
        [sql], config={"exclude_columns": ["internal_*"]},
    )
    customer = result.get_model("customer")
    assert customer is not None
    assert {f.name for f in customer.fields} == {"id", "email"}


def test_empty_config_behaves_like_no_config(tmp_path):
    """``config={}`` must apply only the defaults, not anything extra."""
    sql = _sql(tmp_path, "schema.sql",
        "CREATE TABLE customer (id INT PRIMARY KEY);\n"
    )
    with_empty = build_schema_from_sql_files([sql], config={})
    without = build_schema_from_sql_files([sql])
    assert {m.name for m in with_empty.models} == {m.name for m in without.models}
