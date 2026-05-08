"""Tests for Source B — the governance extractor.

Source B reads a curated JSON governance reference file and produces
GovernanceRecord objects. Its role is validation of Source A concepts,
not heavy extraction.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ontozense.extractors.governance_extractor import (
    GovernanceExtractor,
    GovernanceExtractionResult,
    GovernanceRecord,
)


REAL_EXAMPLE = Path(__file__).parent.parent / "docs" / "governance_example.json"


@pytest.fixture
def extractor():
    return GovernanceExtractor()


# ─── Real file test ──────────────────────────────────────────────────────────


class TestRealGovernanceFile:
    """Test against the real docs/governance_example.json."""

    def test_extracts_from_real_example(self, extractor):
        if not REAL_EXAMPLE.exists():
            pytest.skip("governance_example.json not found")
        result = extractor.extract_from_file(REAL_EXAMPLE)
        assert len(result.records) == 18
        assert result.records[0].element_name == "Borrower"
        assert result.records[0].domain_name == "Risk Management"
        assert result.records[0].is_critical is True
        assert "data marketplace" in result.records[0].citation
        assert result.records[0].confidence == 0.95
        # Check a non-critical entry
        receiver = result.get_record("Receiver")
        assert receiver is not None
        assert receiver.is_critical is False


# ─── Single object vs array ─────────────────────────────────────────────────


class TestInputFormats:
    def test_single_object(self, extractor, tmp_path):
        f = tmp_path / "single.json"
        f.write_text(json.dumps({
            "element_name": "Exposure",
            "definition": "A financial exposure.",
        }), encoding="utf-8")
        result = extractor.extract_from_file(f)
        assert len(result.records) == 1
        assert result.records[0].element_name == "Exposure"

    def test_array_of_objects(self, extractor, tmp_path):
        f = tmp_path / "array.json"
        f.write_text(json.dumps([
            {"element_name": "Exposure", "is_critical": True},
            {"element_name": "Collateral", "is_critical": False},
            {"element_name": "Counterparty"},
        ]), encoding="utf-8")
        result = extractor.extract_from_file(f)
        assert len(result.records) == 3
        names = [r.element_name for r in result.records]
        assert names == ["Exposure", "Collateral", "Counterparty"]

    def test_empty_array(self, extractor, tmp_path):
        f = tmp_path / "empty.json"
        f.write_text("[]", encoding="utf-8")
        result = extractor.extract_from_file(f)
        assert len(result.records) == 0
        assert not result.warnings


# ─── Field handling ──────────────────────────────────────────────────────────


class TestFieldHandling:
    def test_is_critical_bool_true(self, extractor, tmp_path):
        f = tmp_path / "t.json"
        f.write_text(json.dumps({"element_name": "X", "is_critical": True}))
        r = extractor.extract_from_file(f).records[0]
        assert r.is_critical is True

    def test_is_critical_bool_false(self, extractor, tmp_path):
        f = tmp_path / "t.json"
        f.write_text(json.dumps({"element_name": "X", "is_critical": False}))
        r = extractor.extract_from_file(f).records[0]
        assert r.is_critical is False

    def test_is_critical_string_yes(self, extractor, tmp_path):
        f = tmp_path / "t.json"
        f.write_text(json.dumps({"element_name": "X", "is_critical": "Yes"}))
        r = extractor.extract_from_file(f).records[0]
        assert r.is_critical is True

    def test_is_critical_string_no(self, extractor, tmp_path):
        f = tmp_path / "t.json"
        f.write_text(json.dumps({"element_name": "X", "is_critical": "No"}))
        r = extractor.extract_from_file(f).records[0]
        assert r.is_critical is False

    def test_is_critical_absent_defaults_false(self, extractor, tmp_path):
        f = tmp_path / "t.json"
        f.write_text(json.dumps({"element_name": "X"}))
        r = extractor.extract_from_file(f).records[0]
        assert r.is_critical is False

    def test_extra_fields_preserved(self, extractor, tmp_path):
        f = tmp_path / "t.json"
        f.write_text(json.dumps({
            "element_name": "X",
            "custom_field": "custom_value",
            "another": 42,
        }))
        r = extractor.extract_from_file(f).records[0]
        assert r.extra_fields["custom_field"] == "custom_value"
        assert r.extra_fields["another"] == 42

    def test_source_file_populated(self, extractor, tmp_path):
        f = tmp_path / "t.json"
        f.write_text(json.dumps({"element_name": "X"}))
        r = extractor.extract_from_file(f).records[0]
        assert r.source_file == str(f)

    def test_get_record_case_insensitive(self, extractor, tmp_path):
        f = tmp_path / "t.json"
        f.write_text(json.dumps([
            {"element_name": "Default"},
            {"element_name": "Exposure"},
        ]))
        result = extractor.extract_from_file(f)
        assert result.get_record("default") is not None
        assert result.get_record("DEFAULT") is not None
        assert result.get_record("nonexistent") is None


# ─── Error handling ──────────────────────────────────────────────────────────


class TestErrorHandling:
    def test_file_not_found(self, extractor):
        with pytest.raises(FileNotFoundError):
            extractor.extract_from_file("/nonexistent/path.json")

    def test_invalid_json(self, extractor, tmp_path):
        f = tmp_path / "bad.json"
        f.write_text("this is not json {{{", encoding="utf-8")
        result = extractor.extract_from_file(f)
        assert len(result.records) == 0
        assert result.warnings
        assert "Invalid JSON" in result.warnings[0]

    def test_missing_element_name_skipped_with_warning(self, extractor, tmp_path):
        f = tmp_path / "t.json"
        f.write_text(json.dumps([
            {"element_name": "Valid"},
            {"definition": "missing element_name"},
            {"element_name": "", "definition": "empty element_name"},
        ]))
        result = extractor.extract_from_file(f)
        assert len(result.records) == 1
        assert result.records[0].element_name == "Valid"
        assert len(result.warnings) == 2

    def test_non_object_entry_skipped_with_warning(self, extractor, tmp_path):
        f = tmp_path / "t.json"
        f.write_text(json.dumps(["not an object", {"element_name": "Valid"}]))
        result = extractor.extract_from_file(f)
        assert len(result.records) == 1
        assert result.warnings


# ─── Source B anchors (wrap-up #2) ──────────────────────────────────────────


class TestSourceBAnchors:
    """The governance extractor captures the (line, column, char_offset,
    snippet, segment_id=filename) of each entry's opening ``{`` so
    fusion can attach an anchor per B-contributed field. Phase 6 added
    the ``FieldAnchor`` shape; this wrap-up phase populates it from
    Source B."""

    def test_array_records_have_distinct_line_numbers(self, extractor, tmp_path):
        """Each record in a JSON array gets a different line number
        when the source is pretty-printed across multiple lines."""
        f = tmp_path / "gov.json"
        # Pretty-print with one record per indented block — typical
        # human-curated governance file shape.
        f.write_text(json.dumps([
            {"element_name": "First", "definition": "a"},
            {"element_name": "Second", "definition": "b"},
            {"element_name": "Third", "definition": "c"},
        ], indent=2), encoding="utf-8")

        result = extractor.extract_from_file(f)
        assert len(result.records) == 3
        anchors = [r.source_anchor for r in result.records]
        # All three got anchors
        assert all(a is not None for a in anchors)
        # And the lines are strictly increasing (entries are ordered)
        lines = [a.line for a in anchors]
        assert lines == sorted(lines)
        assert len(set(lines)) == 3, "Each record must land on its own line"

    def test_anchor_records_filename_in_segment_id(self, extractor, tmp_path):
        f = tmp_path / "my-governance.json"
        f.write_text(json.dumps({"element_name": "X"}), encoding="utf-8")
        result = extractor.extract_from_file(f)
        assert result.records[0].source_anchor.segment_id == "my-governance.json"

    def test_anchor_snippet_starts_with_opening_brace(self, extractor, tmp_path):
        """The captured snippet starts at the entry's ``{`` so a
        reviewer reading the snippet sees recognisable JSON."""
        f = tmp_path / "g.json"
        f.write_text(json.dumps([
            {"element_name": "Customer", "definition": "A buyer."},
        ], indent=2), encoding="utf-8")
        result = extractor.extract_from_file(f)
        anchor = result.records[0].source_anchor
        assert anchor.snippet.startswith("{")
        assert "Customer" in anchor.snippet

    def test_single_object_input_anchor_at_offset_zero(self, extractor, tmp_path):
        """A single-object governance file (not an array) anchors
        the one record at the start of the file (after any leading
        whitespace)."""
        f = tmp_path / "g.json"
        f.write_text('{"element_name": "Solo", "definition": "x"}',
                     encoding="utf-8")
        result = extractor.extract_from_file(f)
        anchor = result.records[0].source_anchor
        assert anchor.char_offset == 0
        assert anchor.line == 1
        assert anchor.column == 1

    def test_anchor_column_reflects_indentation(self, extractor, tmp_path):
        """For pretty-printed arrays, the entry's column equals the
        indentation level (the number of spaces before ``{`` plus 1
        for 1-indexed)."""
        f = tmp_path / "g.json"
        f.write_text(json.dumps([
            {"element_name": "A"},
        ], indent=4), encoding="utf-8")
        result = extractor.extract_from_file(f)
        anchor = result.records[0].source_anchor
        # json.dumps with indent=4 puts entries at column 5 (4 spaces + 1)
        assert anchor.column == 5

    def test_no_file_records_constructed_directly_have_no_anchor(self):
        """A GovernanceRecord constructed without going through
        extract_from_file (e.g. a unit test stub) has source_anchor=None,
        which is the documented default."""
        rec = GovernanceRecord(element_name="X")
        assert rec.source_anchor is None

