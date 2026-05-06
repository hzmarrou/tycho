"""Fusion layer — combines Sources A, B, C, D into a rich data dictionary.

The fusion layer is the point where the four-source architecture
delivers value. Before fusion, each source is a partial view — after
fusion, the expert has a single artifact to review with per-field
provenance and honest confidence.

The fused output is the **rich data dictionary** described in
``docs/PLAYBOOK.md`` §2. Each element carries every field at least one
source could defensibly provide, plus:

  - Which source provided each field (provenance)
  - Whether the element was governance-validated (Source B confirmed it)
  - Conflicts where two sources disagreed (with rejected values preserved)
  - An overall confidence score (average across populated field confidences)

Pipeline:

  1. **Seed** from Source A concepts (the primary extractor)
  2. **Validate/enrich** with Source B governance records (match by name)
  3. **Enrich** with Source C schema fields (data_type, enum_values, nullable)
  4. **Attach** Source D code rules as business_rules (match by name/symbol)
  5. **Report** unmatched items from each source

Source B, C, and D are all optional. The minimum viable fusion is
Source A alone — producing a data dictionary from domain documents
that the expert reviews in Excel.

Conflict resolution per PLAYBOOK §4:
  priority (default A > B > C > D) → confidence → recency → unresolved.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from ..extractors.domain_doc_extractor import (
    Concept,
    DomainDocumentExtractionResult,
    Relationship,
)
from ..extractors.governance_extractor import (
    GovernanceExtractionResult,
    GovernanceRecord,
)
from ..extractors.django_schema import SchemaField, SchemaModel, SchemaResult
from ..extractors.code_extractor import CodeExtractionResult, CodeRule


# ─── Name normalisation ─────────────────────────────────────────────────────


def normalise_name(name: str) -> str:
    """Normalise an element name for cross-source matching.

    Lowercase, replace underscores and hyphens with spaces, collapse
    whitespace, strip. This means ``"Customer Identifier"`` matches
    ``"customer_identifier"`` matches ``"CUSTOMER-IDENTIFIER"``.
    """
    s = name.lower()
    s = re.sub(r"[_\-]", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


# ─── Dataclasses ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class FieldAnchor:
    """Where a field's value came from inside the source artifact.

    Phase 6: per-field provenance anchors. Pre-Phase-6 fused outputs
    only knew the source document name (Source A) or file path
    (Source D). Phase 6 adds the location *within* the document so a
    reviewer can click through to the exact span the LLM extracted.

    All fields are optional. Different upstream extractors populate
    different subsets — Source A's prose extractor may have
    ``segment_id`` + ``snippet`` from a markdown heading; Source D's
    AST has ``line`` + ``column``; PDF-converted Source A has ``page``
    + ``char_offset``. Defaults are 0 / empty so a partially-anchored
    field round-trips cleanly.

    AC1 contract: the JSON serialiser emits the ``anchor`` key on
    a ``FieldProvenance`` ONLY when ``FieldAnchor`` is non-default
    (i.e. at least one field carries a real value). Pre-Phase-6
    fused JSON round-trips byte-identical because no upstream
    extractor populates anchors yet by default.
    """
    page: int = 0           # 1-indexed page (PDF-derived)
    char_offset: int = 0    # 0-indexed offset into the source text
    char_length: int = 0    # length in characters of the matched span
    line: int = 0           # 1-indexed line number (text/code)
    end_line: int = 0       # 1-indexed end line for multi-line spans
    column: int = 0         # 1-indexed column (code)
    segment_id: str = ""    # named section / heading / anchor identifier
    snippet: str = ""       # short verbatim quote for human verification

    def is_empty(self) -> bool:
        """True when no anchor field carries data — used to suppress
        the anchor key on serialisation so AC1 byte-identity holds for
        unanchored values (pre-Phase-6 callers see no shape change)."""
        return (
            self.page == 0
            and self.char_offset == 0
            and self.char_length == 0
            and self.line == 0
            and self.end_line == 0
            and self.column == 0
            and not self.segment_id
            and not self.snippet
        )


@dataclass
class FieldProvenance:
    """Where a single field value came from."""
    source: str          # "A", "B", "C", "D"
    confidence: float
    original_value: str  # the raw value from the source
    # Phase 6: optional fine-grained location within the source doc.
    # ``None`` = unanchored (pre-Phase-6 behaviour). The CLI serialiser
    # omits this key entirely when it's None or an empty FieldAnchor,
    # preserving AC1 byte-identity for unanchored output.
    anchor: Optional["FieldAnchor"] = None


@dataclass
class FieldConflict:
    """Two sources disagreed on a field value."""
    field_name: str
    winner: FieldProvenance
    rejected: list[FieldProvenance]
    resolution: str  # "priority", "confidence", "recency", "unresolved"


@dataclass
class FusedElement:
    """One element in the fused rich data dictionary."""
    element_name: str
    domain_name: str = ""
    definition: str = ""
    is_critical: bool = False
    citation: str = ""
    data_type: str = ""
    enum_values: list[str] = field(default_factory=list)
    business_rules: list[str] = field(default_factory=list)
    extra_fields: dict[str, Any] = field(default_factory=dict)

    # ── Provenance & quality ──
    sources: list[str] = field(default_factory=list)
    field_provenance: dict[str, FieldProvenance] = field(default_factory=dict)
    conflicts: list[FieldConflict] = field(default_factory=list)
    governance_validated: bool = False

    # ── Confidence (average across populated fields) ──
    confidence: float = 0.0

    def recompute_confidence(self) -> float:
        """Recompute element-level confidence from field provenance."""
        if not self.field_provenance:
            self.confidence = 0.0
            return 0.0
        total = sum(fp.confidence for fp in self.field_provenance.values())
        self.confidence = total / len(self.field_provenance)
        return self.confidence

    def needs_review(self, threshold: float = 0.7) -> bool:
        return self.confidence < threshold or self.has_unresolved_conflicts()

    def has_unresolved_conflicts(self) -> bool:
        return any(c.resolution == "unresolved" for c in self.conflicts)


@dataclass
class FusedRelationship:
    """A relationship carried through from Source A or Source C."""
    subject: str
    predicate: str
    object: str
    source: str  # "A" or "C"
    confidence: float = 0.0


@dataclass
class FusionResult:
    """The output of the fusion layer."""
    elements: list[FusedElement] = field(default_factory=list)
    relationships: list[FusedRelationship] = field(default_factory=list)
    unmatched_governance: list[GovernanceRecord] = field(default_factory=list)
    unmatched_schema_fields: list[tuple[str, SchemaField]] = field(default_factory=list)
    unmatched_code_rules: list[CodeRule] = field(default_factory=list)
    sources_used: list[str] = field(default_factory=list)
    fusion_timestamp: str = ""

    def get_element(self, name: str) -> Optional[FusedElement]:
        target = normalise_name(name)
        for e in self.elements:
            if normalise_name(e.element_name) == target:
                return e
        return None

    @property
    def governance_validated_count(self) -> int:
        return sum(1 for e in self.elements if e.governance_validated)

    @property
    def conflict_count(self) -> int:
        return sum(len(e.conflicts) for e in self.elements)


# ─── Fusion engine ───────────────────────────────────────────────────────────

# Default priority order per PLAYBOOK §4
DEFAULT_PRIORITY = ["A", "B", "C", "D"]


class FusionEngine:
    """Combines Sources A, B, C, D into a fused rich data dictionary.

    All sources are optional. The minimum viable fusion is Source A alone.
    """

    def __init__(
        self,
        priority_order: list[str] | None = None,
    ):
        self.priority = priority_order or list(DEFAULT_PRIORITY)

    def fuse(
        self,
        source_a: (
            DomainDocumentExtractionResult
            | list[DomainDocumentExtractionResult]
            | None
        ) = None,
        source_b: GovernanceExtractionResult | None = None,
        source_c: SchemaResult | None = None,
        source_d: CodeExtractionResult | None = None,
    ) -> FusionResult:
        """Fuse Sources A, B, C, D into a rich data dictionary.

        ``source_a`` may be a single ``DomainDocumentExtractionResult``
        (single document) or a list of them (multi-document). When a
        list is given, concepts that share an id (in profile mode) or a
        normalised name (unconstrained) are consolidated into one
        element, with each contributing document tracked in
        ``el.extra_fields["source_documents"]`` and a
        ``corroborating_doc_count`` count. AC1 (no-profile byte-
        identity) is preserved: a single-element list behaves the same
        as a single result, and unconstrained mode falls back to the
        normalised-name keying that pre-Phase-5 code used.
        """
        result = FusionResult(
            fusion_timestamp=datetime.utcnow().isoformat(),
        )

        # Normalise source_a to a list. Order matters for "first wins"
        # semantics on ties — earlier docs in the list seed first.
        a_results: list[DomainDocumentExtractionResult]
        if source_a is None:
            a_results = []
        elif isinstance(source_a, list):
            a_results = source_a
        else:
            a_results = [source_a]

        # Track which sources were provided
        if a_results:
            result.sources_used.append("A")
        if source_b:
            result.sources_used.append("B")
        if source_c:
            result.sources_used.append("C")
        if source_d:
            result.sources_used.append("D")

        # The index is keyed by normalised name (always populated).
        # ``id_lookup`` maps deterministic IDs (Phase 1) to the index
        # key — so cross-source enrichment can find an element by its
        # profile-mode id even when names diverge between sources.
        index: dict[str, FusedElement] = {}
        id_lookup: dict[str, str] = {}

        # ── Pass 1: Seed from Source A (multi-doc consolidation) ──
        # Track corroboration only when there are 2+ Source A inputs.
        # Single-doc fusion preserves AC1 byte-identity by NOT adding
        # ``source_documents`` / ``corroborating_doc_count`` keys to
        # ``extra_fields`` — pre-Phase-5 behaviour for any single-doc
        # call.
        track_corroboration = len(a_results) > 1
        for sa in a_results:
            self._merge_source_a(
                sa, index, id_lookup, result,
                track_corroboration=track_corroboration,
            )

        # ── Pass 2: Validate/enrich from Source B ──
        if source_b:
            self._merge_source_b(source_b, index, id_lookup, result)

        # ── Pass 3: Enrich from Source C ──
        if source_c:
            self._merge_source_c(source_c, index, id_lookup, result)

        # ── Pass 4: Attach business rules from Source D ──
        if source_d:
            self._merge_source_d(source_d, index, id_lookup, result)

        # Finalize
        result.elements = list(index.values())
        for el in result.elements:
            el.recompute_confidence()

        return result

    # ── Source A: seed elements from concepts ────────────────────────────

    def _merge_source_a(
        self,
        source_a: DomainDocumentExtractionResult,
        index: dict[str, FusedElement],
        id_lookup: dict[str, str],
        result: FusionResult,
        *,
        track_corroboration: bool = False,
    ) -> None:
        for concept in source_a.concepts:
            if not concept.name.strip():
                continue
            el = self._get_or_create(
                index, id_lookup, name=concept.name, eid=concept.id,
            )
            conf = concept.overall_confidence()

            # Phase 6: derive an anchor from the concept's Provenance,
            # if one was supplied by the upstream extractor. Same anchor
            # applies to every Source-A field on this concept (the
            # fields share an extraction context).
            anchor = self._anchor_from_concept_provenance(concept)

            self._set_field(el, "element_name", concept.name, "A", conf, anchor)

            if concept.definition:
                self._set_field(el, "definition", concept.definition, "A", conf, anchor)

            if concept.citation:
                self._set_field(el, "citation", concept.citation, "A", conf, anchor)

            if source_a.domain_name:
                self._set_field(
                    el, "domain_name", source_a.domain_name, "A", conf, anchor,
                )

            # Carry profile-mode metadata into extra_fields so downstream
            # stages (validate, lint) can use them. These are empty in
            # unconstrained mode — backward-compat unaffected.
            if concept.id:
                el.extra_fields.setdefault("id", concept.id)
            if concept.entity_type:
                el.extra_fields.setdefault("entity_type", concept.entity_type)

            # Multi-doc corroboration: track every document this concept
            # appeared in. Skipped for single-doc fusion to preserve
            # AC1 byte-identity (no new extra_fields keys when nothing
            # multi-doc is happening). Source A only — B/C/D each have
            # a single provenance per record handled elsewhere.
            if track_corroboration:
                self._track_corroboration(el, concept)

            if "A" not in el.sources:
                el.sources.append("A")

        # Carry relationships through
        for rel in source_a.relationships:
            if rel.subject.strip() and rel.object.strip():
                result.relationships.append(
                    FusedRelationship(
                        subject=rel.subject,
                        predicate=rel.predicate,
                        object=rel.object,
                        source="A",
                        confidence=rel.overall_confidence(),
                    )
                )

    # ── Source B: validate/enrich from governance ────────────────────────

    def _merge_source_b(
        self,
        source_b: GovernanceExtractionResult,
        index: dict[str, FusedElement],
        id_lookup: dict[str, str],
        result: FusionResult,
    ) -> None:
        for rec in source_b.records:
            el = self._lookup(index, id_lookup, eid=rec.id, name=rec.element_name)
            if el is not None:
                # Governance-validated: this Source A concept exists in
                # the governance system.
                el.governance_validated = True

                # Source B definition may be richer than Source A's
                if rec.definition:
                    self._set_field(
                        el, "definition", rec.definition, "B", rec.confidence,
                    )

                # is_critical comes from Source B only
                if rec.is_critical:
                    el.is_critical = True
                    self._set_field(
                        el, "is_critical", "true", "B", rec.confidence,
                    )

                # Citations are additive — both sources contribute
                # complementary references (Source A cites regulation
                # sections, Source B cites governance tools). No conflict
                # detection; just merge.
                if rec.citation:
                    if el.citation and rec.citation not in el.citation:
                        el.citation = f"{el.citation}; {rec.citation}"
                    elif not el.citation:
                        el.citation = rec.citation
                    # Record provenance without conflict detection
                    el.field_provenance["citation"] = FieldProvenance(
                        source="A+B",
                        confidence=max(
                            el.field_provenance.get("citation", FieldProvenance("", 0, "")).confidence,
                            rec.confidence,
                        ),
                        original_value=el.citation,
                    )

                if rec.domain_name:
                    self._set_field(
                        el, "domain_name", rec.domain_name, "B", rec.confidence,
                    )

                # Carry extra fields from governance
                for k, v in rec.extra_fields.items():
                    el.extra_fields[f"gov_{k}"] = v

                # Profile-mode metadata: only set if Source A didn't
                # already populate them (Source A wins for id/type).
                if rec.id:
                    el.extra_fields.setdefault("id", rec.id)
                if rec.entity_type:
                    el.extra_fields.setdefault("entity_type", rec.entity_type)

                if "B" not in el.sources:
                    el.sources.append("B")
            else:
                # Governance-only term: exists in governance but Source A
                # didn't extract it. Add as a new element.
                el = self._get_or_create(
                    index, id_lookup, name=rec.element_name, eid=rec.id,
                )
                if rec.definition:
                    self._set_field(
                        el, "definition", rec.definition, "B", rec.confidence,
                    )
                if rec.domain_name:
                    self._set_field(
                        el, "domain_name", rec.domain_name, "B", rec.confidence,
                    )
                if rec.is_critical:
                    el.is_critical = True
                if rec.citation:
                    el.citation = rec.citation
                if rec.id:
                    el.extra_fields.setdefault("id", rec.id)
                if rec.entity_type:
                    el.extra_fields.setdefault("entity_type", rec.entity_type)
                el.governance_validated = True
                el.sources.append("B")
                # Also track as unmatched for the gap report
                result.unmatched_governance.append(rec)

    # ── Source C: enrich from schema ─────────────────────────────────────

    def _merge_source_c(
        self,
        source_c: SchemaResult,
        index: dict[str, FusedElement],
        id_lookup: dict[str, str],
        result: FusionResult,
    ) -> None:
        for model in source_c.models:
            for sf in model.fields:
                el = self._lookup(
                    index, id_lookup, eid=sf.id, name=sf.name,
                )
                if el is not None:
                    # data_type from schema (PLAYBOOK §2: primary source)
                    if sf.playground_type:
                        self._set_field(
                            el, "data_type", sf.playground_type, "C", 0.95,
                        )
                    # enum_values from choices
                    if sf.choices_values:
                        el.enum_values = list(sf.choices_values)
                        self._set_field(
                            el, "enum_values",
                            ", ".join(sf.choices_values), "C", 0.95,
                        )
                    # mandatory_optional from nullable
                    if not sf.is_nullable:
                        self._set_field(
                            el, "mandatory_optional", "M", "C", 0.95,
                        )
                    # Carry profile-mode metadata if Source A/B didn't.
                    if sf.id:
                        el.extra_fields.setdefault("id", sf.id)
                    if sf.entity_type:
                        el.extra_fields.setdefault("entity_type", sf.entity_type)
                    if "C" not in el.sources:
                        el.sources.append("C")
                else:
                    # Schema-only field: not mentioned in Source A or B.
                    # Add as a new element with schema provenance.
                    el = self._get_or_create(
                        index, id_lookup, name=sf.name, eid=sf.id,
                    )
                    if sf.playground_type:
                        el.data_type = sf.playground_type
                        self._set_field(
                            el, "data_type", sf.playground_type, "C", 0.95,
                        )
                    if sf.choices_values:
                        el.enum_values = list(sf.choices_values)
                    if model.doc:
                        el.extra_fields["schema_entity"] = model.name
                        el.extra_fields["schema_doc"] = model.doc
                    if sf.id:
                        el.extra_fields.setdefault("id", sf.id)
                    if sf.entity_type:
                        el.extra_fields.setdefault("entity_type", sf.entity_type)
                    el.sources.append("C")
                    result.unmatched_schema_fields.append((model.name, sf))

            # Schema relationships → fused relationships
            for sr in model.relationships:
                result.relationships.append(
                    FusedRelationship(
                        subject=sr.from_model,
                        predicate=f"FK:{sr.field_name}",
                        object=sr.to_model,
                        source="C",
                        confidence=0.95,
                    )
                )

    # ── Source D: attach business rules from code ────────────────────────

    def _merge_source_d(
        self,
        source_d: CodeExtractionResult,
        index: dict[str, FusedElement],
        id_lookup: dict[str, str],
        result: FusionResult,
    ) -> None:
        for rule in source_d.rules:
            matched = False
            rule_desc = self._rule_to_description(rule)

            # Profile-mode: Phase 3 may have already attached this rule
            # to an entity ID via _apply_profile. Try id-first.
            attached_id = getattr(rule, "attached_to_entity_id", "")

            el = self._lookup(
                index, id_lookup, eid=attached_id, name=rule.name,
            )
            if el is not None:
                el.business_rules.append(rule_desc)
                if "D" not in el.sources:
                    el.sources.append("D")
                matched = True
            else:
                # Try matching by referenced symbols
                for sym in rule.referenced_symbols:
                    sym_el = self._lookup(
                        index, id_lookup, name=sym.split(".")[-1],
                    )
                    if sym_el is not None:
                        sym_el.business_rules.append(rule_desc)
                        if "D" not in sym_el.sources:
                            sym_el.sources.append("D")
                        matched = True
                        break

            if not matched:
                result.unmatched_code_rules.append(rule)

    @staticmethod
    def _rule_to_description(rule: CodeRule) -> str:
        """Convert a CodeRule to a human-readable business rule string."""
        parts = [f"[{rule.rule_type}]"]
        if rule.rule_type == "constant":
            parts.append(f"{rule.name} = {rule.value!r}")
        elif rule.rule_type == "conditional":
            parts.append(rule.expression)
        elif rule.rule_type == "function":
            parts.append(f"{rule.name}()")
            if rule.docstring:
                # First sentence of docstring
                first = rule.docstring.split(".")[0].strip()
                if first:
                    parts.append(f"— {first}")
        elif rule.rule_type in ("sql_check", "sql_where"):
            parts.append(rule.expression)
        elif rule.rule_type in ("sql_view", "sql_table"):
            parts.append(rule.name)
        elif rule.rule_type == "comment_citation":
            parts.append(rule.expression)
        else:
            parts.append(rule.expression or rule.name)

        if rule.citations:
            parts.append(f"(ref: {', '.join(rule.citations)})")

        if rule.provenance:
            fname = rule.provenance.file_path.replace("\\", "/").split("/")[-1]
            parts.append(f"[{fname}:{rule.provenance.line}]")

        return " ".join(parts)

    # ── Helpers ──────────────────────────────────────────────────────────

    def _get_or_create(
        self,
        index: dict[str, FusedElement],
        id_lookup: dict[str, str],
        *,
        name: str,
        eid: str = "",
    ) -> FusedElement:
        """Get an existing element by id or name, or create a new one.

        Id-first when supplied. Falls back to name lookup so mixed-mode
        pipelines (e.g. unconstrained Source A + profile-mode Source B)
        still consolidate correctly.

        Two profile-mode entities that share a normalised name but
        carry distinct ids stay SEPARATE — id is the source of truth in
        profile mode, and name collisions resolved by appending the id
        to the index key.
        """
        # 1. Direct id hit (same eid seen before).
        if eid and eid in id_lookup:
            return index[id_lookup[eid]]

        # 2. Try name fallback. Two sub-cases when eid is supplied:
        #    a. existing element has no id — promote it (mixed-mode).
        #    b. existing element has a different id — collision: keep
        #       both via id-suffixed key so distinct entities don't
        #       silently merge on a surface-name coincidence.
        name_key = normalise_name(name)
        if name_key in index:
            existing = index[name_key]
            existing_id = existing.extra_fields.get("id", "")
            if eid and existing_id and existing_id != eid:
                # Collision — distinct entities sharing a name. Stash
                # this one under a name+id composite key so name-only
                # callers can still find the original by name, while
                # id-based callers route to the right one via id_lookup.
                collision_key = f"{name_key}#id:{eid}"
                if collision_key not in index:
                    index[collision_key] = FusedElement(
                        element_name=name.strip(),
                    )
                id_lookup[eid] = collision_key
                return index[collision_key]
            # Same id, or one side unclaimed — merge into existing.
            if eid and not existing_id:
                # Promote: bind this eid to the existing element so
                # later id-keyed callers find it.
                id_lookup[eid] = name_key
            return existing

        # 3. New element — create keyed by normalised name (always),
        # and register the id_lookup mapping if profile mode.
        index[name_key] = FusedElement(element_name=name.strip())
        if eid:
            id_lookup[eid] = name_key
        return index[name_key]

    def _lookup(
        self,
        index: dict[str, FusedElement],
        id_lookup: dict[str, str],
        *,
        eid: str = "",
        name: str = "",
    ) -> FusedElement | None:
        """Look up an existing element without creating one.

        Tries id first when supplied (profile mode), falls back to name.

        **Id-collision safety:** if ``eid`` is supplied but missing from
        ``id_lookup``, the name fallback only succeeds when the matched
        element either has no id yet OR has the *same* id. If the
        matched element already carries a *different* id, this returns
        ``None`` — the caller must route through ``_get_or_create``,
        whose composite-key path keeps distinct profile-mode entities
        separate even when their normalised names collide.

        **Atomic id promotion:** when the name fallback succeeds AND
        ``eid`` is supplied AND the matched element had no id yet, the
        eid is registered into ``id_lookup`` and written to
        ``extra_fields["id"]`` as part of this call. This keeps the
        two stores consistent for any subsequent id-keyed lookup of
        the same element from another source.
        """
        if eid and eid in id_lookup:
            return index[id_lookup[eid]]
        if name:
            key = normalise_name(name)
            if key in index:
                existing = index[key]
                if eid:
                    existing_id = existing.extra_fields.get("id", "")
                    if existing_id and existing_id != eid:
                        # Collision: refuse to merge by name when ids
                        # differ. Caller falls through to creation.
                        return None
                    if not existing_id:
                        # Promote: bind this eid to the existing
                        # element so future id-keyed lookups resolve
                        # to it, and persist the id on the element.
                        id_lookup[eid] = key
                        existing.extra_fields["id"] = eid
                return existing
        return None

    @staticmethod
    def _track_corroboration(
        el: FusedElement,
        concept: "Concept",
    ) -> None:
        """Record that this concept appeared in another source document.

        Multi-doc consolidation contract: when the same concept appears
        in multiple authoritative documents, the fused element gathers
        each document's path under ``extra_fields["source_documents"]``
        and exposes the count as ``extra_fields["corroborating_doc_count"]``.
        Higher counts mean more documents agree the term exists — useful
        for downstream review weighting.

        Concepts without provenance or with empty source_document
        (e.g. unit-test stubs) are skipped silently.
        """
        if concept.provenance is None:
            return
        src_doc = concept.provenance.source_document
        if not src_doc:
            return
        docs = el.extra_fields.setdefault("source_documents", [])
        if src_doc not in docs:
            docs.append(src_doc)
        el.extra_fields["corroborating_doc_count"] = len(docs)

    @staticmethod
    def _anchor_from_concept_provenance(
        concept: "Concept",
    ) -> Optional[FieldAnchor]:
        """Map a Source A ``Concept.provenance`` to a ``FieldAnchor``.

        Returns ``None`` when no anchor data is available — that
        case round-trips byte-identical to pre-Phase-6 output. This is
        critical for AC1: the LLM extractor doesn't currently emit
        page numbers or char offsets, so most concepts will yield
        ``None`` here today, and FieldProvenance.anchor stays ``None``.

        When the upstream extractor *does* populate richer location
        data (PDF page number, line number, etc.), this helper picks
        it up and converts it to the typed anchor.
        """
        prov = concept.provenance
        if prov is None:
            return None
        # Only build an anchor if we actually have anchor-shaped data.
        # ``source_document`` alone isn't an anchor (it's the doc name
        # tracked separately via corroboration); we want section /
        # snippet / page / line / offset.
        if not (prov.source_section or prov.source_text_snippet):
            return None
        return FieldAnchor(
            segment_id=prov.source_section or "",
            snippet=prov.source_text_snippet or "",
        )

    @staticmethod
    def _anchor_from_code_provenance(
        rule: CodeRule,
    ) -> Optional[FieldAnchor]:
        """Map a Source D ``CodeRule.provenance`` to a ``FieldAnchor``.

        Reserved for the eventual structured business-rule pipeline
        (see Phase 6 scope notes). Today's ``business_rules`` field is
        a list[str] with no per-element anchor slot, so this helper
        isn't called yet — kept here so the contract for Source D is
        documented and ready for follow-up.
        """
        prov = rule.provenance
        if prov is None:
            return None
        return FieldAnchor(
            line=prov.line,
            end_line=prov.end_line,
            column=prov.column,
            snippet=prov.snippet or "",
            segment_id=prov.file_path or "",
        )

    def _set_field(
        self,
        el: FusedElement,
        field_name: str,
        value: str,
        source: str,
        confidence: float,
        anchor: Optional[FieldAnchor] = None,
    ) -> None:
        """Set a field on a FusedElement, handling conflict detection.

        Per PLAYBOOK §4: if the field already has a value from a different
        source, detect the conflict and resolve by priority order.

        Phase 6: callers may pass ``anchor`` to record the location
        within the source artifact where the field's value came from.
        Conflict resolution preserves the *winner's* anchor (so a
        loser's location data is dropped).
        """
        new_prov = FieldProvenance(
            source=source,
            confidence=confidence,
            original_value=value,
            anchor=anchor,
        )

        if field_name not in el.field_provenance:
            # First source to provide this field — no conflict
            el.field_provenance[field_name] = new_prov
            self._apply_value(el, field_name, value)
            return

        existing = el.field_provenance[field_name]

        # Same source updating its own field (e.g. Source B enriching
        # Source B's own citation) — no conflict
        if existing.source == source:
            el.field_provenance[field_name] = new_prov
            self._apply_value(el, field_name, value)
            return

        # Different source, different value → conflict
        if existing.original_value.strip().lower() == value.strip().lower():
            # Same value from different source — no real conflict,
            # just add the source to provenance
            return

        # Real conflict — resolve per PLAYBOOK §4
        winner, loser, reason = self._resolve_conflict(
            existing, new_prov,
        )
        el.conflicts.append(
            FieldConflict(
                field_name=field_name,
                winner=winner,
                rejected=[loser],
                resolution=reason,
            )
        )
        el.field_provenance[field_name] = winner
        self._apply_value(el, field_name, winner.original_value)

    def _resolve_conflict(
        self,
        existing: FieldProvenance,
        new: FieldProvenance,
    ) -> tuple[FieldProvenance, FieldProvenance, str]:
        """Resolve a conflict between two field values.

        Returns (winner, loser, resolution_reason).
        """
        # Rule 1: priority order
        try:
            existing_pri = self.priority.index(existing.source)
            new_pri = self.priority.index(new.source)
        except ValueError:
            existing_pri = new_pri = 99

        if existing_pri < new_pri:
            return existing, new, "priority"
        if new_pri < existing_pri:
            return new, existing, "priority"

        # Rule 2: confidence
        if existing.confidence > new.confidence:
            return existing, new, "confidence"
        if new.confidence > existing.confidence:
            return new, existing, "confidence"

        # Rule 3: recency — newer wins (later in the pipeline = newer)
        # Since we process A → B → C → D in order, the new value is
        # always more recent when we reach this point.
        return new, existing, "recency"

    @staticmethod
    def _apply_value(el: FusedElement, field_name: str, value: str) -> None:
        """Write a resolved value to the FusedElement's typed field."""
        if field_name == "element_name":
            el.element_name = value
        elif field_name == "domain_name":
            el.domain_name = value
        elif field_name == "definition":
            el.definition = value
        elif field_name == "citation":
            el.citation = value
        elif field_name == "is_critical":
            el.is_critical = value.lower() in ("true", "yes", "y", "1")
        elif field_name == "data_type":
            el.data_type = value
        elif field_name == "mandatory_optional":
            el.extra_fields["mandatory_optional"] = value
