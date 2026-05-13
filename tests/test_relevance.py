"""Tests for the relevance scoring stage (profile induction
architecture, Phase 2 / Task 3).

The scoring stage takes the ``CandidateConcept`` list from Phase 1's
candidate graph and assigns ``relevance_score``, ``relevance_breakdown``,
and ``classification`` to each candidate.

These tests pin the documented contract:

  - Seven weighted signals listed in ``DEFAULT_WEIGHTS``.
  - Thresholds 0.70 / 0.40 split candidates into
    ``core_business`` / ``supporting_technical`` / ``noise``.
  - The breakdown values are weighted contributions (signal × weight)
    and sum to the total relevance score, so the explanation is
    transparent and reviewable.
  - Custom weights override the defaults (Phase 3 plumbs a YAML
    override; tests pass a dict directly).
  - Edge cases: empty list, saturation, threshold boundaries,
    business-naming penalty, whitespace-only definitions.
"""

from __future__ import annotations

import pytest

from ontozense.core.discovery_contracts import CandidateConcept
from ontozense.core.relevance import (
    DEFAULT_THRESHOLDS,
    DEFAULT_WEIGHTS,
    score_candidates,
)


# ─── Helpers ────────────────────────────────────────────────────────────────


def _concept(
    label: str,
    *,
    a: int = 0,
    b: int = 0,
    c: int = 0,
    d: int = 0,
    degree: int = 0,
    definition: str = "",
) -> CandidateConcept:
    """Build a candidate concept with the source counts and graph
    metrics the scorer reads. ``label`` drives the business-naming
    signal; ``definition`` drives definition-richness."""
    return CandidateConcept(
        candidate_id=f"cand_{label.lower().replace(' ', '_')}",
        label=label,
        normalized_label=label.lower(),
        suggested_entity_type="Concept",
        classification="unknown",
        summary_definition=definition,
        source_presence={"A": a > 0, "B": b > 0, "C": c > 0, "D": d > 0},
        source_counts={"A": a, "B": b, "C": c, "D": d},
        authoritative_evidence_count=a,
        graph_degree=degree,
    )


# ─── Classification bands (the three documented thresholds) ────────────────


class TestClassificationBands:
    """A high-evidence candidate must score ≥ 0.70 → core_business.
    A mid-evidence candidate lands in [0.40, 0.70) → supporting_technical.
    A barely-evidenced candidate lands < 0.40 → noise."""

    def test_high_evidence_concept_classifies_as_core_business(self):
        c = _concept(
            "Customer", a=3, b=1, c=1, d=1, degree=5,
            definition="A party that receives a service.",
        )
        scored = score_candidates([c])[0]
        assert scored.classification == "core_business"
        assert scored.relevance_score >= 0.70

    def test_mid_evidence_concept_classifies_as_supporting_technical(self):
        # A=2 + B present + degree=1 + definition + clean name lands
        # in the middle band with default weights.
        c = _concept(
            "Address", a=2, b=1, degree=1,
            definition="A postal location.",
        )
        scored = score_candidates([c])[0]
        assert 0.40 <= scored.relevance_score < 0.70
        assert scored.classification == "supporting_technical"

    def test_low_evidence_concept_classifies_as_noise(self):
        c = _concept("tmp_col_1", c=1)  # noise-y name, almost no signals
        scored = score_candidates([c])[0]
        assert scored.classification == "noise"
        assert scored.relevance_score < 0.40


# ─── Individual signal contributions ───────────────────────────────────────


class TestIndividualSignals:
    """One test per signal in DEFAULT_WEIGHTS — a regression in any
    single signal (formula change, weight zeroed) is caught here."""

    def test_authoritative_frequency_contributes_with_source_a_count(self):
        zero = _concept("Widget")
        with_a = _concept("Widget", a=3)
        zero_score = score_candidates([zero])[0]
        with_a_score = score_candidates([with_a])[0]
        assert with_a_score.relevance_breakdown["authoritative_frequency"] > \
            zero_score.relevance_breakdown["authoritative_frequency"]

    def test_governance_presence_fires_on_source_b(self):
        without = _concept("Widget")
        with_b = _concept("Widget", b=1)
        assert score_candidates([with_b])[0].relevance_breakdown[
            "governance_presence"] > 0
        assert score_candidates([without])[0].relevance_breakdown[
            "governance_presence"] == 0

    def test_schema_linkage_fires_on_source_c(self):
        without = _concept("Widget")
        with_c = _concept("Widget", c=1)
        assert score_candidates([with_c])[0].relevance_breakdown[
            "schema_linkage"] > 0
        assert score_candidates([without])[0].relevance_breakdown[
            "schema_linkage"] == 0

    def test_code_usage_fires_on_source_d(self):
        without = _concept("Widget")
        with_d = _concept("Widget", d=1)
        assert score_candidates([with_d])[0].relevance_breakdown[
            "code_usage"] > 0
        assert score_candidates([without])[0].relevance_breakdown[
            "code_usage"] == 0

    def test_graph_centrality_contributes_with_graph_degree(self):
        zero = _concept("Widget")
        connected = _concept("Widget", degree=4)
        assert score_candidates([connected])[0].relevance_breakdown[
            "graph_centrality"] > \
            score_candidates([zero])[0].relevance_breakdown[
                "graph_centrality"]

    def test_definition_richness_fires_on_nonempty_definition(self):
        without = _concept("Widget")
        with_def = _concept("Widget", definition="A useful thing.")
        assert score_candidates([with_def])[0].relevance_breakdown[
            "definition_richness"] > 0
        assert score_candidates([without])[0].relevance_breakdown[
            "definition_richness"] == 0

    def test_business_naming_signal_full_value_for_clean_label(self):
        clean = _concept("Widget")
        scored = score_candidates([clean])[0]
        # Clean labels get the full naming contribution (weight × 0.8)
        expected = DEFAULT_WEIGHTS["business_naming_signal"] * 0.8
        assert scored.relevance_breakdown["business_naming_signal"] == \
            pytest.approx(expected)


# ─── Business-naming signal: domain-neutral noise patterns ─────────────────


class TestBusinessNamingSignal:
    """The naming signal penalises two documented noise patterns:
    ``tmp_<...>`` prefix and ``<...>_id`` suffix. Both are
    domain-neutral conventions (temp columns and surrogate-key
    suffixes) — no banking terms in the source module."""

    def test_tmp_prefix_dampens_naming_signal(self):
        clean = _concept("Customer")
        noisy = _concept("tmp_col_1")
        clean_b = score_candidates([clean])[0].relevance_breakdown[
            "business_naming_signal"]
        noisy_b = score_candidates([noisy])[0].relevance_breakdown[
            "business_naming_signal"]
        assert noisy_b < clean_b

    def test_id_suffix_dampens_naming_signal(self):
        clean = _concept("Customer")
        noisy = _concept("customer_id")
        clean_b = score_candidates([clean])[0].relevance_breakdown[
            "business_naming_signal"]
        noisy_b = score_candidates([noisy])[0].relevance_breakdown[
            "business_naming_signal"]
        assert noisy_b < clean_b

    def test_naming_check_is_case_insensitive(self):
        # TMP_FOO and tmp_foo should both trigger the penalty.
        upper = _concept("TMP_FOO")
        lower = _concept("tmp_foo")
        upper_b = score_candidates([upper])[0].relevance_breakdown[
            "business_naming_signal"]
        lower_b = score_candidates([lower])[0].relevance_breakdown[
            "business_naming_signal"]
        assert upper_b == lower_b


# ─── Explanation contract ──────────────────────────────────────────────────


class TestExplanationContract:
    """The breakdown is the documented transparency mechanism — its
    keys must match ``DEFAULT_WEIGHTS`` exactly and its values must
    sum to ``relevance_score`` so a reviewer can verify the score by
    eye."""

    def test_breakdown_keys_match_default_weights_keys(self):
        c = _concept("Widget", a=1)
        scored = score_candidates([c])[0]
        assert set(scored.relevance_breakdown.keys()) == set(
            DEFAULT_WEIGHTS.keys()
        )

    def test_breakdown_values_sum_to_relevance_score(self):
        # The breakdown values are the exact same float
        # contributions that were summed to form relevance_score —
        # no intermediate rounding — so the invariant holds with a
        # very tight absolute tolerance (handles only the typical
        # ulp-level reordering noise of Python's ``sum``).
        c = _concept("Widget", a=2, b=1, degree=3, definition="A thing.")
        scored = score_candidates([c])[0]
        assert sum(scored.relevance_breakdown.values()) == \
            pytest.approx(scored.relevance_score, abs=1e-12)


# ─── Custom weights and edge cases ─────────────────────────────────────────


class TestCustomWeightsAndEdgeCases:

    def test_empty_candidate_list_returns_empty_list(self):
        assert score_candidates([]) == []

    def test_custom_weights_override_defaults(self):
        # Custom weights that put 100 % of mass on definition_richness:
        # a candidate with a non-empty definition should score 1.0
        # (the only non-zero contribution).
        only_def = {
            "authoritative_frequency": 0.0,
            "governance_presence": 0.0,
            "schema_linkage": 0.0,
            "code_usage": 0.0,
            "graph_centrality": 0.0,
            "definition_richness": 1.0,
            "business_naming_signal": 0.0,
        }
        c = _concept("Widget", definition="Anything.")
        scored = score_candidates([c], weights=only_def)[0]
        assert scored.relevance_score == pytest.approx(1.0)
        # All other signals contribute zero.
        for key in (
            "authoritative_frequency", "governance_presence",
            "schema_linkage", "code_usage", "graph_centrality",
            "business_naming_signal",
        ):
            assert scored.relevance_breakdown[key] == 0.0

    def test_authoritative_frequency_saturates_at_three_sources(self):
        # A=3 and A=10 should produce the same authoritative_frequency
        # contribution — the formula clips at /3.
        three = _concept("Widget", a=3)
        ten = _concept("Widget", a=10)
        three_b = score_candidates([three])[0].relevance_breakdown[
            "authoritative_frequency"]
        ten_b = score_candidates([ten])[0].relevance_breakdown[
            "authoritative_frequency"]
        assert three_b == pytest.approx(ten_b)

    def test_graph_centrality_saturates_at_five_neighbours(self):
        # degree=5 and degree=50 should give the same centrality
        # contribution — the formula clips at /5.
        five = _concept("Widget", degree=5)
        many = _concept("Widget", degree=50)
        five_b = score_candidates([five])[0].relevance_breakdown[
            "graph_centrality"]
        many_b = score_candidates([many])[0].relevance_breakdown[
            "graph_centrality"]
        assert five_b == pytest.approx(many_b)

    def test_definition_richness_treats_whitespace_only_as_empty(self):
        c = _concept("Widget", definition="   \t  \n")
        scored = score_candidates([c])[0]
        assert scored.relevance_breakdown["definition_richness"] == 0.0

    def test_input_candidates_not_mutated(self):
        c = _concept("Widget", a=1)
        original_score = c.relevance_score
        original_breakdown = dict(c.relevance_breakdown)
        original_classification = c.classification
        score_candidates([c])
        # CandidateConcept is frozen so mutation is impossible by
        # construction, but a returned-instead-of-replaced regression
        # would still leave the original instance with its
        # pre-scoring state. Pin that here.
        assert c.relevance_score == original_score
        assert c.relevance_breakdown == original_breakdown
        assert c.classification == original_classification


# ─── Threshold-boundary precision ───────────────────────────────────────────


class TestThresholdBoundaries:
    """Pin the inclusive-on-the-high-side threshold contract.
    Engineered with custom weights so the totals land exactly on the
    boundary without floating-point drift."""

    def test_exact_score_070_is_core_business(self):
        weights = dict.fromkeys(DEFAULT_WEIGHTS.keys(), 0.0)
        weights["authoritative_frequency"] = 0.70
        c = _concept("Widget", a=3)  # clip(3/3) = 1.0 → 0.70 × 1.0 = 0.70
        scored = score_candidates([c], weights=weights)[0]
        assert scored.relevance_score == pytest.approx(0.70)
        assert scored.classification == "core_business"

    def test_exact_score_040_is_supporting_technical(self):
        weights = dict.fromkeys(DEFAULT_WEIGHTS.keys(), 0.0)
        weights["authoritative_frequency"] = 0.40
        c = _concept("Widget", a=3)  # 0.40 × 1.0 = 0.40
        scored = score_candidates([c], weights=weights)[0]
        assert scored.relevance_score == pytest.approx(0.40)
        assert scored.classification == "supporting_technical"

    def test_just_below_040_is_noise(self):
        weights = dict.fromkeys(DEFAULT_WEIGHTS.keys(), 0.0)
        weights["authoritative_frequency"] = 0.39
        c = _concept("Widget", a=3)  # 0.39 × 1.0 = 0.39
        scored = score_candidates([c], weights=weights)[0]
        assert scored.relevance_score < 0.40
        assert scored.classification == "noise"


# ─── Rounding-boundary precision (round-1 reviewer finding) ────────────────


class TestRoundingBoundaryPrecision:
    """The classifier must consult the un-rounded total, not a
    coarsened display value. A previous implementation rounded the
    score to 4 decimals *before* classification, so a true total of
    ``0.69999`` rounded to ``0.7000`` and was mis-classified as
    ``core_business``. Same risk at the ``0.40`` boundary.

    These tests engineer the exact boundary cases that round up
    across a threshold; with the un-rounded classifier the band
    assignment tracks the true score."""

    def test_score_just_below_070_classifies_as_supporting_technical(self):
        # round(0.69999, 4) == 0.7 — would have flipped to
        # core_business under the buggy implementation. The
        # un-rounded total stays at 0.69999 < 0.70 → supporting.
        weights = dict.fromkeys(DEFAULT_WEIGHTS.keys(), 0.0)
        weights["authoritative_frequency"] = 0.69999
        c = _concept("Widget", a=3)
        scored = score_candidates([c], weights=weights)[0]
        assert scored.relevance_score < 0.70
        assert scored.classification == "supporting_technical"

    def test_score_just_below_040_classifies_as_noise(self):
        # round(0.39999, 4) == 0.4 — would have flipped to
        # supporting_technical under the buggy implementation. The
        # un-rounded total stays at 0.39999 < 0.40 → noise.
        weights = dict.fromkeys(DEFAULT_WEIGHTS.keys(), 0.0)
        weights["authoritative_frequency"] = 0.39999
        c = _concept("Widget", a=3)
        scored = score_candidates([c], weights=weights)[0]
        assert scored.relevance_score < 0.40
        assert scored.classification == "noise"

    def test_relevance_score_is_stored_unrounded(self):
        # Sanity: 0.69999 must survive into the stored field intact,
        # not be coarsened to 4 decimal places.
        weights = dict.fromkeys(DEFAULT_WEIGHTS.keys(), 0.0)
        weights["authoritative_frequency"] = 0.69999
        c = _concept("Widget", a=3)
        scored = score_candidates([c], weights=weights)[0]
        # If the implementation still rounded to 4 decimals, the
        # stored value would equal 0.7 within float tolerance.
        assert scored.relevance_score != pytest.approx(0.7, abs=1e-8)
        assert scored.relevance_score == pytest.approx(0.69999, abs=1e-8)


# ─── Configurable thresholds (round-1 reviewer finding) ────────────────────


class TestConfigurableThresholds:
    """Architecture §"Classification thresholds": "These thresholds
    must be configurable." The CLI in Phase 3 reads an optional
    override; tests pass a dict directly through ``thresholds=``."""

    def test_default_thresholds_is_publicly_exposed(self):
        # Phase 3 imports this for its YAML-merge step; the
        # InductionReport writer in Task 4 may also need it.
        assert DEFAULT_THRESHOLDS["core_business"] == 0.70
        assert DEFAULT_THRESHOLDS["supporting_technical"] == 0.40

    def test_custom_thresholds_can_tighten_to_demote_candidate(self):
        # A candidate that lands in supporting_technical under
        # defaults must drop to noise when supporting_technical's
        # lower bound is raised above its score.
        c = _concept("Widget", a=2, b=1, degree=1, definition="A thing.")
        default_scored = score_candidates([c])[0]
        assert default_scored.classification == "supporting_technical"

        tighter = {
            "core_business": 0.99,
            "supporting_technical": default_scored.relevance_score + 0.01,
        }
        tighter_scored = score_candidates([c], thresholds=tighter)[0]
        # Score is independent of thresholds; only the band changes.
        assert tighter_scored.relevance_score == default_scored.relevance_score
        assert tighter_scored.classification == "noise"

    def test_custom_thresholds_can_relax_to_promote_candidate(self):
        # Same candidate; lowering core_business's lower bound below
        # the score promotes it to core_business.
        c = _concept("Widget", a=2, b=1, degree=1, definition="A thing.")
        default_scored = score_candidates([c])[0]
        assert default_scored.classification == "supporting_technical"

        relaxed = {
            "core_business": default_scored.relevance_score - 0.01,
            "supporting_technical": 0.10,
        }
        relaxed_scored = score_candidates([c], thresholds=relaxed)[0]
        assert relaxed_scored.classification == "core_business"

    def test_custom_weights_and_thresholds_compose_independently(self):
        # Both knobs at once. Custom weights yield a known score;
        # custom thresholds map it to a chosen band.
        weights = dict.fromkeys(DEFAULT_WEIGHTS.keys(), 0.0)
        weights["definition_richness"] = 1.0  # raw = 1.0 → score = 1.0
        thresholds = {"core_business": 0.99, "supporting_technical": 0.50}
        c = _concept("Widget", definition="A thing.")
        scored = score_candidates(
            [c], weights=weights, thresholds=thresholds,
        )[0]
        assert scored.relevance_score == pytest.approx(1.0)
        assert scored.classification == "core_business"

    def test_thresholds_none_uses_defaults(self):
        # Sanity: explicit ``thresholds=None`` is equivalent to
        # omitting the argument (the supported "use defaults" form).
        c = _concept("Widget", a=3, b=1, c=1, d=1, degree=5,
                     definition="A thing.")
        with_none = score_candidates([c], thresholds=None)[0]
        omitted = score_candidates([c])[0]
        assert with_none.classification == omitted.classification
        assert with_none.relevance_score == omitted.relevance_score
