"""Tests for the regex-based definitions extractor.

These tests use synthetic prose-shaped markdown that exercises each pattern
individually, plus a combined sample. No LLM calls — pure regex.

All synthetic content is domain-neutral (e.g. widgets, customers, orders) so
the engine remains domain-agnostic per ``tests/test_domain_neutrality.py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest


# ─── Synthetic source samples ────────────────────────────────────────────────


BOLD_COLON_SAMPLE = """
# Catalog

## Definitions

**Widget**: a unit of inventory representing a single sellable item.

**Customer**: an individual or organization that purchases widgets.

**Order**: a transaction in which a customer purchases one or more widgets.
"""

CODE_COLON_SAMPLE = """
## Field Definitions

`order_id`: the primary key of an order, generated as an integer.

`customer_id`: a foreign key referencing the customer that placed the order.
"""

QUOTED_COLON_SAMPLE = """
"Active Customer": a customer with at least one order in the past 90 days.

"Lapsed Customer": a customer with no orders in the past 365 days.
"""

IS_DEFINED_AS_SAMPLE = """
Premium Widget is defined as a widget with a list price exceeding 100 currency units.

Bulk Order is defined as an order containing more than 50 line items.
"""

MEANS_SAMPLE = """
Backorder means an order that cannot currently be fulfilled because the
required widgets are out of stock.
"""

NUMBERED_LIST_SAMPLE = """
## Glossary

1. Returned Widget: a widget returned by a customer within the return window.

2. Refund Issued: a credit applied to a customer account for a returned widget.
"""

COMBINED_SAMPLE = """
# Catalog

## Section 1 — Definitions

**Widget**: a unit of inventory representing a single sellable item.

`order_id`: the primary key of an order.

"Active Customer": a customer with recent activity.

Premium Widget is defined as a widget with a list price exceeding a threshold.

## Section 2 — Glossary

1. Returned Widget: a widget returned by a customer.

2. Bulk Order: an order containing many items.
"""


# ─── Pattern-by-pattern tests ────────────────────────────────────────────────


class TestBoldColonPattern:
    def test_extracts_bold_colon_definitions(self):
        from ontozense.extractors import extract_definitions_from_text

        matches = extract_definitions_from_text(BOLD_COLON_SAMPLE)
        terms = [m.term for m in matches]
        assert "Widget" in terms
        assert "Customer" in terms
        assert "Order" in terms

    def test_bold_colon_definition_content(self):
        from ontozense.extractors import extract_definitions_from_text

        matches = extract_definitions_from_text(BOLD_COLON_SAMPLE)
        widget = next((m for m in matches if m.term == "Widget"), None)
        assert widget is not None
        assert "unit of inventory" in widget.definition

    def test_bold_colon_pattern_name_recorded(self):
        from ontozense.extractors import extract_definitions_from_text

        matches = extract_definitions_from_text(BOLD_COLON_SAMPLE)
        widget = next((m for m in matches if m.term == "Widget"), None)
        assert widget is not None
        assert widget.pattern_name == "bold_colon"


class TestCodeColonPattern:
    def test_extracts_code_span_definitions(self):
        from ontozense.extractors import extract_definitions_from_text

        matches = extract_definitions_from_text(CODE_COLON_SAMPLE)
        terms = [m.term for m in matches]
        assert "order_id" in terms
        assert "customer_id" in terms


class TestQuotedColonPattern:
    def test_extracts_quoted_definitions(self):
        from ontozense.extractors import extract_definitions_from_text

        matches = extract_definitions_from_text(QUOTED_COLON_SAMPLE)
        terms = [m.term for m in matches]
        assert "Active Customer" in terms
        assert "Lapsed Customer" in terms


class TestIsDefinedAsPattern:
    def test_extracts_is_defined_as(self):
        from ontozense.extractors import extract_definitions_from_text

        matches = extract_definitions_from_text(IS_DEFINED_AS_SAMPLE)
        terms = [m.term.strip() for m in matches]
        assert any("Premium Widget" in t for t in terms)
        assert any("Bulk Order" in t for t in terms)


class TestMeansPattern:
    def test_extracts_means_pattern(self):
        from ontozense.extractors import extract_definitions_from_text

        matches = extract_definitions_from_text(MEANS_SAMPLE)
        assert len(matches) >= 1
        backorder = next((m for m in matches if "Backorder" in m.term), None)
        assert backorder is not None
        assert "out of stock" in backorder.definition


class TestNumberedListPattern:
    def test_extracts_numbered_definitions(self):
        from ontozense.extractors import extract_definitions_from_text

        matches = extract_definitions_from_text(NUMBERED_LIST_SAMPLE)
        terms = [m.term for m in matches]
        assert any("Returned Widget" in t for t in terms)
        assert any("Refund Issued" in t for t in terms)


# ─── Combined / multi-pattern tests ──────────────────────────────────────────


class TestCombinedSample:
    def test_finds_definitions_from_multiple_patterns(self):
        from ontozense.extractors import extract_definitions_from_text

        matches = extract_definitions_from_text(COMBINED_SAMPLE)
        # Should find at least: Widget, order_id, Active Customer, Premium Widget,
        # Returned Widget, Bulk Order
        assert len(matches) >= 5
        terms = {m.term for m in matches}
        assert "Widget" in terms
        assert "order_id" in terms
        assert "Active Customer" in terms

    def test_section_assigned_to_each_match(self):
        from ontozense.extractors import extract_definitions_from_text

        matches = extract_definitions_from_text(COMBINED_SAMPLE)
        # Every match should have a non-empty section (since the sample has headings)
        for m in matches:
            assert m.source_section, f"No section for {m.term}"

    def test_matches_sorted_by_document_position(self):
        from ontozense.extractors import extract_definitions_from_text

        matches = extract_definitions_from_text(COMBINED_SAMPLE)
        offsets = [m.char_offset for m in matches]
        assert offsets == sorted(offsets), "Matches should be in document order"


# ─── Filtering and dedup tests ───────────────────────────────────────────────


class TestFiltering:
    def test_skips_overshort_definitions(self):
        from ontozense.extractors import extract_definitions_from_text

        # Widget has a long-enough definition; Foo is too short and should be filtered
        text = "**Widget**: a unit of inventory representing one sellable item.\n\n**Foo**: x"
        matches = extract_definitions_from_text(text)
        terms = [m.term for m in matches]
        assert "Widget" in terms
        # "Foo" with definition "x" is below the 10-char minimum
        assert "Foo" not in terms

    def test_dedupes_identical_matches(self):
        from ontozense.extractors import extract_definitions_from_text

        text = """
**Widget**: a unit of inventory representing a sellable item.

**Widget**: a unit of inventory representing a sellable item.
"""
        matches = extract_definitions_from_text(text)
        # Should dedupe by (term, definition prefix)
        widget_count = sum(1 for m in matches if m.term == "Widget")
        assert widget_count == 1

    def test_handles_empty_text(self):
        from ontozense.extractors import extract_definitions_from_text

        assert extract_definitions_from_text("") == []
        assert extract_definitions_from_text("   ") == []

    def test_handles_text_with_no_definitions(self):
        from ontozense.extractors import extract_definitions_from_text

        text = "This is just prose with no defining patterns at all."
        matches = extract_definitions_from_text(text)
        assert matches == []


# ─── File loading test ──────────────────────────────────────────────────────


class TestFileLoading:
    def test_extract_from_file(self, tmp_path: Path):
        from ontozense.extractors import extract_definitions_from_file

        doc = tmp_path / "test.md"
        doc.write_text(COMBINED_SAMPLE, encoding="utf-8")

        matches = extract_definitions_from_file(doc)
        assert len(matches) >= 5

    def test_extract_from_file_handles_unicode(self, tmp_path: Path):
        from ontozense.extractors import extract_definitions_from_file

        doc = tmp_path / "unicode.md"
        # Em-dash and en-dash separators
        doc.write_text(
            "**Café**: a small establishment serving coffee — and pastries.\n",
            encoding="utf-8",
        )

        matches = extract_definitions_from_file(doc)
        assert len(matches) >= 1


# ─── DefinitionMatch dataclass test ──────────────────────────────────────────


class TestDefinitionMatchDataclass:
    def test_definition_match_fields(self):
        from ontozense.extractors import DefinitionMatch

        m = DefinitionMatch(
            term="Widget",
            definition="a unit",
            source_section="Definitions",
            pattern_name="bold_colon",
            char_offset=42,
        )
        assert m.term == "Widget"
        assert m.definition == "a unit"
        assert m.source_section == "Definitions"
        assert m.pattern_name == "bold_colon"
        assert m.char_offset == 42

    def test_definition_match_defaults(self):
        from ontozense.extractors import DefinitionMatch

        m = DefinitionMatch(term="X", definition="y is a thing")
        assert m.source_section == ""
        assert m.pattern_name == ""
        assert m.char_offset == 0
