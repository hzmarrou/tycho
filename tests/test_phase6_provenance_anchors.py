"""Tests for Phase 6: per-field provenance anchors.

Pins three things:

1. **Shape** — ``FieldAnchor`` dataclass with eight optional fields,
   ``is_empty()`` correctness, frozen semantics.
2. **Threading** — when a Source A ``Concept.provenance`` carries
   anchor-shaped data (``source_section`` / ``source_text_snippet``),
   it propagates to ``FieldProvenance.anchor`` for every Source-A
   field on the resulting fused element. Conflict resolution
   preserves the *winner's* anchor.
3. **AC1** — when no upstream extractor populates anchor data, the
   serialised JSON output has NO ``anchor`` key on any conflict
   provenance — byte-identical to pre-Phase-6 output. JSON
   round-trip preserves anchors when present.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ontozense.core.fusion import (
    FieldAnchor,
    FieldProvenance,
    FusedElement,
    FusionEngine,
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


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _concept_with_anchor(
    name: str,
    *,
    definition: str = "",
    citation: str = "",
    source_doc: str = "doc1.md",
    section: str = "",
    snippet: str = "",
    confidence: float = 0.9,
) -> Concept:
    c = Concept(
        name=name,
        definition=definition,
        citation=citation,
    )
    c.confidence.append(FieldConfidence("name", confidence, "v"))
    c.provenance = Provenance(
        source_document=source_doc,
        source_section=section,
        source_text_snippet=snippet,
        extraction_timestamp="2026-05-06T00:00:00",
    )
    return c


def _doc(domain: str, concepts: list[Concept]) -> DomainDocumentExtractionResult:
    return DomainDocumentExtractionResult(
        domain_name=domain,
        concepts=concepts,
        extraction_timestamp="2026-05-06T00:00:00",
    )


# ─── 1. FieldAnchor shape ────────────────────────────────────────────────────


class TestFieldAnchorShape:
    def test_default_anchor_is_empty(self):
        a = FieldAnchor()
        assert a.is_empty()

    def test_any_field_makes_non_empty(self):
        assert not FieldAnchor(page=1).is_empty()
        assert not FieldAnchor(line=42).is_empty()
        assert not FieldAnchor(segment_id="intro").is_empty()
        assert not FieldAnchor(snippet="hello").is_empty()
        assert not FieldAnchor(char_offset=100).is_empty()

    def test_frozen(self):
        """FieldAnchor is frozen — anchors are immutable values."""
        from dataclasses import FrozenInstanceError
        a = FieldAnchor(page=1)
        with pytest.raises(FrozenInstanceError):
            a.page = 2  # type: ignore[misc]

    def test_equality_by_value(self):
        a = FieldAnchor(page=1, line=10, snippet="x")
        b = FieldAnchor(page=1, line=10, snippet="x")
        c = FieldAnchor(page=1, line=10, snippet="y")
        assert a == b
        assert a != c

    def test_default_field_values(self):
        a = FieldAnchor()
        assert a.page == 0
        assert a.char_offset == 0
        assert a.char_length == 0
        assert a.line == 0
        assert a.end_line == 0
        assert a.column == 0
        assert a.segment_id == ""
        assert a.snippet == ""


# ─── 2. FieldProvenance carries optional anchor ─────────────────────────────


class TestFieldProvenanceAnchor:
    def test_anchor_defaults_to_none(self):
        """Pre-Phase-6 callers don't pass anchor — it stays None."""
        fp = FieldProvenance(source="A", confidence=0.9, original_value="x")
        assert fp.anchor is None

    def test_anchor_can_be_set(self):
        fp = FieldProvenance(
            source="A", confidence=0.9, original_value="x",
            anchor=FieldAnchor(page=3, snippet="hello"),
        )
        assert fp.anchor is not None
        assert fp.anchor.page == 3
        assert fp.anchor.snippet == "hello"


# ─── 3. Source A → FieldProvenance.anchor threading ─────────────────────────


class TestSourceAAnchorThreading:
    def test_concept_with_section_yields_anchor(self):
        """When Concept.provenance carries source_section, the fused
        FieldProvenance for definition/citation/element_name gets a
        FieldAnchor with segment_id populated."""
        sa = _doc(
            "t",
            [_concept_with_anchor(
                "Customer",
                definition="A buyer.",
                section="3.2 Definitions",
                snippet="Customer means a natural or legal person who...",
            )],
        )
        r = FusionEngine().fuse(source_a=sa)
        el = r.elements[0]
        # Internal field_provenance is the source of truth for anchors
        prov = el.field_provenance.get("definition")
        assert prov is not None
        assert prov.anchor is not None
        assert prov.anchor.segment_id == "3.2 Definitions"
        assert "Customer means" in prov.anchor.snippet

    def test_concept_with_no_anchor_data_yields_none(self):
        """Source-document name alone is NOT anchor data (it's tracked
        elsewhere). Concept.provenance with only source_document but
        no section / snippet / page → anchor stays None."""
        sa = _doc(
            "t",
            [_concept_with_anchor(
                "X",
                definition="d",
                source_doc="doc1.md",
                section="",
                snippet="",
            )],
        )
        r = FusionEngine().fuse(source_a=sa)
        el = r.elements[0]
        assert el.field_provenance["definition"].anchor is None

    def test_concept_without_provenance_yields_no_anchor(self):
        sa = _doc(
            "t",
            [Concept(name="X", definition="d")],
        )
        r = FusionEngine().fuse(source_a=sa)
        el = r.elements[0]
        assert el.field_provenance["definition"].anchor is None

    def test_whitespace_only_section_is_treated_as_empty(self):
        """Regression for review minor: 'source_section'='   ' must
        not create a synthetic anchor with segment_id='   ' that the
        JSON serialiser would then emit. Whitespace = empty."""
        sa = _doc(
            "t",
            [_concept_with_anchor(
                "X",
                definition="d",
                section="   ",
                snippet="\n\t  ",
            )],
        )
        r = FusionEngine().fuse(source_a=sa)
        el = r.elements[0]
        assert el.field_provenance["definition"].anchor is None

    def test_section_is_stripped_when_real_content_present(self):
        """Leading/trailing whitespace around real content is stripped
        from segment_id and snippet."""
        sa = _doc(
            "t",
            [_concept_with_anchor(
                "X",
                definition="d",
                section="  3.2 Definitions  ",
                snippet="  Customer means...  ",
            )],
        )
        r = FusionEngine().fuse(source_a=sa)
        anchor = r.elements[0].field_provenance["definition"].anchor
        assert anchor is not None
        assert anchor.segment_id == "3.2 Definitions"
        assert anchor.snippet == "Customer means..."


# ─── 4. Conflict resolution preserves the winner's anchor ───────────────────


class TestConflictWinnerAnchor:
    def test_priority_winner_keeps_its_anchor(self):
        """Source A wins by priority over Source B (default order
        A>B>C>D). When both provide a definition, A's anchor wins."""
        sa = _doc(
            "t",
            [_concept_with_anchor(
                "Customer",
                definition="A buyer (per regulation X §3.2).",
                section="3.2 Definitions",
                snippet="Customer means...",
            )],
        )
        sb = GovernanceExtractionResult(
            records=[GovernanceRecord(
                element_name="Customer",
                domain_name="t",
                definition="A registered buyer.",
                is_critical=True,
                confidence=0.9,
            )],
        )
        r = FusionEngine().fuse(source_a=sa, source_b=sb)
        el = r.elements[0]
        # A's definition wins by priority — A's anchor must be retained
        defn_prov = el.field_provenance["definition"]
        assert defn_prov.source == "A"
        assert defn_prov.anchor is not None
        assert defn_prov.anchor.segment_id == "3.2 Definitions"
        # The conflict record also preserves the winner's anchor
        conflict = next(
            c for c in el.conflicts if c.field_name == "definition"
        )
        assert conflict.winner.anchor is not None
        assert conflict.winner.anchor.segment_id == "3.2 Definitions"

    def test_source_b_citation_merge_preserves_source_a_anchor(self):
        """Regression for review major: when Source B contributes an
        additive citation to a Source A element, the resulting
        ``A+B``-tagged FieldProvenance must still carry A's original
        citation anchor. Pre-fix the merge constructed a new
        FieldProvenance without the anchor, silently losing
        provenance data."""
        sa = _doc(
            "t",
            [_concept_with_anchor(
                "Customer",
                definition="A buyer.",
                citation="Reg X §3.2",
                section="3.2 Definitions",
                snippet="Customer means a natural or legal person...",
            )],
        )
        sb = GovernanceExtractionResult(
            records=[GovernanceRecord(
                element_name="Customer",
                domain_name="t",
                citation="GOV-CAT-2026-01",
                is_critical=True,
                confidence=0.95,
            )],
        )
        r = FusionEngine().fuse(source_a=sa, source_b=sb)
        el = r.elements[0]
        # Combined citation has both texts
        assert "Reg X §3.2" in el.citation
        assert "GOV-CAT-2026-01" in el.citation
        # The combined provenance is tagged A+B
        cit_prov = el.field_provenance["citation"]
        assert cit_prov.source == "A+B"
        # Crucially: A's anchor is preserved (no anchor data loss)
        assert cit_prov.anchor is not None
        assert cit_prov.anchor.segment_id == "3.2 Definitions"
        assert "Customer means" in cit_prov.anchor.snippet


# ─── 5. AC1 byte-identity in serialised output ──────────────────────────────


class TestAc1SerialisedShape:
    def test_no_anchor_means_no_anchor_key_in_conflict_serialisation(self):
        """When no upstream extractor populates anchor data, the
        serialised conflict winner / rejected entries do NOT include
        an ``anchor`` key. Pre-Phase-6 output is byte-identical."""
        from ontozense.cli import _serialize_field_provenance
        fp = FieldProvenance(source="A", confidence=0.9, original_value="x")
        out = _serialize_field_provenance(fp)
        assert out == {"source": "A", "value": "x"}
        assert "anchor" not in out

    def test_empty_anchor_is_also_suppressed(self):
        """An anchor with all-default fields is functionally absent —
        suppress the key to maintain shape parity."""
        from ontozense.cli import _serialize_field_provenance
        fp = FieldProvenance(
            source="A", confidence=0.9, original_value="x",
            anchor=FieldAnchor(),  # all-defaults
        )
        out = _serialize_field_provenance(fp)
        assert "anchor" not in out

    def test_non_empty_anchor_is_serialised(self):
        from ontozense.cli import _serialize_field_provenance
        fp = FieldProvenance(
            source="A", confidence=0.9, original_value="x",
            anchor=FieldAnchor(page=5, segment_id="3.2", snippet="hi"),
        )
        out = _serialize_field_provenance(fp)
        assert out["anchor"]["page"] == 5
        assert out["anchor"]["segment_id"] == "3.2"
        assert out["anchor"]["snippet"] == "hi"
        # All optional fields included for round-trip clarity
        assert out["anchor"]["line"] == 0
        assert out["anchor"]["char_offset"] == 0


# ─── 6. JSON round-trip preserves anchors ───────────────────────────────────


class TestJsonRoundTrip:
    def test_roundtrip_preserves_anchor(self, tmp_path):
        from ontozense.cli import (
            _serialize_field_provenance,
            _reconstruct_fusion_result,
        )

        # Construct a FusionResult-shaped dict with one element and
        # one conflict whose winner has an anchor; round-trip via
        # serialise → JSON dump → JSON load → _reconstruct_fusion_result.
        fp = FieldProvenance(
            source="A", confidence=0.9, original_value="A's def",
            anchor=FieldAnchor(
                page=5, line=42, segment_id="3.2", snippet="hi",
            ),
        )
        winner_dict = _serialize_field_provenance(fp)
        loser_dict = _serialize_field_provenance(
            FieldProvenance(source="B", confidence=0.8, original_value="B's def"),
        )
        raw = {
            "fusion_timestamp": "2026-05-06T00:00:00",
            "sources_used": ["A", "B"],
            "summary": {},
            "elements": [{
                "element_name": "X",
                "definition": "A's def",
                "is_critical": False,
                "citation": "",
                "data_type": "",
                "enum_values": [],
                "business_rules": [],
                "governance_validated": True,
                "confidence": 0.9,
                "sources": ["A", "B"],
                "needs_review": False,
                "conflicts": [{
                    "field": "definition",
                    "winner": winner_dict,
                    "rejected": [loser_dict],
                    "resolution": "priority",
                }],
                "extra_fields": {},
            }],
            "relationships": [],
        }
        # Round-trip through JSON
        roundtripped = json.loads(json.dumps(raw))
        result = _reconstruct_fusion_result(roundtripped)

        el = result.elements[0]
        assert len(el.conflicts) == 1
        c = el.conflicts[0]
        assert c.winner.anchor is not None
        assert c.winner.anchor.page == 5
        assert c.winner.anchor.line == 42
        assert c.winner.anchor.segment_id == "3.2"
        # Loser had no anchor — stays None on round-trip
        assert c.rejected[0].anchor is None

    def test_roundtrip_no_anchor_key_in_old_json(self):
        """Reading pre-Phase-6 JSON (no ``anchor`` key on conflicts)
        must not crash and must yield FieldProvenance.anchor = None."""
        from ontozense.cli import _reconstruct_fusion_result

        raw = {
            "fusion_timestamp": "2026-05-06T00:00:00",
            "sources_used": ["A", "B"],
            "summary": {},
            "elements": [{
                "element_name": "X",
                "definition": "v",
                "is_critical": False,
                "citation": "",
                "data_type": "",
                "enum_values": [],
                "business_rules": [],
                "governance_validated": False,
                "confidence": 0.9,
                "sources": ["A", "B"],
                "needs_review": False,
                "conflicts": [{
                    "field": "definition",
                    # Pre-Phase-6 shape: no anchor key
                    "winner": {"source": "A", "value": "v"},
                    "rejected": [{"source": "B", "value": "v2"}],
                    "resolution": "priority",
                }],
                "extra_fields": {},
            }],
            "relationships": [],
        }
        result = _reconstruct_fusion_result(raw)
        c = result.elements[0].conflicts[0]
        assert c.winner.anchor is None
        assert c.rejected[0].anchor is None


# ─── Source B anchor threading (wrap-up #2) ─────────────────────────────────


class TestSourceBAnchorThreading:
    """Pins that a GovernanceRecord's ``source_anchor`` lands on the
    fused element's ``field_provenance`` for every B-contributed field
    (definition, citation, domain_name, is_critical), and that the
    citation merge path preserves it when A is absent or anchorless."""

    def test_b_only_record_attaches_anchor_to_definition(self):
        """B-only term: A didn't extract it. The new fused element
        gets B's anchor on its definition / citation / etc."""
        from ontozense.core.fusion import FusionEngine
        from ontozense.extractors.governance_extractor import (
            GovernanceExtractionResult, GovernanceRecord,
        )

        b_anchor = FieldAnchor(line=12, column=5, segment_id="gov.json")
        sb = GovernanceExtractionResult(
            records=[GovernanceRecord(
                element_name="Solo",
                domain_name="t",
                definition="A B-only term.",
                citation="GOV-2026",
                is_critical=True,
                confidence=0.95,
                source_anchor=b_anchor,
            )],
        )
        r = FusionEngine().fuse(source_b=sb)
        el = r.elements[0]
        defn_prov = el.field_provenance["definition"]
        assert defn_prov.source == "B"
        assert defn_prov.anchor == b_anchor

    def test_a_plus_b_citation_merge_falls_back_to_b_anchor_when_a_unanchored(self):
        """When Source A had no anchor on its citation but Source B
        does, the combined ``A+B`` provenance carries B's anchor."""
        from ontozense.core.fusion import FusionEngine
        from ontozense.extractors.governance_extractor import (
            GovernanceExtractionResult, GovernanceRecord,
        )
        from ontozense.extractors.domain_doc_extractor import (
            Concept, DomainDocumentExtractionResult, FieldConfidence,
        )

        # A contributes citation but no anchor
        c = Concept(name="Customer", definition="A buyer.", citation="Reg X")
        c.confidence.append(FieldConfidence("name", 0.9, "v"))
        sa = DomainDocumentExtractionResult(domain_name="t", concepts=[c])

        b_anchor = FieldAnchor(line=42, column=3, segment_id="gov.json")
        sb = GovernanceExtractionResult(
            records=[GovernanceRecord(
                element_name="Customer",
                citation="GOV-CAT",
                confidence=0.95,
                source_anchor=b_anchor,
            )],
        )
        r = FusionEngine().fuse(source_a=sa, source_b=sb)
        el = r.elements[0]
        cit_prov = el.field_provenance["citation"]
        assert cit_prov.source == "A+B"
        # A had no anchor → B's anchor takes over
        assert cit_prov.anchor == b_anchor

    def test_a_anchor_wins_over_b_in_citation_merge(self):
        """When Source A has its own citation anchor, the merge keeps
        A's (it points at the original extraction span). Pinned by
        the existing Phase 6 fix; replicated here against a real
        Source B anchor."""
        from ontozense.core.fusion import FusionEngine
        from ontozense.extractors.governance_extractor import (
            GovernanceExtractionResult, GovernanceRecord,
        )
        from ontozense.extractors.domain_doc_extractor import (
            Concept, DomainDocumentExtractionResult, FieldConfidence,
            Provenance,
        )

        c = Concept(name="Customer", definition="A buyer.", citation="Reg X")
        c.confidence.append(FieldConfidence("name", 0.9, "v"))
        c.provenance = Provenance(
            source_document="docA.md",
            source_section="3.2",
            source_text_snippet="Customer means…",
        )
        sa = DomainDocumentExtractionResult(domain_name="t", concepts=[c])

        b_anchor = FieldAnchor(line=42, segment_id="gov.json")
        sb = GovernanceExtractionResult(
            records=[GovernanceRecord(
                element_name="Customer",
                citation="GOV-CAT",
                confidence=0.95,
                source_anchor=b_anchor,
            )],
        )
        r = FusionEngine().fuse(source_a=sa, source_b=sb)
        el = r.elements[0]
        cit_prov = el.field_provenance["citation"]
        # A's anchor wins
        assert cit_prov.anchor.segment_id == "3.2"
        assert cit_prov.anchor.snippet.startswith("Customer means")
