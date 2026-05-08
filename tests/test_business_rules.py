"""Tests for typed BusinessRule (Tycho 1.0+ wrap-up #1).

Pre-1.0 ``FusedElement.business_rules`` was ``list[str]``. The
wrap-up restructured it to ``list[BusinessRule]`` — a typed
dataclass carrying rule_type, name, expression, description, value,
referenced_symbols, citations, docstring, confidence, and an
optional FieldAnchor. This file covers:

  - The dataclass shape and defaults
  - Source D ``CodeRule`` → ``BusinessRule`` conversion via
    ``_build_business_rule``, including anchor extraction
  - JSON serialise / deserialise round-trip
  - Backward-compat fallback when reading a pre-1.0 list[str] payload
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ontozense.core.fusion import (
    BusinessRule,
    FieldAnchor,
    FusedElement,
    FusedRelationship,
    FusionEngine,
    FusionResult,
)
from ontozense.extractors.code_extractor import (
    CodeExtractionResult,
    CodeProvenance,
    CodeRule,
)
from ontozense.extractors.domain_doc_extractor import (
    Concept,
    DomainDocumentExtractionResult,
    FieldConfidence,
)


# ─── Helpers ────────────────────────────────────────────────────────────────


def _concept(name: str, definition: str = "") -> Concept:
    c = Concept(name=name, definition=definition)
    c.confidence.append(FieldConfidence("name", 0.9, "v"))
    return c


def _doc(concepts: list[Concept]) -> DomainDocumentExtractionResult:
    return DomainDocumentExtractionResult(
        domain_name="t", concepts=concepts,
        extraction_timestamp="2026-05-08T00:00:00",
    )


# ─── 1. Shape ──────────────────────────────────────────────────────────────


class TestBusinessRuleShape:
    def test_minimal_construction(self):
        br = BusinessRule(
            rule_type="constant", name="X",
            expression="X = 1", description="[constant] X = 1",
        )
        assert br.value is None
        assert br.referenced_symbols == []
        assert br.citations == []
        assert br.docstring == ""
        assert br.confidence == 0.95
        assert br.anchor is None

    def test_full_construction(self):
        anchor = FieldAnchor(line=42, column=4, segment_id="rules.py")
        br = BusinessRule(
            rule_type="conditional", name="check_default",
            expression="dpd > 90",
            description="[conditional] dpd > 90",
            value="True", referenced_symbols=["loan.dpd"],
            citations=["Reg X §3"], docstring="Default flag.",
            confidence=0.92, anchor=anchor,
        )
        assert br.anchor.line == 42
        assert br.referenced_symbols == ["loan.dpd"]


# ─── 2. Source D conversion + anchor threading ─────────────────────────────


class TestSourceDToBusinessRule:
    """Phase 6 defined ``_anchor_from_code_provenance`` but didn't
    thread it. Tycho 1.0+ activates it: every CodeRule with
    provenance produces a BusinessRule with a populated anchor."""

    def test_code_rule_with_provenance_yields_anchored_business_rule(self):
        sa = _doc([_concept("Loan", "A debt instrument.")])
        prov = CodeProvenance(
            file_path="rules/loan.py", line=42, column=4,
            end_line=44, snippet="LOAN_MAX_DAYS = 365",
        )
        # ``referenced_symbols=["Loan"]`` so fusion's name-match
        # fallback attaches this rule to the "Loan" concept.
        rule = CodeRule(
            rule_type="constant", name="LOAN_MAX_DAYS",
            expression="LOAN_MAX_DAYS = 365", value=365,
            referenced_symbols=["Loan"],
            provenance=prov,
        )
        sd = CodeExtractionResult(rules=[rule])
        r = FusionEngine().fuse(source_a=sa, source_d=sd)

        el = r.elements[0]
        assert len(el.business_rules) == 1
        br = el.business_rules[0]
        # Typed payload
        assert isinstance(br, BusinessRule)
        assert br.rule_type == "constant"
        assert br.name == "LOAN_MAX_DAYS"
        assert br.value == "365"
        # Anchor came through from CodeProvenance
        assert br.anchor is not None
        assert br.anchor.line == 42
        assert br.anchor.column == 4
        assert br.anchor.end_line == 44
        assert "LOAN_MAX_DAYS" in br.anchor.snippet
        assert br.anchor.segment_id == "rules/loan.py"

    def test_code_rule_without_provenance_yields_no_anchor(self):
        sa = _doc([_concept("Loan", "x")])
        rule = CodeRule(
            rule_type="constant", name="LOAN",
            expression="LOAN = 1", value=1,
        )
        sd = CodeExtractionResult(rules=[rule])
        r = FusionEngine().fuse(source_a=sa, source_d=sd)
        br = r.elements[0].business_rules[0]
        assert br.anchor is None

    def test_referenced_symbol_match_still_produces_typed_rule(self):
        """The fallback symbol-matching path also produces a typed
        rule, not a bare string."""
        sa = _doc([_concept("status")])
        rule = CodeRule(
            rule_type="function", name="classify",
            expression="def classify(record):",
            referenced_symbols=["record.status"],
            docstring="Classify a record by status.",
        )
        sd = CodeExtractionResult(rules=[rule])
        r = FusionEngine().fuse(source_a=sa, source_d=sd)
        el = r.elements[0]
        assert len(el.business_rules) == 1
        assert isinstance(el.business_rules[0], BusinessRule)
        assert el.business_rules[0].name == "classify"


# ─── 3. JSON round-trip ────────────────────────────────────────────────────


class TestJsonRoundTrip:
    def _make_element(self) -> FusedElement:
        return FusedElement(
            element_name="Loan",
            definition="A debt instrument.",
            sources=["A", "D"],
            confidence=0.9,
            business_rules=[
                BusinessRule(
                    rule_type="constant", name="LOAN_MAX_DAYS",
                    expression="LOAN_MAX_DAYS = 365",
                    description="[constant] LOAN_MAX_DAYS = 365 [loan.py:42]",
                    value="365",
                    citations=["Reg X §3.2"],
                    anchor=FieldAnchor(line=42, segment_id="loan.py"),
                ),
                BusinessRule(
                    rule_type="conditional", name="check_default",
                    expression="dpd > 90",
                    description="[conditional] dpd > 90",
                    referenced_symbols=["loan.dpd"],
                ),
            ],
        )

    def test_serialise_then_reconstruct_preserves_typed_rules(self, tmp_path):
        from ontozense.cli import _serialize_element, _reconstruct_fusion_result

        el = self._make_element()
        raw = _serialize_element(el)
        # Confirm JSON-friendly shape
        assert isinstance(raw["business_rules"], list)
        assert raw["business_rules"][0]["rule_type"] == "constant"
        assert raw["business_rules"][0]["anchor"]["line"] == 42
        # Second rule has no anchor → no anchor key emitted (AC1
        # parity with FieldAnchor serialisation)
        assert "anchor" not in raw["business_rules"][1]

        # Round-trip via _reconstruct_fusion_result
        round_tripped = _reconstruct_fusion_result({
            "fusion_timestamp": "", "sources_used": ["A", "D"],
            "summary": {}, "elements": [raw], "relationships": [],
        })
        rt_el = round_tripped.elements[0]
        assert len(rt_el.business_rules) == 2
        assert isinstance(rt_el.business_rules[0], BusinessRule)
        assert rt_el.business_rules[0].name == "LOAN_MAX_DAYS"
        assert rt_el.business_rules[0].anchor.line == 42
        assert rt_el.business_rules[1].anchor is None

    def test_pre_1_0_legacy_string_payload_loads_as_minimal_business_rule(self):
        """A fused JSON written by pre-1.0 Tycho contains
        ``business_rules: ["…"]`` (raw strings). Tycho 1.0
        reconstruction wraps each string in a minimal BusinessRule
        with only ``description`` set, so old artefacts still load."""
        from ontozense.cli import _reconstruct_fusion_result

        raw = {
            "fusion_timestamp": "", "sources_used": ["D"],
            "summary": {},
            "elements": [{
                "element_name": "Old",
                "business_rules": ["[constant] THRESHOLD = 90"],
                "extra_fields": {},
                "is_critical": False, "citation": "",
                "data_type": "", "enum_values": [],
                "governance_validated": False, "confidence": 0.0,
                "sources": ["D"], "needs_review": False,
                "conflicts": [],
            }],
            "relationships": [],
        }
        result = _reconstruct_fusion_result(raw)
        el = result.elements[0]
        assert len(el.business_rules) == 1
        br = el.business_rules[0]
        assert isinstance(br, BusinessRule)
        assert br.description == "[constant] THRESHOLD = 90"
        # Other fields default
        assert br.rule_type == ""
        assert br.anchor is None


# ─── 4. Query rendering (handles both shapes) ──────────────────────────────


class TestQueryRendering:
    def test_typed_business_rules_render_via_description(self):
        from ontozense.core.query import query_element

        el = FusedElement(
            element_name="X",
            sources=["A", "D"], confidence=0.8,
            business_rules=[
                BusinessRule(
                    rule_type="constant", name="X_MAX",
                    expression="X_MAX = 7",
                    description="[constant] X_MAX = 7",
                ),
            ],
        )
        r = FusionResult(
            elements=[el], relationships=[], sources_used=["A", "D"],
        )
        md = query_element(r, "X")
        assert md is not None
        assert "Business rules" in md
        assert "X_MAX = 7" in md
