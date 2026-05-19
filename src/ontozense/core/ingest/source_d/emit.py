"""Emit stage — IR facts -> IntermediateCandidate."""
from __future__ import annotations

from collections.abc import Iterable

from ontozense.core.ingest.base import ArtifactKind, IntermediateCandidate, Strength

from .ir import (
    AttributeFact,
    BehaviorFact,
    EntityFact,
    RuleFact,
    VocabularyFact,
)
from .rule_payload import canonical_rule_label, validate_rule_payload


def _rule_strength(confidence: float) -> Strength:
    if confidence >= 0.85:
        return Strength.STRONG
    if confidence >= 0.6:
        return Strength.MEDIUM
    return Strength.WEAK


def _artifact(fact) -> str:
    es = fact.evidence_span
    return f"{es.file}:L{es.start_line}"


def _emit_entity(f: EntityFact) -> IntermediateCandidate:
    return IntermediateCandidate(
        label=f.name,
        definition=f.docstring or "",
        source_type="D",
        source_artifact=_artifact(f),
        raw_type=f.raw_type,
        eid="",
        artifact_kind=ArtifactKind.ENTITY,
        strength=Strength.STRONG,
        promotion_reason=f"{f.extractor_family}: class/dataclass/model",
        suppression_reason=f.suppression_reason,
        suppressed=f.suppressed,
    )


def _emit_attribute(f: AttributeFact) -> IntermediateCandidate:
    label = f"{f.subject_entity}.{f.name}" if f.subject_entity else f.name
    return IntermediateCandidate(
        label=label,
        definition=f.annotation or "",
        source_type="D",
        source_artifact=_artifact(f),
        raw_type="attribute",
        eid="",
        artifact_kind=ArtifactKind.ATTRIBUTE,
        strength=Strength.STRONG,
        promotion_reason=f"{f.extractor_family}: typed field or column",
    )


def _emit_vocabulary(f: VocabularyFact) -> IntermediateCandidate:
    return IntermediateCandidate(
        label=f.name,
        definition=", ".join(str(m) for m in f.members),
        source_type="D",
        source_artifact=_artifact(f),
        raw_type="enum",
        eid="",
        artifact_kind=ArtifactKind.VOCABULARY,
        strength=Strength.MEDIUM,
        promotion_reason=f"{f.extractor_family}: enum class",
    )


def _emit_behavior(f: BehaviorFact) -> IntermediateCandidate:
    label = f"{f.subject_entity}.{f.name}" if f.subject_entity else f.name
    return IntermediateCandidate(
        label=label,
        definition="",
        source_type="D",
        source_artifact=_artifact(f),
        raw_type="method",
        eid="",
        artifact_kind=ArtifactKind.BEHAVIOR,
        strength=Strength.WEAK,
        promotion_reason=f"{f.extractor_family}: non-private method",
    )


def _emit_rule(f: RuleFact, *, suppressed: bool = False, reason: str | None = None) -> IntermediateCandidate:
    payload = f.to_payload()
    if not suppressed:
        validate_rule_payload(payload)
    # Canonical label is the display surface for the rule candidate.
    # Fusion identity is the structured merge_key(payload), routed
    # through _CandidateIndex.by_rule_key (added in Task 1, Step 6).
    # See planning decision #5.
    label = canonical_rule_label(payload)
    return IntermediateCandidate(
        label=label,
        definition=payload["expression"],
        source_type="D",
        source_artifact=_artifact(f),
        raw_type=f"rule:{payload['rule_kind']}",
        eid="",
        artifact_kind=ArtifactKind.RULE,
        strength=_rule_strength(f.confidence),
        promotion_reason=f"{f.extractor_family}: deterministic rule extraction",
        suppression_reason=reason,
        suppressed=suppressed,
        rule_payload=payload,
    )


def emit_candidates(
    facts: Iterable[object],
    suppressed: Iterable[tuple[RuleFact, str]],
) -> Iterable[IntermediateCandidate]:
    for f in facts:
        if isinstance(f, EntityFact):
            yield _emit_entity(f)
        elif isinstance(f, AttributeFact):
            yield _emit_attribute(f)
        elif isinstance(f, VocabularyFact):
            yield _emit_vocabulary(f)
        elif isinstance(f, BehaviorFact):
            yield _emit_behavior(f)
        elif isinstance(f, RuleFact):
            yield _emit_rule(f)
        else:
            raise TypeError(
                f"emit_candidates: unknown IR fact type {type(f).__name__!r}. "
                "Did a new IR class get added without updating the emit dispatch?"
            )
    for rule, reason in suppressed:
        yield _emit_rule(rule, suppressed=True, reason=reason)
