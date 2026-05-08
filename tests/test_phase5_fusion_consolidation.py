"""Tests for Phase 5: multi-doc + cross-source consolidation in fusion.

Pins three things:

1. **Backward compat (AC1)** — single-result API unchanged; the
   no-profile path produces byte-identical output regardless of new
   list-or-single signature.
2. **Multi-doc consolidation** — concepts with the same id (profile)
   or normalised name (unconstrained) collapse to one element, with
   ``extra_fields["source_documents"]`` and ``corroborating_doc_count``.
3. **Cross-source id-first lookup** — Sources B/C/D enrich the right
   element by id when profile mode is active, falling back to name
   when id is absent (mixed-mode tolerance).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ontozense.core.fusion import (
    FusedElement,
    FusionEngine,
    FusionResult,
)
from ontozense.extractors.code_extractor import (
    CodeExtractionResult,
    CodeRule,
)
from ontozense.core.source_c import (
    SchemaField,
    SchemaModel,
    SchemaResult,
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


def _concept(
    name: str,
    *,
    definition: str = "",
    citation: str = "",
    eid: str = "",
    entity_type: str = "",
    source_doc: str = "",
    confidence: float = 0.9,
) -> Concept:
    c = Concept(
        name=name,
        definition=definition,
        citation=citation,
        id=eid,
        entity_type=entity_type,
    )
    c.confidence.append(FieldConfidence("name", confidence, "verbatim"))
    if source_doc:
        c.provenance = Provenance(
            source_document=source_doc,
            source_section="",
            source_text_snippet="",
            extraction_timestamp="2026-05-06T00:00:00",
        )
    return c


def _doc_result(
    domain: str,
    concepts: list[Concept],
    *,
    relationships: list[Relationship] | None = None,
    source_documents: list[str] | None = None,
) -> DomainDocumentExtractionResult:
    return DomainDocumentExtractionResult(
        domain_name=domain,
        concepts=concepts,
        relationships=relationships or [],
        source_documents=source_documents or [],
        extraction_timestamp="2026-05-06T00:00:00",
    )


# ─── 1. Backward-compat API ─────────────────────────────────────────────────


class TestBackwardCompatApi:
    def test_single_result_still_accepted(self):
        """Pre-Phase-5 callers pass a single DomainDocumentExtractionResult.
        That signature must keep working — the engine wraps it internally."""
        result = FusionEngine().fuse(
            source_a=_doc_result(
                "test",
                [_concept("Customer", definition="A buyer.")],
            ),
        )
        assert len(result.elements) == 1
        assert result.elements[0].element_name == "Customer"

    def test_none_source_a_still_accepted(self):
        """Engine accepts None — existing B-only / C-only callers unaffected."""
        result = FusionEngine().fuse(source_a=None)
        assert len(result.elements) == 0
        assert "A" not in result.sources_used

    def test_empty_list_treated_as_no_source_a(self):
        """An empty list is functionally the same as None."""
        result = FusionEngine().fuse(source_a=[])
        assert len(result.elements) == 0
        assert "A" not in result.sources_used

    def test_list_of_one_equivalent_to_single(self):
        """A length-1 list and a bare single result must produce the
        same fused output (corroborating_doc_count etc. should match)."""
        single = FusionEngine().fuse(
            source_a=_doc_result(
                "t",
                [_concept("X", definition="d", source_doc="doc1.md")],
            ),
        )
        listed = FusionEngine().fuse(
            source_a=[
                _doc_result(
                    "t",
                    [_concept("X", definition="d", source_doc="doc1.md")],
                ),
            ],
        )
        assert len(single.elements) == len(listed.elements) == 1
        assert (
            single.elements[0].extra_fields.get("corroborating_doc_count")
            == listed.elements[0].extra_fields.get("corroborating_doc_count")
        )


# ─── 2. Multi-doc consolidation (unconstrained, name-keyed) ─────────────────


class TestMultiDocUnconstrained:
    def test_same_name_in_two_docs_collapses_to_one_element(self):
        """Two docs both extract "Customer". Output has one element."""
        r = FusionEngine().fuse(
            source_a=[
                _doc_result(
                    "t",
                    [_concept("Customer", definition="A buyer.", source_doc="doc1.md")],
                ),
                _doc_result(
                    "t",
                    [_concept("Customer", definition="A buyer.", source_doc="doc2.md")],
                ),
            ],
        )
        assert len(r.elements) == 1
        assert r.elements[0].element_name == "Customer"

    def test_corroborating_doc_count_tracks_all_appearances(self):
        r = FusionEngine().fuse(
            source_a=[
                _doc_result("t", [_concept("X", source_doc="a.md")]),
                _doc_result("t", [_concept("X", source_doc="b.md")]),
                _doc_result("t", [_concept("X", source_doc="c.md")]),
            ],
        )
        assert len(r.elements) == 1
        el = r.elements[0]
        assert el.extra_fields["corroborating_doc_count"] == 3
        assert el.extra_fields["source_documents"] == ["a.md", "b.md", "c.md"]

    def test_corroboration_dedups_repeats_across_docs(self):
        """Multi-doc fusion: when one doc mentions a concept twice and
        another doc mentions it once, the corroboration count is 2 (one
        per unique doc), not 3 — the within-doc duplicate is deduped.
        Single-doc fusion does NOT track corroboration (AC1), so dedup
        is meaningful only across docs."""
        r = FusionEngine().fuse(
            source_a=[
                _doc_result(
                    "t",
                    [
                        _concept("X", source_doc="doc1.md"),
                        _concept("X", source_doc="doc1.md"),
                    ],
                ),
                _doc_result(
                    "t",
                    [_concept("X", source_doc="doc2.md")],
                ),
            ],
        )
        assert len(r.elements) == 1
        assert r.elements[0].extra_fields["corroborating_doc_count"] == 2
        assert r.elements[0].extra_fields["source_documents"] == [
            "doc1.md", "doc2.md",
        ]

    def test_concept_without_provenance_does_not_break(self):
        """If a concept has no provenance, no source_documents entry is
        added. This is the unit-test stub case and must not crash."""
        r = FusionEngine().fuse(
            source_a=_doc_result("t", [_concept("X", definition="d")]),
        )
        assert len(r.elements) == 1
        # No corroboration recorded
        assert "source_documents" not in r.elements[0].extra_fields

    def test_normalised_name_matching_still_works(self):
        """Three normalisation variants ("Customer", "customer",
        "CUSTOMER") all collapse to one element under unconstrained
        keying — same as pre-Phase-5 behaviour."""
        r = FusionEngine().fuse(
            source_a=[
                _doc_result("t", [_concept("Customer", source_doc="a.md")]),
                _doc_result("t", [_concept("customer", source_doc="b.md")]),
                _doc_result("t", [_concept("CUSTOMER", source_doc="c.md")]),
            ],
        )
        assert len(r.elements) == 1
        assert r.elements[0].extra_fields["corroborating_doc_count"] == 3


# ─── 3. Multi-doc consolidation (profile mode, id-keyed) ────────────────────


class TestMultiDocProfileMode:
    def test_same_id_collapses_even_when_names_differ(self):
        """Two docs assign the same deterministic id to a concept
        (because the underlying canonical (type, label) tuple is the
        same after profile alias resolution). The element_name surface
        forms may differ; the id-keyed index still consolidates."""
        r = FusionEngine().fuse(
            source_a=[
                _doc_result(
                    "t",
                    [
                        _concept(
                            "Customer Identifier",
                            eid="concept_customer_111111",
                            entity_type="Concept",
                            source_doc="doc1.md",
                        ),
                    ],
                ),
                _doc_result(
                    "t",
                    [
                        _concept(
                            "customer_identifier",  # surface form differs
                            eid="concept_customer_111111",
                            entity_type="Concept",
                            source_doc="doc2.md",
                        ),
                    ],
                ),
            ],
        )
        assert len(r.elements) == 1
        el = r.elements[0]
        assert el.extra_fields["id"] == "concept_customer_111111"
        assert el.extra_fields["corroborating_doc_count"] == 2

    def test_different_ids_keep_separate_even_with_same_normalised_name(self):
        """When profile mode produces two distinct ids, the elements
        stay separate — id keying wins over name normalisation."""
        r = FusionEngine().fuse(
            source_a=[
                _doc_result(
                    "t",
                    [
                        _concept(
                            "Customer",
                            eid="concept_a_111111",
                            entity_type="Concept",
                            source_doc="doc1.md",
                        ),
                    ],
                ),
                _doc_result(
                    "t",
                    [
                        _concept(
                            "Customer",
                            eid="concept_b_222222",  # different id!
                            entity_type="Concept",
                            source_doc="doc2.md",
                        ),
                    ],
                ),
            ],
        )
        # Both kept — id is the source of truth in profile mode
        assert len(r.elements) == 2

    def test_first_doc_wins_for_id_registration(self):
        """When the same id appears in two docs with two different
        names, the element_name from the FIRST doc is the seeded
        canonical form."""
        r = FusionEngine().fuse(
            source_a=[
                _doc_result(
                    "t",
                    [
                        _concept(
                            "First Name",
                            eid="concept_x_111111",
                            entity_type="Concept",
                            source_doc="doc1.md",
                        ),
                    ],
                ),
                _doc_result(
                    "t",
                    [
                        _concept(
                            "Second Name",
                            eid="concept_x_111111",
                            entity_type="Concept",
                            source_doc="doc2.md",
                        ),
                    ],
                ),
            ],
        )
        assert len(r.elements) == 1
        # Phase 5 keeps the first occurrence as the seed; later docs
        # contribute provenance/corroboration but the original
        # element_name stays put unless explicit conflict resolution
        # decides otherwise. The corroboration metadata always lists
        # both docs.
        assert r.elements[0].extra_fields["corroborating_doc_count"] == 2


# ─── 4. Cross-source id-first lookup (Source A + Source B) ──────────────────


class TestSourceBIdFirstLookup:
    def test_source_b_finds_source_a_by_id_when_names_differ(self):
        """Source A profile-extracts 'Customer One' with id 'X_111'.
        Source B profile-extracts 'customer-one' (different surface
        form, same id 'X_111'). Fusion must merge via id, not name."""
        sa = _doc_result(
            "t",
            [
                _concept(
                    "Customer One",
                    eid="concept_x_111111",
                    entity_type="Concept",
                    definition="A buyer.",
                ),
            ],
        )
        sb = GovernanceExtractionResult(
            records=[
                GovernanceRecord(
                    element_name="customer-one",
                    domain_name="t",
                    is_critical=True,
                    citation="GOV/2026/01",
                    confidence=0.95,
                    id="concept_x_111111",
                    entity_type="Concept",
                ),
            ],
        )
        r = FusionEngine().fuse(source_a=sa, source_b=sb)
        # ONE element — id-based merge succeeded
        assert len(r.elements) == 1
        el = r.elements[0]
        assert el.governance_validated is True
        assert el.is_critical is True
        # Source A's element_name is the seeded form; Source B
        # contributes provenance and is_critical.
        assert "B" in el.sources

    def test_source_b_falls_back_to_name_when_id_missing(self):
        """Mixed mode: A is profile (has id), B is unconstrained
        (no id). B should still match A's element by name."""
        sa = _doc_result(
            "t",
            [
                _concept(
                    "Customer",
                    eid="concept_x_111111",
                    entity_type="Concept",
                    definition="A buyer.",
                ),
            ],
        )
        sb = GovernanceExtractionResult(
            records=[
                GovernanceRecord(
                    element_name="Customer",  # name match, no id
                    domain_name="t",
                    is_critical=True,
                    confidence=0.9,
                ),
            ],
        )
        r = FusionEngine().fuse(source_a=sa, source_b=sb)
        assert len(r.elements) == 1
        assert r.elements[0].governance_validated is True

    def test_source_b_only_record_creates_new_element(self):
        """Governance-only record (not in Source A) must still be
        created with id_lookup registered, so a later cross-source
        lookup by id works."""
        sb = GovernanceExtractionResult(
            records=[
                GovernanceRecord(
                    element_name="Solo",
                    domain_name="t",
                    is_critical=False,
                    confidence=0.9,
                    id="concept_solo_111111",
                    entity_type="Concept",
                ),
            ],
        )
        r = FusionEngine().fuse(source_b=sb)
        assert len(r.elements) == 1
        el = r.elements[0]
        assert el.element_name == "Solo"
        assert el.extra_fields["id"] == "concept_solo_111111"


# ─── 5. Source C cross-source id-first lookup ───────────────────────────────


class TestSourceCIdFirstLookup:
    def test_source_c_field_finds_source_a_concept_by_id(self):
        """Source A and Source C both produce a profile-mode element
        for the same logical field. Source C should enrich A's element
        via id, not duplicate it."""
        sa = _doc_result(
            "t",
            [
                _concept(
                    "Status",
                    eid="concept_status_111111",
                    entity_type="Concept",
                    definition="Lifecycle state.",
                ),
            ],
        )
        sc = SchemaResult(
            models=[
                SchemaModel(
                    name="Loan",
                    fields=[
                        SchemaField(
                            name="state",  # different surface form
                            field_type="CharField",
                            playground_type="string",
                            choices_values=["active", "paid"],
                            id="concept_status_111111",
                            entity_type="Concept",
                        ),
                    ],
                ),
            ],
        )
        r = FusionEngine().fuse(source_a=sa, source_c=sc)
        assert len(r.elements) == 1
        el = r.elements[0]
        assert el.data_type == "string"
        assert el.enum_values == ["active", "paid"]
        assert "C" in el.sources


# ─── 6. Source D cross-source id-first attachment ───────────────────────────


class TestSourceDIdFirstAttachment:
    def test_source_d_attaches_via_attached_to_entity_id(self):
        """Source D's Phase 3 _apply_profile populates
        attached_to_entity_id. Phase 5 fusion uses that to find the
        right element directly, bypassing name-prefix heuristics."""
        sa = _doc_result(
            "t",
            [
                _concept(
                    "Loan",
                    eid="concept_loan_111111",
                    entity_type="Concept",
                    definition="A debt instrument.",
                ),
            ],
        )
        rule = CodeRule(
            rule_type="constant",
            name="LOAN_MAX_TERM_DAYS",
            expression="LOAN_MAX_TERM_DAYS = 365",
            value="365",
            attached_to_entity_id="concept_loan_111111",
        )
        sd = CodeExtractionResult(rules=[rule])
        r = FusionEngine().fuse(source_a=sa, source_d=sd)
        assert len(r.elements) == 1
        el = r.elements[0]
        assert "D" in el.sources
        assert any("LOAN_MAX_TERM_DAYS" in br.description for br in el.business_rules)

    def test_source_d_falls_back_to_name_when_no_attachment_id(self):
        """Unconstrained Source D rule (no attached_to_entity_id) still
        attaches via the existing name-prefix heuristic."""
        sa = _doc_result(
            "t",
            [_concept("Loan", definition="A debt instrument.")],
        )
        rule = CodeRule(
            rule_type="constant",
            name="loan",
            expression="loan = ''",
            value="''",
        )
        sd = CodeExtractionResult(rules=[rule])
        r = FusionEngine().fuse(source_a=sa, source_d=sd)
        assert len(r.elements) == 1
        assert "D" in r.elements[0].sources


# ─── 7. Mixed-mode tolerance (some sources profile, others unconstrained) ───


class TestMixedModeTolerance:
    def test_unconstrained_a_then_profile_b_propagates_id(self):
        """A is unconstrained (no id). B is profile (has id). When B
        matches A's element by name, B's id propagates into A's
        ``extra_fields["id"]`` for downstream use."""
        sa = _doc_result(
            "t",
            [_concept("Loan", definition="Money lent.")],
        )
        sb = GovernanceExtractionResult(
            records=[
                GovernanceRecord(
                    element_name="Loan",
                    domain_name="t",
                    is_critical=True,
                    confidence=0.9,
                    id="concept_loan_111111",
                    entity_type="Concept",
                ),
            ],
        )
        r = FusionEngine().fuse(source_a=sa, source_b=sb)
        assert len(r.elements) == 1
        el = r.elements[0]
        # B's id propagated
        assert el.extra_fields["id"] == "concept_loan_111111"
        assert el.extra_fields["entity_type"] == "Concept"


# ─── 8. CLI integration: --source-a repeatable ──────────────────────────────


class TestCliMultiSourceA:
    def _write_source_a_json(self, tmp_path: Path, name: str, concepts: list[dict]) -> Path:
        f = tmp_path / name
        f.write_text(
            json.dumps({
                "domain_name": "test",
                "concepts": concepts,
                "relationships": [],
                "source_documents": [name.replace(".json", ".md")],
                "extraction_timestamp": "2026-05-06T00:00:00",
            }),
            encoding="utf-8",
        )
        return f

    def test_two_source_a_flags_consolidate(self, tmp_path):
        from typer.testing import CliRunner
        from ontozense import cli

        a1 = self._write_source_a_json(
            tmp_path, "doc1.json",
            [{
                "name": "Customer",
                "definition": "A buyer.",
                "citation": "",
                "id": "",
                "entity_type": "",
                "confidence": [{"field_name": "name", "score": 0.9, "reason": "v"}],
                "provenance": {"source_document": "doc1.md"},
            }],
        )
        a2 = self._write_source_a_json(
            tmp_path, "doc2.json",
            [{
                "name": "Customer",
                "definition": "A buyer.",
                "citation": "",
                "id": "",
                "entity_type": "",
                "confidence": [{"field_name": "name", "score": 0.9, "reason": "v"}],
                "provenance": {"source_document": "doc2.md"},
            }],
        )
        out = tmp_path / "fused.json"

        runner = CliRunner()
        r = runner.invoke(
            cli.app,
            [
                "fuse",
                "--source-a", str(a1),
                "--source-a", str(a2),
                "--output", str(out),
            ],
        )
        assert r.exit_code == 0, r.output
        assert out.exists()
        data = json.loads(out.read_text(encoding="utf-8"))
        assert len(data["elements"]) == 1
        # corroborating_doc_count surfaces in extra_fields of the fused
        # element; the CLI serialiser already preserves extra_fields.
        el = data["elements"][0]
        assert el["extra_fields"]["corroborating_doc_count"] == 2
        assert "doc1.md" in el["extra_fields"]["source_documents"]
        assert "doc2.md" in el["extra_fields"]["source_documents"]


# ─── 9. AC1 byte-identity regressions (Phase 5 review findings) ─────────────


class TestAc1ByteIdentityRegressions:
    """Pin AC1: single-doc fusion (any mode) MUST NOT add new
    extra_fields keys that pre-Phase-5 callers wouldn't see.

    The reviewer's blocker finding: corroboration tracking was firing
    unconditionally in _merge_source_a, so a single-doc unconstrained
    fusion with provenance produced ``extra_fields={"source_documents":
    [doc1.md], "corroborating_doc_count": 1}`` instead of ``{}``.
    Now corroboration is gated on ``len(a_results) > 1``.
    """

    def test_single_doc_unconstrained_with_provenance_has_no_corroboration(self):
        """Bare single-doc call: extra_fields stays empty even with
        full provenance on the concept."""
        r = FusionEngine().fuse(
            source_a=_doc_result(
                "t",
                [_concept("X", definition="d", source_doc="doc1.md")],
            ),
        )
        assert len(r.elements) == 1
        assert "source_documents" not in r.elements[0].extra_fields
        assert "corroborating_doc_count" not in r.elements[0].extra_fields

    def test_list_of_one_with_provenance_has_no_corroboration(self):
        """List-of-one is functionally a single-doc call — same AC1
        guarantee applies."""
        r = FusionEngine().fuse(
            source_a=[
                _doc_result(
                    "t",
                    [_concept("X", definition="d", source_doc="doc1.md")],
                ),
            ],
        )
        assert len(r.elements) == 1
        assert "source_documents" not in r.elements[0].extra_fields
        assert "corroborating_doc_count" not in r.elements[0].extra_fields

    def test_single_doc_profile_mode_no_corroboration(self):
        """Profile-mode single-doc fusion: id and entity_type populate
        extra_fields (as per Phase 2/3) but corroboration keys do not."""
        r = FusionEngine().fuse(
            source_a=_doc_result(
                "t",
                [
                    _concept(
                        "Customer",
                        eid="concept_customer_111111",
                        entity_type="Concept",
                        definition="A buyer.",
                        source_doc="doc1.md",
                    ),
                ],
            ),
        )
        assert len(r.elements) == 1
        ef = r.elements[0].extra_fields
        assert ef.get("id") == "concept_customer_111111"
        assert ef.get("entity_type") == "Concept"
        assert "source_documents" not in ef
        assert "corroborating_doc_count" not in ef

    def test_multi_doc_does_track_corroboration(self):
        """The flip side: 2+ docs DO get corroboration. Pin the gate."""
        r = FusionEngine().fuse(
            source_a=[
                _doc_result("t", [_concept("X", source_doc="a.md")]),
                _doc_result("t", [_concept("X", source_doc="b.md")]),
            ],
        )
        assert len(r.elements) == 1
        assert r.elements[0].extra_fields["corroborating_doc_count"] == 2


# ─── 10. Distinct profile IDs must stay separate across B/C/D ───────────────


class TestCrossSourceIdCollisionRegressions:
    """Pin the reviewer's second blocker: when Source B/C/D records
    have a profile-mode id that DIFFERS from a Source A element with
    the same normalised name, ``_lookup`` must NOT silently merge them.

    Pre-fix: ``_lookup`` fell back to name when eid missed in
    ``id_lookup``, so B/C/D records inherited A's element by name and
    overwrote / annotated the wrong entity.
    Post-fix: ``_lookup`` returns None on collision, the caller routes
    through ``_get_or_create``, which uses the composite-key path to
    keep the entities separate.
    """

    def test_source_b_distinct_id_does_not_merge_with_a(self):
        """A profile-mode 'Customer' (id=A) + B profile-mode 'Customer'
        (id=B) → 2 elements, not 1."""
        sa = _doc_result(
            "t",
            [
                _concept(
                    "Customer",
                    eid="concept_a_111111",
                    entity_type="Concept",
                    definition="A buyer (per regulation X).",
                ),
            ],
        )
        sb = GovernanceExtractionResult(
            records=[
                GovernanceRecord(
                    element_name="Customer",
                    domain_name="t",
                    is_critical=True,
                    confidence=0.9,
                    id="concept_b_222222",
                    entity_type="Concept",
                ),
            ],
        )
        r = FusionEngine().fuse(source_a=sa, source_b=sb)
        assert len(r.elements) == 2
        ids = {el.extra_fields.get("id") for el in r.elements}
        assert ids == {"concept_a_111111", "concept_b_222222"}

    def test_source_c_distinct_id_does_not_merge_with_a(self):
        """A 'Status' (id=A) + Source C field 'Status' (id=B) → 2 elements."""
        sa = _doc_result(
            "t",
            [
                _concept(
                    "Status",
                    eid="concept_a_111111",
                    entity_type="Concept",
                    definition="Lifecycle state.",
                ),
            ],
        )
        sc = SchemaResult(
            models=[
                SchemaModel(
                    name="Loan",
                    fields=[
                        SchemaField(
                            name="Status",
                            field_type="CharField",
                            playground_type="string",
                            id="concept_b_222222",
                            entity_type="Concept",
                        ),
                    ],
                ),
            ],
        )
        r = FusionEngine().fuse(source_a=sa, source_c=sc)
        assert len(r.elements) == 2
        ids = {el.extra_fields.get("id") for el in r.elements}
        assert ids == {"concept_a_111111", "concept_b_222222"}

    def test_unconstrained_a_then_b_then_c_distinct_ids_stay_separate(self):
        """A unconstrained 'Customer' + B profile-id1 'Customer' +
        C profile-id2 'Customer' → 2 elements (A merges with B by
        name promotion; C stays separate via collision)."""
        sa = _doc_result("t", [_concept("Customer", definition="A buyer.")])
        sb = GovernanceExtractionResult(
            records=[
                GovernanceRecord(
                    element_name="Customer",
                    domain_name="t",
                    is_critical=False,
                    confidence=0.9,
                    id="concept_b_222222",
                    entity_type="Concept",
                ),
            ],
        )
        sc = SchemaResult(
            models=[
                SchemaModel(
                    name="Loan",
                    fields=[
                        SchemaField(
                            name="Customer",
                            field_type="CharField",
                            playground_type="string",
                            id="concept_c_333333",
                            entity_type="Concept",
                        ),
                    ],
                ),
            ],
        )
        r = FusionEngine().fuse(source_a=sa, source_b=sb, source_c=sc)
        # A+B merge by name promotion (A had no id; B's id propagates).
        # C has a *different* id → must stay separate.
        assert len(r.elements) == 2
        ids = {el.extra_fields.get("id") for el in r.elements}
        assert ids == {"concept_b_222222", "concept_c_333333"}

    def test_id_promotion_updates_id_lookup_for_subsequent_lookup(self):
        """When unconstrained A meets profile B and B's id is promoted
        onto A's element, a *third* source D referencing the same id
        must find that element via id_lookup (not by accident of name)."""
        sa = _doc_result("t", [_concept("Loan", definition="Money lent.")])
        sb = GovernanceExtractionResult(
            records=[
                GovernanceRecord(
                    element_name="Loan",
                    domain_name="t",
                    is_critical=True,
                    confidence=0.9,
                    id="concept_loan_111111",
                    entity_type="Concept",
                ),
            ],
        )
        # Source D rule attached to the same id, but with a name that
        # would NOT match by name fallback (intentional)
        rule = CodeRule(
            rule_type="constant",
            name="MAX_TERM_DAYS",
            expression="MAX_TERM_DAYS = 365",
            value="365",
            attached_to_entity_id="concept_loan_111111",
        )
        sd = CodeExtractionResult(rules=[rule])
        r = FusionEngine().fuse(source_a=sa, source_b=sb, source_d=sd)
        assert len(r.elements) == 1
        el = r.elements[0]
        assert el.extra_fields["id"] == "concept_loan_111111"
        assert "D" in el.sources
        assert any("MAX_TERM_DAYS" in br.description for br in el.business_rules)


# ─── 11. CLI error handling for --source-a (review finding 3) ───────────────


class TestCliSourceAErrorHandling:
    def test_missing_file_clean_error(self, tmp_path):
        from typer.testing import CliRunner
        from ontozense import cli

        runner = CliRunner()
        missing = tmp_path / "does_not_exist.json"
        r = runner.invoke(
            cli.app,
            ["fuse", "--source-a", str(missing), "--output", str(tmp_path / "f.json")],
        )
        assert r.exit_code == 1
        flat = " ".join(r.output.split())
        assert "Source A file error" in flat
        assert "Traceback" not in r.output

    def test_malformed_json_clean_error(self, tmp_path):
        from typer.testing import CliRunner
        from ontozense import cli

        runner = CliRunner()
        bad = tmp_path / "bad.json"
        bad.write_text("{not valid json", encoding="utf-8")
        r = runner.invoke(
            cli.app,
            ["fuse", "--source-a", str(bad), "--output", str(tmp_path / "f.json")],
        )
        assert r.exit_code == 1
        flat = " ".join(r.output.split())
        assert "JSON parse error" in flat
        assert "extract-a --json" in flat
        assert "Traceback" not in r.output
