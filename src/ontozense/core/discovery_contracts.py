"""Typed contracts for the discovery / profile-induction workflow.

These dataclasses are the on-disk schema for ``candidate-graph.json``,
``candidate-provenance.json``, and ``induction_report.json`` —
the artifacts the new ``ontozense discover`` / ``ontozense induce-profile``
commands emit.

Design notes:

- All dataclasses are frozen so callers can't accidentally mutate a
  candidate after scoring. Mutation goes through ``dataclasses.replace``.
- Each dataclass owns its own JSON round-trip via ``to_dict`` /
  ``from_dict``. Nested ``EvidenceEntry`` lists are walked explicitly
  rather than relying on ``asdict`` reconstruction.
- The contracts mirror the design in ``docs/PROFILE_INDUCTION_ARCHITECTURE.md``
  §"Data Model". Field defaults match the architecture spec.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class EvidenceEntry:
    """One piece of evidence linking a candidate to a specific source location.

    Used in ``CandidateConcept.provenance`` and
    ``CandidateRelationship.provenance``. The ``anchor`` field is a
    dict rather than a typed ``FieldAnchor`` so discovery doesn't take
    a hard dependency on the Phase 6 anchor module — the existing
    Phase 6 FieldAnchor can be serialised into this dict shape if
    needed.
    """
    source_type: str         # "A", "B", "C", "D"
    source_artifact: str     # file path or identifier
    anchor: dict[str, Any] | None = None
    snippet: str = ""
    raw_label: str = ""
    raw_type: str = ""
    confidence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> EvidenceEntry:
        return cls(**raw)


@dataclass(frozen=True)
class CandidateConcept:
    """One candidate concept in the discovery graph.

    Holds the merged view across sources A/B/C/D for a single
    normalised label, plus the relevance signals the scoring stage
    fills in. The classification (``core_business`` / ``supporting_technical``
    / ``noise`` / ``unknown``) is set by the relevance stage; until
    then it stays ``"unknown"``.
    """
    candidate_id: str
    label: str
    normalized_label: str
    suggested_entity_type: str
    classification: str
    summary_definition: str
    source_presence: dict[str, bool]
    source_counts: dict[str, int]
    schema_links: list[dict[str, Any]] = field(default_factory=list)
    code_links: list[dict[str, Any]] = field(default_factory=list)
    governance_links: list[dict[str, Any]] = field(default_factory=list)
    authoritative_evidence_count: int = 0
    graph_degree: int = 0
    relevance_score: float = 0.0
    relevance_breakdown: dict[str, float] = field(default_factory=dict)
    provenance: list[EvidenceEntry] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)
    status: str = "candidate"

    def to_dict(self) -> dict[str, Any]:
        raw = asdict(self)
        # asdict() turns EvidenceEntry into dicts already, but be
        # explicit so any future non-trivial field types stay correct.
        raw["provenance"] = [p.to_dict() for p in self.provenance]
        return raw

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> CandidateConcept:
        data = dict(raw)
        data["provenance"] = [
            EvidenceEntry.from_dict(p) for p in data.get("provenance", [])
        ]
        return cls(**data)


@dataclass(frozen=True)
class CandidateRelationship:
    """One candidate relationship in the discovery graph.

    Subject / object reference candidate IDs (not labels) so the
    relationship survives later alias resolution and merging. The
    ``canonical_predicate`` field is filled in once the predicate
    has been normalised against the profile's ``canonical_verbs`` —
    until then it's the empty string.
    """
    subject_candidate_id: str
    predicate: str
    object_candidate_id: str
    canonical_predicate: str = ""
    source_presence: dict[str, bool] = field(default_factory=dict)
    relevance_score: float = 0.0
    provenance: list[EvidenceEntry] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        raw = asdict(self)
        raw["provenance"] = [p.to_dict() for p in self.provenance]
        return raw

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> CandidateRelationship:
        data = dict(raw)
        data["provenance"] = [
            EvidenceEntry.from_dict(p) for p in data.get("provenance", [])
        ]
        return cls(**data)


@dataclass(frozen=True)
class InductionReport:
    """The human-readable audit trail for a single ``induce-profile`` run.

    Contains the top selected candidates, rejected examples,
    suggested predicates, suggested required fields per type, and
    free-form ``review_notes`` for things the induction stage
    surfaces for the reviewer but can't decide automatically.

    ``scoring_thresholds`` (Phase 1 contract amendment added during
    Task 4) records which classification cut-offs the induction
    used — paired with ``scoring_weights`` it lets a reviewer
    reproduce the band assignments exactly. Defaulted to an empty
    dict so legacy reports (emitted before this field existed) load
    cleanly via :meth:`from_dict`.
    """
    domain_name: str
    generated_at: str
    candidate_count: int
    selected_core_count: int
    selected_supporting_count: int
    rejected_count: int
    scoring_weights: dict[str, float]
    top_candidates: list[dict[str, Any]]
    rejected_examples: list[dict[str, Any]]
    predicate_suggestions: list[dict[str, Any]]
    required_field_suggestions: dict[str, list[str]]
    review_notes: list[str]
    scoring_thresholds: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> InductionReport:
        return cls(**raw)
