"""Tests for the fusion layer (Step 6).

The fusion layer combines Sources A, B, C, D into a rich data dictionary.
These tests verify:
  - Source A concepts seed the element list
  - Source B governance records validate and enrich Source A concepts
  - Source C schema fields add data_type, enum_values, mandatory_optional
  - Source D code rules attach as business_rules
  - Conflicts between sources are detected and resolved per PLAYBOOK §4
  - Name normalisation enables cross-source matching
  - Unmatched items are tracked for gap reporting
"""

from __future__ import annotations

from dataclasses import field

import pytest

from ontozense.core.fusion import (
    FusedElement,
    FusionEngine,
    FusionResult,
    normalise_name,
)
from ontozense.extractors.domain_doc_extractor import (
    Concept,
    DomainDocumentExtractionResult,
    FieldConfidence,
    Provenance,
    Relationship,
)
from ontozense.extractors.governance_extractor import (
    GovernanceExtractionResult,
    GovernanceRecord,
)
from ontozense.core.source_c import (
    SchemaField,
    SchemaModel,
    SchemaRelationship,
    SchemaResult,
)
from ontozense.extractors.code_extractor import (
    CodeExtractionResult,
    CodeProvenance,
    CodeRule,
)


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _concept(name: str, definition: str = "", citation: str = "") -> Concept:
    c = Concept(name=name, definition=definition, citation=citation)
    c.confidence.append(FieldConfidence("name", 0.95, "verbatim"))
    if definition:
        c.confidence.append(FieldConfidence("definition", 0.95, "verbatim"))
    else:
        c.confidence.append(FieldConfidence("definition", 0.0, "missing"))
    c.provenance = Provenance(
        source_document="test.md",
        extraction_timestamp="2026-04-12T00:00:00",
    )
    return c


def _source_a(*concepts, domain="Test Domain", relationships=None):
    return DomainDocumentExtractionResult(
        domain_name=domain,
        concepts=list(concepts),
        relationships=list(relationships or []),
        source_documents=["test.md"],
        extraction_timestamp="2026-04-12T00:00:00",
    )


def _source_b(*records):
    return GovernanceExtractionResult(
        source_file="governance.json",
        records=list(records),
        extraction_timestamp="2026-04-12T00:00:00",
    )


def _gov(name, definition="", is_critical=False, citation="", **extra):
    return GovernanceRecord(
        element_name=name,
        definition=definition,
        is_critical=is_critical,
        citation=citation,
        extra_fields=extra,
        source_file="governance.json",
    )


def _source_c(*models):
    return SchemaResult(models=list(models), source_dir="models/")


def _schema_model(name, fields, doc="", relationships=None):
    return SchemaModel(
        name=name,
        doc=doc,
        fields=list(fields),
        relationships=list(relationships or []),
    )


def _schema_field(name, ptype="string", nullable=True, choices=None):
    return SchemaField(
        name=name,
        field_type="CharField",
        playground_type=ptype,
        is_nullable=nullable,
        choices_values=list(choices or []),
    )


def _source_d(*rules):
    return CodeExtractionResult(
        rules=list(rules),
        files_scanned=["test.py"],
        extraction_timestamp="2026-04-12T00:00:00",
    )


def _code_rule(name, rule_type="constant", expression="", value=None,
               symbols=None, citations=None, docstring=""):
    return CodeRule(
        rule_type=rule_type,
        name=name,
        expression=expression or f"{name} = {value!r}",
        value=value,
        referenced_symbols=list(symbols or []),
        citations=list(citations or []),
        docstring=docstring,
        provenance=CodeProvenance(file_path="test.py", line=1),
    )


# ─── Name normalisation ─────────────────────────────────────────────────────


class TestNormaliseName:
    def test_lowercase(self):
        assert normalise_name("Default") == "default"

    def test_underscore_to_space(self):
        assert normalise_name("customer_id") == "customer id"

    def test_hyphen_to_space(self):
        assert normalise_name("non-performing") == "non performing"

    def test_collapse_whitespace(self):
        assert normalise_name("  customer   identifier  ") == "customer identifier"

    def test_mixed(self):
        assert normalise_name("CUSTOMER_ID") == "customer id"
        assert normalise_name("Customer-Identifier") == "customer identifier"


# ─── Source A only (minimum viable fusion) ───────────────────────────────────


class TestSourceAOnly:
    def test_concepts_become_elements(self):
        a = _source_a(
            _concept("Default", "A status indicating inability to pay."),
            _concept("Exposure"),
        )
        result = FusionEngine().fuse(source_a=a)
        assert len(result.elements) == 2
        names = {e.element_name for e in result.elements}
        assert "Default" in names
        assert "Exposure" in names

    def test_definition_carried_through(self):
        a = _source_a(_concept("Default", "The formal definition."))
        result = FusionEngine().fuse(source_a=a)
        el = result.get_element("Default")
        assert el.definition == "The formal definition."

    def test_domain_name_from_source_a(self):
        a = _source_a(_concept("X"), domain="Risk Management")
        result = FusionEngine().fuse(source_a=a)
        assert result.elements[0].domain_name == "Risk Management"

    def test_relationships_carried_through(self):
        rel = Relationship(subject="A", predicate="relates_to", object="B")
        rel.confidence.append(FieldConfidence("triple", 0.95, "test"))
        a = _source_a(_concept("A"), _concept("B"), relationships=[rel])
        result = FusionEngine().fuse(source_a=a)
        assert len(result.relationships) == 1
        assert result.relationships[0].subject == "A"

    def test_sources_used_tracks_a(self):
        a = _source_a(_concept("X"))
        result = FusionEngine().fuse(source_a=a)
        assert "A" in result.sources_used

    def test_empty_source_a_produces_empty_result(self):
        a = _source_a()
        result = FusionEngine().fuse(source_a=a)
        assert len(result.elements) == 0

    def test_no_sources_produces_empty_result(self):
        result = FusionEngine().fuse()
        assert len(result.elements) == 0
        assert result.sources_used == []


# ─── Source A + B (governance validation) ────────────────────────────────────


class TestSourceAB:
    def test_matching_record_marks_governance_validated(self):
        a = _source_a(_concept("Default", "From regulation."))
        b = _source_b(_gov("Default", "From governance.", is_critical=True))
        result = FusionEngine().fuse(source_a=a, source_b=b)
        el = result.get_element("Default")
        assert el.governance_validated is True
        assert el.is_critical is True

    def test_governance_definition_enriches_when_both_present(self):
        a = _source_a(_concept("Default", "Source A definition."))
        b = _source_b(_gov("Default", "Source B definition."))
        result = FusionEngine().fuse(source_a=a, source_b=b)
        el = result.get_element("Default")
        # Conflict: A has priority over B per default order
        assert len(el.conflicts) >= 1

    def test_governance_adds_is_critical(self):
        a = _source_a(_concept("Default"))
        b = _source_b(_gov("Default", is_critical=True))
        result = FusionEngine().fuse(source_a=a, source_b=b)
        assert result.get_element("Default").is_critical is True

    def test_governance_citations_merged(self):
        a = _source_a(_concept("Default", citation="Section 5"))
        b = _source_b(_gov("Default", citation="Collibra, A-LEX"))
        result = FusionEngine().fuse(source_a=a, source_b=b)
        el = result.get_element("Default")
        assert "Section 5" in el.citation
        assert "Collibra" in el.citation

    def test_unmatched_governance_record_creates_element(self):
        a = _source_a(_concept("Default"))
        b = _source_b(
            _gov("Default"),
            _gov("Forbearance", "A governance-only term."),
        )
        result = FusionEngine().fuse(source_a=a, source_b=b)
        assert len(result.elements) == 2
        forb = result.get_element("Forbearance")
        assert forb is not None
        assert forb.definition == "A governance-only term."
        assert len(result.unmatched_governance) == 1

    def test_case_insensitive_matching(self):
        a = _source_a(_concept("Default"))
        b = _source_b(_gov("default", is_critical=True))
        result = FusionEngine().fuse(source_a=a, source_b=b)
        el = result.get_element("Default")
        assert el.governance_validated is True

    def test_underscore_normalisation_matching(self):
        a = _source_a(_concept("Customer Identifier"))
        b = _source_b(_gov("customer_identifier", is_critical=True))
        result = FusionEngine().fuse(source_a=a, source_b=b)
        el = result.get_element("Customer Identifier")
        assert el.governance_validated is True

    def test_extra_fields_from_governance_preserved(self):
        a = _source_a(_concept("Default"))
        b = _source_b(_gov("Default", custom_field="custom_value"))
        result = FusionEngine().fuse(source_a=a, source_b=b)
        el = result.get_element("Default")
        assert el.extra_fields.get("gov_custom_field") == "custom_value"


# ─── Source A + C (schema enrichment) ────────────────────────────────────────


class TestSourceAC:
    def test_schema_field_enriches_matching_concept(self):
        a = _source_a(_concept("status", "The account status."))
        c = _source_c(_schema_model("Account", [
            _schema_field("status", "string", nullable=False,
                          choices=["active", "inactive"]),
        ]))
        result = FusionEngine().fuse(source_a=a, source_c=c)
        el = result.get_element("status")
        assert el.data_type == "string"
        assert "active" in el.enum_values
        assert "C" in el.sources

    def test_schema_mandatory_from_not_nullable(self):
        a = _source_a(_concept("email"))
        c = _source_c(_schema_model("User", [
            _schema_field("email", "string", nullable=False),
        ]))
        result = FusionEngine().fuse(source_a=a, source_c=c)
        el = result.get_element("email")
        assert el.extra_fields.get("mandatory_optional") == "M"

    def test_unmatched_schema_field_creates_element(self):
        a = _source_a(_concept("Default"))
        c = _source_c(_schema_model("Account", [
            _schema_field("balance", "decimal"),
        ]))
        result = FusionEngine().fuse(source_a=a, source_c=c)
        assert len(result.elements) == 2
        assert result.get_element("balance") is not None
        assert len(result.unmatched_schema_fields) == 1

    def test_schema_relationships_carried_through(self):
        c = _source_c(_schema_model("Account", [
            _schema_field("id", "integer"),
        ], relationships=[
            SchemaRelationship(
                field_name="owner",
                from_model="Account",
                to_model="Customer",
            ),
        ]))
        result = FusionEngine().fuse(source_c=c)
        fk_rels = [r for r in result.relationships if r.source == "C"]
        assert fk_rels
        assert fk_rels[0].subject == "Account"
        assert fk_rels[0].object == "Customer"


# ─── Source A + D (business rules from code) ─────────────────────────────────


class TestSourceAD:
    def test_code_rule_matches_concept_by_name(self):
        a = _source_a(_concept("threshold days"))
        d = _source_d(
            _code_rule("THRESHOLD_DAYS", value=90),
        )
        result = FusionEngine().fuse(source_a=a, source_d=d)
        el = result.get_element("threshold days")
        assert el.business_rules
        # Tycho 1.0+: business_rules is list[BusinessRule]; the
        # human-readable description carries the same content the
        # pre-1.0 list[str] had.
        assert "90" in el.business_rules[0].description
        assert "D" in el.sources

    def test_code_rule_matches_by_referenced_symbol(self):
        a = _source_a(_concept("status"))
        d = _source_d(
            _code_rule("classify", rule_type="function",
                       symbols=["record.status", "threshold"],
                       docstring="Classify a record by its status."),
        )
        result = FusionEngine().fuse(source_a=a, source_d=d)
        el = result.get_element("status")
        assert el.business_rules
        assert "classify" in el.business_rules[0].description

    def test_unmatched_code_rule_tracked(self):
        a = _source_a(_concept("Default"))
        d = _source_d(
            _code_rule("TOTALLY_UNRELATED", value=42),
        )
        result = FusionEngine().fuse(source_a=a, source_d=d)
        assert len(result.unmatched_code_rules) == 1

    def test_code_citations_in_business_rule_description(self):
        a = _source_a(_concept("threshold days"))
        d = _source_d(
            _code_rule("THRESHOLD_DAYS", value=90,
                       citations=["Section 14"]),
        )
        result = FusionEngine().fuse(source_a=a, source_d=d)
        el = result.get_element("threshold days")
        assert "Section 14" in el.business_rules[0].description


# ─── Conflict resolution (PLAYBOOK §4) ──────────────────────────────────────


class TestConflictResolution:
    def test_priority_wins_a_over_b(self):
        """Default priority A > B. If both provide definition, A wins."""
        a = _source_a(_concept("Default", "A's definition."))
        b = _source_b(_gov("Default", "B's definition."))
        result = FusionEngine().fuse(source_a=a, source_b=b)
        el = result.get_element("Default")
        assert el.definition == "A's definition."
        assert len(el.conflicts) >= 1
        assert el.conflicts[0].resolution == "priority"

    def test_custom_priority_b_over_a(self):
        """With priority ["B", "A", ...], B wins."""
        a = _source_a(_concept("Default", "A's definition."))
        b = _source_b(_gov("Default", "B's definition."))
        engine = FusionEngine(priority_order=["B", "A", "C", "D"])
        result = engine.fuse(source_a=a, source_b=b)
        el = result.get_element("Default")
        assert el.definition == "B's definition."

    def test_rejected_values_preserved(self):
        a = _source_a(_concept("Default", "A's definition."))
        b = _source_b(_gov("Default", "B's definition."))
        result = FusionEngine().fuse(source_a=a, source_b=b)
        el = result.get_element("Default")
        conflict = el.conflicts[0]
        assert conflict.rejected[0].original_value == "B's definition."

    def test_same_value_no_conflict(self):
        """If both sources provide the same value, no conflict is raised."""
        a = _source_a(_concept("Default", "Same definition."))
        b = _source_b(_gov("Default", "Same definition."))
        result = FusionEngine().fuse(source_a=a, source_b=b)
        el = result.get_element("Default")
        assert len(el.conflicts) == 0


# ─── Full 4-source fusion ───────────────────────────────────────────────────


class TestFullFusion:
    def test_all_four_sources(self):
        a = _source_a(
            _concept("status", "The account status."),
            _concept("Default", "Inability to pay."),
        )
        b = _source_b(
            _gov("Default", "Governance definition.", is_critical=True,
                 citation="Collibra"),
        )
        c = _source_c(_schema_model("Account", [
            _schema_field("status", "string", nullable=False,
                          choices=["active", "inactive"]),
        ]))
        d = _source_d(
            _code_rule("STATUS_ACTIVE", value="active"),
        )
        result = FusionEngine().fuse(
            source_a=a, source_b=b, source_c=c, source_d=d,
        )
        assert result.sources_used == ["A", "B", "C", "D"]
        assert len(result.elements) >= 2

        # "status" should be enriched by A + C + D
        el_status = result.get_element("status")
        assert el_status is not None
        assert el_status.definition == "The account status."
        assert el_status.data_type == "string"

        # "Default" should be validated by B
        el_default = result.get_element("Default")
        assert el_default.governance_validated is True
        assert el_default.is_critical is True

    def test_confidence_recomputed_after_fusion(self):
        a = _source_a(_concept("Default", "A definition."))
        result = FusionEngine().fuse(source_a=a)
        el = result.get_element("Default")
        assert 0.0 < el.confidence <= 1.0

    def test_fusion_timestamp_populated(self):
        result = FusionEngine().fuse(source_a=_source_a(_concept("X")))
        assert result.fusion_timestamp

    def test_governance_validated_count(self):
        a = _source_a(_concept("A"), _concept("B"), _concept("C"))
        b = _source_b(_gov("A"), _gov("B"))
        result = FusionEngine().fuse(source_a=a, source_b=b)
        assert result.governance_validated_count == 2

    def test_conflict_count(self):
        a = _source_a(_concept("Default", "A version."))
        b = _source_b(_gov("Default", "B version."))
        result = FusionEngine().fuse(source_a=a, source_b=b)
        assert result.conflict_count >= 1
