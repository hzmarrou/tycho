"""Tests for the data dictionary extractor.

Uses mock OntoGPT output so the tests don't require Azure OpenAI.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest


# ─── Mock OntoGPT output ──────────────────────────────────────────────────────

MOCK_ONTOGPT_OUTPUT = json.dumps({
    "extracted_object": {
        "domain_name": "Non-Performing Loans",
        "data_elements": [
            {
                "element_name": "Default",
                "sub_domain": "Loan",
                "definition": "A default occurs when an obligor is past due more than 90 days on any material credit obligation",
                "term_definition": "A default is considered to have occurred with regard to a particular obligor when either or both of the two following events have taken place",
                "is_critical": "Y",
                "citation": "Basel D403 Section 3.1 Paragraph 14",
                "mandatory_optional": "M",
                "dq_completeness": "Should be filled at facility level for Program Lending exposures",
                "dq_accuracy": "",
                "dq_uniqueness": "",
                "dq_timeliness": "",
                "dq_consistency": "",
                "dq_validity": "Y/N",
            },
            {
                "element_name": "Days Past Due",
                "sub_domain": "Loan",
                "definition": "Number of days an exposure has been past due",
                "term_definition": "",
                "is_critical": "Y",
                "citation": "Basel D403 Paragraph 18",
                "mandatory_optional": "M",
                "dq_completeness": "",
                "dq_accuracy": "Calculated from first day of missed payment",
                "dq_uniqueness": "",
                "dq_timeliness": "",
                "dq_consistency": "",
                "dq_validity": "Non-negative integer",
            },
            {
                "element_name": "Forbearance",
                "sub_domain": "Forbearance",
                "definition": "A concession granted to a counterparty for reasons of financial difficulty",
                "term_definition": "",
                "is_critical": "Y",
                "citation": "Basel D403 Section 4",
                "mandatory_optional": "",
                "dq_completeness": "",
                "dq_accuracy": "",
                "dq_uniqueness": "",
                "dq_timeliness": "",
                "dq_consistency": "",
                "dq_validity": "",
            },
        ],
    },
})

MOCK_SOURCE_TEXT = """
# Basel Committee D403

## Section 3.1 Identification of non-performing exposures

A default is considered to have occurred with regard to a particular obligor
when either or both of the two following events have taken place: the bank
considers the obligor unlikely to pay; the obligor is past due more than 90
days on any material credit obligation.

A default occurs when an obligor is past due more than 90 days on any material
credit obligation.

## Section 4 Forbearance

A concession granted to a counterparty for reasons of financial difficulty
that would not otherwise be considered by the lender.
"""


@pytest.fixture
def temp_doc(tmp_path: Path) -> Path:
    doc = tmp_path / "test-doc.md"
    doc.write_text(MOCK_SOURCE_TEXT, encoding="utf-8")
    return doc


# ─── Tests: dataclasses ──────────────────────────────────────────────────────

class TestDataclasses:
    def test_data_element_defaults(self):
        from ontozense.extractors import DataElement

        el = DataElement(element_name="Loan ID")
        assert el.element_name == "Loan ID"
        assert el.sub_domain == ""
        assert el.confidence == []
        assert el.merge_conflicts == []
        assert el.overall_confidence() == 0.0

    def test_data_element_overall_confidence(self):
        from ontozense.extractors import DataElement, FieldConfidence

        el = DataElement(element_name="Loan ID")
        el.confidence = [
            FieldConfidence("definition", 0.95, "verbatim"),
            FieldConfidence("sub_domain", 0.8, "non_empty"),
            FieldConfidence("dq_accuracy", 0.0, "empty"),
        ]
        # (0.95 + 0.8 + 0.0) / 3 ≈ 0.583
        assert abs(el.overall_confidence() - 0.583) < 0.01

    def test_needs_review_threshold(self):
        from ontozense.extractors import DataElement, FieldConfidence

        el = DataElement(element_name="Default")
        el.confidence = [FieldConfidence("definition", 0.95, "verbatim")]
        assert not el.needs_review(threshold=0.7)

        el2 = DataElement(element_name="Default")
        el2.confidence = [FieldConfidence("definition", 0.5, "non_empty")]
        assert el2.needs_review(threshold=0.7)

    def test_needs_review_with_conflicts(self):
        from ontozense.extractors import DataElement, FieldConfidence

        el = DataElement(element_name="Default")
        el.confidence = [FieldConfidence("definition", 0.95, "verbatim")]
        el.merge_conflicts = ["different definition in source B"]
        assert el.needs_review()  # has conflicts, needs review even with high confidence

    def test_get_element_case_insensitive(self):
        from ontozense.extractors import DataDictionaryResult, DataElement

        result = DataDictionaryResult()
        result.elements = [
            DataElement(element_name="Default"),
            DataElement(element_name="Days Past Due"),
        ]
        assert result.get_element("default") is not None
        assert result.get_element("DEFAULT") is not None
        assert result.get_element("days past due") is not None
        assert result.get_element("nonexistent") is None


# ─── Tests: extractor parsing ─────────────────────────────────────────────────

class TestExtractorParsing:
    """Tests that don't call OntoGPT — only test the parser."""

    def test_parses_ontogpt_output(self, temp_doc: Path):
        from ontozense.extractors import DataDictionaryExtractor

        extractor = DataDictionaryExtractor()
        # Mock the OntoGPT subprocess call
        with patch.object(
            extractor._ontogpt, "_run_ontogpt", return_value=MOCK_ONTOGPT_OUTPUT
        ):
            result = extractor.extract_from_file(temp_doc)

        assert result.domain_name == "Non-Performing Loans"
        assert len(result.elements) == 3

        names = [el.element_name for el in result.elements]
        assert "Default" in names
        assert "Days Past Due" in names
        assert "Forbearance" in names

    def test_field_mapping(self, temp_doc: Path):
        from ontozense.extractors import DataDictionaryExtractor

        extractor = DataDictionaryExtractor()
        with patch.object(
            extractor._ontogpt, "_run_ontogpt", return_value=MOCK_ONTOGPT_OUTPUT
        ):
            result = extractor.extract_from_file(temp_doc)

        default = result.get_element("Default")
        assert default is not None
        assert default.sub_domain == "Loan"
        assert "past due more than 90 days" in default.definition.lower()
        assert default.is_critical == "Y"
        assert "Basel D403" in default.citation
        assert default.mandatory_optional == "M"
        assert "Program Lending" in default.dq_completeness

    def test_confidence_scoring_verbatim(self, temp_doc: Path):
        """Definitions that appear verbatim in source should score 0.95."""
        from ontozense.extractors import DataDictionaryExtractor

        extractor = DataDictionaryExtractor()
        with patch.object(
            extractor._ontogpt, "_run_ontogpt", return_value=MOCK_ONTOGPT_OUTPUT
        ):
            result = extractor.extract_from_file(temp_doc)

        default = result.get_element("Default")
        assert default is not None

        # Find the confidence score for the definition field
        def_confidence = next(
            (c for c in default.confidence if c.field_name == "definition"),
            None,
        )
        assert def_confidence is not None
        # The mock definition matches text in MOCK_SOURCE_TEXT
        assert def_confidence.score == 0.95
        assert def_confidence.reason == "verbatim"

    def test_confidence_scoring_empty(self, temp_doc: Path):
        """Empty fields should score 0.0."""
        from ontozense.extractors import DataDictionaryExtractor

        extractor = DataDictionaryExtractor()
        with patch.object(
            extractor._ontogpt, "_run_ontogpt", return_value=MOCK_ONTOGPT_OUTPUT
        ):
            result = extractor.extract_from_file(temp_doc)

        forbearance = result.get_element("Forbearance")
        assert forbearance is not None

        # dq_completeness is empty in the mock output
        completeness = next(
            (c for c in forbearance.confidence if c.field_name == "dq_completeness"),
            None,
        )
        assert completeness is not None
        assert completeness.score == 0.0
        assert completeness.reason == "empty"

    def test_provenance_tracking(self, temp_doc: Path):
        """Each element should have provenance pointing to the source document."""
        from ontozense.extractors import DataDictionaryExtractor

        extractor = DataDictionaryExtractor()
        with patch.object(
            extractor._ontogpt, "_run_ontogpt", return_value=MOCK_ONTOGPT_OUTPUT
        ):
            result = extractor.extract_from_file(temp_doc)

        for el in result.elements:
            assert el.provenance is not None
            assert str(temp_doc) in el.provenance.source_document
            assert el.provenance.extraction_timestamp != ""

    def test_provenance_finds_section(self, temp_doc: Path):
        """Provenance should detect the markdown section heading."""
        from ontozense.extractors import DataDictionaryExtractor

        extractor = DataDictionaryExtractor()
        with patch.object(
            extractor._ontogpt, "_run_ontogpt", return_value=MOCK_ONTOGPT_OUTPUT
        ):
            result = extractor.extract_from_file(temp_doc)

        forbearance = result.get_element("Forbearance")
        assert forbearance is not None
        assert forbearance.provenance is not None
        # Should detect "Section 4 Forbearance" or "Basel Committee D403"
        assert forbearance.provenance.source_section != ""

    def test_overall_confidence_calculation(self, temp_doc: Path):
        from ontozense.extractors import DataDictionaryExtractor

        extractor = DataDictionaryExtractor()
        with patch.object(
            extractor._ontogpt, "_run_ontogpt", return_value=MOCK_ONTOGPT_OUTPUT
        ):
            result = extractor.extract_from_file(temp_doc)

        default = result.get_element("Default")
        assert default is not None
        # Should be > 0 since several fields are populated
        assert default.overall_confidence() > 0.0
        # And <= 1.0
        assert default.overall_confidence() <= 1.0

    def test_extraction_metadata(self, temp_doc: Path):
        from ontozense.extractors import DataDictionaryExtractor

        extractor = DataDictionaryExtractor()
        with patch.object(
            extractor._ontogpt, "_run_ontogpt", return_value=MOCK_ONTOGPT_OUTPUT
        ):
            result = extractor.extract_from_file(temp_doc)

        assert result.source_documents == [str(temp_doc)]
        assert result.extraction_timestamp != ""
        assert len(result.raw_outputs) == 1

    def test_handles_yaml_output(self, temp_doc: Path):
        """OntoGPT sometimes returns YAML — should still parse."""
        from ontozense.extractors import DataDictionaryExtractor

        yaml_output = """
extracted_object:
  domain_name: NPL
  data_elements:
    - element_name: Loan ID
      sub_domain: Loan
      definition: Unique loan identifier
      is_critical: Y
"""
        extractor = DataDictionaryExtractor()
        with patch.object(
            extractor._ontogpt, "_run_ontogpt", return_value=yaml_output
        ):
            result = extractor.extract_from_file(temp_doc)

        assert result.domain_name == "NPL"
        assert len(result.elements) == 1
        assert result.elements[0].element_name == "Loan ID"

    def test_handles_empty_output(self, temp_doc: Path):
        """Empty/garbage output should return an empty result, not crash."""
        from ontozense.extractors import DataDictionaryExtractor

        extractor = DataDictionaryExtractor()
        with patch.object(
            extractor._ontogpt, "_run_ontogpt", return_value=""
        ):
            result = extractor.extract_from_file(temp_doc)

        assert result.elements == []

    def test_template_path_exists(self):
        """The bundled template should be discoverable."""
        from ontozense.extractors.dd_extractor import TEMPLATE_PATH
        assert TEMPLATE_PATH.exists(), f"Template not found at {TEMPLATE_PATH}"

    def test_extractor_uses_bundled_template_by_default(self):
        from ontozense.extractors import DataDictionaryExtractor
        from ontozense.extractors.dd_extractor import TEMPLATE_PATH

        extractor = DataDictionaryExtractor()
        assert extractor.template_path == TEMPLATE_PATH


# ─── Field-aware confidence scoring tests ────────────────────────────────────

class TestFieldAwareConfidenceScoring:
    """Tests for the post-review tightened confidence semantics."""

    def test_enum_field_valid_value_high_score(self):
        from ontozense.extractors.dd_extractor import DataDictionaryExtractor

        score, reason = DataDictionaryExtractor._score_field(
            "Y", "irrelevant source", "is_critical"
        )
        assert score == 0.85
        assert reason == "valid_enum"

    def test_enum_field_invalid_value_low_score(self):
        from ontozense.extractors.dd_extractor import DataDictionaryExtractor

        score, reason = DataDictionaryExtractor._score_field(
            "maybe", "irrelevant source", "is_critical"
        )
        assert score == 0.3
        assert reason == "invalid_enum_value"

    def test_mandatory_optional_valid(self):
        from ontozense.extractors.dd_extractor import DataDictionaryExtractor

        for v in ("M", "O", "Mandatory", "OPTIONAL"):
            score, _ = DataDictionaryExtractor._score_field(
                v, "irrelevant", "mandatory_optional"
            )
            assert score == 0.85, f"Expected 0.85 for {v!r}"

    def test_reference_field_with_citation_pattern(self):
        from ontozense.extractors.dd_extractor import DataDictionaryExtractor

        # Generic citation patterns — no banking terms
        for v in (
            "Section 3.1 Paragraph 14",
            "Article 178",
            "Chapter 5",
            "§14",
            "Para. 12",
        ):
            score, _ = DataDictionaryExtractor._score_field(
                v, "some unrelated source", "citation"
            )
            assert score >= 0.7, f"Expected ≥0.7 for citation {v!r}, got {score}"

    def test_reference_field_without_citation_low_score(self):
        from ontozense.extractors.dd_extractor import DataDictionaryExtractor

        score, reason = DataDictionaryExtractor._score_field(
            "this looks like a citation maybe", "source", "citation"
        )
        assert score == 0.4
        assert reason == "non_citation_text"

    def test_reference_field_verbatim_in_source_highest(self):
        from ontozense.extractors.dd_extractor import DataDictionaryExtractor

        ref = "Section 3.1 Paragraph 14"
        source = f"... see {ref} for the full definition ..."
        score, reason = DataDictionaryExtractor._score_field(
            ref, source, "citation"
        )
        assert score == 0.95
        assert reason == "verbatim_citation"

    def test_narrative_field_verbatim(self):
        from ontozense.extractors.dd_extractor import DataDictionaryExtractor

        definition = "the unique identifier of a customer record"
        source = f"... where {definition} appears in section 4 ..."
        score, reason = DataDictionaryExtractor._score_field(
            definition, source, "definition"
        )
        assert score == 0.95
        assert reason == "verbatim"

    def test_narrative_field_high_overlap(self):
        from ontozense.extractors.dd_extractor import DataDictionaryExtractor

        definition = "unique customer identifier record number"
        source = "the unique identifier for each customer record number is..."
        score, reason = DataDictionaryExtractor._score_field(
            definition, source, "definition"
        )
        # Most words appear in source even though phrasing differs
        assert score >= 0.55

    def test_narrative_field_low_evidence(self):
        from ontozense.extractors.dd_extractor import DataDictionaryExtractor

        definition = "completely fabricated description that nobody said"
        source = "totally different content here"
        score, reason = DataDictionaryExtractor._score_field(
            definition, source, "definition"
        )
        assert score == 0.35
        assert reason == "low_evidence"

    def test_categorical_field_non_empty(self):
        from ontozense.extractors.dd_extractor import DataDictionaryExtractor

        score, reason = DataDictionaryExtractor._score_field(
            "Customer Account", "irrelevant", "sub_domain"
        )
        assert score == 0.7
        assert reason == "non_empty_category"

    def test_empty_field_zero(self):
        from ontozense.extractors.dd_extractor import DataDictionaryExtractor

        for fname in ("definition", "is_critical", "citation", "sub_domain"):
            score, reason = DataDictionaryExtractor._score_field("", "src", fname)
            assert score == 0.0
            assert reason == "empty"


# ─── Provenance fidelity tests ───────────────────────────────────────────────

class TestProvenanceFidelity:
    """Provenance must point to real text in the source — not just be non-empty."""

    @pytest.fixture
    def doc_with_canonicalized_term(self, tmp_path: Path) -> Path:
        # Source uses "customer accounts" but extraction may canonicalize
        # the element_name to "Customer Account"
        text = """
# Customer Master Data

## Section 1.2 Customer Definition

A customer account represents a billing relationship with a single
purchasing entity. Each customer account has a unique identifier and a
billing address.
"""
        doc = tmp_path / "doc.md"
        doc.write_text(text, encoding="utf-8")
        return doc

    def test_provenance_falls_back_to_definition_when_name_not_in_source(
        self, doc_with_canonicalized_term
    ):
        """If element_name is canonicalized away from source wording, provenance
        should still find a snippet via the definition."""
        from ontozense.extractors import DataDictionaryExtractor

        # Note: element_name is "Customer Account" (canonical), but source
        # has "customer account" — case mismatch is fine. The harder case
        # is when the canonical name doesn't appear at all and we fall back.
        mock = json.dumps({
            "extracted_object": {
                "domain_name": "Customer Master",
                "data_elements": [{
                    "element_name": "CustomerAccountId",
                    "sub_domain": "Customer",
                    "definition": "a billing relationship with a single purchasing entity",
                    "is_critical": "Y",
                    "citation": "Section 1.2",
                }],
            },
        })

        extractor = DataDictionaryExtractor()
        with patch.object(extractor._ontogpt, "_run_ontogpt", return_value=mock):
            result = extractor.extract_from_file(doc_with_canonicalized_term)

        el = result.elements[0]
        assert el.provenance is not None
        # CustomerAccountId is NOT in the source, but the definition phrase IS
        assert el.provenance.source_text_snippet != "", \
            "Provenance should fall back to definition text when name not found"
        # The snippet should contain text actually from the source
        assert "billing relationship" in el.provenance.source_text_snippet.lower()

    def test_provenance_section_detected(self, doc_with_canonicalized_term):
        from ontozense.extractors import DataDictionaryExtractor

        mock = json.dumps({
            "extracted_object": {
                "domain_name": "Customer Master",
                "data_elements": [{
                    "element_name": "CustomerAccountId",
                    "definition": "a billing relationship with a single purchasing entity",
                }],
            },
        })

        extractor = DataDictionaryExtractor()
        with patch.object(extractor._ontogpt, "_run_ontogpt", return_value=mock):
            result = extractor.extract_from_file(doc_with_canonicalized_term)

        el = result.elements[0]
        assert el.provenance is not None
        # Should detect "Section 1.2 Customer Definition" or similar
        assert el.provenance.source_section != ""

    def test_provenance_snippet_actually_in_source(self):
        """The snippet must be a real substring of the source, not made up."""
        from ontozense.extractors import DataDictionaryExtractor

        source = "The widget table contains rows with widget identifiers."
        result = DataDictionaryExtractor._find_snippet_anywhere(
            "widget identifiers", source, min_length=4
        )
        assert "widget identifiers" in result
        # And the snippet must literally exist in the source
        assert result in source or source.find(result) >= 0
