"""PR2 — draft auto-loads discovery/source-c.json + discovery/source-d.json.

Exercises _run_fuse_for_draft's PR2 wiring directly. Bypasses the
LLM-dependent Source A extract-a step by writing a hand-crafted
``discovery/source-a.json`` with concepts that match the synthetic
SQL / Python fixtures.
"""

import json
from pathlib import Path

from ontozense.cli import _run_fuse_for_draft
from ontozense.core.source_c import (
    SchemaField,
    SchemaModel,
    SchemaResult,
    dump_source_c_json,
)
from ontozense.core.source_d import (
    SourceDAttribute,
    SourceDEntity,
    SourceDResult,
    dump_source_d_json,
)


def _write_source_a_json(path: Path, concept_names: list[str]) -> None:
    """Write a minimal but valid source-a.json the loader accepts.

    Matches the shape produced by survey's extract-a pass + the
    multi-doc consolidation: a list of DomainDocumentExtractionResult
    objects with concepts. We stay schema-faithful so the existing
    _load_source_a_json helper does not raise.
    """
    payload = {
        "concepts": [
            {
                "name": n,
                "definition": f"{n} (test fixture)",
                "id": "",
                "entity_type": "",
                "extraction_confidence": 0.9,
                "grounding_confidence": 0.9,
                "extraction_provenance": None,
            }
            for n in concept_names
        ],
        "relationships": [],
        "domain_name": "test",
        "extraction_method": "test-fixture",
        "extraction_timestamp": "2026-01-01T00:00:00",
        "source_document": "test-fixture.md",
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _make_schema() -> SchemaResult:
    return SchemaResult(models=[
        SchemaModel(
            name="customer",
            fields=[
                SchemaField(
                    name="id", field_type="INT",
                    playground_type="integer", is_primary_key=True,
                    is_nullable=False,
                ),
                SchemaField(
                    name="email", field_type="VARCHAR(255)",
                    playground_type="string", is_nullable=False,
                ),
            ],
            source_file="schema.sql",
        ),
    ])


def _make_source_d() -> SourceDResult:
    return SourceDResult(entities=[
        SourceDEntity(
            name="Customer",
            source_file="customer.py",
            attributes=[
                SourceDAttribute(
                    name="email", raw_type="str",
                    description="Customer login email",
                ),
            ],
        ),
    ])


# ─── PR2: draft picks up discovery files ───────────────────────────────────


def test_draft_loads_discovery_source_c_json(tmp_path):
    domain = tmp_path / "domain"
    discovery = domain / "discovery"
    sa_path = discovery / "source-a.json"
    _write_source_a_json(sa_path, ["Customer"])
    dump_source_c_json(_make_schema(), discovery / "source-c.json")

    fused = _run_fuse_for_draft(
        sa_path, domain / "fused.json",
        discovery_dir=discovery,
    )
    customer = fused.get_element("Customer")
    assert customer is not None
    assert {a.name for a in customer.attributes} == {"id", "email"}
    id_attr = next(a for a in customer.attributes if a.name == "id")
    assert id_attr.is_id is True
    assert id_attr.field_provenance[0].source == "C"


def test_draft_loads_discovery_source_d_json(tmp_path):
    domain = tmp_path / "domain"
    discovery = domain / "discovery"
    sa_path = discovery / "source-a.json"
    _write_source_a_json(sa_path, ["Customer"])
    dump_source_d_json(_make_source_d(), discovery / "source-d.json")

    fused = _run_fuse_for_draft(
        sa_path, domain / "fused.json",
        discovery_dir=discovery,
    )
    customer = fused.get_element("Customer")
    assert customer is not None
    email_attrs = [a for a in customer.attributes if a.name == "email"]
    assert len(email_attrs) == 1
    assert email_attrs[0].description == "Customer login email"
    assert email_attrs[0].field_provenance[0].source == "D"


def test_draft_merges_source_c_and_d_when_both_present(tmp_path):
    domain = tmp_path / "domain"
    discovery = domain / "discovery"
    sa_path = discovery / "source-a.json"
    _write_source_a_json(sa_path, ["Customer"])
    dump_source_c_json(_make_schema(), discovery / "source-c.json")
    dump_source_d_json(_make_source_d(), discovery / "source-d.json")

    fused = _run_fuse_for_draft(
        sa_path, domain / "fused.json",
        discovery_dir=discovery,
    )
    customer = fused.get_element("Customer")
    email = next(a for a in customer.attributes if a.name == "email")
    # C wins storage facts, D wins description.
    assert email.xsd_type == "xsd:string"
    assert email.description == "Customer login email"
    sources = {fp.source for fp in email.field_provenance}
    assert sources == {"C", "D"}


# ─── Missing-file fallback ─────────────────────────────────────────────────


def test_draft_with_missing_discovery_files_yields_empty_attributes(tmp_path):
    """Missing discovery/source-c.json + source-d.json must not raise.
    FusedElement.attributes stays empty."""
    domain = tmp_path / "domain"
    discovery = domain / "discovery"
    sa_path = discovery / "source-a.json"
    _write_source_a_json(sa_path, ["IsolatedConcept"])
    # NOTE: deliberately do NOT write source-c.json or source-d.json.

    fused = _run_fuse_for_draft(
        sa_path, domain / "fused.json",
        discovery_dir=discovery,
    )
    element = fused.get_element("IsolatedConcept")
    assert element is not None
    assert element.attributes == []


def test_draft_without_discovery_dir_kwarg_skips_attribute_attachment(tmp_path):
    """When discovery_dir is None, _run_fuse_for_draft must not look up
    discovery files at all (preserves byte-identical behaviour for any
    call sites that don't opt in)."""
    domain = tmp_path / "domain"
    discovery = domain / "discovery"
    sa_path = discovery / "source-a.json"
    _write_source_a_json(sa_path, ["X"])
    # Even with discovery files present...
    dump_source_c_json(_make_schema(), discovery / "source-c.json")

    fused = _run_fuse_for_draft(
        sa_path, domain / "fused.json",
        # discovery_dir intentionally omitted.
    )
    assert all(el.attributes == [] for el in fused.elements)


# ─── Invalid discovery file tolerance ──────────────────────────────────────


def test_draft_tolerates_invalid_source_c_json(tmp_path, capsys):
    """An unparseable source-c.json must not crash draft — just log
    and continue with empty C contributions."""
    domain = tmp_path / "domain"
    discovery = domain / "discovery"
    sa_path = discovery / "source-a.json"
    _write_source_a_json(sa_path, ["X"])
    # Bad schema_version → SourceCContractError.
    (discovery / "source-c.json").write_text(
        '{"schema_version": "9.0", "models": []}', encoding="utf-8",
    )
    fused = _run_fuse_for_draft(
        sa_path, domain / "fused.json", discovery_dir=discovery,
    )
    # No exception; element has no attributes.
    assert fused.get_element("X") is not None
    assert fused.get_element("X").attributes == []


def test_draft_tolerates_invalid_source_d_json(tmp_path):
    domain = tmp_path / "domain"
    discovery = domain / "discovery"
    sa_path = discovery / "source-a.json"
    _write_source_a_json(sa_path, ["Y"])
    (discovery / "source-d.json").write_text(
        '{"schema_version": "9.0", "entities": []}', encoding="utf-8",
    )
    fused = _run_fuse_for_draft(
        sa_path, domain / "fused.json", discovery_dir=discovery,
    )
    assert fused.get_element("Y") is not None
    assert fused.get_element("Y").attributes == []


def test_draft_tolerates_nested_malformed_source_d_json(tmp_path):
    """Umbrella cleanup (Codex finding 1): nested malformed shapes in
    source-d.json must surface as SourceDContractError so draft's
    catch-and-warn path handles them — not a raw AttributeError."""
    domain = tmp_path / "domain"
    discovery = domain / "discovery"
    sa_path = discovery / "source-a.json"
    _write_source_a_json(sa_path, ["Z"])
    # entities[0] is an int, not a dict.
    (discovery / "source-d.json").write_text(
        '{"schema_version": "1.0", "entities": [123]}', encoding="utf-8",
    )
    fused = _run_fuse_for_draft(
        sa_path, domain / "fused.json", discovery_dir=discovery,
    )
    assert fused.get_element("Z") is not None
    assert fused.get_element("Z").attributes == []


def test_draft_tolerates_nested_malformed_attributes_in_source_d_json(tmp_path):
    """Umbrella cleanup: attributes[i] of the wrong shape also gets
    caught and warned, not crashed."""
    domain = tmp_path / "domain"
    discovery = domain / "discovery"
    sa_path = discovery / "source-a.json"
    _write_source_a_json(sa_path, ["W"])
    (discovery / "source-d.json").write_text(
        '{"schema_version": "1.0", "entities": ['
        '{"name": "W", "attributes": [42]}'
        ']}',
        encoding="utf-8",
    )
    fused = _run_fuse_for_draft(
        sa_path, domain / "fused.json", discovery_dir=discovery,
    )
    assert fused.get_element("W") is not None
    assert fused.get_element("W").attributes == []
