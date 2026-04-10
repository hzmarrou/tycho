"""Tests for the domain document extractor (Source A).

These tests use mocked OntoGPT output so they don't require Azure OpenAI.
The mocks reproduce the exact structure of OntoGPT's actual JSON output,
including both the ``raw_completion_output`` text field (which we parse
directly) and the ``extracted_object`` structured field (which SPIRES
populates lossily — used as fallback only).

Two output formats are tested because gpt-5.2 emits both depending on
context: YAML list and JSON-array-on-one-line.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest


# ─── Mock OntoGPT outputs ────────────────────────────────────────────────────


def _ontogpt_json_with_yaml_lists() -> str:
    """OntoGPT JSON where the LLM emitted YAML-list format (the most common)."""
    raw_completion = """domain_name: Customer Master Data Management

concepts:
- customer identifier :: a unique string assigned to each customer record
- customer email :: the primary email address of the customer
- billing address
- account status :: one of active, inactive, suspended

relationships:
- customer identifier -> uniquely identifies -> customer record
- customer email -> required for -> billing notifications
- billing address -> belongs to -> customer record
"""
    extracted = {
        "domain_name": "Customer Master Data Management",
        # SPIRES only captures the first concept — the rest is in raw_completion
        "concepts": ["customer identifier"],
    }
    return json.dumps(
        {
            "input_text": "...",
            "raw_completion_output": raw_completion,
            "prompt": "...",
            "extracted_object": extracted,
        }
    )


def _ontogpt_json_with_json_arrays() -> str:
    """OntoGPT JSON where the LLM emitted JSON-array-on-one-line format."""
    raw_completion = (
        'domain_name: Product Catalog Management\n\n'
        'concepts: ["product identifier", "product name :: the human readable label", '
        '"price", "stock keeping unit (SKU)"]\n\n'
        'relationships: ["product identifier -> uniquely identifies -> product", '
        '"price -> applies to -> product", "stock keeping unit -> abbreviated as -> SKU"]\n'
    )
    extracted = {"domain_name": "Product Catalog Management"}
    return json.dumps(
        {
            "input_text": "...",
            "raw_completion_output": raw_completion,
            "prompt": "...",
            "extracted_object": extracted,
        }
    )


def _ontogpt_json_empty_raw_with_extracted() -> str:
    """OntoGPT JSON where raw_completion is missing — fallback to extracted_object."""
    return json.dumps(
        {
            "input_text": "...",
            "raw_completion_output": "",
            "prompt": "...",
            "extracted_object": {
                "domain_name": "Order Management",
                "concepts": [
                    {"name": "order identifier", "definition": "primary key of an order"},
                    {"name": "order date"},
                ],
                "relationships": [
                    {
                        "subject": "order identifier",
                        "predicate": "uniquely identifies",
                        "object": "order",
                    },
                ],
            },
        }
    )


# ─── Source text fixture ─────────────────────────────────────────────────────


SOURCE_TEXT_CUSTOMER = """
# Customer Master Data

## Section 1.1 Identifiers
A customer identifier is a unique string assigned to each customer record.
The identifier must be present for all customer accounts.

## Section 1.2 Contact Details
The customer email is the primary email address of the customer.
A billing address belongs to a customer record.

## Section 1.3 State
Account status is one of active, inactive, or suspended.
"""


@pytest.fixture
def source_doc(tmp_path: Path) -> Path:
    doc = tmp_path / "customer-master.md"
    doc.write_text(SOURCE_TEXT_CUSTOMER, encoding="utf-8")
    return doc


# ─── Dataclass tests ─────────────────────────────────────────────────────────


class TestDataclasses:
    def test_concept_defaults(self):
        from ontozense.extractors import Concept

        c = Concept(name="customer")
        assert c.name == "customer"
        assert c.definition == ""
        assert c.citation == ""
        assert c.confidence == []
        assert c.overall_confidence() == 0.0

    def test_concept_overall_confidence(self):
        from ontozense.extractors import Concept
        from ontozense.extractors.domain_doc_extractor import FieldConfidence

        c = Concept(name="customer")
        c.confidence = [
            FieldConfidence("name", 0.95, "verbatim"),
            FieldConfidence("definition", 0.75, "high_overlap"),
        ]
        assert abs(c.overall_confidence() - 0.85) < 0.01

    def test_concept_needs_review_threshold(self):
        from ontozense.extractors import Concept
        from ontozense.extractors.domain_doc_extractor import FieldConfidence

        c = Concept(name="customer")
        c.confidence = [FieldConfidence("name", 0.95, "verbatim")]
        assert not c.needs_review(threshold=0.7)

        c2 = Concept(name="other")
        c2.confidence = [FieldConfidence("name", 0.5, "low")]
        assert c2.needs_review(threshold=0.7)

    def test_relationship_defaults(self):
        from ontozense.extractors import Relationship

        r = Relationship(subject="A", predicate="relates_to", object="B")
        assert r.subject == "A"
        assert r.predicate == "relates_to"
        assert r.object == "B"
        assert r.overall_confidence() == 0.0

    def test_get_concept_case_insensitive(self):
        from ontozense.extractors import Concept, DomainDocumentExtractionResult

        result = DomainDocumentExtractionResult()
        result.concepts.append(Concept(name="Customer Identifier"))
        result.concepts.append(Concept(name="Order Date"))

        assert result.get_concept("customer identifier") is not None
        assert result.get_concept("CUSTOMER IDENTIFIER") is not None
        assert result.get_concept("nonexistent") is None


# ─── Section / list parser tests ─────────────────────────────────────────────


class TestSectionAndListParsers:
    def test_extract_section_yaml_list(self):
        from ontozense.extractors.domain_doc_extractor import DomainDocumentExtractor

        text = """domain_name: Test

concepts:
- item one
- item two
- item three

relationships:
- a -> b -> c
"""
        body = DomainDocumentExtractor._extract_section(text, "concepts")
        assert "item one" in body
        assert "item two" in body
        assert "item three" in body
        # Must NOT include the relationships section
        assert "a -> b -> c" not in body

    def test_extract_section_json_array(self):
        from ontozense.extractors.domain_doc_extractor import DomainDocumentExtractor

        text = 'concepts: ["a","b","c"]\nrelationships: ["x -> y -> z"]\n'
        body = DomainDocumentExtractor._extract_section(text, "concepts")
        assert '["a","b","c"]' in body
        assert "x -> y -> z" not in body

    def test_extract_section_missing(self):
        from ontozense.extractors.domain_doc_extractor import DomainDocumentExtractor

        text = "domain_name: Test\n"
        body = DomainDocumentExtractor._extract_section(text, "concepts")
        assert body == ""

    def test_parse_list_json_array(self):
        from ontozense.extractors.domain_doc_extractor import DomainDocumentExtractor

        items = DomainDocumentExtractor._parse_list('["a","b","c"]')
        assert items == ["a", "b", "c"]

    def test_parse_list_yaml(self):
        from ontozense.extractors.domain_doc_extractor import DomainDocumentExtractor

        text = "- item one\n- item two\n- item three"
        items = DomainDocumentExtractor._parse_list(text)
        assert items == ["item one", "item two", "item three"]

    def test_parse_list_semicolon(self):
        from ontozense.extractors.domain_doc_extractor import DomainDocumentExtractor

        items = DomainDocumentExtractor._parse_list("a; b; c")
        assert items == ["a", "b", "c"]

    def test_parse_list_empty(self):
        from ontozense.extractors.domain_doc_extractor import DomainDocumentExtractor

        assert DomainDocumentExtractor._parse_list("") == []
        assert DomainDocumentExtractor._parse_list("   ") == []


# ─── Concept builder tests ───────────────────────────────────────────────────


class TestConceptBuilder:
    def test_concept_with_double_colon_separator(self, source_doc: Path):
        from ontozense.extractors.domain_doc_extractor import DomainDocumentExtractor

        ext = DomainDocumentExtractor()
        c = ext._build_concept(
            "customer identifier :: a unique string assigned to each customer record",
            source_doc,
            SOURCE_TEXT_CUSTOMER,
        )
        assert c.name == "customer identifier"
        assert "unique string" in c.definition

    def test_concept_with_parenthetical_definition(self, source_doc: Path):
        from ontozense.extractors.domain_doc_extractor import DomainDocumentExtractor

        ext = DomainDocumentExtractor()
        c = ext._build_concept(
            "customer identifier (the unique string assigned to each customer)",
            source_doc,
            SOURCE_TEXT_CUSTOMER,
        )
        assert c.name == "customer identifier"
        assert "unique string" in c.definition

    def test_concept_with_acronym_parenthetical_kept_as_name(self, source_doc: Path):
        """Short uppercase parens are acronyms, not definitions."""
        from ontozense.extractors.domain_doc_extractor import DomainDocumentExtractor

        ext = DomainDocumentExtractor()
        c = ext._build_concept(
            "stock keeping unit (SKU)",
            source_doc,
            SOURCE_TEXT_CUSTOMER,
        )
        # The whole thing should be the name; SKU is an acronym, not a definition
        assert "SKU" in c.name
        assert c.definition == ""

    def test_concept_just_name(self, source_doc: Path):
        from ontozense.extractors.domain_doc_extractor import DomainDocumentExtractor

        ext = DomainDocumentExtractor()
        c = ext._build_concept("billing address", source_doc, SOURCE_TEXT_CUSTOMER)
        assert c.name == "billing address"
        assert c.definition == ""

    def test_concept_without_definition_is_penalised(self, source_doc: Path):
        """A concept with only a name (no definition) should NOT score 0.95
        overall, even when the name is verbatim in source. Half of the
        expected information is missing — the score must reflect that.
        """
        from ontozense.extractors.domain_doc_extractor import DomainDocumentExtractor

        ext = DomainDocumentExtractor()
        # "billing address" is verbatim in SOURCE_TEXT_CUSTOMER, so the
        # name field would score 0.95 by itself.
        c = ext._build_concept("billing address", source_doc, SOURCE_TEXT_CUSTOMER)
        assert c.name == "billing address"
        assert c.definition == ""
        # Two confidence entries: name 0.95 + missing definition 0.0
        assert len(c.confidence) == 2
        # Find the definition entry
        def_entry = next(
            (fc for fc in c.confidence if fc.field_name == "definition"), None
        )
        assert def_entry is not None
        assert def_entry.score == 0.0
        assert def_entry.reason == "missing"
        # Overall: average of 0.95 + 0.0 = 0.475 → flagged for review
        assert abs(c.overall_confidence() - 0.475) < 0.01
        assert c.needs_review(threshold=0.7)

    def test_concept_with_definition_not_penalised(self, source_doc: Path):
        """When the definition is present, the missing-definition penalty
        does NOT apply — only the actual definition score is recorded."""
        from ontozense.extractors.domain_doc_extractor import DomainDocumentExtractor

        ext = DomainDocumentExtractor()
        c = ext._build_concept(
            "customer identifier :: a unique string assigned to each customer record",
            source_doc,
            SOURCE_TEXT_CUSTOMER,
        )
        # Should have two entries (name + definition), neither marked "missing"
        reasons = {fc.reason for fc in c.confidence}
        assert "missing" not in reasons

    def test_concept_strips_quotes(self, source_doc: Path):
        from ontozense.extractors.domain_doc_extractor import DomainDocumentExtractor

        ext = DomainDocumentExtractor()
        c = ext._build_concept('"customer identifier"', source_doc, SOURCE_TEXT_CUSTOMER)
        assert c.name == "customer identifier"

    def test_concept_provenance_populated(self, source_doc: Path):
        from ontozense.extractors.domain_doc_extractor import DomainDocumentExtractor

        ext = DomainDocumentExtractor()
        c = ext._build_concept("customer identifier", source_doc, SOURCE_TEXT_CUSTOMER)
        assert c.provenance is not None
        assert "customer-master.md" in c.provenance.source_document
        # Snippet should contain text from the actual source
        assert c.provenance.source_text_snippet
        assert "customer identifier" in c.provenance.source_text_snippet.lower()

    def test_concept_section_detected(self, source_doc: Path):
        from ontozense.extractors.domain_doc_extractor import DomainDocumentExtractor

        ext = DomainDocumentExtractor()
        c = ext._build_concept(
            "customer identifier :: a unique string", source_doc, SOURCE_TEXT_CUSTOMER
        )
        assert c.provenance is not None
        # Should detect the markdown section heading
        assert c.provenance.source_section


# ─── Relationship builder tests ──────────────────────────────────────────────


class TestRelationshipBuilder:
    def test_relationship_arrow_separator(self, source_doc: Path):
        from ontozense.extractors.domain_doc_extractor import DomainDocumentExtractor

        ext = DomainDocumentExtractor()
        r = ext._build_relationship(
            "customer identifier -> uniquely identifies -> customer record",
            source_doc,
            SOURCE_TEXT_CUSTOMER,
        )
        assert r.subject == "customer identifier"
        assert r.predicate == "uniquely identifies"
        assert r.object == "customer record"

    def test_relationship_double_arrow(self, source_doc: Path):
        from ontozense.extractors.domain_doc_extractor import DomainDocumentExtractor

        ext = DomainDocumentExtractor()
        r = ext._build_relationship(
            "A --> relates to --> B",
            source_doc,
            SOURCE_TEXT_CUSTOMER,
        )
        assert r.subject == "A"
        assert r.predicate == "relates to"
        assert r.object == "B"

    def test_relationship_unparseable_returns_empty(self, source_doc: Path):
        from ontozense.extractors.domain_doc_extractor import DomainDocumentExtractor

        ext = DomainDocumentExtractor()
        r = ext._build_relationship(
            "this is just prose with no separator",
            source_doc,
            SOURCE_TEXT_CUSTOMER,
        )
        assert r.subject == ""
        assert r.object == ""

    def test_relationship_provenance_populated(self, source_doc: Path):
        from ontozense.extractors.domain_doc_extractor import DomainDocumentExtractor

        ext = DomainDocumentExtractor()
        r = ext._build_relationship(
            "customer identifier -> uniquely identifies -> customer record",
            source_doc,
            SOURCE_TEXT_CUSTOMER,
        )
        assert r.provenance is not None
        assert "customer-master.md" in r.provenance.source_document

    def test_relationship_both_endpoints_in_source_high_score(self, source_doc: Path):
        from ontozense.extractors.domain_doc_extractor import DomainDocumentExtractor

        ext = DomainDocumentExtractor()
        # Both 'customer identifier' and 'customer record' appear in SOURCE_TEXT_CUSTOMER
        r = ext._build_relationship(
            "customer identifier -> uniquely identifies -> customer record",
            source_doc,
            SOURCE_TEXT_CUSTOMER,
        )
        assert r.overall_confidence() == 0.95

    def test_relationship_neither_endpoint_in_source_low_score(self, source_doc: Path):
        """A relationship whose endpoints don't appear in source should be
        flagged for review, not parked at 0.5 above the review threshold."""
        from ontozense.extractors.domain_doc_extractor import DomainDocumentExtractor

        ext = DomainDocumentExtractor()
        r = ext._build_relationship(
            "fictional widget -> totally invented predicate -> nonexistent thing",
            source_doc,
            SOURCE_TEXT_CUSTOMER,
        )
        # Both endpoints absent → 0.30 (clearly below review threshold)
        assert r.overall_confidence() == 0.30
        # And needs_review (using 0.7 default) reflects that
        assert r.overall_confidence() < 0.7

    def test_relationship_one_endpoint_in_source_mid_score(self, source_doc: Path):
        from ontozense.extractors.domain_doc_extractor import DomainDocumentExtractor

        ext = DomainDocumentExtractor()
        # 'customer identifier' is in source, 'martian widget' is not
        r = ext._build_relationship(
            "customer identifier -> orbits around -> martian widget",
            source_doc,
            SOURCE_TEXT_CUSTOMER,
        )
        # (0.95 + 0.30) / 2 = 0.625
        assert abs(r.overall_confidence() - 0.625) < 0.01

    def test_relationship_snippet_falls_back_to_object_when_subject_absent(
        self, source_doc: Path
    ):
        """If the subject isn't in the source but the object is, the
        provenance snippet should still be populated (anchored on the
        object). Without this fallback, half of the mixed-grounding
        relationships would have empty provenance despite having
        evidence.
        """
        from ontozense.extractors.domain_doc_extractor import DomainDocumentExtractor

        ext = DomainDocumentExtractor()
        # Subject 'martian widget' is absent, object 'customer identifier'
        # is present in SOURCE_TEXT_CUSTOMER
        r = ext._build_relationship(
            "martian widget -> orbits around -> customer identifier",
            source_doc,
            SOURCE_TEXT_CUSTOMER,
        )
        assert r.provenance is not None
        assert r.provenance.source_text_snippet, (
            "Relationship provenance snippet should fall back to the "
            "object anchor when the subject is absent"
        )
        assert "customer identifier" in r.provenance.source_text_snippet.lower()


# ─── End-to-end parsing tests (with mocked OntoGPT) ─────────────────────────


class TestEndToEndYamlList:
    def test_extracts_all_concepts_from_yaml_list_format(self, source_doc: Path):
        from ontozense.extractors import DomainDocumentExtractor

        ext = DomainDocumentExtractor()
        with patch.object(
            ext._ontogpt, "_run_ontogpt", return_value=_ontogpt_json_with_yaml_lists()
        ):
            result = ext.extract_from_file(source_doc)

        assert result.domain_name == "Customer Master Data Management"
        # All four concepts should be extracted (NOT just the first one
        # SPIRES would have captured)
        assert len(result.concepts) == 4
        names = [c.name for c in result.concepts]
        assert "customer identifier" in names
        assert "customer email" in names
        assert "billing address" in names
        assert "account status" in names

    def test_concept_with_inline_definition_parsed(self, source_doc: Path):
        from ontozense.extractors import DomainDocumentExtractor

        ext = DomainDocumentExtractor()
        with patch.object(
            ext._ontogpt, "_run_ontogpt", return_value=_ontogpt_json_with_yaml_lists()
        ):
            result = ext.extract_from_file(source_doc)

        identifier = result.get_concept("customer identifier")
        assert identifier is not None
        assert "unique string" in identifier.definition

    def test_concept_without_definition_leaves_field_empty(self, source_doc: Path):
        from ontozense.extractors import DomainDocumentExtractor

        ext = DomainDocumentExtractor()
        with patch.object(
            ext._ontogpt, "_run_ontogpt", return_value=_ontogpt_json_with_yaml_lists()
        ):
            result = ext.extract_from_file(source_doc)

        billing = result.get_concept("billing address")
        assert billing is not None
        assert billing.definition == ""

    def test_extracts_all_relationships(self, source_doc: Path):
        from ontozense.extractors import DomainDocumentExtractor

        ext = DomainDocumentExtractor()
        with patch.object(
            ext._ontogpt, "_run_ontogpt", return_value=_ontogpt_json_with_yaml_lists()
        ):
            result = ext.extract_from_file(source_doc)

        assert len(result.relationships) == 3
        subjects = [r.subject for r in result.relationships]
        assert "customer identifier" in subjects
        assert "customer email" in subjects
        assert "billing address" in subjects


class TestEndToEndJsonArray:
    def test_extracts_all_concepts_from_json_array_format(self, source_doc: Path):
        from ontozense.extractors import DomainDocumentExtractor

        ext = DomainDocumentExtractor()
        with patch.object(
            ext._ontogpt, "_run_ontogpt", return_value=_ontogpt_json_with_json_arrays()
        ):
            result = ext.extract_from_file(source_doc)

        assert result.domain_name == "Product Catalog Management"
        assert len(result.concepts) == 4
        names = [c.name for c in result.concepts]
        assert "product identifier" in names
        assert "product name" in names
        assert "price" in names

    def test_concept_with_inline_definition_in_json_array(self, source_doc: Path):
        from ontozense.extractors import DomainDocumentExtractor

        ext = DomainDocumentExtractor()
        with patch.object(
            ext._ontogpt, "_run_ontogpt", return_value=_ontogpt_json_with_json_arrays()
        ):
            result = ext.extract_from_file(source_doc)

        product_name = result.get_concept("product name")
        assert product_name is not None
        assert "human readable" in product_name.definition

    def test_extracts_relationships_from_json_array(self, source_doc: Path):
        from ontozense.extractors import DomainDocumentExtractor

        ext = DomainDocumentExtractor()
        with patch.object(
            ext._ontogpt, "_run_ontogpt", return_value=_ontogpt_json_with_json_arrays()
        ):
            result = ext.extract_from_file(source_doc)

        assert len(result.relationships) == 3


class TestFallbackToExtractedObject:
    def test_falls_back_when_raw_completion_empty(self, source_doc: Path):
        """If raw_completion_output is missing, use extracted_object."""
        from ontozense.extractors import DomainDocumentExtractor

        ext = DomainDocumentExtractor()
        with patch.object(
            ext._ontogpt,
            "_run_ontogpt",
            return_value=_ontogpt_json_empty_raw_with_extracted(),
        ):
            result = ext.extract_from_file(source_doc)

        # Should have extracted from extracted_object
        assert result.domain_name == "Order Management"
        assert len(result.concepts) >= 1
        names = [c.name for c in result.concepts]
        assert "order identifier" in names

    def test_fallback_handles_dict_concepts(self, source_doc: Path):
        from ontozense.extractors import DomainDocumentExtractor

        ext = DomainDocumentExtractor()
        with patch.object(
            ext._ontogpt,
            "_run_ontogpt",
            return_value=_ontogpt_json_empty_raw_with_extracted(),
        ):
            result = ext.extract_from_file(source_doc)

        order_id = result.get_concept("order identifier")
        assert order_id is not None
        assert "primary key" in order_id.definition


class TestRobustness:
    def test_garbage_input_returns_empty(self, source_doc: Path):
        from ontozense.extractors import DomainDocumentExtractor

        ext = DomainDocumentExtractor()
        with patch.object(ext._ontogpt, "_run_ontogpt", return_value="not json"):
            result = ext.extract_from_file(source_doc)

        assert result.concepts == []
        assert result.relationships == []
        # source_documents should still be set (we tracked it before parsing)
        assert len(result.source_documents) == 1

    def test_empty_input_returns_empty(self, source_doc: Path):
        from ontozense.extractors import DomainDocumentExtractor

        ext = DomainDocumentExtractor()
        with patch.object(ext._ontogpt, "_run_ontogpt", return_value=""):
            result = ext.extract_from_file(source_doc)

        assert result.concepts == []

    def test_template_path_exists(self):
        from ontozense.extractors.domain_doc_extractor import TEMPLATE_PATH

        assert TEMPLATE_PATH.exists(), f"Template missing at {TEMPLATE_PATH}"

    def test_extractor_uses_bundled_template_by_default(self):
        from ontozense.extractors import DomainDocumentExtractor
        from ontozense.extractors.domain_doc_extractor import TEMPLATE_PATH

        ext = DomainDocumentExtractor()
        assert ext.template_path == TEMPLATE_PATH

    def test_provenance_falls_back_to_definition_when_name_not_in_source(
        self, source_doc: Path
    ):
        """If element name is canonicalized away from source wording,
        provenance should still find a snippet via the definition text."""
        from ontozense.extractors.domain_doc_extractor import DomainDocumentExtractor

        ext = DomainDocumentExtractor()
        # The canonical name "CustomerID" is NOT in the source, but the
        # definition phrase IS
        c = ext._build_concept(
            "CustomerID :: a unique string assigned to each customer",
            source_doc,
            SOURCE_TEXT_CUSTOMER,
        )
        assert c.provenance is not None
        # Snippet should fall back to the definition phrase
        assert c.provenance.source_text_snippet
