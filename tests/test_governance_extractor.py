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
        assert len(result.records) == 1
        assert result.records[0].element_name == "Default"
        assert result.records[0].domain_name == "Risk Management"
        assert result.records[0].is_critical is True
        assert result.records[0].definition.startswith("Default is a status")
        assert "Collibra" in result.records[0].citation
        assert result.records[0].confidence == 0.95


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
