"""PR2 — serializer + reconstructor round-trip with attributes.

Covers _serialize_element / _reconstruct_fusion_result in cli.py.
Backwards-compat: legacy fused.json without ``attributes`` key
reloads cleanly with empty list (test_legacy_fused_json_reload).
"""

import json

from ontozense.cli import (
    _reconstruct_fusion_result,
    _serialize_element,
)
from ontozense.core.attribute import Attribute, FieldProvenance as AttrFieldProvenance
from ontozense.core.fusion import (
    FusedElement,
)


# ─── Serializer ────────────────────────────────────────────────────────────


def test_serialize_element_includes_attributes_key():
    el = FusedElement(
        element_name="Customer",
        attributes=[Attribute(
            name="email", xsd_type="xsd:string",
            description="Login email",
            field_provenance=[AttrFieldProvenance(
                source="D", artifact="cust.py", line=12,
                confidence=1.0, extractor="ast",
            )],
        )],
    )
    out = _serialize_element(el)
    assert "attributes" in out
    assert len(out["attributes"]) == 1
    assert out["attributes"][0]["name"] == "email"
    assert out["attributes"][0]["xsd_type"] == "xsd:string"
    assert out["attributes"][0]["description"] == "Login email"
    assert out["attributes"][0]["field_provenance"][0]["source"] == "D"


def test_serialize_element_empty_attributes_yields_empty_list():
    el = FusedElement(element_name="x")
    out = _serialize_element(el)
    assert out["attributes"] == []


# ─── Reconstructor ─────────────────────────────────────────────────────────


def test_reconstruct_fusion_result_carries_attributes():
    raw = {
        "elements": [{
            "element_name": "Customer",
            "attributes": [{
                "name": "id",
                "xsd_type": "xsd:integer",
                "is_id": True,
                "is_nullable": False,
                "raw_type": "INT",
                "field_provenance": [{
                    "source": "C",
                    "artifact": "schema.sql",
                    "line": 5,
                    "confidence": 1.0,
                    "extractor": "ddl",
                }],
            }],
        }],
    }
    fused = _reconstruct_fusion_result(raw)
    assert len(fused.elements) == 1
    el = fused.elements[0]
    assert len(el.attributes) == 1
    assert el.attributes[0].name == "id"
    assert el.attributes[0].xsd_type == "xsd:integer"
    assert el.attributes[0].is_id is True
    assert el.attributes[0].field_provenance[0].source == "C"


# ─── Round-trip ────────────────────────────────────────────────────────────


def test_serialize_reconstruct_round_trip():
    el = FusedElement(
        element_name="Loan",
        attributes=[
            Attribute(
                name="loan_id", xsd_type="xsd:string",
                description="Loan PK", is_id=True, is_nullable=False,
                raw_type="VARCHAR(32)",
            ),
            Attribute(
                name="status", xsd_type="xsd:string",
                description="State", enum_values=["open", "closed"],
                raw_type="VARCHAR(16)",
            ),
        ],
    )
    serialised = json.loads(json.dumps({"elements": [_serialize_element(el)]}))
    reloaded = _reconstruct_fusion_result(serialised)
    rel = reloaded.elements[0]
    assert [a.name for a in rel.attributes] == ["loan_id", "status"]
    assert rel.attributes[0].is_id is True
    assert rel.attributes[1].enum_values == ["open", "closed"]


# ─── Legacy fused.json (no attributes key) ─────────────────────────────────


def test_legacy_fused_json_without_attributes_reloads_cleanly():
    """Pre-PR2 fused.json files have no ``attributes`` key. Reload must
    default to empty list, no exception."""
    raw = {
        "elements": [{
            "element_name": "LegacyConcept",
            "definition": "Old-shape definition",
            "is_critical": False,
            "data_type": "string",
            # No "attributes" key — pre-PR2 shape.
        }],
    }
    fused = _reconstruct_fusion_result(raw)
    assert len(fused.elements) == 1
    assert fused.elements[0].attributes == []
    assert fused.elements[0].element_name == "LegacyConcept"


def test_legacy_fused_json_with_attributes_null_treated_as_empty():
    """``"attributes": null`` (rare but tolerated) deserialises to []."""
    raw = {
        "elements": [{
            "element_name": "X",
            "attributes": None,
        }],
    }
    fused = _reconstruct_fusion_result(raw)
    assert fused.elements[0].attributes == []


# ─── Standalone fuse parity (PR2 r1 — Codex blocker 1) ─────────────────────
#
# The standalone `fuse` CLI command must produce fused.json with the
# same element shape as `_run_fuse_for_draft`. Pre-PR2 r1 it built the
# dict by hand and silently omitted ``attributes``.


def test_standalone_fuse_command_emits_attributes_key(tmp_path):
    """Invoke the `fuse` CLI command on a minimal source-a fixture and
    verify each element in the output JSON carries an ``attributes``
    key (even when empty). Guards against the inline-dict-build
    regression Codex flagged in PR2 r0."""
    from typer.testing import CliRunner

    from ontozense.cli import app

    sa = tmp_path / "source-a.json"
    sa.write_text(json.dumps({
        "concepts": [
            {"name": "Customer", "definition": "A customer."},
        ],
        "relationships": [],
    }), encoding="utf-8")

    output = tmp_path / "fused.json"
    result = CliRunner().invoke(app, [
        "fuse",
        "--source-a", str(sa),
        "--output", str(output),
    ])
    assert result.exit_code == 0, result.output
    assert output.exists()
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["elements"], "expected at least one element in fuse output"
    for el in payload["elements"]:
        assert "attributes" in el, (
            f"fuse output element {el.get('element_name')!r} missing "
            f"'attributes' key — serializer parity regression"
        )
        # Empty list is fine here — engine.fuse() alone doesn't populate
        # attributes (that's _run_fuse_for_draft's discovery-load step).
        # The key MUST be present so downstream tooling sees a
        # consistent shape.
        assert isinstance(el["attributes"], list)
