"""Tests for the deterministic ID generator (Phase 1)."""

from __future__ import annotations

import pytest

from ontozense.core.identity import (
    compute_id,
    normalize_label,
    parse_id,
)


# ─── normalize_label ────────────────────────────────────────────────────────


class TestNormalizeLabel:
    def test_lowercase(self):
        assert normalize_label("Carbon") == "carbon"

    def test_strip_whitespace(self):
        assert normalize_label("  carbon  ") == "carbon"

    def test_internal_whitespace_to_underscore(self):
        assert normalize_label("Carbon Emissions") == "carbon_emissions"

    def test_multiple_whitespace_collapses(self):
        assert normalize_label("GHG    Emissions") == "ghg_emissions"

    def test_hyphens_become_underscores(self):
        assert normalize_label("Scope-1 Emissions") == "scope_1_emissions"

    def test_underscores_kept_as_separator(self):
        assert normalize_label("scope_1_emissions") == "scope_1_emissions"

    def test_dot_separator_normalised(self):
        assert normalize_label("v1.2.3") == "v1_2_3"

    def test_slash_separator_normalised(self):
        assert normalize_label("co2/ch4") == "co2_ch4"

    def test_unicode_combining_marks_stripped(self):
        # NFKD decomposes; combining accents are dropped
        assert normalize_label("café") == "cafe"
        assert normalize_label("naïve") == "naive"

    def test_unicode_subscript_normalised(self):
        # NFKD decomposes CO₂ to CO2
        assert normalize_label("CO₂ Equivalent") == "co2_equivalent"

    def test_empty_string(self):
        assert normalize_label("") == ""

    def test_only_separators_strips_to_empty(self):
        assert normalize_label("   ") == ""
        assert normalize_label("---") == ""

    def test_punctuation_dropped(self):
        assert normalize_label("Currency (USD)") == "currency_usd"
        assert normalize_label("Note: required") == "note_required"

    def test_idempotent_on_already_normalised(self):
        n = normalize_label("carbon_emissions")
        assert normalize_label(n) == n


# ─── compute_id ──────────────────────────────────────────────────────────────


class TestComputeId:
    def test_basic(self):
        eid = compute_id("Metric", "Carbon Emissions")
        assert eid.startswith("metric_carbon_emissions_")
        assert len(eid.split("_")[-1]) == 6  # 6-char hash suffix

    def test_deterministic_same_inputs_same_id(self):
        a = compute_id("Metric", "Carbon Emissions")
        b = compute_id("Metric", "Carbon Emissions")
        assert a == b

    def test_case_insensitive_on_type_and_label(self):
        a = compute_id("Metric", "Carbon Emissions")
        b = compute_id("metric", "carbon emissions")
        c = compute_id("METRIC", "CARBON EMISSIONS")
        assert a == b == c

    def test_punctuation_normalised_into_same_id(self):
        a = compute_id("Metric", "Scope-1 Emissions")
        b = compute_id("Metric", "Scope 1 Emissions")
        c = compute_id("Metric", "scope_1_emissions")
        assert a == b == c

    def test_different_type_different_id(self):
        a = compute_id("Metric", "Default")
        b = compute_id("Concept", "Default")
        assert a != b
        assert a.startswith("metric_")
        assert b.startswith("concept_")

    def test_different_label_different_id(self):
        a = compute_id("Metric", "Carbon Emissions")
        b = compute_id("Metric", "Methane Emissions")
        assert a != b

    def test_unicode_normalised_into_same_id(self):
        a = compute_id("Metric", "CO₂ Emissions")
        b = compute_id("Metric", "CO2 Emissions")
        assert a == b

    def test_empty_type_raises(self):
        with pytest.raises(ValueError, match="entity_type"):
            compute_id("", "Default")
        with pytest.raises(ValueError, match="entity_type"):
            compute_id("   ", "Default")

    def test_empty_label_raises(self):
        with pytest.raises(ValueError, match="normalises to empty"):
            compute_id("Metric", "")

    def test_label_only_punctuation_raises(self):
        with pytest.raises(ValueError, match="normalises to empty"):
            compute_id("Metric", "---")

    def test_short_hash_rejected(self):
        with pytest.raises(ValueError, match="hash_length"):
            compute_id("Metric", "Default", hash_length=3)

    def test_custom_hash_length(self):
        eid = compute_id("Metric", "Carbon", hash_length=10)
        # type + label + 10-char hash
        assert eid.split("_")[-1].__len__() == 10

    def test_no_collision_for_distinct_concepts_with_short_labels(self):
        """Sanity check: 100 distinct concepts → 100 distinct IDs at default hash."""
        ids = {compute_id("Metric", f"label_{i}") for i in range(100)}
        assert len(ids) == 100


# ─── parse_id ────────────────────────────────────────────────────────────────


class TestParseId:
    def test_roundtrip_basic(self):
        eid = compute_id("Metric", "Carbon Emissions")
        type_part, label_part, hash_part = parse_id(eid)
        assert type_part == "metric"
        assert label_part == "carbon_emissions"
        assert len(hash_part) == 6

    def test_roundtrip_with_underscored_label(self):
        eid = compute_id("Concept", "Non Performing Exposure")
        t, l, h = parse_id(eid)
        assert t == "concept"
        assert l == "non_performing_exposure"

    def test_invalid_format_raises(self):
        with pytest.raises(ValueError):
            parse_id("not-a-valid-id")

    def test_missing_separator_raises(self):
        with pytest.raises(ValueError):
            parse_id("metriclabelhash")

    def test_non_hex_suffix_raises(self):
        with pytest.raises(ValueError):
            parse_id("metric_label_zzzzzz")

    def test_empty_string_raises(self):
        with pytest.raises(ValueError):
            parse_id("")
