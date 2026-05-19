"""Shared rule_payload contract.

This contract is intentionally cross-source: Source C and Source D both
populate it for explicit rule-shaped evidence so that structurally
equivalent rules merge through identity, not label text.
"""
from __future__ import annotations

from enum import Enum


class RuleKind(str, Enum):
    VALIDATION = "validation"
    DERIVATION = "derivation"
    DEFAULTING = "defaulting"
    ELIGIBILITY = "eligibility"
    TRANSITION = "transition"
    CALCULATION = "calculation"
    DEPENDENCY = "dependency"


ALLOWED_PREDICATES = frozenset({
    "gt", "gte", "lt", "lte", "eq", "neq",
    "required",
    "in_set", "not_in_set",
    "range",
    "derived_from",
    "transitions_to",
    "default_to",
    "depends_on",
})

ALLOWED_NORMALIZATION_STATUS = frozenset({"deterministic", "llm_rephrased"})

_RULE_KIND_VALUES: frozenset[str] = frozenset(k.value for k in RuleKind)

REQUIRED_FIELDS = (
    "rule_kind", "subject_entity", "predicate", "object_value",
    "expression", "evidence_span", "normalization_status",
)


def validate_rule_payload(p: dict) -> None:
    """Raise ValueError if p does not satisfy the v1.2 rule_payload contract."""
    for f in REQUIRED_FIELDS:
        if f not in p:
            raise ValueError(f"rule_payload missing required field: {f}")
    if p["rule_kind"] not in _RULE_KIND_VALUES:
        raise ValueError(f"rule_kind {p['rule_kind']!r} not in closed enum")
    if p["predicate"] not in ALLOWED_PREDICATES:
        raise ValueError(f"predicate {p['predicate']!r} not allowed")
    if p["normalization_status"] not in ALLOWED_NORMALIZATION_STATUS:
        raise ValueError(f"normalization_status {p['normalization_status']!r} not allowed")
    ev = p["evidence_span"]
    if not isinstance(ev, dict) or not {"file", "start_line", "end_line", "snippet"} <= ev.keys():
        raise ValueError("evidence_span must be {file, start_line, end_line, snippet}")


def merge_key(p: dict) -> tuple:
    """Identity tuple for rule fusion. Labels are display-only and not included.

    Per spec §11.1: matching considers rule_kind, subject_entity,
    subject_attribute, predicate, normalized object_value, normalized condition.
    """
    return (
        p.get("rule_kind"),
        p.get("subject_entity"),
        p.get("subject_attribute"),
        p.get("predicate"),
        _normalize_value(p.get("object_value")),
        _normalize_value(p.get("condition")),
    )


def _normalize_value(v):
    if isinstance(v, list):
        return tuple(sorted(_normalize_value(x) for x in v))
    if isinstance(v, dict):
        return tuple(sorted((k, _normalize_value(val)) for k, val in v.items()))
    return v


def canonical_rule_label(payload: dict) -> str:
    """Deterministic surface label derived from rule_payload.

    Both Source C and Source D use this so rule candidates carry a
    consistent display label. The label is display-only — fusion
    identity is the structured ``merge_key`` (spec §11.1).

    Notes:
    - ``object_value=None`` renders as the string ``"None"`` (Python's
      default). Two payloads that produce the same label-string but
      have different structured ``object_value`` will NOT merge,
      because ``merge_key`` preserves the typed value. Callers who
      need a distinct sentinel for null/absent should normalize
      ``object_value`` before display.
    - ``subject_entity`` of ``None`` or ``""`` is treated identically:
      the entity prefix is omitted.
    """
    subject_entity = payload.get("subject_entity") or ""
    subject_attribute = payload.get("subject_attribute") or ""
    predicate = payload.get("predicate") or ""
    object_value = payload.get("object_value")
    head = f"{subject_entity}.{subject_attribute}" if subject_entity else subject_attribute
    return f"{head} {predicate} {object_value}".strip()
