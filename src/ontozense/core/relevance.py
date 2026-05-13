"""Transparent relevance scoring for candidate concepts (profile
induction architecture, Phase 2 / Task 3).

The scoring stage consumes the :class:`CandidateConcept` list from
:mod:`ontozense.core.candidate_graph` and produces an annotated copy
with three fields populated:

  - ``relevance_score`` — the total in ``[0.0, 1.0]`` formed by
    summing seven weighted signal contributions.
  - ``relevance_breakdown`` — per-signal weighted contribution. The
    values sum to ``relevance_score`` (modulo float precision), so
    reviewers can verify the score by eye and see which signal
    pushed a candidate into ``core_business`` or down to ``noise``.
  - ``classification`` — bucketed by two thresholds:

      * score ``≥ 0.70`` → ``"core_business"``
      * score ``≥ 0.40`` and ``< 0.70`` → ``"supporting_technical"``
      * score ``< 0.40`` → ``"noise"``

## The seven signals

Default weights are exposed as :data:`DEFAULT_WEIGHTS` and sum to
``1.00``. The CLI in Phase 3 reads an optional weights override from
YAML; tests pass a dict directly.

============================== ==========  =========================================
Signal                          Weight     Formula
============================== ==========  =========================================
``authoritative_frequency``     ``0.25``   ``clip(source_counts['A'] / 3)``
``governance_presence``         ``0.20``   ``1.0 if source_presence['B'] else 0.0``
``schema_linkage``              ``0.15``   ``1.0 if source_presence['C'] else 0.0``
``code_usage``                  ``0.10``   ``1.0 if source_presence['D'] else 0.0``
``graph_centrality``            ``0.10``   ``clip(graph_degree / 5)``
``definition_richness``         ``0.10``   ``1.0 if summary_definition.strip() else 0.0``
``business_naming_signal``      ``0.10``   ``0.1 if tmp_*/_id else 0.8``
============================== ==========  =========================================

Saturation points (``/3`` for authoritative frequency, ``/5`` for
centrality) come from the architecture's "diminishing returns"
discussion: three independent authoritative sources is *enough*
evidence; ten is not more meaningful. Same for graph centrality.

``business_naming_signal`` caps clean labels at ``0.8`` rather than
``1.0`` so the score can never be a perfect ``1.0`` without external
evidence. Two domain-neutral noise patterns are penalised: the
``tmp_<...>`` prefix (temp / scratch columns) and the ``<...>_id``
suffix (surrogate keys). Both checks are case-insensitive.

## What scoring does *not* do

It doesn't filter the candidate list. ``"noise"`` candidates are
retained in the output so the induction stage can still emit them
as ``rejected_examples`` in the ``InductionReport``. The architecture
is explicit that a reviewer must be able to see why something was
rejected.
"""

from __future__ import annotations

from dataclasses import replace

from .discovery_contracts import CandidateConcept


DEFAULT_WEIGHTS: dict[str, float] = {
    "authoritative_frequency": 0.25,
    "governance_presence": 0.20,
    "schema_linkage": 0.15,
    "code_usage": 0.10,
    "graph_centrality": 0.10,
    "definition_richness": 0.10,
    "business_naming_signal": 0.10,
}

# Classification thresholds (inclusive on the high side).
_CORE_BUSINESS_THRESHOLD = 0.70
_SUPPORTING_TECHNICAL_THRESHOLD = 0.40

# Saturation denominators for the diminishing-returns signals.
_AUTHORITATIVE_SATURATION = 3
_CENTRALITY_SATURATION = 5

# Naming-signal endpoints.
_NAMING_CLEAN = 0.8
_NAMING_PENALTY = 0.1


def _clip(value: float) -> float:
    """Clamp a value to the unit interval. Saturation formulas like
    ``count / 3`` need this so a count of ``10`` doesn't blow past
    ``1.0`` and skew the breakdown sum."""
    return max(0.0, min(1.0, value))


def _business_naming_signal(label: str) -> float:
    """Return the raw business-naming signal value in ``[0.0, 1.0]``.

    Domain-neutral conventions: labels starting with ``tmp_`` (temp
    columns) or ending with ``_id`` (surrogate keys) are penalised
    to :data:`_NAMING_PENALTY`. Clean labels return
    :data:`_NAMING_CLEAN` (capped below ``1.0`` so the total score
    cannot reach ``1.0`` without external evidence).

    Case-insensitive — ``TMP_FOO`` and ``tmp_foo`` are scored alike.
    """
    lowered = (label or "").lower()
    if lowered.startswith("tmp_") or lowered.endswith("_id"):
        return _NAMING_PENALTY
    return _NAMING_CLEAN


def _classify(score: float) -> str:
    """Bucket a relevance score into the three documented bands.
    Both thresholds are inclusive on the high side, matching the
    architecture's spec."""
    if score >= _CORE_BUSINESS_THRESHOLD:
        return "core_business"
    if score >= _SUPPORTING_TECHNICAL_THRESHOLD:
        return "supporting_technical"
    return "noise"


def score_candidates(
    candidates: list[CandidateConcept],
    weights: dict[str, float] | None = None,
) -> list[CandidateConcept]:
    """Score and classify a list of candidate concepts.

    Each input candidate is returned as a new
    :class:`CandidateConcept` (it's frozen, so mutation goes through
    :func:`dataclasses.replace`) with ``relevance_score``,
    ``relevance_breakdown``, and ``classification`` populated.

    ``weights`` (optional) — full override of the per-signal weights.
    If omitted, :data:`DEFAULT_WEIGHTS` is used. The caller is
    expected to pass a complete dict; missing keys are an
    internal-contract error and surface as :class:`KeyError`.
    Phase 3's CLI loads this from a YAML override and validates
    completeness before calling.

    Returns an empty list for empty input. Order is preserved.
    """
    weight_map = DEFAULT_WEIGHTS if weights is None else weights

    scored: list[CandidateConcept] = []
    for candidate in candidates:
        # Raw signal values in [0.0, 1.0] before weighting.
        raw_auth = _clip(
            candidate.source_counts.get("A", 0) / _AUTHORITATIVE_SATURATION
        )
        raw_gov = 1.0 if candidate.source_presence.get("B") else 0.0
        raw_schema = 1.0 if candidate.source_presence.get("C") else 0.0
        raw_code = 1.0 if candidate.source_presence.get("D") else 0.0
        raw_centrality = _clip(
            candidate.graph_degree / _CENTRALITY_SATURATION
        )
        raw_def = (
            1.0 if (candidate.summary_definition or "").strip() else 0.0
        )
        raw_naming = _business_naming_signal(candidate.label)

        # Weighted contributions — these are what land in the
        # breakdown so it sums to the total.
        breakdown: dict[str, float] = {
            "authoritative_frequency": weight_map["authoritative_frequency"] * raw_auth,
            "governance_presence": weight_map["governance_presence"] * raw_gov,
            "schema_linkage": weight_map["schema_linkage"] * raw_schema,
            "code_usage": weight_map["code_usage"] * raw_code,
            "graph_centrality": weight_map["graph_centrality"] * raw_centrality,
            "definition_richness": weight_map["definition_richness"] * raw_def,
            "business_naming_signal": weight_map["business_naming_signal"] * raw_naming,
        }
        total = round(sum(breakdown.values()), 4)

        scored.append(
            replace(
                candidate,
                relevance_score=total,
                relevance_breakdown=breakdown,
                classification=_classify(total),
            )
        )
    return scored
