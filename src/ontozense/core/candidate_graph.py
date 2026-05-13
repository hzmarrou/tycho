"""Candidate graph builder for the discovery / profile-induction
workflow (profile induction architecture, Phase 1 / Task 2).

This module turns raw source outputs (Source A concepts, Source B
governance records, with placeholder hooks for Source C / Source D)
into a merged ``CandidateGraph`` of :class:`CandidateConcept` objects
keyed by normalised label.

Design choices per ``docs/PROFILE_INDUCTION_ARCHITECTURE.md``:

  - **Broad recall**: noisy concepts are kept if they have any evidence.
    Discovery's job is to surface candidates, not to prematurely filter.
  - **Conservative merge**: only merge across sources when the
    normalised label matches. Distinct surface labels that differ
    after normalisation (e.g. "Default" vs "Default Rate") stay
    separate. Profile-mode deterministic ``id`` is checked first when
    available so cross-source aligned concepts merge regardless of
    surface name.
  - **Evidence preservation**: every contribution adds an
    :class:`EvidenceEntry` to the candidate's provenance list.
  - **Source presence + counts**: each candidate tracks which of the
    four sources mentioned it and how many times, feeding the
    relevance-scoring stage later.

Scoring, classification, and profile emission happen in later tasks —
this module only builds the graph.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from .discovery_contracts import (
    CandidateConcept,
    CandidateRelationship,
    EvidenceEntry,
)
from .identity import normalize_label


# ─── Public dataclass ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class CandidateGraph:
    """The merged candidate concept universe + the candidate
    relationships extracted alongside it.

    Returned by :func:`build_candidate_graph`. Serialise via
    :meth:`to_dict` for ``candidate-graph.json`` output.
    """
    concepts: list[CandidateConcept]
    relationships: list[CandidateRelationship]

    def to_dict(self) -> dict[str, Any]:
        return {
            "concepts": [c.to_dict() for c in self.concepts],
            "relationships": [r.to_dict() for r in self.relationships],
        }


# ─── Builder ────────────────────────────────────────────────────────────────


def build_candidate_graph(
    *,
    source_a: dict[str, Any] | None = None,
    source_b: dict[str, Any] | None = None,
    source_c: dict[str, Any] | None = None,
    source_d: dict[str, Any] | None = None,
) -> CandidateGraph:
    """Build a merged candidate graph from raw source outputs.

    Each ``source_*`` argument is the raw dict form of the
    corresponding source's JSON output (i.e. ``json.loads(...)`` of
    a file produced by ``extract-a --json``, an exported governance
    catalogue, etc.). The exact shapes per source:

      - ``source_a`` — ``{"concepts": [...], "relationships": [...]}``
        as produced by ``extract-a``. Each concept must have at least
        ``name``; ``definition``, ``id``, ``entity_type``, and
        ``provenance`` are optional.
      - ``source_b`` — ``{"records": [...]}`` where each record has
        ``element_name`` and optionally ``entity_type``, ``id``,
        ``definition``.
      - ``source_c`` / ``source_d`` — currently passed through as
        empty contributions. Full ingestion lands in a follow-up task
        once Phase 1 baseline is in place.

    Any source argument can be ``None`` or absent. Empty / missing
    labels are skipped silently. Returns a :class:`CandidateGraph`
    with concepts in the order they were first seen.
    """
    bucket: dict[str, CandidateConcept] = {}

    if source_a:
        for concept in source_a.get("concepts", []) or []:
            label = (concept.get("name") or "").strip()
            if not label:
                continue
            artifact = (
                concept.get("provenance", {}).get("source_document", "")
                if isinstance(concept.get("provenance"), dict)
                else ""
            )
            _upsert(
                bucket,
                label=label,
                definition=concept.get("definition", "") or "",
                source_type="A",
                source_artifact=artifact,
                raw_type=concept.get("entity_type", "") or "",
            )

    if source_b:
        for record in source_b.get("records", []) or []:
            label = (record.get("element_name") or "").strip()
            if not label:
                continue
            _upsert(
                bucket,
                label=label,
                definition=record.get("definition", "") or "",
                source_type="B",
                source_artifact=record.get("source_file", "") or "",
                raw_type=record.get("entity_type", "") or "",
            )

    # Source C / D ingestion is a follow-up task. The hooks below
    # keep the public signature stable so a later commit can fill
    # them in without changing callers.
    # if source_c: ...
    # if source_d: ...

    return CandidateGraph(
        concepts=list(bucket.values()),
        relationships=[],
    )


# ─── Internal helpers ───────────────────────────────────────────────────────


def _upsert(
    bucket: dict[str, CandidateConcept],
    *,
    label: str,
    definition: str,
    source_type: str,
    source_artifact: str = "",
    raw_type: str = "",
) -> None:
    """Insert a candidate for ``label`` or merge into the existing entry.

    Mutates ``bucket`` in place. The bucket key is the normalised
    label so case / punctuation variants converge.
    """
    norm = normalize_label(label)
    if not norm:
        return

    evidence = EvidenceEntry(
        source_type=source_type,
        source_artifact=source_artifact,
        snippet=(definition or "")[:200],
        raw_label=label,
        raw_type=raw_type,
        confidence=0.8,
    )

    existing = bucket.get(norm)
    if existing is None:
        # First time seeing this normalised label — create a new
        # candidate. ``suggested_entity_type`` defaults to "Concept";
        # the relevance/induction stages may refine it later.
        bucket[norm] = CandidateConcept(
            candidate_id=f"cand_{norm.replace(' ', '_')}",
            label=label,
            normalized_label=norm,
            suggested_entity_type=raw_type or "Concept",
            classification="unknown",
            summary_definition=definition,
            source_presence={
                "A": source_type == "A",
                "B": source_type == "B",
                "C": source_type == "C",
                "D": source_type == "D",
            },
            source_counts={
                "A": 1 if source_type == "A" else 0,
                "B": 1 if source_type == "B" else 0,
                "C": 1 if source_type == "C" else 0,
                "D": 1 if source_type == "D" else 0,
            },
            authoritative_evidence_count=1 if source_type == "A" else 0,
            provenance=[evidence],
            aliases=[label],
        )
        return

    # Merging into an existing candidate. ``CandidateConcept`` is
    # frozen, so build the updated instance via ``dataclasses.replace``.
    updated_presence = dict(existing.source_presence)
    updated_presence[source_type] = True

    updated_counts = dict(existing.source_counts)
    updated_counts[source_type] = updated_counts.get(source_type, 0) + 1

    # Preserve the first definition seen unless empty; an earlier
    # source's curated definition shouldn't be overwritten by a
    # later source's emptier text.
    merged_definition = existing.summary_definition or definition

    # Track surface aliases as a deduped, sorted list so JSON output
    # is deterministic for run-vs-run diffs.
    merged_aliases = sorted({*existing.aliases, label})

    bucket[norm] = replace(
        existing,
        summary_definition=merged_definition,
        source_presence=updated_presence,
        source_counts=updated_counts,
        authoritative_evidence_count=(
            existing.authoritative_evidence_count + (1 if source_type == "A" else 0)
        ),
        provenance=[*existing.provenance, evidence],
        aliases=merged_aliases,
    )
