"""Base types for the per-source ingestion pipeline.

Each Source A/B/C/D has its own ingester that turns raw source-native
artifacts (LLM JSON, governance JSON, SQL DDL, Python AST) into a
stream of :class:`IntermediateCandidate` records. The orchestrator
in :mod:`candidate_graph` feeds these into the existing ``_upsert``
merge primitive, which preserves the architecture's merge-key
priority (id > normalised label > alias > new).

See ``docs/superpowers/specs/2026-05-17-source-cd-seeders-design.md``
for the full design rationale.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable


class ArtifactKind(Enum):
    """Closed vocabulary classifying a candidate's nature.

    Every candidate is exactly one kind. See §5 of the design spec
    for the per-source mapping table.
    """
    ENTITY = "entity"
    ATTRIBUTE = "attribute"
    RELATIONSHIP = "relationship"
    VOCABULARY = "vocabulary"
    BEHAVIOR = "behavior"
    RULE = "rule"


class Strength(Enum):
    """Three-tier confidence band for a candidate.

    Independent of :class:`ArtifactKind`. Recorded in v1.1 but not
    yet consumed by downstream stages (profile induction, fusion).
    See design spec §13.1 for the v1.2 consumption plan.
    """
    STRONG = "strong"
    MEDIUM = "medium"
    WEAK = "weak"


@dataclass(frozen=True)
class IntermediateCandidate:
    """One candidate emitted by a per-source ingester, before merge.

    The orchestrator hands these to ``_upsert`` to merge into
    :class:`~ontozense.core.discovery_contracts.CandidateConcept`
    records. Suppressed candidates (``suppressed=True``) are emitted
    too; they are written to the ``audit`` block of
    ``candidate-graph.json`` but excluded from the merged concept
    list by default.
    """
    label: str
    definition: str
    source_type: str            # "A" | "B" | "C" | "D"
    source_artifact: str        # file path + locator
    raw_type: str               # source-native type hint
    eid: str                    # optional profile-mode id (default "")
    artifact_kind: ArtifactKind
    strength: Strength
    promotion_reason: str
    suppression_reason: str | None = None
    suppressed: bool = False


class IngestionPolicy(ABC):
    """Abstract base for per-source ingesters.

    Each ingester implements the extract → classify → filter →
    promote pipeline as a single ``ingest()`` entry point that
    yields a stream of :class:`IntermediateCandidate`. The
    sub-pipeline stages are kept as named methods on each concrete
    subclass for testability — they aren't enforced by the ABC so
    subclasses can fold them differently when source-native shapes
    don't fit the four-stage model cleanly.
    """

    @abstractmethod
    def ingest(self, raw_input: Any) -> Iterable[IntermediateCandidate]:
        """Yield candidates extracted from ``raw_input``.

        ``raw_input`` shape is source-specific (parsed JSON for A/B,
        file paths or sqlglot AST for C, package paths for D).
        Implementations are responsible for their own filtering and
        promotion-reason / suppression-reason recording.
        """
        ...
