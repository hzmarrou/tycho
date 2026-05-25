"""PR2 — attribute-level fusion coverage.

Exercises ``attach_attributes_to_elements`` across every precedence
path: C-only, D-only, C+D agreement, C+D type conflict (C wins),
B-only via ``extra_fields["data_type"]``, B enum_values shape
normalisation, governance record with neither key, enum extraction
from Source D, exact + normalised matching only.
"""


import pytest

from ontozense.core.attribute import Attribute
from ontozense.core.fusion import (
    FusedElement,
    FusionResult,
    attach_attributes_to_elements,
)
from ontozense.core.source_c import (
    SchemaField,
    SchemaModel,
    SchemaResult,
)
from ontozense.core.source_d import (
    SourceDAttribute,
    SourceDEntity,
    SourceDResult,
)
from ontozense.extractors.governance_extractor import (
    GovernanceExtractionResult,
    GovernanceRecord,
)


# ─── Helpers ────────────────────────────────────────────────────────────────


def _fused_with(*element_names: str) -> FusionResult:
    return FusionResult(
        elements=[FusedElement(element_name=n) for n in element_names],
    )


def _attr_by(element: FusedElement, name: str) -> Attribute:
    matches = [a for a in element.attributes if a.name == name]
    assert len(matches) == 1, (
        f"expected one attribute {name!r}, got {[a.name for a in element.attributes]}"
    )
    return matches[0]


# ─── C-only path ────────────────────────────────────────────────────────────


def test_c_only_attributes_attached_with_storage_facts():
    fused = _fused_with("Customer")
    schema = SchemaResult(models=[
        SchemaModel(
            name="customer",
            fields=[
                SchemaField(
                    name="id", field_type="INT", playground_type="integer",
                    is_primary_key=True, is_nullable=False,
                ),
                SchemaField(
                    name="email", field_type="VARCHAR(255)",
                    playground_type="string", is_nullable=False,
                    max_length=255,
                ),
            ],
            source_file="schema.sql",
        ),
    ])
    attach_attributes_to_elements(fused, schema=schema)
    el = fused.elements[0]
    assert {a.name for a in el.attributes} == {"id", "email"}
    id_attr = _attr_by(el, "id")
    assert id_attr.is_id is True
    assert id_attr.is_nullable is False
    assert id_attr.xsd_type == "xsd:integer"
    assert [fp.source for fp in id_attr.field_provenance] == ["C"]


def test_c_only_enum_values_carried_from_check_choices():
    fused = _fused_with("Order")
    schema = SchemaResult(models=[
        SchemaModel(
            name="order",
            fields=[
                SchemaField(
                    name="status", field_type="VARCHAR(16)",
                    playground_type="string",
                    choices_values=["open", "closed"],
                ),
            ],
        ),
    ])
    attach_attributes_to_elements(fused, schema=schema)
    status = _attr_by(fused.elements[0], "status")
    assert status.enum_values == ["open", "closed"]


# ─── D-only path ────────────────────────────────────────────────────────────


def test_d_only_attributes_attached_with_description():
    fused = _fused_with("Account")
    sd = SourceDResult(entities=[
        SourceDEntity(
            name="Account",
            source_file="acct.py",
            attributes=[
                SourceDAttribute(
                    name="account_id",
                    raw_type="str",
                    description="Unique account identifier",
                    is_pk=False,
                ),
                SourceDAttribute(
                    name="tags",
                    raw_type="list[str]",
                    is_multivalued=True,
                ),
            ],
        ),
    ])
    attach_attributes_to_elements(fused, source_d=sd)
    el = fused.elements[0]
    acct = _attr_by(el, "account_id")
    assert acct.description == "Unique account identifier"
    assert acct.xsd_type == "xsd:string"
    tags = _attr_by(el, "tags")
    assert tags.is_multivalued is True


def test_d_only_enum_values_from_literal_propagate():
    fused = _fused_with("Account")
    sd = SourceDResult(entities=[
        SourceDEntity(
            name="Account",
            attributes=[
                SourceDAttribute(
                    name="status",
                    raw_type="Literal['open', 'closed']",
                    enum_values=["open", "closed"],
                ),
            ],
        ),
    ])
    attach_attributes_to_elements(fused, source_d=sd)
    status = _attr_by(fused.elements[0], "status")
    assert status.enum_values == ["open", "closed"]


# ─── C+D merge ──────────────────────────────────────────────────────────────


def test_c_and_d_agreement_merges_with_dual_provenance():
    fused = _fused_with("Customer")
    schema = SchemaResult(models=[
        SchemaModel(
            name="customer",
            fields=[SchemaField(
                name="email", field_type="VARCHAR(255)",
                playground_type="string", is_nullable=False,
            )],
        ),
    ])
    sd = SourceDResult(entities=[
        SourceDEntity(
            name="Customer",
            attributes=[SourceDAttribute(
                name="email", raw_type="str",
                description="Customer login email",
            )],
        ),
    ])
    attach_attributes_to_elements(fused, schema=schema, source_d=sd)
    email = _attr_by(fused.elements[0], "email")
    # C wins storage (xsd:string from VARCHAR), D wins description.
    assert email.xsd_type == "xsd:string"
    assert email.description == "Customer login email"
    assert email.is_nullable is False
    sources = {fp.source for fp in email.field_provenance}
    assert sources == {"C", "D"}


def test_c_and_d_type_conflict_logs_to_element_conflicts():
    fused = _fused_with("Customer")
    schema = SchemaResult(models=[
        SchemaModel(
            name="customer",
            fields=[SchemaField(
                name="balance", field_type="DECIMAL(18,2)",
                playground_type="decimal",
            )],
        ),
    ])
    sd = SourceDResult(entities=[
        SourceDEntity(
            name="Customer",
            attributes=[SourceDAttribute(
                name="balance", raw_type="int",
            )],
        ),
    ])
    attach_attributes_to_elements(fused, schema=schema, source_d=sd)
    el = fused.elements[0]
    balance = _attr_by(el, "balance")
    # C wins storage type.
    assert balance.xsd_type == "xsd:decimal"
    # Conflict recorded.
    type_conflicts = [
        c for c in el.conflicts if c.field_name == "balance.xsd_type"
    ]
    assert len(type_conflicts) == 1
    assert type_conflicts[0].winner.source == "C"
    assert type_conflicts[0].rejected[0].source == "D"


def test_c_multivalued_silent_d_collection_flips_flag():
    fused = _fused_with("Order")
    schema = SchemaResult(models=[
        SchemaModel(
            name="order",
            fields=[SchemaField(
                name="tags", field_type="VARCHAR(255)",
                playground_type="string",
            )],
        ),
    ])
    sd = SourceDResult(entities=[
        SourceDEntity(
            name="Order",
            attributes=[SourceDAttribute(
                name="tags", raw_type="list[str]", is_multivalued=True,
            )],
        ),
    ])
    attach_attributes_to_elements(fused, schema=schema, source_d=sd)
    tags = _attr_by(fused.elements[0], "tags")
    assert tags.is_multivalued is True


# ─── B-only fallback path ──────────────────────────────────────────────────


def _gov(name: str, *, data_type: str | None = None,
         enum_values=None) -> GovernanceRecord:
    extra: dict = {}
    if data_type is not None:
        extra["data_type"] = data_type
    if enum_values is not None:
        extra["enum_values"] = enum_values
    return GovernanceRecord(element_name=name, extra_fields=extra)


def test_b_only_attribute_from_extra_fields_data_type():
    fused = _fused_with("Borrower")
    gov = GovernanceExtractionResult(
        records=[_gov("Borrower", data_type="VARCHAR")],
    )
    attach_attributes_to_elements(fused, governance=gov)
    el = fused.elements[0]
    assert len(el.attributes) == 1
    attr = el.attributes[0]
    assert attr.xsd_type == "xsd:string"
    assert attr.confidence == pytest.approx(0.7)
    assert [fp.source for fp in attr.field_provenance] == ["B"]


def test_b_enum_values_as_list():
    fused = _fused_with("Loan")
    gov = GovernanceExtractionResult(records=[
        _gov("Loan", data_type="VARCHAR", enum_values=["a", "b", "c"]),
    ])
    attach_attributes_to_elements(fused, governance=gov)
    assert fused.elements[0].attributes[0].enum_values == ["a", "b", "c"]


def test_b_enum_values_as_comma_string():
    fused = _fused_with("Loan")
    gov = GovernanceExtractionResult(records=[
        _gov("Loan", data_type="VARCHAR", enum_values="open, closed"),
    ])
    attach_attributes_to_elements(fused, governance=gov)
    assert fused.elements[0].attributes[0].enum_values == ["open", "closed"]


def test_b_enum_values_as_semicolon_string_takes_precedence_over_comma():
    fused = _fused_with("Loan")
    gov = GovernanceExtractionResult(records=[
        _gov("Loan", data_type="VARCHAR", enum_values="alpha;beta,gamma"),
    ])
    attach_attributes_to_elements(fused, governance=gov)
    # Semicolon delimiter wins when present — "beta,gamma" stays one token.
    assert fused.elements[0].attributes[0].enum_values == ["alpha", "beta,gamma"]


def test_b_malformed_enum_values_logs_conflict_and_skips():
    fused = _fused_with("Loan")
    gov = GovernanceExtractionResult(records=[
        _gov("Loan", enum_values={"not": "a list"}),
    ])
    attach_attributes_to_elements(fused, governance=gov)
    el = fused.elements[0]
    assert el.attributes == []
    assert any(
        c.field_name == "Loan.b_enum_values" and c.resolution == "unresolved"
        for c in el.conflicts
    )


def test_b_malformed_data_type_logs_conflict_and_skips():
    """Codex r1 (PR2): non-str data_type must skip + log, not silently
    fall back to xsd:string."""
    fused = _fused_with("Loan")
    gov = GovernanceExtractionResult(records=[
        _gov("Loan", data_type={"oops": "object"}),
    ])
    attach_attributes_to_elements(fused, governance=gov)
    el = fused.elements[0]
    assert el.attributes == []
    assert any(
        c.field_name == "Loan.b_data_type" and c.resolution == "unresolved"
        for c in el.conflicts
    )


def test_b_malformed_data_type_with_valid_enum_still_skips():
    """Even when enum_values is valid, a malformed data_type must
    suppress the whole attribute and log the data_type conflict."""
    fused = _fused_with("Loan")
    gov = GovernanceExtractionResult(records=[
        _gov("Loan", data_type=42, enum_values=["open", "closed"]),
    ])
    attach_attributes_to_elements(fused, governance=gov)
    el = fused.elements[0]
    assert el.attributes == []
    assert any(
        c.field_name == "Loan.b_data_type" for c in el.conflicts
    )


def test_b_data_type_numeric_int_treated_as_malformed():
    """``data_type: 42`` is a contract violation (must be str). Skip + log."""
    fused = _fused_with("Loan")
    gov = GovernanceExtractionResult(records=[
        _gov("Loan", data_type=42),
    ])
    attach_attributes_to_elements(fused, governance=gov)
    el = fused.elements[0]
    assert el.attributes == []
    assert any(c.field_name == "Loan.b_data_type" for c in el.conflicts)


def test_b_data_type_empty_string_treated_as_absent():
    """Empty string is not a contract violation — it's a no-op
    (governance left the field blank). No conflict logged."""
    fused = _fused_with("Loan")
    gov = GovernanceExtractionResult(records=[
        _gov("Loan", data_type=""),
    ])
    attach_attributes_to_elements(fused, governance=gov)
    el = fused.elements[0]
    assert el.attributes == []
    assert not any(c.field_name == "Loan.b_data_type" for c in el.conflicts)


def test_b_with_neither_key_materialises_no_attribute():
    fused = _fused_with("Counterparty")
    gov = GovernanceExtractionResult(records=[_gov("Counterparty")])
    attach_attributes_to_elements(fused, governance=gov)
    assert fused.elements[0].attributes == []


def test_b_silent_when_c_or_d_already_populated():
    """B is a fallback only — must not contribute when C / D matched."""
    fused = _fused_with("Customer")
    schema = SchemaResult(models=[
        SchemaModel(
            name="customer",
            fields=[SchemaField(
                name="id", field_type="INT",
                playground_type="integer", is_primary_key=True,
            )],
        ),
    ])
    gov = GovernanceExtractionResult(records=[
        _gov("Customer", data_type="VARCHAR"),
    ])
    attach_attributes_to_elements(fused, schema=schema, governance=gov)
    el = fused.elements[0]
    # Only C's id attribute survives; B fallback skipped.
    assert {a.name for a in el.attributes} == {"id"}
    assert el.attributes[0].field_provenance[0].source == "C"


# ─── Matching: exact + normalised only ─────────────────────────────────────


def test_normalised_match_handles_case_and_separator_differences():
    fused = _fused_with("Customer Account")  # element label as in Source A
    schema = SchemaResult(models=[
        SchemaModel(  # SQL table name uses snake_case
            name="customer_account",
            fields=[SchemaField(
                name="id", field_type="INT", playground_type="integer",
                is_primary_key=True,
            )],
        ),
    ])
    attach_attributes_to_elements(fused, schema=schema)
    assert len(fused.elements[0].attributes) == 1


def test_no_match_yields_empty_attributes_no_exception():
    fused = _fused_with("Concept")
    schema = SchemaResult(models=[SchemaModel(name="unrelated_table")])
    attach_attributes_to_elements(fused, schema=schema)
    assert fused.elements[0].attributes == []


def test_no_fuzzy_match():
    """Substring-similarity must NOT match. Codex hard constraint:
    exact + normalised only in Phase A."""
    fused = _fused_with("Customer Profile")
    schema = SchemaResult(models=[SchemaModel(name="customer")])
    attach_attributes_to_elements(fused, schema=schema)
    assert fused.elements[0].attributes == []


# ─── Empty inputs ──────────────────────────────────────────────────────────


def test_all_sources_none_leaves_attributes_empty():
    fused = _fused_with("Loan")
    attach_attributes_to_elements(fused)
    assert fused.elements[0].attributes == []


def test_empty_schema_and_source_d_leave_attributes_empty():
    fused = _fused_with("Loan")
    attach_attributes_to_elements(
        fused,
        schema=SchemaResult(),
        source_d=SourceDResult(),
    )
    assert fused.elements[0].attributes == []
