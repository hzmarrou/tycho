"""Candidate graph builder for the discovery / profile-induction
workflow (profile induction architecture, Phase 1 / Task 2).

This module turns raw source outputs (Source A concepts and
relationships, Source B governance records) into a merged
:class:`CandidateGraph` of :class:`CandidateConcept` and
:class:`CandidateRelationship` objects.

## Merge contract (per ``docs/PROFILE_INDUCTION_ARCHITECTURE.md`` §"Candidate merge rules")

Merge key priority is enforced explicitly:

  1. **Existing profile-mode ``id``** — if the incoming concept has
     an ``id`` and that ``id`` already exists in the bucket, merge.
  2. **Normalised canonical label** — if no id-match but the
     normalised label matches an existing entry that *also lacks* an
     id (or has the *same* id), merge. When an incoming concept
     carries an id and the existing entry doesn't, the existing is
     promoted (claims the id).
  3. **Alias-expanded label** — if no id-match and no direct
     normalised-label match, but an optional ``alias_map`` resolves
     the incoming label to a canonical form whose normalised version
     already exists in the bucket, merge there. The original surface
     form is preserved in ``aliases``.
  4. **Source-specific fallback** — brand-new candidate (create).

Implementation note: alias-expansion happens up-front, *before* the
normalised-label lookup. That collapses steps 2 and 3 into a single
lookup against the alias-expanded normalised label — same observable
behaviour, simpler code path. Without an alias_map, the resolver is
the identity function and behaviour reduces to the Phase 1 baseline.

**Ambiguity preservation**: when two concepts share a normalised
label (after alias expansion) but carry *different* profile-mode ids,
they stay as separate candidates. The architecture is explicit that
ambiguous cases must not be silently collapsed.

## Relationship ingestion (per architecture §"Candidate graph builder")

Source A relationships (subject-predicate-object triples) are
mapped to :class:`CandidateRelationship` objects whose endpoints
reference candidate IDs (not raw labels) — so the relationship
survives later alias resolution. The endpoint resolver applies the
same alias-expansion pass as concept ingestion, so a relationship
endpoint spelled with a synonym surface form resolves to the
candidate merged under the canonical label. Endpoints that don't
resolve to any existing candidate are skipped (Source A occasionally
produces relationships that reference entities it didn't extract as
concepts; that's drift the lint stage catches downstream).

``graph_degree`` is the distinct-neighbour count for each candidate,
computed from the resolved relationships. It feeds the relevance-
scoring stage in Phase 2.

## What this module does not do

Scoring, classification, and profile emission live in
:mod:`ontozense.core.relevance` and
:mod:`ontozense.core.profile_induction`. This module only builds
the graph; the scoring stage reads :class:`CandidateConcept` and
produces a scored version.
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
        key (``"id:<id>"`` or ``"name:<norm>"`` or
        ``"name:<norm>#id:<id>"`` for collision survivors, or
        ``"name:<norm>#ambiguous"`` for the bucket that holds
        name-only contributions whose destination is undetermined).
      - ``by_id`` — id → key, used for the first-priority lookup.
      - ``by_name`` — normalised label → key, used for the
        second-priority lookup.
      - ``ambiguous_norms`` — the set of normalised labels for which
        two or more id-bearing candidates have been seen with
        distinct ids. Name-only contributions and relationship
        endpoints that hit one of these norms are not safely
        attributable to a single candidate, so they route through
        the dedicated ambiguous-bucket key (for upserts) or resolve
        to ``None`` (for relationship endpoints).

    All four are kept consistent on each mutation.
    """

    def __init__(self) -> None:
        self.by_key: dict[str, CandidateConcept] = {}
        self.by_id: dict[str, str] = {}
        self.by_name: dict[str, str] = {}
        self.ambiguous_norms: set[str] = set()
        self.attestations: dict[str, list[tuple[str, str]]] = {}

    def values(self) -> list[CandidateConcept]:
        return list(self.by_key.values())


# ─── Builder ────────────────────────────────────────────────────────────────


def build_candidate_graph(
    *,
    source_a: dict[str, Any] | None = None,
    source_b: dict[str, Any] | None = None,
    source_c: dict[str, Any] | None = None,
    source_d: dict[str, Any] | None = None,
    alias_map: dict[str, str] | None = None,
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
      - ``source_c`` / ``source_d`` — accepted in the signature
        so callers can pass them uniformly across sources. Their
        payloads do not affect candidate generation in this
        implementation.

    Any source argument can be ``None`` or absent. Empty / missing
    labels are skipped silently.

    ``alias_map`` (optional) — lowercased synonym → canonical-label
    map, identical in shape to ``Profile.alias_map``. Drives the
    architecture's step-3 alias-expanded merge: synonyms in different
    sources converge on the canonical label even if their normalised
    forms differ. Per the architecture, the ``discover`` CLI accepts
    an optional ``--profile`` whose alias_map is passed in here (for
    light normalisation only — *not* for filtering or type
    constraints). Without an alias_map, behaviour reduces to the
    id-first / name-only Phase 1 baseline.
    """
    index = _CandidateIndex()
    aliases = alias_map or {}

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
                alias_map=aliases,
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
                alias_map=aliases,
            )

    # source_c and source_d are accepted so callers can pass them
    # uniformly across sources. Their payloads do not affect the
    # candidate concepts or relationships this builder emits.

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
            subj_id = _resolve_endpoint_to_candidate_id(
                index, subj_label, alias_map=aliases,
            )
            obj_id = _resolve_endpoint_to_candidate_id(
                index, obj_label, alias_map=aliases,
            )
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
    artifact_kind: str = "entity",
    strength: str = "medium",
    promotion_reason: str = "",
    suppression_reason: str | None = None,
    suppressed: bool = False,
    alias_map: dict[str, str] | None = None,
) -> None:
    """Insert or merge a candidate for ``label`` following the
    architecture's merge-key priority.

    Mutates the index in place. Handles the four documented cases:

      1. **Same id seen before** → merge into the existing entry by id.
      2. **Same normalised label, existing has no id** → merge.
         If incoming carries an id, promote it onto the existing.
      3. **Alias-expanded label** — the incoming label is resolved via
         the optional ``alias_map`` before normalisation. So
         ``"car"`` with alias_map ``{"car": "Automobile"}``
         normalises to ``"automobile"`` and merges with any existing
         ``"Automobile"`` candidate. The original surface form is
         tracked in ``aliases``.
      4. **Same normalised label, existing has a different id** →
         ambiguity preserved as a separate candidate (composite key).
      5. **Brand-new candidate** → create.

    The architecture lists alias-expansion as step 3 in the merge
    priority. Implementing it as up-front normalisation (rather than
    a separate post-name-miss lookup) collapses steps 2 and 3 into
    one lookup with identical observable behaviour.
    """
    # Step 3: alias-expand the label up-front (with prefix-strip and
    # singularization). With no alias_map the resolver strips prefixes
    # and singularizes before normalisation; with an alias_map the map
    # wins first. Behaviour is a strict superset of the pre-alias baseline.
    canonical_label = _resolve_alias_with_normalisation(label, alias_map or {})
    norm = normalize_label(canonical_label)
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
        _merge_into(
            index, key, evidence, label, definition, source_type,
            raw_type, canonical_label=canonical_label,
            artifact_kind=artifact_kind, strength=strength,
            promotion_reason=promotion_reason,
            suppression_reason=suppression_reason, suppressed=suppressed,
        )
        _record_attestation_and_boost(index, key, source_type, strength)
        return

    # 1b. Ambiguity guard. If this norm has already been split into
    # multiple id-bearing candidates, a name-only contribution can't
    # be safely attached to either of them — neither is guaranteed
    # to be the right destination. Route to a dedicated
    # ambiguous-bucket candidate so the contribution is recorded
    # but not silently misattributed.
    if not eid and norm in index.ambiguous_norms:
        ambig_key = f"name:{norm}#ambiguous"
        if ambig_key not in index.by_key:
            bucket = _new_candidate(
                norm=norm, label=label, definition=definition,
                raw_type=raw_type, source_type=source_type,
                eid="", evidence=evidence,
                canonical_label=canonical_label,
                artifact_kind=artifact_kind, strength=strength,
                promotion_reason=promotion_reason,
                suppression_reason=suppression_reason, suppressed=suppressed,
            )
            # Distinguish the bucket from regular cand_<norm> ids so
            # downstream consumers can spot it.
            index.by_key[ambig_key] = replace(
                bucket,
                candidate_id=f"cand_ambig_{norm.replace(' ', '_')}",
            )
        else:
            _merge_into(
                index, ambig_key, evidence, label, definition,
                source_type, raw_type, canonical_label=canonical_label,
                artifact_kind=artifact_kind, strength=strength,
                promotion_reason=promotion_reason,
                suppression_reason=suppression_reason, suppressed=suppressed,
            )
        _record_attestation_and_boost(index, ambig_key, source_type, strength)
        return

    # 2. Normalised-label hit (already alias-expanded) — disambiguation cases:
    if norm in index.by_name:
        existing_key = index.by_name[norm]
        existing = index.by_key[existing_key]
        existing_id = _candidate_id_of(existing)
        if eid and existing_id and existing_id != eid:
            # Case 4: ambiguity — same name, different ids. Keep
            # them separate via a composite key, and mark the norm
            # as ambiguous so subsequent name-only contributions and
            # relationship endpoints can't silently leak into one
            # of the splits.
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
                    canonical_label=canonical_label,
                    artifact_kind=artifact_kind, strength=strength,
                    promotion_reason=promotion_reason,
                    suppression_reason=suppression_reason,
                    suppressed=suppressed,
                )
                index.by_id[eid] = collision_key
                index.ambiguous_norms.add(norm)
            else:
                _merge_into(
                    index, collision_key, evidence, label, definition,
                    source_type, raw_type, canonical_label=canonical_label,
                    artifact_kind=artifact_kind, strength=strength,
                    promotion_reason=promotion_reason,
                    suppression_reason=suppression_reason,
                    suppressed=suppressed,
                )
            _record_attestation_and_boost(
                index, collision_key, source_type, strength,
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
                canonical_label=canonical_label,
                artifact_kind=artifact_kind, strength=strength,
                promotion_reason=promotion_reason,
                suppression_reason=suppression_reason, suppressed=suppressed,
            )
            _record_attestation_and_boost(
                index, existing_key, source_type, strength,
            )
            return
        # Case 2b / 3: both have no id (or matching id), or alias-expansion
        # collapsed to this entry — plain merge.
        _merge_into(
            index, existing_key, evidence, label, definition,
            source_type, raw_type, canonical_label=canonical_label,
            artifact_kind=artifact_kind, strength=strength,
            promotion_reason=promotion_reason,
            suppression_reason=suppression_reason, suppressed=suppressed,
        )
        _record_attestation_and_boost(
            index, existing_key, source_type, strength,
        )
        return

    # 5. Brand-new candidate.
    new = _new_candidate(
        norm=norm, label=label, definition=definition,
        raw_type=raw_type, source_type=source_type,
        eid=eid, evidence=evidence,
        canonical_label=canonical_label,
        artifact_kind=artifact_kind, strength=strength,
        promotion_reason=promotion_reason,
        suppression_reason=suppression_reason, suppressed=suppressed,
    )
    if eid:
        key = f"id:{eid}"
        index.by_id[eid] = key
    else:
        key = f"name:{norm}"
    index.by_key[key] = new
    index.by_name[norm] = key
    _record_attestation_and_boost(index, key, source_type, strength)


def _record_attestation_and_boost(
    index: _CandidateIndex,
    key: str,
    source_type: str,
    strength: str,
) -> None:
    """Append an attestation for *key* and recompute its strength via
    :func:`_apply_corroboration_boost`.

    Called at the end of every ``_upsert`` merge case so the candidate's
    ``strength`` field always reflects the cross-source boost.
    """
    attestations = index.attestations.setdefault(key, [])
    attestations.append((source_type, strength))
    if key in index.by_key:
        existing = index.by_key[key]
        boosted = _apply_corroboration_boost(attestations)
        index.by_key[key] = replace(existing, strength=boosted)


def _new_candidate(
    *,
    norm: str,
    label: str,
    definition: str,
    raw_type: str,
    source_type: str,
    eid: str,
    evidence: EvidenceEntry,
    canonical_label: str = "",
    artifact_kind: str = "entity",
    strength: str = "medium",
    promotion_reason: str = "",
    suppression_reason: str | None = None,
    suppressed: bool = False,
) -> CandidateConcept:
    """Construct a fresh :class:`CandidateConcept` for a never-seen-before
    normalised label.

    ``label`` is the surface form the caller passed.
    ``canonical_label`` is the alias-resolved form — when an
    alias_map is in effect, this is the value the merge keyed on.

    Round-1 reviewer finding pinned here: the candidate's primary
    ``label`` is the *canonical* form (alias-resolved), not the
    first surface form encountered. That makes the emitted label
    order-independent — reversing source order with the same
    alias_map and same evidence yields the same primary label
    instead of flipping between synonym and canonical. The
    original surface form is still preserved in ``aliases`` so
    callers can locate the candidate via either spelling.
    """
    candidate_id = (
        f"cand_id_{eid}"
        if eid
        else f"cand_{norm.replace(' ', '_')}"
    )
    # Prefer the canonical (alias-resolved) form for the primary
    # label. Falls back to the surface ``label`` only when no
    # canonical was supplied (callers that don't pass alias_map).
    preferred_label = canonical_label if canonical_label else label
    initial_aliases = (
        sorted({label, canonical_label})
        if canonical_label and canonical_label != label
        else [label]
    )
    return CandidateConcept(
        candidate_id=candidate_id,
        label=preferred_label,
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
        aliases=initial_aliases,
        artifact_kind=artifact_kind,
        strength=strength,
        promotion_reason=promotion_reason,
        suppression_reason=suppression_reason,
        suppressed=suppressed,
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
    canonical_label: str = "",
    artifact_kind: str = "entity",
    strength: str = "medium",
    promotion_reason: str = "",
    suppression_reason: str | None = None,
    suppressed: bool = False,
) -> None:
    """Merge incoming evidence into the candidate stored at ``key``.

    Both the original surface ``label`` and the alias-resolved
    ``canonical_label`` (when different) are added to the candidate's
    ``aliases`` list so the merge is observable from either spelling.

    New v1.1 fields are merged as follows:
      - ``artifact_kind``: prefer non-default ("entity") value; if both
        are non-default and differ, keep the existing value.
      - ``strength``: take the max via :data:`_STRENGTH_RANK`.
      - ``promotion_reason``: concatenate with ``"; "`` separator, skipping
        empty values.
      - ``suppression_reason``: prefer the non-None incoming value when the
        existing is ``None``; otherwise keep existing.
      - ``suppressed``: logical OR (suppressed if either side is suppressed).

    Note: the caller's ``_record_attestation_and_boost`` will overwrite
    ``strength`` with the corroboration-boosted value immediately after
    this function returns, so the max-strength computation here is only
    a fallback used if attestation tracking is somehow bypassed.
    """
    existing = index.by_key[key]

    updated_presence = dict(existing.source_presence)
    updated_presence[source_type] = True
    updated_counts = dict(existing.source_counts)
    updated_counts[source_type] = updated_counts.get(source_type, 0) + 1
    merged_definition = existing.summary_definition or definition
    new_aliases = {*existing.aliases, label}
    if canonical_label:
        new_aliases.add(canonical_label)
    merged_aliases = sorted(new_aliases)
    suggested_type = existing.suggested_entity_type
    if (not suggested_type or suggested_type == "Concept") and raw_type:
        suggested_type = raw_type

    # Merge v1.1 fields.
    merged_artifact_kind = (
        artifact_kind
        if existing.artifact_kind == "entity" and artifact_kind != "entity"
        else existing.artifact_kind
    )
    merged_strength_rank = max(
        _STRENGTH_RANK.get(existing.strength, 1),
        _STRENGTH_RANK.get(strength, 1),
    )
    merged_strength = _RANK_TO_NAME.get(merged_strength_rank, "medium")
    parts = [p for p in [existing.promotion_reason, promotion_reason] if p]
    merged_promotion_reason = "; ".join(parts)
    merged_suppression_reason = (
        suppression_reason
        if existing.suppression_reason is None and suppression_reason is not None
        else existing.suppression_reason
    )
    merged_suppressed = existing.suppressed or suppressed

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
        artifact_kind=merged_artifact_kind,
        strength=merged_strength,
        promotion_reason=merged_promotion_reason,
        suppression_reason=merged_suppression_reason,
        suppressed=merged_suppressed,
    )


def _resolve_alias(label: str, alias_map: dict[str, str]) -> str:
    """Resolve a surface label through the alias map.

    Lookup is case-insensitive on the key (mirroring how
    :class:`~ontozense.core.profile.Profile.resolve_alias` works for
    the profile-mode pipeline). Returns the canonical label if a
    matching alias entry exists, otherwise returns the original label
    unchanged. With an empty / ``None`` alias_map this is the
    identity function — Phase 1 baseline behaviour.
    """
    if not alias_map:
        return label
    return alias_map.get(label.strip().lower(), label)


def _resolve_alias_with_normalisation(
    label: str, alias_map: dict[str, str],
) -> str:
    """Apply alias_map first (case-insensitive lookup); then strip
    table-name prefixes and singularize plurals before normalisation.

    Returns the canonical surface form (alias-resolved if a match
    is found, otherwise the prefix-stripped + singularized label).

    The downstream normalisation (case-fold etc.) happens in
    :func:`normalize_label` as before — this function only does the
    semantic-mapping work that needs to happen *before* normalisation.
    """
    # Alias map: exact match first, then case-insensitive.
    if label in alias_map:
        return alias_map[label]
    label_lower = label.lower()
    if label_lower in alias_map:
        return alias_map[label_lower]
    # Case-insensitive search through alias_map keys.
    for k, v in alias_map.items():
        if k.lower() == label_lower:
            return v

    work = label
    lower = work.lower()
    for prefix in ("tbl_", "dim_", "fact_"):
        if lower.startswith(prefix):
            work = work[len(prefix):]
            break

    # English singularization via inflect; safe-fallback to chop trailing 's'.
    # Guard: only accept the singularized form when the round-trip
    # plural(singular) matches the original (case-insensitive).  This
    # rejects inflect false-positives such as "Address" → "Addres".
    try:
        import inflect
        engine = inflect.engine()
        singular = engine.singular_noun(work)
        if singular and isinstance(singular, str):
            # Round-trip check: plural of the candidate singular should
            # equal the original word (case-insensitive).
            round_trip = engine.plural(singular)
            if isinstance(round_trip, str) and round_trip.lower() == work.lower():
                work = singular
    except ImportError:
        if work.lower().endswith("s") and len(work) > 1:
            work = work[:-1]

    return work


_STRENGTH_RANK: dict[str, int] = {"weak": 0, "medium": 1, "strong": 2}
_RANK_TO_NAME: dict[int, str] = {v: k for k, v in _STRENGTH_RANK.items()}


def _apply_corroboration_boost(
    attestations: list[tuple[str, str]],
) -> str:
    """Given a list of (source_type, strength) attestations, return
    the boosted strength tier.

    Rules:
      - max strength across all attestations
      - +1 tier if at least 2 distinct axes attest
        (semantic axis = A or B; structural axis = C; executable axis = D)
      - capped at 'strong'
    """
    if not attestations:
        return "medium"

    max_rank = max(
        _STRENGTH_RANK.get(s, 1) for _, s in attestations
    )

    axes_seen: set[str] = set()
    for src, _ in attestations:
        if src in ("A", "B"):
            axes_seen.add("semantic")
        elif src == "C":
            axes_seen.add("structural")
        elif src == "D":
            axes_seen.add("executable")

    if len(axes_seen) >= 2:
        max_rank = min(max_rank + 1, 2)

    return _RANK_TO_NAME.get(max_rank, "medium")


def _candidate_id_of(candidate: CandidateConcept) -> str:
    """Return the candidate's deterministic profile-mode id, if any.

    The id is encoded into ``candidate_id`` as ``cand_id_<eid>`` for
    profile-mode candidates (Phase 1 convention). Returns empty
    string for candidates that have no id."""
    if candidate.candidate_id.startswith("cand_id_"):
        return candidate.candidate_id[len("cand_id_"):]
    return ""


def _resolve_endpoint_to_candidate_id(
    index: _CandidateIndex,
    endpoint_label: str,
    *,
    alias_map: dict[str, str] | None = None,
) -> str | None:
    """Map a relationship endpoint string to a candidate's
    ``candidate_id``, or ``None`` if no candidate exists.

    Endpoints typically come from Source A's free-form text where
    the LLM uses element_name strings, not deterministic ids — so
    resolution is name-based. The lookup applies the same
    alias-expansion pass that concept ingestion uses (see
    :func:`_upsert`): the endpoint label is resolved through
    ``alias_map`` *before* normalisation. That way a relationship
    endpoint spelled with a synonym surface form (e.g. ``"car"``)
    still resolves to the candidate that was merged under the
    canonical label (e.g. ``"Automobile"``).

    Without an alias_map, :func:`_resolve_alias` is the identity
    function and behaviour reduces to the pre-alias baseline:
    direct normalised-label lookup only.
    """
    canonical_label = _resolve_alias(endpoint_label, alias_map or {})
    norm = normalize_label(canonical_label)
    if not norm:
        return None
    # Ambiguity guard: if the norm has multiple id-bearing
    # candidates with distinct ids, the endpoint can't be safely
    # attributed to any single one. Treat as unresolvable so the
    # caller drops the relationship (same path as "no candidate
    # exists at all").
    if norm in index.ambiguous_norms:
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
