"""Optional LLM normalization — rewrites RULE candidate labels only.

Per spec §12, the LLM must never:
- invent rules
- override deterministic evidence
- change merge identity

This module only touches IntermediateCandidate.label for RULE candidates
and toggles rule_payload["normalization_status"] to "llm_rephrased". The
structured merge_key (rule_kind, subject_entity, subject_attribute,
predicate, object_value, condition) is preserved exactly, so fusion
identity is unchanged whether the LLM is on or off (AC9).
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace
from typing import Protocol

from ontozense.core.ingest.base import ArtifactKind, IntermediateCandidate


class LLMRephraser(Protocol):
    def rephrase(self, label: str, payload: dict) -> str: ...


def normalize_labels(
    candidates: Iterable[IntermediateCandidate],
    llm: LLMRephraser | None,
) -> Iterable[IntermediateCandidate]:
    """Rewrite RULE candidate labels using an LLM rephraser.

    Behavior:
    - llm is None: pass-through, no mutation.
    - llm provided: each RULE candidate's label is replaced with
      ``llm.rephrase(label, payload)`` and its rule_payload gets
      ``normalization_status = "llm_rephrased"``. Non-RULE candidates
      pass through untouched.
    """
    if llm is None:
        yield from candidates
        return
    for c in candidates:
        if c.artifact_kind != ArtifactKind.RULE or c.rule_payload is None:
            yield c
            continue
        new_label = llm.rephrase(c.label, c.rule_payload)
        new_payload = dict(c.rule_payload)
        new_payload["normalization_status"] = "llm_rephrased"
        yield replace(c, label=new_label, rule_payload=new_payload)
