"""PR1a — coverage for AttributeFact extended metadata extraction.

Exercises every new field added to AttributeFact for the property-
extraction Phase A:

  - description     (Pydantic Field, dataclass field metadata,
                     SQLAlchemy Column/mapped_column comment, inline
                     ``#`` comment fallback)
  - is_multivalued  (list[T] / Sequence[T] / set[T] / default_factory=list)
  - default_factory (Pydantic / dataclass)
  - enum_values     (Literal[...] and same-module Enum class reference)
  - is_pk           (SQLAlchemy primary_key=True)
  - is_nullable     (Optional[T] / T | None / SQLAlchemy nullable=False)
  - raw_type        (verbatim annotation source)

Backwards-compat is also exercised: the fixture used by the existing
test_source_d_model_extractor.py suite must still emit AttributeFact
records (existing semantics unchanged), with the new fields defaulted.
"""
from pathlib import Path

import pytest

from ontozense.core.ingest.source_d.ir import AttributeFact, EvidenceSpan
from ontozense.core.ingest.source_d.model_extractor import extract_model
from ontozense.core.ingest.source_d.parse import parse_module

FIXTURES = Path(__file__).parent / "fixtures" / "source_d"


# ─── Helpers ────────────────────────────────────────────────────────────────


def _attrs_by(name: tuple[str, str], facts) -> AttributeFact:
    """Pick the (subject_entity, attribute_name) AttributeFact from facts."""
    matches = [
        f for f in facts
        if isinstance(f, AttributeFact)
        and f.subject_entity == name[0]
        and f.name == name[1]
    ]
    assert len(matches) == 1, f"expected exactly one {name}, got {len(matches)}"
    return matches[0]


@pytest.fixture(scope="module")
def attr_facts():
    pm = parse_module(FIXTURES / "property_metadata_fixture.py")
    return list(extract_model(pm))


# ─── Backwards-compatible defaults (existing fixture) ───────────────────────


def test_attributefact_dataclass_defaults_remain_backwards_compatible():
    """Constructing AttributeFact with only the pre-PR1a args yields
    the documented defaults for every new field."""
    a = AttributeFact(
        name="x",
        evidence_span=EvidenceSpan(file="f.py", start_line=1, end_line=1, snippet=""),
        extractor_family="model",
    )
    assert a.description == ""
    assert a.is_multivalued is False
    assert a.default_factory is None
    assert a.enum_values == []
    assert a.is_pk is False
    assert a.is_nullable is True
    assert a.raw_type == ""


def test_existing_model_fixture_attributes_still_extracted():
    """No regression on the existing model_fixture.py — pre-PR1a tests
    cover names + anchors; this guards against accidental field-loss."""
    pm = parse_module(FIXTURES / "model_fixture.py")
    facts = list(extract_model(pm))
    pairs = {(a.subject_entity, a.name)
             for a in facts if isinstance(a, AttributeFact)}
    assert ("Borrower", "credit_score") in pairs
    assert ("Loan", "amount") in pairs


# ─── description ────────────────────────────────────────────────────────────


def test_description_from_pydantic_field(attr_facts):
    a = _attrs_by(("Account", "account_id"), attr_facts)
    assert a.description == "Unique account identifier"


def test_description_from_dataclass_field_metadata(attr_facts):
    a = _attrs_by(("Order", "order_id"), attr_facts)
    assert a.description == "Order primary key"


def test_description_from_sqlalchemy_mapped_column_comment(attr_facts):
    a = _attrs_by(("Customer", "id"), attr_facts)
    assert a.description == "PK"


def test_description_from_inline_comment_fallback(attr_facts):
    a = _attrs_by(("Account", "notes"), attr_facts)
    assert a.description == "Free-form notes"


def test_description_empty_when_no_signal(attr_facts):
    a = _attrs_by(("Account", "name"), attr_facts)
    assert a.description == ""


# ─── is_multivalued ─────────────────────────────────────────────────────────


def test_is_multivalued_from_list_annotation(attr_facts):
    a = _attrs_by(("Account", "tags"), attr_facts)
    assert a.is_multivalued is True


def test_is_multivalued_from_default_factory_list(attr_facts):
    # Account.tags uses both list[str] AND default_factory=list — either
    # signal alone should flip the flag. Order.items hits the
    # default_factory path while annotation is also list[str].
    a = _attrs_by(("Order", "items"), attr_facts)
    assert a.is_multivalued is True
    assert a.default_factory == "list"


def test_is_multivalued_false_for_scalar_annotation(attr_facts):
    a = _attrs_by(("Account", "name"), attr_facts)
    assert a.is_multivalued is False


# ─── default_factory ────────────────────────────────────────────────────────


def test_default_factory_captured_as_source_string(attr_facts):
    a = _attrs_by(("Account", "tags"), attr_facts)
    assert a.default_factory == "list"


def test_default_factory_none_when_absent(attr_facts):
    a = _attrs_by(("Account", "account_id"), attr_facts)
    assert a.default_factory is None


# ─── enum_values ────────────────────────────────────────────────────────────


def test_enum_values_from_literal(attr_facts):
    a = _attrs_by(("Account", "status"), attr_facts)
    assert a.enum_values == ["open", "closed"]


def test_enum_values_from_same_module_enum_class_reference(attr_facts):
    a = _attrs_by(("Order", "priority"), attr_facts)
    assert a.enum_values == ["LOW", "HIGH"]


def test_enum_values_empty_when_annotation_is_plain_scalar(attr_facts):
    a = _attrs_by(("Account", "name"), attr_facts)
    assert a.enum_values == []


# ─── is_pk ──────────────────────────────────────────────────────────────────


def test_is_pk_from_sqlalchemy_primary_key_true(attr_facts):
    a = _attrs_by(("Customer", "id"), attr_facts)
    assert a.is_pk is True


def test_is_pk_false_for_non_sqla_attribute(attr_facts):
    a = _attrs_by(("Account", "account_id"), attr_facts)
    assert a.is_pk is False


# ─── is_nullable ────────────────────────────────────────────────────────────


def test_is_nullable_from_optional_annotation(attr_facts):
    a = _attrs_by(("Account", "nickname"), attr_facts)
    assert a.is_nullable is True


def test_is_nullable_from_pep604_union_with_none(attr_facts):
    a = _attrs_by(("Order", "note"), attr_facts)
    assert a.is_nullable is True


def test_is_nullable_false_from_sqlalchemy_nullable_false(attr_facts):
    a = _attrs_by(("Customer", "email"), attr_facts)
    assert a.is_nullable is False


def test_is_nullable_true_from_sqlalchemy_nullable_true(attr_facts):
    a = _attrs_by(("Customer", "nickname"), attr_facts)
    assert a.is_nullable is True


def test_is_nullable_default_true_when_no_signal(attr_facts):
    a = _attrs_by(("Account", "account_id"), attr_facts)
    assert a.is_nullable is True


# ─── raw_type ───────────────────────────────────────────────────────────────


def test_raw_type_preserves_annotation_verbatim(attr_facts):
    a = _attrs_by(("Account", "tags"), attr_facts)
    assert a.raw_type == "list[str]"


def test_raw_type_preserves_literal_form(attr_facts):
    a = _attrs_by(("Account", "status"), attr_facts)
    # ast.unparse normalises whitespace and quoting style; the form below
    # is what the standard library produces from a Literal['open','closed'].
    assert a.raw_type == "Literal['open', 'closed']"


def test_raw_type_empty_when_annotation_missing():
    """No annotation -> raw_type stays empty. This case is rare in the
    fixture set but guarded explicitly so a regression that always
    populates raw_type is caught."""
    a = AttributeFact(
        name="x",
        evidence_span=EvidenceSpan(file="f.py", start_line=1, end_line=1, snippet=""),
        extractor_family="model",
    )
    assert a.raw_type == ""


# ─── Wrapped-annotation recursion (Codex r1) ────────────────────────────────
#
# These tests guard the recursive annotation walker. The r0 walker
# only inspected the top-level node and silently dropped signals
# inside Optional / Mapped / list wrappers.


def test_optional_enum_propagates_enum_values_and_nullability(attr_facts):
    a = _attrs_by(("Wrapped", "opt_enum"), attr_facts)
    assert a.is_nullable is True
    assert a.enum_values == ["LOW", "HIGH"]


def test_pep604_enum_or_none_propagates_enum_values_and_nullability(attr_facts):
    a = _attrs_by(("Wrapped", "pep604_enum"), attr_facts)
    assert a.is_nullable is True
    assert a.enum_values == ["LOW", "HIGH"]


def test_list_of_enum_propagates_multivalued_and_enum_values(attr_facts):
    a = _attrs_by(("Wrapped", "list_enum"), attr_facts)
    assert a.is_multivalued is True
    assert a.enum_values == ["LOW", "HIGH"]


def test_list_of_literal_propagates_multivalued_and_enum_values(attr_facts):
    a = _attrs_by(("Wrapped", "list_literal"), attr_facts)
    assert a.is_multivalued is True
    assert a.enum_values == ["red", "green"]


def test_optional_list_propagates_both_signals(attr_facts):
    a = _attrs_by(("Wrapped", "opt_list_str"), attr_facts)
    assert a.is_nullable is True
    assert a.is_multivalued is True


def test_mapped_enum_propagates_enum_values(attr_facts):
    a = _attrs_by(("WrappedColumn", "mapped_enum"), attr_facts)
    assert a.enum_values == ["LOW", "HIGH"]


def test_mapped_literal_propagates_enum_values(attr_facts):
    a = _attrs_by(("WrappedColumn", "mapped_literal"), attr_facts)
    assert a.enum_values == ["open", "closed"]


def test_mapped_list_propagates_multivalued(attr_facts):
    a = _attrs_by(("WrappedColumn", "mapped_list_str"), attr_facts)
    assert a.is_multivalued is True


def test_mapped_optional_propagates_nullability(attr_facts):
    a = _attrs_by(("WrappedColumn", "mapped_opt_str"), attr_facts)
    assert a.is_nullable is True


def test_mapped_pk_int_does_not_falsely_flip_multivalued_or_enum(attr_facts):
    """Mapped[int] is a transparent wrapper around a plain type — no
    signals should leak. Guards against over-eager unwrapping that
    treats Mapped itself as a container."""
    a = _attrs_by(("WrappedColumn", "mid"), attr_facts)
    assert a.is_multivalued is False
    assert a.enum_values == []
    assert a.is_pk is True  # from mapped_column(primary_key=True)
