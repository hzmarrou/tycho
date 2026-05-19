import pytest

from ontozense.core.ingest.source_d.rule_payload import (
    ALLOWED_PREDICATES,
    RuleKind,
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
