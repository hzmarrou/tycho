"""Anchor stage — resolve subject_entity for rule facts; suppress unanchored ones.

Anchoring order (spec §10.1):
  1. enclosing class/entity context (already set by extractor)
  2. explicit field/attribute context (lookup via AttributeFact in same module)
  3. local symbol context with dependency-only fallback (left for fusion)
  4. otherwise suppress to audit

A RuleFact whose subject_entity AND subject_attribute are both None
has no anchor surface at all — fusion can't resolve it via Source
A/B/C either, so it's suppressed here.
"""
from __future__ import annotations

from collections.abc import Iterable

from .ir import AttributeFact, RuleFact


def anchor_facts(facts: Iterable[object]) -> tuple[list[object], list[tuple[object, str]]]:
    """Resolve or suppress RuleFacts. Returns (anchored, suppressed) where
    suppressed is a list of (rule, reason) tuples for the audit block.

    Note: single-match RuleFacts are mutated in-place — ``subject_entity``
    is set on the original ``RuleFact`` object. The IR is mutable by
    design (Task 5); callers that hold references to these facts will
    see the resolved subject_entity after this function returns.
    """
    facts = list(facts)
    attr_index: dict[str, list[str]] = {}
    for f in facts:
        if isinstance(f, AttributeFact) and f.subject_entity:
            attr_index.setdefault(f.name, []).append(f.subject_entity)

    anchored: list[object] = []
    suppressed: list[tuple[object, str]] = []
    for f in facts:
        if not isinstance(f, RuleFact):
            anchored.append(f)
            continue
        if f.subject_entity is not None:
            anchored.append(f)
            continue
        if f.subject_attribute is None:
            suppressed.append((f, "unanchored:no_subject_entity_and_no_subject_attribute"))
            continue
        candidates = attr_index.get(f.subject_attribute, [])
        if len(candidates) == 1:
            f.subject_entity = candidates[0]
            anchored.append(f)
        elif len(candidates) > 1:
            # Ambiguous — leave unresolved for fusion-time disambiguation.
            anchored.append(f)
        else:
            # No matching AttributeFact in this module; fusion may anchor
            # via Source A/B/C cross-source attestation.
            anchored.append(f)
    return anchored, suppressed
