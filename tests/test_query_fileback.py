"""Tests for query and file-back (Step 8).

Query looks up elements in a FusionResult and renders markdown.
File-back saves derived artifacts to <domain>/derived/<category>/.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ontozense.core.fusion import (
    FusedElement,
    FusedRelationship,
    FieldConflict,
    FieldProvenance,
    FusionResult,
)
from ontozense.core.query import query_element, search_elements, render_search_results
from ontozense.core.fileback import file_back


# ─── Fixtures ────────────────────────────────────────────────────────────────


def _el(name, definition="", citation="", sources=None,
        data_type="", business_rules=None, governance_validated=False):
    return FusedElement(
        element_name=name,
        definition=definition,
        citation=citation,
        sources=list(sources or ["A"]),
        data_type=data_type,
        business_rules=list(business_rules or []),
        governance_validated=governance_validated,
        confidence=0.8,
    )


def _result(elements=None, relationships=None):
    return FusionResult(
        elements=list(elements or []),
        relationships=list(relationships or []),
        sources_used=["A"],
    )


# ─── Query: element lookup ──────────────────────────────────────────────────


class TestQueryElement:
    def test_exact_match_returns_markdown(self):
        r = _result([_el("Default", "The definition.", "Section 5")])
        md = query_element(r, "Default")
        assert md is not None
        assert "Default" in md
        assert "The definition." in md
        assert "Section 5" in md

    def test_case_insensitive_lookup(self):
        r = _result([_el("Default")])
        assert query_element(r, "default") is not None
        assert query_element(r, "DEFAULT") is not None

    def test_not_found_returns_none(self):
        r = _result([_el("Default")])
        assert query_element(r, "Nonexistent") is None

    def test_governance_validated_shown(self):
        r = _result([_el("Default", governance_validated=True)])
        md = query_element(r, "Default")
        assert "Governance validated" in md

    def test_business_rules_shown(self):
        r = _result([_el("Default", business_rules=["[constant] THRESHOLD = 90"])])
        md = query_element(r, "Default")
        assert "THRESHOLD" in md
        assert "Business rules" in md

    def test_relationships_shown(self):
        r = _result(
            elements=[_el("Default"), _el("Exposure")],
            relationships=[
                FusedRelationship("Default", "triggers", "Exposure", "A", 0.9),
            ],
        )
        md = query_element(r, "Default")
        assert "triggers" in md
        assert "Exposure" in md

    def test_conflicts_shown(self):
        el = _el("Default", definition="A def")
        el.conflicts.append(FieldConflict(
            field_name="definition",
            winner=FieldProvenance("A", 0.9, "A def"),
            rejected=[FieldProvenance("B", 0.8, "B def")],
            resolution="priority",
        ))
        r = _result([el])
        md = query_element(r, "Default")
        assert "Conflicts" in md
        assert "B def" in md

    def test_data_type_shown(self):
        r = _result([_el("status", data_type="string")])
        md = query_element(r, "status")
        assert "string" in md


# ─── Query: search ──────────────────────────────────────────────────────────


class TestSearchElements:
    def test_substring_match(self):
        r = _result([
            _el("Customer Identifier"),
            _el("Customer Email"),
            _el("Account Status"),
        ])
        matches = search_elements(r, "customer")
        assert len(matches) == 2
        names = {e.element_name for e in matches}
        assert "Customer Identifier" in names
        assert "Customer Email" in names

    def test_no_match_returns_empty(self):
        r = _result([_el("Default")])
        assert search_elements(r, "xyz") == []

    def test_render_search_results_markdown(self):
        r = _result([_el("Default", "The definition.")])
        matches = search_elements(r, "default")
        md = render_search_results(matches, "default", r)
        assert "Search: 'default'" in md
        assert "1 match" in md
        assert "Default" in md

    def test_render_empty_search(self):
        r = _result()
        md = render_search_results([], "xyz", r)
        assert "No elements found" in md


# ─── File-back ───────────────────────────────────────────────────────────────


class TestFileBack:
    def test_files_to_derived_analyses(self, tmp_path):
        # Create a source file
        src = tmp_path / "my-review.md"
        src.write_text("# Expert review\n\nLooks good.", encoding="utf-8")

        # Create a domain dir
        domain = tmp_path / "domains" / "npl"
        domain.mkdir(parents=True)

        dest = file_back(src, domain, category="analyses")

        assert dest.exists()
        assert dest.parent == domain / "derived" / "analyses"
        assert dest.name == "my-review.md"
        assert dest.read_text(encoding="utf-8").startswith("# Expert review")

    def test_log_entry_appended(self, tmp_path):
        src = tmp_path / "review.md"
        src.write_text("content", encoding="utf-8")
        domain = tmp_path / "domain"
        domain.mkdir()

        file_back(src, domain)

        log = (domain / "log.md").read_text(encoding="utf-8")
        assert "file-back" in log
        assert "review.md" in log

    def test_duplicate_filename_gets_timestamp_suffix(self, tmp_path):
        src = tmp_path / "review.md"
        src.write_text("v1", encoding="utf-8")
        domain = tmp_path / "domain"
        domain.mkdir()

        dest1 = file_back(src, domain)
        assert dest1.name == "review.md"

        # File back again with the same filename
        src.write_text("v2", encoding="utf-8")
        dest2 = file_back(src, domain)
        # Should have a timestamp suffix, not overwrite v1
        assert dest2.name != "review.md"
        assert dest2.name.startswith("review_")
        assert dest2.exists()
        # Original is still v1
        assert dest1.read_text(encoding="utf-8") == "v1"

    def test_custom_category(self, tmp_path):
        src = tmp_path / "comparison.xlsx"
        src.write_text("data", encoding="utf-8")
        domain = tmp_path / "domain"
        domain.mkdir()

        dest = file_back(src, domain, category="comparisons")
        assert dest.parent == domain / "derived" / "comparisons"

    def test_file_not_found_raises(self, tmp_path):
        domain = tmp_path / "domain"
        domain.mkdir()
        with pytest.raises(FileNotFoundError):
            file_back(tmp_path / "nonexistent.md", domain)
