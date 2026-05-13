"""Candidate graph builder for the discovery / profile-induction
workflow (profile induction architecture, Phase 1 / Task 2).

This module turns raw source outputs (Source A concepts +
relationships, Source B governance records, with placeholder hooks
for Source C / Source D) into a merged :class:`CandidateGraph` of
:class:`CandidateConcept` and :class:`CandidateRelationship` objects.

## Merge contract (per ``docs/PROFILE_INDUCTION_ARCHITECTURE.md`` §"Candidate merge rules")

Merge key priority is enforced explicitly:

  1. **Existing profile-mode ``id``** — if the incoming concept has
     an ``id`` and that ``id`` already exists in the bucket, merge.
  2. **Normalised canonical label** — if no id-match but the
     normalised label matches an existing entry that *also lacks* an
     id (or has the *same* id), merge. When an incoming concept
     carries an id and the existing entry doesn't, the existing is
     promoted (claims the id).
  3. **Source-specific fallback** — concepts with no id or matching
     entry fall through to plain normalised-label keying. (Aliases
     are tracked in ``CandidateConcept.aliases`` and surface in the
     dedup logic above.)

**Ambiguity preservation**: when two concepts share a normalised
label but carry *different* profile-mode ids, they stay as separate
candidates. The architecture is explicit that ambiguous cases must
not be silently collapsed.

## Relationship ingestion (per architecture §"Candidate graph builder")

Source A relationships (subject-predicate-object triples) are
mapped to :class:`CandidateRelationship` objects whose endpoints
reference candidate IDs (not raw labels) — so the relationship
survives later alias resolution. Endpoints that don't resolve to
any existing candidate are skipped (Source A occasionally produces
relationships that reference entities it didn't extract as concepts;
that's drift the lint stage catches downstream).

``graph_degree`` is the distinct-neighbour count for each candidate,
computed from the resolved relationships. It feeds the relevance-
scoring stage in Phase 2.

## Out of scope for Phase 1

Scoring, classification, profile emission. The relevance stage in
Phase 2 reads :class:`CandidateConcept` and produces a scored
version; this module only builds the graph.
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


# ─── Internal index ─────────────────────────────────────────────────────────


class _CandidateIndex:
    """Mutable working state for the build process.

    Keeps three parallel maps so merge lookup is O(1):

      - ``by_key`` — the canonical store, keyed by an opaque internal
        key (``"id:<id>"`` or ``"name:<norm>"`` or ``"name:<norm>#id:<id>"``
        for collision survivors).
      - ``by_id`` — id → key, used for the first-priority lookup.
      - ``by_name`` — normalised label → key, used for the
        second-priority lookup.

    All three are kept consistent on each mutation.
    """

    def __init__(self) -> None:
        self.by_key: dict[str, CandidateConcept] = {}
        self.by_id: dict[str, str] = {}
        self.by_name: dict[str, str] = {}

    def values(self) -> list[CandidateConcept]:
        return list(self.by_key.values())


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
    catalogue, etc.). Shapes:

      - ``source_a`` — ``{"concepts": [...], "relationships": [...]}``
        as produced by ``extract-a``. Concept must have ``name``;
        ``id``, ``entity_type``, ``definition``, ``provenance`` are
        optional. Relationship is ``{subject, predicate, object,
        confidence?, provenance?}``.
      - ``source_b`` — ``{"records": [...]}`` where each record has
        ``element_name`` and optionally ``entity_type``, ``id``,
        ``definition``.
      - ``source_c`` / ``source_d`` — currently passed through as
        empty contributions. Full ingestion lands in a follow-up.

    Any source argument can be ``None`` or absent. Empty / missing
    labels are skipped silently.
    """
    index = _CandidateIndex()

    # ─── Concept ingestion ────────────────────────────────────────────────
    if source_a:
        for concept in source_a.get("concepts", []) or []:
            label = (concept.get("name") or "").strip()
            if not label:
                continue
            artifact = ""
            prov_obj = concept.get("provenance")
            if isinstance(prov_obj, dict):
                artifact = prov_obj.get("source_document", "") or ""
            _upsert(
                index,
                label=label,
                definition=concept.get("definition", "") or "",
                source_type="A",
                source_artifact=artifact,
                raw_type=concept.get("entity_type", "") or "",
                eid=concept.get("id", "") or "",
            )

    if source_b:
        for record in source_b.get("records", []) or []:
            label = (record.get("element_name") or "").strip()
            if not label:
                continue
            _upsert(
                index,
                label=label,
                definition=record.get("definition", "") or "",
                source_type="B",
                source_artifact=record.get("source_file", "") or "",
                raw_type=record.get("entity_type", "") or "",
                eid=record.get("id", "") or "",
            )

    # Source C / D ingestion is a follow-up task. The hooks below
    # keep the public signature stable so a later commit can fill
    # them in without changing callers.
    # if source_c: ...
    # if source_d: ...

    # ─── Relationship ingestion ───────────────────────────────────────────
    relationships: list[CandidateRelationship] = []
    degree_neighbours: dict[str, set[str]] = {}

    if source_a:
        for rel in source_a.get("relationships", []) or []:
            subj_label = (rel.get("subject") or "").strip()
            obj_label = (rel.get("object") or "").strip()
            predicate = (rel.get("predicate") or "").strip()
            if not (subj_label and obj_label and predicate):
                continue
            subj_id = _resolve_endpoint_to_candidate_id(index, subj_label)
            obj_id = _resolve_endpoint_to_candidate_id(index, obj_label)
            if subj_id is None or obj_id is None:
                # Endpoint references a concept the extractor didn't
                # surface — let lint catch the dangling reference
                # downstream. Don't fabricate a stub here.
                continue
            relationships.append(
                CandidateRelationship(
                    subject_candidate_id=subj_id,
                    predicate=predicate,
                    object_candidate_id=obj_id,
                    source_presence={"A": True, "B": False, "C": False, "D": False},
                    provenance=[
                        EvidenceEntry(
                            source_type="A",
                            source_artifact="",
                            raw_label=f"{subj_label} -> {predicate} -> {obj_label}",
                            confidence=0.8,
                        ),
                    ],
                )
            )
            # Track distinct-neighbour degree (undirected) for centrality
            degree_neighbours.setdefault(subj_id, set()).add(obj_id)
            degree_neighbours.setdefault(obj_id, set()).add(subj_id)

    # Apply graph_degree updates to candidates. CandidateConcept is
    # frozen, so we rebuild via replace.
    if degree_neighbours:
        for candidate_id, neighbours in degree_neighbours.items():
            key = _find_key_for_candidate_id(index, candidate_id)
            if key is None:
                continue
            existing = index.by_key[key]
            index.by_key[key] = replace(
                existing, graph_degree=len(neighbours),
            )

    return CandidateGraph(
        concepts=index.values(),
        relationships=relationships,
    )


# ─── Merge primitives ───────────────────────────────────────────────────────


def _upsert(
    index: _CandidateIndex,
    *,
    label: str,
    definition: str,
    source_type: str,
    source_artifact: str = "",
    raw_type: str = "",
    eid: str = "",
) -> None:
    """Insert or merge a candidate for ``label`` following the
    architecture's merge-key priority.

    Mutates the index in place. Handles the four documented cases:

      1. **Same id seen before** → merge into the existing entry by id.
      2. **Same normalised label, existing has no id** → merge.
         If incoming carries an id, promote it onto the existing.
      3. **Same normalised label, existing has a different id** →
         ambiguity preserved as a separate candidate (composite key).
      4. **Brand-new candidate** → create.
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

    # 1. Direct id hit — same canonical entity seen before.
    if eid and eid in index.by_id:
        key = index.by_id[eid]
        _merge_into(index, key, evidence, label, definition, source_type, raw_type)
        return

    # 2. Normalised-label hit — disambiguation cases:
    if norm in index.by_name:
        existing_key = index.by_name[norm]
        existing = index.by_key[existing_key]
        existing_id = _candidate_id_of(existing)
        if eid and existing_id and existing_id != eid:
            # Case 3: ambiguity — same name, different ids. Keep
            # them separate via a composite key. Future scoring /
            # human review can surface the ambiguity.
            collision_key = f"name:{norm}#id:{eid}"
            if collision_key not in index.by_key:
                index.by_key[collision_key] = _new_candidate(
                    norm=norm,
                    label=label,
                    definition=definition,
                    raw_type=raw_type,
                    source_type=source_type,
                    eid=eid,
                    evidence=evidence,
                )
                index.by_id[eid] = collision_key
            else:
                _merge_into(
                    index, collision_key, evidence, label, definition,
                    source_type, raw_type,
                )
            return
        if eid and not existing_id:
            # Case 2a: existing has no id, incoming has id — promote.
            promoted = replace(
                existing,
                # Stamp the candidate_id off the deterministic id
                # so downstream consumers can rely on it.
                candidate_id=f"cand_id_{eid}",
            )
            index.by_key[existing_key] = promoted
            index.by_id[eid] = existing_key
            _merge_into(
                index, existing_key, evidence, label, definition,
                source_type, raw_type, promote_id=eid,
            )
            return
        # Case 2b: both have no id, or both have the same id — plain merge.
        _merge_into(
            index, existing_key, evidence, label, definition, source_type, raw_type,
        )
        return

    # 4. Brand-new candidate.
    new = _new_candidate(
        norm=norm, label=label, definition=definition,
        raw_type=raw_type, source_type=source_type,
        eid=eid, evidence=evidence,
    )
    if eid:
        key = f"id:{eid}"
        index.by_id[eid] = key
    else:
        key = f"name:{norm}"
    index.by_key[key] = new
    index.by_name[norm] = key


def _new_candidate(
    *,
    norm: str,
    label: str,
    definition: str,
    raw_type: str,
    source_type: str,
    eid: str,
    evidence: EvidenceEntry,
) -> CandidateConcept:
    """Construct a fresh :class:`CandidateConcept` for a never-seen-before
    normalised label."""
    candidate_id = (
        f"cand_id_{eid}"
        if eid
        else f"cand_{norm.replace(' ', '_')}"
    )
    return CandidateConcept(
        candidate_id=candidate_id,
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


def _merge_into(
    index: _CandidateIndex,
    key: str,
    evidence: EvidenceEntry,
    label: str,
    definition: str,
    source_type: str,
    raw_type: str,
    *,
    promote_id: str = "",
) -> None:
    """Merge incoming evidence into the candidate stored at ``key``."""
    existing = index.by_key[key]

    updated_presence = dict(existing.source_presence)
    updated_presence[source_type] = True
    updated_counts = dict(existing.source_counts)
    updated_counts[source_type] = updated_counts.get(source_type, 0) + 1
    merged_definition = existing.summary_definition or definition
    merged_aliases = sorted({*existing.aliases, label})
    suggested_type = existing.suggested_entity_type
    if (not suggested_type or suggested_type == "Concept") and raw_type:
        suggested_type = raw_type

    index.by_key[key] = replace(
        existing,
        suggested_entity_type=suggested_type,
        summary_definition=merged_definition,
        source_presence=updated_presence,
        source_counts=updated_counts,
        authoritative_evidence_count=(
            existing.authoritative_evidence_count + (1 if source_type == "A" else 0)
        ),
        provenance=[*existing.provenance, evidence],
        aliases=merged_aliases,
    )


def _candidate_id_of(candidate: CandidateConcept) -> str:
    """Return the candidate's deterministic profile-mode id, if any.

    The id is encoded into ``candidate_id`` as ``cand_id_<eid>`` for
    profile-mode candidates (Phase 1 convention). Returns empty
    string for candidates that have no id."""
    if candidate.candidate_id.startswith("cand_id_"):
        return candidate.candidate_id[len("cand_id_"):]
    return ""


def _resolve_endpoint_to_candidate_id(
    index: _CandidateIndex, endpoint_label: str,
) -> str | None:
    """Map a relationship endpoint string to a candidate's
    ``candidate_id``, or ``None`` if no candidate exists.

    Tries by normalised label only — endpoints typically come from
    Source A's free-form text where the LLM uses element_name
    strings, not deterministic ids.
    """
    norm = normalize_label(endpoint_label)
    if not norm:
        return None
    key = index.by_name.get(norm)
    if key is None:
        return None
    return index.by_key[key].candidate_id


def _find_key_for_candidate_id(
    index: _CandidateIndex, candidate_id: str,
) -> str | None:
    """Reverse lookup: find the index key that maps to a candidate
    with the given ``candidate_id``. O(N) over the bucket but N is
    small for typical extractions and this only runs during the
    graph_degree pass.
    """
    for k, cand in index.by_key.items():
        if cand.candidate_id == candidate_id:
            return k
    return None
