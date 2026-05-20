import pytest

from ontozense.core.ingest.source_d.rule_payload import (
    ALLOWED_PREDICATES,
    RuleKind,
    canonical_rule_label,
    merge_key,
    validate_rule_payload,
)


def test_rulekind_enum_values():
    assert {k.value for k in RuleKind} == {
        "validation", "derivation", "defaulting",
        "eligibility", "transition", "calculation", "dependency",
    }


def test_allowed_predicates_includes_core_set():
    for p in ["gt", "gte", "lt", "lte", "eq", "neq", "required",
              "in_set", "not_in_set", "derived_from", "transitions_to"]:
        assert p in ALLOWED_PREDICATES


def test_validate_accepts_minimal_payload():
    validate_rule_payload({
        "rule_kind": "validation",
        "subject_entity": "Loan",
        "subject_attribute": "amount",
        "predicate": "gt",
        "object_value": 0,
        "expression": "amount > 0",
        "evidence_span": {"file": "loans.py", "start_line": 1, "end_line": 1, "snippet": "x"},
        "normalization_status": "deterministic",
    })


def test_validate_rejects_unknown_rule_kind():
    with pytest.raises(ValueError, match="rule_kind"):
        validate_rule_payload({
            "rule_kind": "bogus",
            "subject_entity": "Loan",
            "predicate": "gt",
            "object_value": 0,
            "expression": "x",
            "evidence_span": {"file": "f", "start_line": 1, "end_line": 1, "snippet": ""},
            "normalization_status": "deterministic",
        })


def test_validate_rejects_unknown_predicate():
    with pytest.raises(ValueError, match="predicate"):
        validate_rule_payload({
            "rule_kind": "validation",
            "subject_entity": "Loan",
            "predicate": "wat",
            "object_value": 0,
            "expression": "x",
            "evidence_span": {"file": "f", "start_line": 1, "end_line": 1, "snippet": ""},
            "normalization_status": "deterministic",
        })


def test_merge_key_uses_payload_not_label():
    a = {"rule_kind": "validation", "subject_entity": "Loan",
         "subject_attribute": "amount", "predicate": "gt", "object_value": 0,
         "condition": None}
    b = {"rule_kind": "validation", "subject_entity": "Loan",
         "subject_attribute": "amount", "predicate": "gt", "object_value": 0,
         "condition": None}
    assert merge_key(a) == merge_key(b)


def test_merge_key_differs_when_predicate_differs():
    a = {"rule_kind": "validation", "subject_entity": "Loan",
         "subject_attribute": "amount", "predicate": "gt", "object_value": 0,
         "condition": None}
    b = {"rule_kind": "validation", "subject_entity": "Loan",
         "subject_attribute": "amount", "predicate": "gte", "object_value": 0,
         "condition": None}
    assert merge_key(a) != merge_key(b)


def test_validate_rejects_evidence_span_missing_end_line():
    with pytest.raises(ValueError, match="evidence_span"):
        validate_rule_payload({
            "rule_kind": "validation",
            "subject_entity": "Loan",
            "subject_attribute": "amount",
            "predicate": "gt",
            "object_value": 0,
            "expression": "amount > 0",
            "evidence_span": {"file": "loans.py", "start_line": 1},  # missing end_line + snippet
            "normalization_status": "deterministic",
        })


def test_canonical_rule_label_matches_for_equivalent_payloads():
    a = {"subject_entity": "loan", "subject_attribute": "amount", "predicate": "gt", "object_value": 0}
    b = {"subject_entity": "loan", "subject_attribute": "amount", "predicate": "gt", "object_value": 0}
    assert canonical_rule_label(a) == canonical_rule_label(b) == "loan.amount gt 0"


def test_canonical_rule_label_without_subject_entity():
    p = {"subject_entity": None, "subject_attribute": "amount", "predicate": "gt", "object_value": 0}
    assert canonical_rule_label(p) == "amount gt 0"


def test_normalize_subject_preserves_words_with_trailing_s_that_arent_plural():
    """inflect.singular_noun is naive: it strips trailing 's' from
    words like 'address' (-> 'addres') or 'analysis' (-> 'analysi').
    The round-trip guard rejects these false-positive singularizations
    so the merge key stays stable."""
    from ontozense.core.ingest.source_d.rule_payload import _normalize_subject

    # Each pair: input -> expected normalized form.
    # These all end in 's' but are NOT plurals; the original lowercase
    # form must be preserved.
    assert _normalize_subject("address") == "address"
    assert _normalize_subject("Address") == "address"
    assert _normalize_subject("analysis") == "analysis"
    assert _normalize_subject("status") == "status"
    assert _normalize_subject("customer_status") == "customer_status"


def test_normalize_subject_singularizes_real_plurals_safely():
    """Real plurals still singularize correctly through the
    round-trip guard."""
    from ontozense.core.ingest.source_d.rule_payload import _normalize_subject

    assert _normalize_subject("loans") == "loan"
    assert _normalize_subject("customers") == "customer"
    assert _normalize_subject("addresses") == "address"
    # Compound names with a trailing real plural still singularize:
    assert _normalize_subject("customer_statuses") == "customer_status"


def test_address_and_addresses_fuse_via_merge_key():
    """The false-positive singularization bug would have made
    'address' and 'addresses' produce different merge_keys. With the
    round-trip guard, they normalize to the same form and fuse."""
    from ontozense.core.ingest.source_d.rule_payload import merge_key

    a = {
        "rule_kind": "validation", "subject_entity": "Address",
        "subject_attribute": "city", "predicate": "required",
        "object_value": True, "condition": None,
    }
    b = {
        "rule_kind": "validation", "subject_entity": "addresses",
        "subject_attribute": "city", "predicate": "required",
        "object_value": True, "condition": None,
    }
    assert merge_key(a) == merge_key(b), (
        f"Address (PEP 8) and addresses (SQL plural) must fuse; "
        f"got {merge_key(a)} vs {merge_key(b)}"
    )


def test_compound_status_names_fuse_singular_and_plural():
    """customer_status (SQL) and customer_statuses (SQL plural) must
    produce identical merge_keys. Without the round-trip guard, the
    singular form was being mangled to 'customer_statu'."""
    from ontozense.core.ingest.source_d.rule_payload import merge_key

    singular = {
        "rule_kind": "validation", "subject_entity": "customer_status",
        "subject_attribute": "state", "predicate": "required",
        "object_value": True, "condition": None,
    }
    plural = {
        "rule_kind": "validation", "subject_entity": "customer_statuses",
        "subject_attribute": "state", "predicate": "required",
        "object_value": True, "condition": None,
    }
    assert merge_key(singular) == merge_key(plural)
