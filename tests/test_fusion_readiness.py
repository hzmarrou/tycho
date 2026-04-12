"""Fusion-readiness contract tests — Step 5.9.

These tests pin down the invariants that Sources A, B, C, and D must
satisfy BEFORE the fusion layer is built. They are the contract the
future ``core/fusion.py`` will rely on to combine extractor outputs
without per-source special cases.

If any of these tests fails, the fusion layer's assumptions are wrong
and should be fixed in the relevant extractor — not worked around in
fusion.

The tests are organised by source. Each block asserts a set of shape,
provenance, and confidence invariants. The reviewer's suggestion in
``docs/REVIEW_2026-04-10.md`` ("add a minimal fusion-readiness contract
test suite now, before writing fusion logic") is implemented here.

Invariants shared across all sources:
  1. Every extracted item has a non-empty primary identifier
     (Concept.name, GovernanceRecord.element_name, SchemaModel.name,
     CodeRule.name)
  2. Every confidence score is in [0.0, 1.0]
  3. Every item that makes a verbatim claim about a source has
     provenance pointing back to that source (file path + some anchor)
  4. Primary dataclasses are immutable-ish — their public fields don't
     drift across extractor runs
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ontozense.extractors.domain_doc_extractor import (
    Concept,
    DomainDocumentExtractionResult,
    FieldConfidence,
    Provenance,
    Relationship,
)
from ontozense.extractors.governance_extractor import (
    KNOWN_FIELDS,
    GovernanceExtractionResult,
    GovernanceRecord,
)
from ontozense.extractors.django_schema import (
    SchemaField,
    SchemaModel,
    SchemaRelationship,
    SchemaResult,
)
from ontozense.extractors.code_extractor import (
    CodeExtractor,
    CodeProvenance,
    CodeRule,
)


SYNTHETIC_CODE_DIR = Path(__file__).parent / "fixtures" / "synthetic_npl_code"


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _assert_confidence_in_unit_interval(score: float, context: str) -> None:
    assert 0.0 <= score <= 1.0, (
        f"{context}: confidence {score!r} is not in [0.0, 1.0]"
    )


# ─── Source A — DomainDocumentExtractionResult ───────────────────────────────


class TestSourceAContract:
    """Shape contract for Source A output.

    Uses a synthetic DomainDocumentExtractionResult that mirrors what the
    real extractor produces. We don't invoke the LLM here — the goal is
    to lock the dataclass shape, not test extraction quality.
    """

    @pytest.fixture
    def sample_result(self) -> DomainDocumentExtractionResult:
        c1 = Concept(
            name="Customer Identifier",
            definition="A unique alphanumeric string that identifies each customer.",
            citation="Section 2.1",
            confidence=[
                FieldConfidence("name", 0.95, "verbatim"),
                FieldConfidence("definition", 0.95, "verbatim"),
            ],
            provenance=Provenance(
                source_document="customer_policy.md",
                source_section="Section 2.1",
                source_text_snippet="A unique alphanumeric string...",
                extraction_timestamp="2026-04-10T12:00:00",
            ),
        )
        # Name-only concept — the explicit missing-definition entry is
        # required so element-level confidence reflects the gap.
        c2 = Concept(
            name="Customer Record",
            definition="",
            confidence=[
                FieldConfidence("name", 0.95, "verbatim"),
                FieldConfidence("definition", 0.00, "missing"),
            ],
            provenance=Provenance(
                source_document="customer_policy.md",
                source_section="",
                source_text_snippet="Customer Record",
                extraction_timestamp="2026-04-10T12:00:00",
            ),
        )
        r1 = Relationship(
            subject="Customer Identifier",
            predicate="identifies",
            object="Customer Record",
            confidence=[FieldConfidence("triple", 0.95, "source_overlap")],
            provenance=Provenance(
                source_document="customer_policy.md",
                source_section="Section 2.1",
                source_text_snippet="Customer Identifier identifies...",
                extraction_timestamp="2026-04-10T12:00:00",
            ),
        )
        return DomainDocumentExtractionResult(
            domain_name="Customer MDM",
            concepts=[c1, c2],
            relationships=[r1],
            source_documents=["customer_policy.md"],
            extraction_timestamp="2026-04-10T12:00:00",
        )

    def test_every_concept_has_non_empty_name(self, sample_result):
        for c in sample_result.concepts:
            assert c.name.strip(), "Concept.name must be non-empty"

    def test_every_concept_has_confidence_list(self, sample_result):
        for c in sample_result.concepts:
            assert c.confidence, (
                f"Concept {c.name!r}: confidence list is empty — fusion "
                "cannot score it"
            )

    def test_name_only_concept_has_explicit_missing_definition_entry(self, sample_result):
        """The penalty rule (PLAYBOOK §3, NAME fields): a concept with
        no definition must carry a FieldConfidence('definition', 0.0, 'missing')
        entry so its element-level confidence reflects the gap. Without
        this, a name-only concept would score ~0.95 and slip through the
        review threshold.
        """
        name_only = [c for c in sample_result.concepts if not c.definition]
        assert name_only, "Test fixture must include a name-only concept"
        for c in name_only:
            def_entries = [e for e in c.confidence if e.field_name == "definition"]
            assert def_entries, (
                f"Concept {c.name!r}: no 'definition' confidence entry. "
                "Without this, overall_confidence() ignores the missing "
                "definition and reports ~0.95 for an incomplete concept."
            )
            # And the score must actually be 0.0
            assert any(e.score == 0.0 for e in def_entries), (
                f"Concept {c.name!r}: 'definition' confidence entries "
                f"don't include a 0.0 missing marker: "
                f"{[(e.field_name, e.score, e.reason) for e in def_entries]}"
            )

    def test_name_only_concept_overall_confidence_is_penalised(self, sample_result):
        """Name-only concept overall should score ~0.475 (average of
        0.95 name + 0.00 missing definition), well below the 0.7 review
        threshold.
        """
        name_only = next(c for c in sample_result.concepts if not c.definition)
        overall = name_only.overall_confidence()
        assert abs(overall - 0.475) < 0.01, (
            f"Name-only concept should score ~0.475, got {overall}"
        )
        assert name_only.needs_review(), (
            "Name-only concept must trip the review threshold"
        )

    def test_every_confidence_score_in_unit_interval(self, sample_result):
        for c in sample_result.concepts:
            for entry in c.confidence:
                _assert_confidence_in_unit_interval(
                    entry.score, f"Concept {c.name!r} field {entry.field_name!r}"
                )
            _assert_confidence_in_unit_interval(
                c.overall_confidence(), f"Concept {c.name!r} overall"
            )
        for r in sample_result.relationships:
            for entry in r.confidence:
                _assert_confidence_in_unit_interval(
                    entry.score,
                    f"Relationship {r.subject}→{r.object} field {entry.field_name!r}",
                )

    def test_every_concept_has_provenance(self, sample_result):
        """Every concept must carry provenance so the fusion layer can
        report back to the human where the claim came from.
        """
        for c in sample_result.concepts:
            assert c.provenance is not None, f"Concept {c.name!r}: no provenance"
            assert c.provenance.source_document, (
                f"Concept {c.name!r}: empty source_document"
            )
            assert c.provenance.extraction_timestamp, (
                f"Concept {c.name!r}: empty extraction_timestamp"
            )

    def test_every_relationship_has_non_empty_endpoints(self, sample_result):
        for r in sample_result.relationships:
            assert r.subject.strip(), "Relationship subject must be non-empty"
            assert r.object.strip(), "Relationship object must be non-empty"

    def test_verbatim_claims_have_non_empty_snippet(self, sample_result):
        """If a confidence entry claims 'verbatim', the provenance snippet
        must be non-empty — otherwise the claim is unverifiable.
        """
        for c in sample_result.concepts:
            has_verbatim = any(
                e.reason == "verbatim" for e in c.confidence
            )
            if has_verbatim:
                assert c.provenance and c.provenance.source_text_snippet, (
                    f"Concept {c.name!r} claims verbatim but has no snippet"
                )


# ─── Source B — GovernanceExtractionResult ───────────────────────────────────


class TestSourceBContract:
    """Shape contract for Source B output.

    Source B reads a curated JSON governance reference file. Its role is
    validation: confirming that Source A concepts exist in the governance
    system and providing canonical definitions, criticality flags, and
    citations.
    """

    @pytest.fixture
    def sample_result(self) -> GovernanceExtractionResult:
        return GovernanceExtractionResult(
            source_file="governance.json",
            records=[
                GovernanceRecord(
                    element_name="Default",
                    domain_name="Risk Management",
                    definition="Default is a status of a counterparty...",
                    is_critical=True,
                    citation="A-lex, Collibra, OpenMetadata",
                    source_file="governance.json",
                    confidence=0.95,
                ),
                GovernanceRecord(
                    element_name="Forbearance",
                    domain_name="Risk Management",
                    source_file="governance.json",
                    confidence=0.95,
                ),
            ],
            extraction_timestamp="2026-04-12T12:00:00",
        )

    def test_known_fields_include_element_name(self):
        """element_name is the primary key for fusion matching."""
        assert "element_name" in KNOWN_FIELDS

    def test_every_record_has_non_empty_element_name(self, sample_result):
        for r in sample_result.records:
            assert r.element_name.strip(), (
                "GovernanceRecord.element_name must be non-empty — "
                "it's the key the fusion layer matches on"
            )

    def test_every_record_confidence_in_unit_interval(self, sample_result):
        for r in sample_result.records:
            _assert_confidence_in_unit_interval(
                r.confidence, f"GovernanceRecord {r.element_name!r}"
            )

    def test_every_record_has_source_file(self, sample_result):
        for r in sample_result.records:
            assert r.source_file, f"{r.element_name!r}: empty source_file"

    def test_structured_source_confidence_matches_playbook(self, sample_result):
        """PLAYBOOK §3 STRUCTURED-SOURCE rule: structured sources score 0.95."""
        for r in sample_result.records:
            assert r.confidence == 0.95, (
                f"{r.element_name!r}: Source B records should score 0.95 "
                f"per PLAYBOOK §3 STRUCTURED-SOURCE, got {r.confidence}"
            )

    def test_is_critical_is_bool(self, sample_result):
        """is_critical must be a real boolean, not a string."""
        for r in sample_result.records:
            assert isinstance(r.is_critical, bool), (
                f"{r.element_name!r}: is_critical should be bool, "
                f"got {type(r.is_critical).__name__}"
            )


# ─── Source C — SchemaResult ─────────────────────────────────────────────────


class TestSourceCContract:
    """Shape contract for Source C output.

    Source C has two producers (DjangoSchemaParser, PostgresSchemaParser)
    that emit the same dataclasses. We synthesise a small SchemaResult
    directly — the per-backend tests live elsewhere.
    """

    @pytest.fixture
    def sample_result(self) -> SchemaResult:
        return SchemaResult(
            models=[
                SchemaModel(
                    name="Customer",
                    doc="A customer of the platform.",
                    fields=[
                        SchemaField(
                            name="customer_id",
                            field_type="UUIDField",
                            playground_type="string",
                            is_primary_key=True,
                            is_nullable=False,
                        ),
                        SchemaField(
                            name="email",
                            field_type="EmailField",
                            playground_type="string",
                            is_nullable=False,
                            max_length=254,
                        ),
                        SchemaField(
                            name="status",
                            field_type="CharField",
                            playground_type="string",
                            is_nullable=False,
                            choices_var="STATUS_CHOICES",
                            choices_values=["active", "inactive", "suspended"],
                        ),
                    ],
                    relationships=[
                        SchemaRelationship(
                            field_name="account",
                            from_model="Customer",
                            to_model="Account",
                            on_delete="CASCADE",
                            is_nullable=False,
                        ),
                    ],
                    source_file="models/customer.py",
                ),
            ],
            source_dir="models/",
        )

    def test_every_model_has_non_empty_name(self, sample_result):
        for m in sample_result.models:
            assert m.name.strip(), "SchemaModel.name must be non-empty"

    def test_every_model_has_at_least_one_field(self, sample_result):
        """An entity with zero fields is not useful for fusion — it would
        match against nothing on the element side.
        """
        for m in sample_result.models:
            assert m.fields, (
                f"SchemaModel {m.name!r}: no fields — can't contribute "
                "entities/properties to fusion"
            )

    def test_every_field_has_non_empty_name_and_type(self, sample_result):
        for m in sample_result.models:
            for f in m.fields:
                assert f.name.strip(), (
                    f"SchemaField in {m.name!r}: empty name"
                )
                assert f.playground_type, (
                    f"SchemaField {m.name}.{f.name}: empty playground_type"
                )

    def test_every_relationship_has_both_endpoints(self, sample_result):
        for m in sample_result.models:
            for r in m.relationships:
                assert r.from_model.strip(), "SchemaRelationship.from_model empty"
                assert r.to_model.strip(), "SchemaRelationship.to_model empty"

    def test_get_model_is_case_insensitive(self, sample_result):
        """Fusion uses this helper to match by name across sources —
        it must be case-insensitive so 'Customer' in Source C matches
        'customer' in Source A / B.
        """
        assert sample_result.get_model("CUSTOMER") is not None
        assert sample_result.get_model("customer") is not None
        assert sample_result.get_model("Customer") is not None

    def test_enum_values_exposed_via_choices_values(self, sample_result):
        """Fusion maps Source C enum values to the enum_values column.
        The contract: fields with a non-empty choices_values list are
        enum fields.
        """
        customer = sample_result.get_model("Customer")
        status = next(f for f in customer.fields if f.name == "status")
        assert status.choices_values
        assert "active" in status.choices_values


# ─── Source D — CodeExtractionResult ─────────────────────────────────────────


class TestSourceDContract:
    """Shape contract for Source D output.

    Runs the real code extractor against the synthetic NPL codebase
    fixture. Unlike Sources A/B/C we use real output here because the
    extractor is deterministic and fast.
    """

    @pytest.fixture(scope="class")
    def result(self):
        if not SYNTHETIC_CODE_DIR.exists():
            pytest.skip("synthetic_npl_code fixture missing")
        return CodeExtractor().extract_from_directory(SYNTHETIC_CODE_DIR)

    def test_produced_some_rules(self, result):
        assert result.rules, "Code extractor returned no rules — fixture broken?"

    def test_every_rule_has_rule_type_in_known_set(self, result):
        known_types = {
            "constant", "function", "conditional",
            "sql_view", "sql_table", "sql_check", "sql_where",
            "comment_citation",
        }
        for r in result.rules:
            assert r.rule_type in known_types, (
                f"Unknown rule_type {r.rule_type!r} — fusion layer may not "
                "know how to handle it. Add to the known set or rename."
            )

    def test_every_rule_has_non_empty_name(self, result):
        for r in result.rules:
            assert r.name.strip(), f"CodeRule {r.rule_type}: empty name"

    def test_every_rule_has_provenance_with_file_and_line(self, result):
        for r in result.rules:
            assert r.provenance is not None, (
                f"CodeRule {r.rule_type}:{r.name}: no provenance"
            )
            assert r.provenance.file_path, (
                f"CodeRule {r.name}: empty provenance.file_path"
            )
            assert r.provenance.line > 0, (
                f"CodeRule {r.name}: provenance.line == 0"
            )

    def test_every_rule_confidence_in_unit_interval(self, result):
        for r in result.rules:
            _assert_confidence_in_unit_interval(
                r.confidence, f"CodeRule {r.rule_type}:{r.name}"
            )

    def test_every_rule_has_referenced_symbols_list(self, result):
        """Even if empty, referenced_symbols must be a list — the future
        symbol-table validator (AI-RBX step 3) walks it unconditionally.
        """
        for r in result.rules:
            assert isinstance(r.referenced_symbols, list), (
                f"CodeRule {r.name}: referenced_symbols is not a list"
            )

    def test_function_rules_carry_docstring_field(self, result):
        """Functions must have the docstring field present (possibly
        empty). The LLM labelling step consumes this.
        """
        for r in result.rules:
            if r.rule_type == "function":
                assert hasattr(r, "docstring")
                assert isinstance(r.docstring, str)

    def test_no_failed_files(self, result):
        """Fusion must not silently skip unparseable files. If the
        fixture produces parse failures, the test suite should know
        about them.
        """
        assert not result.files_failed, (
            f"Unexpected parse failures in synthetic fixture: "
            f"{result.files_failed}"
        )

    def test_extraction_timestamp_populated(self, result):
        assert result.extraction_timestamp, "Extraction timestamp empty"


# ─── Cross-source contract ───────────────────────────────────────────────────


class TestCrossSourceContract:
    """Invariants that must hold across ALL four source outputs.

    If a new source is added later, these tests are the minimum bar it
    must clear before it can be wired into the fusion layer.
    """

    def test_all_sources_have_distinguishable_dataclasses(self):
        """The fusion layer dispatches on type. Two sources must not
        share the same primary dataclass, otherwise fusion can't tell
        them apart.
        """
        from ontozense.extractors.domain_doc_extractor import Concept
        from ontozense.extractors.governance_extractor import GovernanceRecord
        from ontozense.extractors.django_schema import SchemaModel
        from ontozense.extractors.code_extractor import CodeRule

        types = {Concept, GovernanceRecord, SchemaModel, CodeRule}
        assert len(types) == 4, "Sources must have distinct primary types"

    def test_all_sources_have_a_primary_name_field(self):
        """Fusion matches elements by name across sources. Each primary
        dataclass must have a canonical name-like field.
        """
        from dataclasses import fields as dc_fields
        from ontozense.extractors.domain_doc_extractor import Concept
        from ontozense.extractors.governance_extractor import GovernanceRecord
        from ontozense.extractors.django_schema import SchemaModel
        from ontozense.extractors.code_extractor import CodeRule

        expectations = {
            Concept: "name",
            GovernanceRecord: "element_name",
            SchemaModel: "name",
            CodeRule: "name",
        }
        for cls, expected in expectations.items():
            field_names = {f.name for f in dc_fields(cls)}
            assert expected in field_names, (
                f"{cls.__name__}: expected field {expected!r} not found. "
                f"Available: {sorted(field_names)}"
            )
