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
)
from ..extractors.governance_extractor import (
    GovernanceExtractionResult,
    GovernanceRecord,
)
from .source_c import SchemaField, SchemaModel, SchemaResult
from ..extractors.code_extractor import CodeExtractionResult, CodeRule
from .attribute import (
    Attribute,
    FieldProvenance as AttrFieldProvenance,
    xsd_type_for_python,
    xsd_type_for_sql,
)
from .source_d import SourceDAttribute, SourceDEntity, SourceDResult


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
class BusinessRule:
    """One business rule attached to an entity (Tycho 1.0+).

    Replaces the pre-1.0 ``list[str]`` shape on ``FusedElement.business_rules``.
    Carries enough structure for downstream tooling to render the rule
    differently from the human-readable description, jump back to the
    source line via the anchor, and group rules by ``rule_type``.

    The wrap-up activates the dormant ``_anchor_from_code_provenance``
    helper Phase 6 defined: every CodeRule that lands on a fused
    element now contributes its (file, line, column, end_line, snippet)
    as a ``FieldAnchor`` here.
    """
    rule_type: str          # "constant", "conditional", "function", "sql_check", ...
    name: str               # e.g. "NPE_DPD_THRESHOLD"
    expression: str         # source-text expression
    description: str        # human-readable rendering (was list[str] item)
    # ``value`` preserves the original CodeRule.value type — int, float,
    # bool, str, list, dict — so a numeric threshold like ``90`` stays
    # an int and downstream tooling can consume it as structured data
    # rather than presentation text. Round-trip safe through JSON for
    # all primitive types and JSON-serialisable containers.
    value: Optional[Any] = None
    referenced_symbols: list[str] = field(default_factory=list)
    citations: list[str] = field(default_factory=list)
    docstring: str = ""
    confidence: float = 0.95
    anchor: Optional[FieldAnchor] = None


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
    business_rules: list[BusinessRule] = field(default_factory=list)
    extra_fields: dict[str, Any] = field(default_factory=dict)

    # ── Provenance & quality ──
    sources: list[str] = field(default_factory=list)
    field_provenance: dict[str, FieldProvenance] = field(default_factory=dict)
    conflicts: list[FieldConflict] = field(default_factory=list)
    governance_validated: bool = False

    # ── Per-attribute typed properties (PR2 of property extraction) ──
    # Populated by ``attach_attributes_to_elements`` from the deterministic
    # Source C / D / B discovery artifacts. Empty when no matching
    # Source C table / Source D class / Source B record carries
    # attribute metadata. PR3 projects each Attribute into one
    # ``owl:DatatypeProperty`` on the OWL output. Default ``[]`` so
    # legacy code paths and fused.json files without an attributes key
    # round-trip cleanly.
    attributes: list[Attribute] = field(default_factory=list)

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
            # Phase 6 wrap-up #2: thread the record's source_anchor
            # (the (line, column, file) of this entry in the
            # governance JSON) through to every B-contributed field.
            b_anchor = getattr(rec, "source_anchor", None)
            el = self._lookup(index, id_lookup, eid=rec.id, name=rec.element_name)
            if el is not None:
                # Governance-validated: this Source A concept exists in
                # the governance system.
                el.governance_validated = True

                # Source B definition may be richer than Source A's
                if rec.definition:
                    self._set_field(
                        el, "definition", rec.definition, "B", rec.confidence,
                        b_anchor,
                    )

                # is_critical comes from Source B only
                if rec.is_critical:
                    el.is_critical = True
                    self._set_field(
                        el, "is_critical", "true", "B", rec.confidence,
                        b_anchor,
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
                    # Record provenance without conflict detection.
                    # Preserve A's anchor if it had one (still points
                    # at A's citation span); otherwise fall back to B's
                    # anchor so the combined citation has *some*
                    # location data.
                    existing = el.field_provenance.get(
                        "citation", FieldProvenance("", 0, ""),
                    )
                    el.field_provenance["citation"] = FieldProvenance(
                        source="A+B",
                        confidence=max(existing.confidence, rec.confidence),
                        original_value=el.citation,
                        anchor=existing.anchor or b_anchor,
                    )

                if rec.domain_name:
                    self._set_field(
                        el, "domain_name", rec.domain_name, "B", rec.confidence,
                        b_anchor,
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
                        b_anchor,
                    )
                if rec.domain_name:
                    self._set_field(
                        el, "domain_name", rec.domain_name, "B", rec.confidence,
                        b_anchor,
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
            # Build a typed BusinessRule with the human-readable
            # description and the FieldAnchor derived from the rule's
            # CodeProvenance (file, line, column, end_line, snippet).
            br = self._build_business_rule(rule)

            # Profile-mode: Phase 3 may have already attached this rule
            # to an entity ID via _apply_profile. Try id-first.
            attached_id = getattr(rule, "attached_to_entity_id", "")

            el = self._lookup(
                index, id_lookup, eid=attached_id, name=rule.name,
            )
            if el is not None:
                el.business_rules.append(br)
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
                        sym_el.business_rules.append(br)
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

    @classmethod
    def _build_business_rule(cls, rule: CodeRule) -> BusinessRule:
        """Convert a Source D ``CodeRule`` to a typed ``BusinessRule``.

        Activates the dormant ``_anchor_from_code_provenance`` helper
        defined in Phase 6 so per-rule source coordinates land on the
        ``BusinessRule.anchor`` field. ``description`` is the existing
        ``_rule_to_description`` output — preserved so downstream
        consumers (lint, query, report) can still display rules as
        plain strings via ``br.description``.
        """
        return BusinessRule(
            rule_type=rule.rule_type,
            name=rule.name,
            expression=rule.expression,
            description=cls._rule_to_description(rule),
            # Preserve the original Python type — int, bool, list, etc.
            # The previous implementation flattened to str(); the
            # post-1.0 review (round 4) flagged that as lossy when
            # callers want a numeric threshold or boolean flag as
            # structured data, not display text.
            value=rule.value,
            referenced_symbols=list(rule.referenced_symbols),
            citations=list(rule.citations),
            docstring=rule.docstring,
            confidence=rule.confidence,
            anchor=cls._anchor_from_code_provenance(rule),
        )

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
        # Strip whitespace so values like "   " are treated as empty —
        # otherwise ``is_empty()`` would consider them populated and
        # the JSON serialiser would emit a useless anchor key.
        section = (prov.source_section or "").strip()
        snippet = (prov.source_text_snippet or "").strip()
        if not (section or snippet):
            return None
        return FieldAnchor(
            segment_id=section,
            snippet=snippet,
        )

    @staticmethod
    def _anchor_from_code_provenance(
        rule: CodeRule,
    ) -> Optional[FieldAnchor]:
        """Map a Source D ``CodeRule.provenance`` to a ``FieldAnchor``.

        Tycho 1.0+: called by ``_build_business_rule`` so every typed
        ``BusinessRule`` carries the source coordinates of the
        constant / conditional / function / SQL clause it came from.
        Pre-1.0 this was a documented stub waiting for the structured
        business-rule shape to land.
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


# ─── PR2: attribute-level fusion ────────────────────────────────────────────
#
# Property extraction Phase A (PR2). Mutates an existing FusionResult
# in place, populating ``FusedElement.attributes`` from the deterministic
# discovery artifacts:
#
#   - Source C ``SchemaResult``   (typed columns + PKs + FKs + enum from CHECK)
#   - Source D ``SourceDResult``  (typed fields + descriptions + Pydantic /
#                                   dataclass / SQLA metadata captured by PR1a)
#   - Source B ``GovernanceExtractionResult`` (governance records whose
#     ``extra_fields["data_type"]`` and ``extra_fields["enum_values"]``
#     carry attribute info — Codex r3 fallback)
#
# Precedence (per design §5 + Codex r1 resolution of Open Question #4):
#   * Source C wins storage facts:
#       xsd_type, is_nullable, is_id (PK), enum_values from DB CHECK.
#   * Source D wins description and contributes is_multivalued when
#     C is silent.
#   * Source B is a silent fallback used only when C and D are both
#     absent for a given attribute; B-only attributes carry
#     confidence = 0.7 (lower than the 1.0 used for deterministic
#     C / D extractions).
#
# Matching is **exact + normalised name only** (Codex hard constraint
# for Phase A — no fuzzy match). Element-to-table-or-class match keys
# the lookup; attribute-name match within the entity uses the same
# rule.
#
# B-only attributes have an extra wrinkle: governance records expose
# their data via ``extra_fields["data_type"]`` (str) and
# ``extra_fields["enum_values"]`` (list[str] | comma-string |
# semicolon-string | malformed). The helper deterministically
# normalises every supported shape and skips silently for malformed
# input.


_B_ATTR_DEFAULT_CONFIDENCE = 0.7


def _normalise_b_enum_values(raw: Any) -> list[str] | None:
    """Coerce ``extra_fields["enum_values"]`` to a list[str].

    Per Codex round-3 implementation caution, governance.json may
    supply enum_values as:
      - ``list``                → use as-is (stringified)
      - ``str``                 → split on ``;`` first, then ``,``
      - anything else           → unsupported; return None

    Returns ``None`` when the shape is unsupported so the caller can
    skip the attribute and log via the existing conflicts channel.
    """
    if raw is None:
        return None
    if isinstance(raw, list):
        return [str(v).strip() for v in raw if str(v).strip()]
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return None
        delim = ";" if ";" in s else ","
        return [tok.strip() for tok in s.split(delim) if tok.strip()]
    return None


def _normalise_b_data_type(raw: Any) -> str | None:
    """Coerce ``extra_fields["data_type"]`` to a str.

    Non-str input → None (caller skips the attribute).
    """
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return None


def _attribute_from_schema_field(
    sf: "SchemaField", model_name: str, artifact: str,
) -> Attribute:
    """Build an Attribute from a Source C SchemaField — the C-side of
    the precedence rule (storage facts)."""
    enum = list(sf.choices_values) if sf.choices_values else []
    raw_type = sf.field_type or ""
    return Attribute(
        name=sf.name,
        xsd_type=xsd_type_for_sql(raw_type) if raw_type else "xsd:string",
        description="",
        is_id=bool(sf.is_primary_key),
        is_multivalued=False,
        is_nullable=bool(sf.is_nullable),
        enum_values=enum,
        raw_type=raw_type,
        field_provenance=[AttrFieldProvenance(
            source="C",
            artifact=artifact,
            line=0,
            confidence=1.0,
            extractor="ddl",
        )],
        confidence=1.0,
    )


def _attribute_from_source_d(
    sa: "SourceDAttribute", entity_name: str, artifact: str,
) -> Attribute:
    """Build an Attribute from a Source D SourceDAttribute — the D-side
    of the precedence rule (description + multivalued fallback)."""
    py = (sa.raw_type or "").strip()
    return Attribute(
        name=sa.name,
        xsd_type=xsd_type_for_python(py) if py else "xsd:string",
        description=sa.description,
        is_id=bool(sa.is_pk),
        is_multivalued=bool(sa.is_multivalued),
        is_nullable=bool(sa.is_nullable),
        enum_values=list(sa.enum_values),
        raw_type=py,
        field_provenance=[AttrFieldProvenance(
            source="D",
            artifact=artifact,
            line=sa.line,
            confidence=1.0,
            extractor="ast",
        )],
        confidence=1.0,
    )


def _merge_attribute_c_into_d(
    c_attr: Attribute, d_attr: Attribute,
) -> tuple[Attribute, list[FieldConflict]]:
    """Merge a C-side Attribute and a D-side Attribute for the same
    column / field name.

    Returns the merged Attribute and a list of any FieldConflict
    records produced when C and D disagreed on a storage fact.

    Precedence (design §5 / Codex r1):
      * xsd_type    — C wins (storage truth). D-side recorded in
                      conflicts when types differ.
      * is_id       — C wins.
      * is_nullable — C wins.
      * enum_values — C wins when populated; else D.
      * raw_type    — C wins.
      * description — D wins when populated; else C.
      * is_multivalued — D wins when True (collection annotation is a
                      strong signal C-side rarely carries cleanly).
      * field_provenance — both contributing sources retained.
    """
    conflicts: list[FieldConflict] = []

    merged = Attribute(
        name=c_attr.name,
        xsd_type=c_attr.xsd_type,
        description=d_attr.description or c_attr.description,
        is_id=c_attr.is_id,
        is_multivalued=d_attr.is_multivalued or c_attr.is_multivalued,
        is_nullable=c_attr.is_nullable,
        enum_values=(
            list(c_attr.enum_values) if c_attr.enum_values
            else list(d_attr.enum_values)
        ),
        raw_type=c_attr.raw_type or d_attr.raw_type,
        field_provenance=list(c_attr.field_provenance) + list(d_attr.field_provenance),
        confidence=1.0,
    )

    if c_attr.xsd_type != d_attr.xsd_type:
        c_fp = c_attr.field_provenance[0] if c_attr.field_provenance else None
        d_fp = d_attr.field_provenance[0] if d_attr.field_provenance else None
        if c_fp and d_fp:
            conflicts.append(FieldConflict(
                field_name=f"{c_attr.name}.xsd_type",
                winner=FieldProvenance(
                    source=c_fp.source,
                    confidence=c_fp.confidence,
                    original_value=c_attr.xsd_type,
                ),
                rejected=[FieldProvenance(
                    source=d_fp.source,
                    confidence=d_fp.confidence,
                    original_value=d_attr.xsd_type,
                )],
                resolution="priority",
            ))

    return merged, conflicts


def _attach_b_only_attributes(
    element: FusedElement,
    governance_records: list["GovernanceRecord"],
) -> None:
    """Populate B-only attributes on ``element`` from governance records
    whose ``extra_fields["data_type"]`` is populated, when C and D
    haven't already supplied an attribute set.

    Shape guards (per Codex r1 review on PR2):
      * ``extra_fields["data_type"]`` present but non-str → skip + log
        a FieldConflict so the curator sees the malformed input.
      * ``extra_fields["enum_values"]`` present but malformed (dict /
        number / nested object) → skip + log.
      * Both keys absent → silent no-op (the governance record carried
        no attribute hint).
    """
    if element.attributes:
        return  # C/D already populated; B is silent fallback
    if not governance_records:
        return
    target = normalise_name(element.element_name)
    for rec in governance_records:
        if normalise_name(rec.element_name) != target:
            continue
        data_type_raw = rec.extra_fields.get("data_type")
        data_type = _normalise_b_data_type(data_type_raw)
        enum_raw = rec.extra_fields.get("enum_values")
        enum_values = _normalise_b_enum_values(enum_raw)

        # Shape guards: present-but-malformed → log + skip.
        # "Malformed" means the wrong type (non-str for data_type,
        # not-list-or-str for enum_values). An empty string is a
        # *valid* type that simply carries no content — that's a
        # silent no-op, not a contract violation, so we don't log it.
        data_type_malformed = (
            data_type_raw is not None
            and not isinstance(data_type_raw, str)
        )
        enum_malformed = enum_raw is not None and enum_values is None
        if data_type_malformed:
            element.conflicts.append(FieldConflict(
                field_name=f"{element.element_name}.b_data_type",
                winner=FieldProvenance("B", 0.0, ""),
                rejected=[],
                resolution="unresolved",
            ))
        if enum_malformed:
            element.conflicts.append(FieldConflict(
                field_name=f"{element.element_name}.b_enum_values",
                winner=FieldProvenance("B", 0.0, ""),
                rejected=[],
                resolution="unresolved",
            ))
        if data_type_malformed or enum_malformed:
            # Don't materialise an attribute from a malformed record —
            # the conflict is logged and the curator gets a chance to
            # fix the governance JSON.
            continue

        if data_type is None and enum_values is None:
            continue
        # Surface as a single Attribute named after the governance
        # record's element so B carries some signal forward. Phase A
        # treats B as a fallback marker, not a column enumerator.
        xsd = xsd_type_for_sql(data_type) if data_type else "xsd:string"
        element.attributes.append(Attribute(
            name=rec.element_name,
            xsd_type=xsd,
            description=rec.definition or "",
            is_id=False,
            is_multivalued=False,
            is_nullable=True,
            enum_values=enum_values or [],
            raw_type=data_type or "",
            field_provenance=[AttrFieldProvenance(
                source="B",
                artifact="governance.json",
                line=0,
                confidence=_B_ATTR_DEFAULT_CONFIDENCE,
                extractor="governance",
            )],
            confidence=_B_ATTR_DEFAULT_CONFIDENCE,
        ))
        break  # one B record per element


def attach_attributes_to_elements(
    fused: FusionResult,
    *,
    schema: SchemaResult | None = None,
    source_d: SourceDResult | None = None,
    governance: GovernanceExtractionResult | None = None,
) -> None:
    """Mutate ``fused`` in place, populating each FusedElement's
    ``attributes`` list from the deterministic Source C/D/B discovery
    artifacts.

    Matching is exact + normalised name only (Codex hard constraint).
    Element-to-table-or-class match keys the lookup; attribute-name
    match within the entity uses the same rule.

    Per-attribute conflict between C and D on storage facts is logged
    to the FusedElement.conflicts list using the existing
    FieldConflict shape.

    Phase A scope: only attaches attributes to elements that already
    exist in the FusionResult. Source-D-only entities (a Python class
    present in code but with no matching FusedElement) are not
    promoted to new elements here — that's deferred.
    """
    # Build name → SchemaModel / SourceDEntity lookup tables.
    c_index: dict[str, "SchemaModel"] = {}
    if schema is not None:
        for m in schema.models:
            c_index[normalise_name(m.name)] = m

    d_index: dict[str, "SourceDEntity"] = {}
    if source_d is not None:
        for e in source_d.entities:
            d_index[normalise_name(e.name)] = e

    governance_records: list["GovernanceRecord"] = (
        list(governance.records) if governance is not None else []
    )

    for element in fused.elements:
        key = normalise_name(element.element_name)
        c_model = c_index.get(key)
        d_entity = d_index.get(key)

        if c_model is None and d_entity is None:
            # Neither C nor D matched: try Source B fallback.
            _attach_b_only_attributes(element, governance_records)
            continue

        # Collect C-side attributes by normalised column name.
        c_attrs: dict[str, Attribute] = {}
        if c_model is not None:
            for sf in c_model.fields:
                c_attrs[normalise_name(sf.name)] = _attribute_from_schema_field(
                    sf, model_name=c_model.name,
                    artifact=c_model.source_file or "",
                )

        # Collect D-side attributes by normalised attribute name.
        d_attrs: dict[str, Attribute] = {}
        if d_entity is not None:
            for da in d_entity.attributes:
                d_attrs[normalise_name(da.name)] = _attribute_from_source_d(
                    da, entity_name=d_entity.name,
                    artifact=d_entity.source_file or "",
                )

        # Merge by name. C-only / D-only kept as-is; C+D merged with
        # conflicts surfaced on the element.
        merged: list[Attribute] = []
        all_keys = sorted(set(c_attrs.keys()) | set(d_attrs.keys()))
        for k in all_keys:
            c_attr = c_attrs.get(k)
            d_attr = d_attrs.get(k)
            if c_attr and d_attr:
                merged_attr, conflicts = _merge_attribute_c_into_d(
                    c_attr, d_attr,
                )
                merged.append(merged_attr)
                element.conflicts.extend(conflicts)
            elif c_attr:
                merged.append(c_attr)
            elif d_attr:
                merged.append(d_attr)

        element.attributes = merged
