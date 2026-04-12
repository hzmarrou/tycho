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


@dataclass
class FieldProvenance:
    """Where a single field value came from."""
    source: str          # "A", "B", "C", "D"
    confidence: float
    original_value: str  # the raw value from the source


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
        source_a: DomainDocumentExtractionResult | None = None,
        source_b: GovernanceExtractionResult | None = None,
        source_c: SchemaResult | None = None,
        source_d: CodeExtractionResult | None = None,
    ) -> FusionResult:
        result = FusionResult(
            fusion_timestamp=datetime.utcnow().isoformat(),
        )

        # Track which sources were provided
        if source_a:
            result.sources_used.append("A")
        if source_b:
            result.sources_used.append("B")
        if source_c:
            result.sources_used.append("C")
        if source_d:
            result.sources_used.append("D")

        # Build an index of fused elements keyed by normalised name
        index: dict[str, FusedElement] = {}

        # ── Pass 1: Seed from Source A ──
        if source_a:
            self._merge_source_a(source_a, index, result)

        # ── Pass 2: Validate/enrich from Source B ──
        if source_b:
            self._merge_source_b(source_b, index, result)

        # ── Pass 3: Enrich from Source C ──
        if source_c:
            self._merge_source_c(source_c, index, result)

        # ── Pass 4: Attach business rules from Source D ──
        if source_d:
            self._merge_source_d(source_d, index, result)

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
        result: FusionResult,
    ) -> None:
        for concept in source_a.concepts:
            if not concept.name.strip():
                continue
            key = normalise_name(concept.name)
            el = self._get_or_create(index, concept.name)
            conf = concept.overall_confidence()

            self._set_field(el, "element_name", concept.name, "A", conf)

            if concept.definition:
                self._set_field(el, "definition", concept.definition, "A", conf)

            if concept.citation:
                self._set_field(el, "citation", concept.citation, "A", conf)

            if source_a.domain_name:
                self._set_field(
                    el, "domain_name", source_a.domain_name, "A", conf,
                )

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
        result: FusionResult,
    ) -> None:
        for rec in source_b.records:
            key = normalise_name(rec.element_name)
            if key in index:
                # Governance-validated: this Source A concept exists in
                # the governance system.
                el = index[key]
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

                if "B" not in el.sources:
                    el.sources.append("B")
            else:
                # Governance-only term: exists in governance but Source A
                # didn't extract it. Add as a new element.
                el = self._get_or_create(index, rec.element_name)
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
                el.governance_validated = True
                el.sources.append("B")
                # Also track as unmatched for the gap report
                result.unmatched_governance.append(rec)

    # ── Source C: enrich from schema ─────────────────────────────────────

    def _merge_source_c(
        self,
        source_c: SchemaResult,
        index: dict[str, FusedElement],
        result: FusionResult,
    ) -> None:
        for model in source_c.models:
            for sf in model.fields:
                key = normalise_name(sf.name)
                if key in index:
                    el = index[key]
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
                    if "C" not in el.sources:
                        el.sources.append("C")
                else:
                    # Schema-only field: not mentioned in Source A or B.
                    # Add as a new element with schema provenance.
                    el = self._get_or_create(index, sf.name)
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
        result: FusionResult,
    ) -> None:
        for rule in source_d.rules:
            matched = False
            rule_desc = self._rule_to_description(rule)
            key = normalise_name(rule.name)

            # Try direct name match first
            if key in index:
                index[key].business_rules.append(rule_desc)
                if "D" not in index[key].sources:
                    index[key].sources.append("D")
                matched = True
            else:
                # Try matching by referenced symbols
                for sym in rule.referenced_symbols:
                    sym_key = normalise_name(sym.split(".")[-1])
                    if sym_key in index:
                        index[sym_key].business_rules.append(rule_desc)
                        if "D" not in index[sym_key].sources:
                            index[sym_key].sources.append("D")
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
        self, index: dict[str, FusedElement], name: str
    ) -> FusedElement:
        key = normalise_name(name)
        if key not in index:
            index[key] = FusedElement(element_name=name.strip())
        return index[key]

    def _set_field(
        self,
        el: FusedElement,
        field_name: str,
        value: str,
        source: str,
        confidence: float,
    ) -> None:
        """Set a field on a FusedElement, handling conflict detection.

        Per PLAYBOOK §4: if the field already has a value from a different
        source, detect the conflict and resolve by priority order.
        """
        new_prov = FieldProvenance(
            source=source,
            confidence=confidence,
            original_value=value,
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
