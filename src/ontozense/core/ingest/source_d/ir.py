"""Shared intermediate representation for Source D extractor families.

All three families (model, pipeline, procedural) lift their findings into
these dataclasses before anchoring and emission. The IR is internal to
Source D; downstream consumers see only IntermediateCandidate.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class EvidenceSpan:
    file: str
    start_line: int
    end_line: int
    snippet: str


@dataclass
class EntityFact:
    name: str
    evidence_span: EvidenceSpan
    extractor_family: str
    docstring: str | None = None
    bases: list[str] = field(default_factory=list)
    raw_type: str = "class"


@dataclass
class AttributeFact:
    name: str
    subject_entity: str | None
    evidence_span: EvidenceSpan
    extractor_family: str
    annotation: str | None = None
    has_default: bool = False


@dataclass
class VocabularyFact:
    name: str
    members: list[Any]
    evidence_span: EvidenceSpan
    extractor_family: str


@dataclass
class BehaviorFact:
    name: str
    subject_entity: str | None
    evidence_span: EvidenceSpan
    extractor_family: str


@dataclass
class RuleFact:
    rule_kind: str
    subject_entity: str | None
    subject_attribute: str | None
    predicate: str
    object_value: Any
    expression: str
    evidence_span: EvidenceSpan
    code_context: str
    confidence: float
    extractor_family: str
    condition: Any = None
    depends_on: list[str] = field(default_factory=list)

    def to_payload(self) -> dict:
        return {
            "rule_kind": self.rule_kind,
            "subject_entity": self.subject_entity,
            "subject_attribute": self.subject_attribute,
            "predicate": self.predicate,
            "object_value": self.object_value,
            "condition": self.condition,
            "depends_on": list(self.depends_on),
            "expression": self.expression,
            "evidence_span": {
                "file": self.evidence_span.file,
                "start_line": self.evidence_span.start_line,
                "end_line": self.evidence_span.end_line,
                "snippet": self.evidence_span.snippet,
            },
            "code_context": self.code_context,
            "confidence": self.confidence,
            "extractor_family": self.extractor_family,
            "normalization_status": "deterministic",
        }
