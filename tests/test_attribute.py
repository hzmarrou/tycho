"""PR1b — Attribute dataclass + XSD type mapping coverage.

Exercises every row of the design-doc XSD table
(``docs/PROPERTY_EXTRACTION_DESIGN.md §5``) plus dataclass round-trip
and provenance.
"""

import pytest

from ontozense.core.attribute import (
    Attribute,
    FieldProvenance,
    xsd_type_for_python,
    xsd_type_for_sql,
)


# ─── xsd_type_for_sql ──────────────────────────────────────────────────────


@pytest.mark.parametrize("sql_type, expected", [
    # Strings
    ("VARCHAR", "xsd:string"),
    ("VARCHAR(255)", "xsd:string"),
    ("CHAR(10)", "xsd:string"),
    ("TEXT", "xsd:string"),
    ("CITEXT", "xsd:string"),
    ("UUID", "xsd:string"),           # r1: was xsd:anyURI; corrected
    ("JSON", "xsd:string"),
    ("JSONB", "xsd:string"),
    ("GEOMETRY", "xsd:string"),
    ("GEOGRAPHY", "xsd:string"),
    # Integers
    ("SMALLINT", "xsd:integer"),
    ("INT", "xsd:integer"),
    ("INTEGER", "xsd:integer"),
    ("BIGINT", "xsd:integer"),
    ("SERIAL", "xsd:integer"),
    ("BIGSERIAL", "xsd:integer"),
    ("SMALLSERIAL", "xsd:integer"),
    # Decimal / money
    ("DECIMAL", "xsd:decimal"),
    ("DECIMAL(10,2)", "xsd:decimal"),
    ("NUMERIC(18, 4)", "xsd:decimal"),
    ("MONEY", "xsd:decimal"),
    # Float
    ("FLOAT", "xsd:double"),
    ("REAL", "xsd:double"),
    ("DOUBLE PRECISION", "xsd:double"),
    # Date / time
    ("DATE", "xsd:date"),
    ("TIME", "xsd:time"),
    ("TIMESTAMP", "xsd:dateTime"),
    ("DATETIME", "xsd:dateTime"),
    ("TIMESTAMPTZ", "xsd:dateTimeStamp"),
    ("TIMESTAMP WITH TIME ZONE", "xsd:dateTimeStamp"),
    ("INTERVAL", "xsd:duration"),
    # Bool
    ("BOOLEAN", "xsd:boolean"),
    ("BOOL", "xsd:boolean"),
    # Binary
    ("BLOB", "xsd:base64Binary"),
    ("BYTEA", "xsd:base64Binary"),
    # Case-insensitive
    ("varchar", "xsd:string"),
    ("VarChar(50)", "xsd:string"),
    ("decimal(10,2)", "xsd:decimal"),
])
def test_xsd_type_for_sql_known_types(sql_type, expected):
    assert xsd_type_for_sql(sql_type) == expected


def test_xsd_type_for_sql_unknown_defaults_to_string():
    assert xsd_type_for_sql("WEIRD_VENDOR_TYPE") == "xsd:string"
    assert xsd_type_for_sql("HSTORE") == "xsd:string"


def test_xsd_type_for_sql_empty_input_defaults_to_string():
    assert xsd_type_for_sql("") == "xsd:string"


def test_xsd_type_for_sql_array_notation_recurses():
    """``INT[]`` looks up the element type and returns xsd:integer.
    Caller is responsible for setting is_multivalued."""
    assert xsd_type_for_sql("INT[]") == "xsd:integer"
    assert xsd_type_for_sql("VARCHAR(255)[]") == "xsd:string"


# ─── xsd_type_for_python ───────────────────────────────────────────────────


@pytest.mark.parametrize("py_type, expected", [
    ("str", "xsd:string"),
    ("int", "xsd:integer"),
    ("float", "xsd:double"),
    ("bool", "xsd:boolean"),
    ("bytes", "xsd:base64Binary"),
    ("date", "xsd:date"),
    ("datetime", "xsd:dateTime"),
    ("UUID", "xsd:string"),
    ("Decimal", "xsd:decimal"),
    # Fully-qualified names: tail-only lookup.
    ("decimal.Decimal", "xsd:decimal"),
    ("datetime.date", "xsd:date"),
    ("datetime.datetime", "xsd:dateTime"),
    ("uuid.UUID", "xsd:string"),
])
def test_xsd_type_for_python_known_types(py_type, expected):
    assert xsd_type_for_python(py_type) == expected


def test_xsd_type_for_python_unknown_defaults_to_string():
    assert xsd_type_for_python("SomeCustomClass") == "xsd:string"


def test_xsd_type_for_python_empty_input_defaults_to_string():
    assert xsd_type_for_python("") == "xsd:string"


# ─── Attribute dataclass round-trip ────────────────────────────────────────


def test_attribute_defaults():
    a = Attribute(name="email", xsd_type="xsd:string")
    assert a.description == ""
    assert a.is_id is False
    assert a.is_multivalued is False
    assert a.is_nullable is True
    assert a.enum_values == []
    assert a.raw_type == ""
    assert a.field_provenance == []
    assert a.confidence == 1.0


def test_attribute_json_round_trip():
    a = Attribute(
        name="status",
        xsd_type="xsd:string",
        description="Order status",
        is_id=False,
        is_multivalued=False,
        is_nullable=False,
        enum_values=["open", "paid", "closed"],
        raw_type="VARCHAR(16)",
        field_provenance=[
            FieldProvenance(
                source="C",
                artifact="/path/synthetic.sql",
                line=12,
                confidence=1.0,
                extractor="ddl",
            ),
        ],
        confidence=1.0,
    )
    roundtripped = Attribute.from_json_dict(a.to_json_dict())
    assert roundtripped == a


def test_attribute_from_legacy_json_with_missing_optional_keys():
    """Older / partial JSON without the full key set still loads with
    sensible defaults — no exception."""
    raw = {"name": "email", "xsd_type": "xsd:string"}
    a = Attribute.from_json_dict(raw)
    assert a.name == "email"
    assert a.xsd_type == "xsd:string"
    assert a.description == ""
    assert a.enum_values == []


def test_field_provenance_json_round_trip():
    fp = FieldProvenance(
        source="D",
        artifact="src/order.py",
        line=42,
        confidence=0.95,
        extractor="ast",
    )
    assert FieldProvenance.from_json_dict(fp.to_json_dict()) == fp
