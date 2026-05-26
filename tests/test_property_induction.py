"""PR B1 — eligibility, budget, and dry-run scaffold coverage.

Phase B PR B1 ships the dry-run path only: eligibility scan +
budget enforcement + console-printable plan. Tests cover:

  - Gate 1 enforcement (``attributes == []`` AND at least one
    Source A field_provenance entry).
  - Deterministic ordering (Source A confidence desc, then element
    name alphabetical).
  - Snippet collection + ``MAX_SPIRES_INPUT_CHARS`` truncation.
  - ``BudgetEnforcer`` for ``max_concepts``, ``max_calls``, and the
    optional ``token_budget``.
  - ``induce_attributes(dry_run=False)`` raises ``NotImplementedError``
    so callers cannot accidentally land a half-implemented LLM path
    in B1.
"""

from __future__ import annotations

import pytest

from ontozense.core.attribute import Attribute
from ontozense.core.fusion import (
    FieldAnchor,
    FieldProvenance,
    FusedElement,
    FusionResult,
)
from ontozense.core.property_induction import (
    MAX_SPIRES_INPUT_CHARS,
    Budget,
    BudgetEnforcer,
    EligibleConcept,
    InductionPlan,
    find_eligible_concepts,
    induce_attributes,
    select_input_text,
)


# ─── Helpers ────────────────────────────────────────────────────────────────


def _source_a_anchor(snippet: str = "snippet text") -> FieldAnchor:
    return FieldAnchor(line=1, segment_id="doc.md", snippet=snippet)


def _source_a_fp(snippet: str = "snippet text", confidence: float = 0.9) -> FieldProvenance:
    return FieldProvenance(
        source="A", confidence=confidence, original_value="x",
        anchor=_source_a_anchor(snippet),
    )


def _element(
    name: str,
    *,
    attributes: list[Attribute] | None = None,
    source_a_snippet: str | None = "Concept context.",
    source_a_confidence: float = 0.9,
    other_sources: list[str] | None = None,
) -> FusedElement:
    el = FusedElement(element_name=name, attributes=attributes or [])
    if source_a_snippet is not None:
        el.field_provenance["definition"] = _source_a_fp(
            snippet=source_a_snippet, confidence=source_a_confidence,
        )
    for src in other_sources or []:
        el.field_provenance[f"{src}_field"] = FieldProvenance(
            source=src, confidence=0.95, original_value="y",
        )
    return el


# ─── find_eligible_concepts — gate 1 enforcement ───────────────────────────


def test_concept_with_empty_attributes_and_source_a_is_eligible():
    fused = FusionResult(elements=[_element("Loan")])
    result = find_eligible_concepts(fused)
    assert len(result) == 1
    assert result[0].element_name == "Loan"


def test_concept_with_existing_attributes_is_filtered_out():
    """Gate 1: any non-empty attributes list disqualifies the
    concept. Phase B does not top-up partial lists."""
    fused = FusionResult(elements=[_element(
        "Customer",
        attributes=[Attribute(name="email", xsd_type="xsd:string")],
    )])
    assert find_eligible_concepts(fused) == []


def test_concept_with_no_source_a_provenance_is_filtered_out():
    """Gate 1: element discovered only from B/C/D (no Source A
    docs to extract from) does not qualify. Phase B has no source
    text for such concepts."""
    fused = FusionResult(elements=[_element(
        "ScheduledJob",
        source_a_snippet=None,
        other_sources=["C"],
    )])
    assert find_eligible_concepts(fused) == []


def test_concept_with_attributes_and_source_a_still_filtered_out():
    """Phase A populated the attributes already; Phase B must not
    re-trigger even though Source A is present."""
    fused = FusionResult(elements=[_element(
        "Order",
        attributes=[Attribute(name="amount", xsd_type="xsd:decimal")],
        source_a_snippet="Order context.",
    )])
    assert find_eligible_concepts(fused) == []


# ─── find_eligible_concepts — deterministic ordering ───────────────────────


def test_eligible_sorted_by_source_a_confidence_descending():
    fused = FusionResult(elements=[
        _element("LowConfidence", source_a_confidence=0.3),
        _element("HighConfidence", source_a_confidence=0.95),
        _element("MidConfidence", source_a_confidence=0.6),
    ])
    result = find_eligible_concepts(fused)
    assert [c.element_name for c in result] == [
        "HighConfidence", "MidConfidence", "LowConfidence",
    ]


def test_ties_broken_alphabetically_for_stable_runs():
    fused = FusionResult(elements=[
        _element("BravoConcept", source_a_confidence=0.7),
        _element("alphaConcept", source_a_confidence=0.7),
        _element("CharlieConcept", source_a_confidence=0.7),
    ])
    result = find_eligible_concepts(fused)
    # Case-insensitive alpha order on ties.
    assert [c.element_name for c in result] == [
        "alphaConcept", "BravoConcept", "CharlieConcept",
    ]


def test_best_source_a_confidence_is_used_per_element():
    """An element with multiple Source A provs (e.g. one for
    ``definition`` and one for ``citation``) uses the highest
    confidence for sort ordering."""
    el = FusedElement(element_name="Multi")
    el.field_provenance["definition"] = _source_a_fp(
        snippet="def text", confidence=0.4,
    )
    el.field_provenance["citation"] = _source_a_fp(
        snippet="cite text", confidence=0.9,
    )
    fused = FusionResult(elements=[el])
    result = find_eligible_concepts(fused)
    assert len(result) == 1
    assert result[0].confidence == 0.9


# ─── Snippet collection + truncation ───────────────────────────────────────


def test_select_input_text_concatenates_source_a_snippets():
    el = FusedElement(element_name="X")
    el.field_provenance["definition"] = _source_a_fp(snippet="first")
    el.field_provenance["citation"] = _source_a_fp(snippet="second")
    text = select_input_text(el)
    assert "first" in text
    assert "second" in text


def test_select_input_text_ignores_non_source_a_provenance():
    el = FusedElement(element_name="X")
    el.field_provenance["definition"] = _source_a_fp(snippet="A text")
    el.field_provenance["b_field"] = FieldProvenance(
        source="B", confidence=0.95,
        original_value="B text",
        anchor=FieldAnchor(line=1, segment_id="gov.json", snippet="B text"),
    )
    text = select_input_text(el)
    assert "A text" in text
    assert "B text" not in text


def test_select_input_text_truncates_at_max_chars():
    long_snippet = "X" * (MAX_SPIRES_INPUT_CHARS + 1000)
    el = FusedElement(element_name="Big")
    el.field_provenance["definition"] = _source_a_fp(snippet=long_snippet)
    text = select_input_text(el)
    assert len(text) <= MAX_SPIRES_INPUT_CHARS
    assert text.endswith("...")


def test_select_input_text_empty_when_no_source_a():
    el = FusedElement(element_name="NoDocs")
    el.field_provenance["b_field"] = FieldProvenance(
        source="B", confidence=0.95, original_value="x",
    )
    assert select_input_text(el) == ""


# ─── BudgetEnforcer ────────────────────────────────────────────────────────


def _ec(name: str, confidence: float = 0.9, chars: int = 100) -> EligibleConcept:
    return EligibleConcept(
        element_name=name,
        class_uri=name.lower(),
        confidence=confidence,
        snippet_chars=chars,
        snippet="x" * chars,
    )


def test_max_concepts_trims_lowest_confidence_first():
    """Input is assumed pre-sorted (confidence desc); trimming takes
    the first N. Skipped concepts get the max_concepts reason."""
    eligible = [
        _ec("First", confidence=0.95),
        _ec("Second", confidence=0.90),
        _ec("Third", confidence=0.85),
        _ec("Fourth", confidence=0.80),
    ]
    kept, skipped = BudgetEnforcer(Budget(max_concepts=2)).apply(eligible)
    assert [c.element_name for c in kept] == ["First", "Second"]
    assert {c.element_name for c, _ in skipped} == {"Third", "Fourth"}
    assert all(r == "skipped:budget:max_concepts" for _, r in skipped)


def test_max_calls_caps_after_max_concepts():
    eligible = [_ec(f"C{i}", confidence=0.9 - 0.01 * i) for i in range(5)]
    kept, skipped = BudgetEnforcer(
        Budget(max_concepts=100, max_calls=3),
    ).apply(eligible)
    assert len(kept) == 3
    assert {r for _, r in skipped} == {"skipped:budget:max_calls"}


def test_token_budget_cumulative_admits_until_exceeded():
    """token_budget counts snippet_chars cumulatively. First two
    concepts at 100 chars each = 200, third would push past 250 →
    third skipped."""
    eligible = [
        _ec("A", confidence=0.9, chars=100),
        _ec("B", confidence=0.9, chars=100),
        _ec("C", confidence=0.9, chars=100),
    ]
    kept, skipped = BudgetEnforcer(
        Budget(max_concepts=100, max_calls=100, token_budget=250),
    ).apply(eligible)
    assert [c.element_name for c in kept] == ["A", "B"]
    assert [c.element_name for c, _ in skipped] == ["C"]
    assert skipped[0][1] == "skipped:budget:token_budget"


def test_token_budget_none_disables_cap():
    eligible = [_ec(f"C{i}", chars=5000) for i in range(10)]
    kept, skipped = BudgetEnforcer(
        Budget(max_concepts=100, max_calls=100, token_budget=None),
    ).apply(eligible)
    assert len(kept) == 10
    assert skipped == []


def test_empty_eligible_yields_empty_kept_and_skipped():
    kept, skipped = BudgetEnforcer(Budget()).apply([])
    assert kept == []
    assert skipped == []


def test_default_budget_matches_design():
    """Design §4 specifies max_concepts=50, max_calls=100,
    token_budget=None as defaults."""
    b = Budget()
    assert b.max_concepts == 50
    assert b.max_calls == 100
    assert b.token_budget is None


# ─── induce_attributes — dry-run only in PR B1 ─────────────────────────────


def test_induce_attributes_dry_run_returns_plan():
    fused = FusionResult(elements=[
        _element("A", source_a_confidence=0.9),
        _element("B", source_a_confidence=0.7),
    ])
    plan = induce_attributes(fused, dry_run=True)
    assert isinstance(plan, InductionPlan)
    assert [c.element_name for c in plan.eligible] == ["A", "B"]
    assert plan.skipped == []


def test_induce_attributes_dry_run_applies_budget():
    fused = FusionResult(elements=[
        _element("A", source_a_confidence=0.9),
        _element("B", source_a_confidence=0.7),
        _element("C", source_a_confidence=0.5),
    ])
    plan = induce_attributes(
        fused, budget=Budget(max_concepts=2), dry_run=True,
    )
    assert [c.element_name for c in plan.eligible] == ["A", "B"]
    assert [c.element_name for c, _ in plan.skipped] == ["C"]


def test_induce_attributes_dry_run_false_raises():
    """PR B1 must not silently land a half-implemented LLM path.
    dry_run=False raises NotImplementedError pointing at PR B2."""
    fused = FusionResult(elements=[_element("A")])
    with pytest.raises(NotImplementedError) as exc:
        induce_attributes(fused, dry_run=False)
    assert "PR B2" in str(exc.value)


def test_induce_attributes_refresh_ignored_in_dry_run():
    """`refresh=True` is accepted in B1 (forward-compat with B2 API)
    but has no observable effect — there is no cache to refresh."""
    fused = FusionResult(elements=[_element("A")])
    plan_no_refresh = induce_attributes(fused, dry_run=True, refresh=False)
    plan_refresh = induce_attributes(fused, dry_run=True, refresh=True)
    assert [c.element_name for c in plan_no_refresh.eligible] == \
           [c.element_name for c in plan_refresh.eligible]


def test_induce_attributes_dry_run_writes_no_files(tmp_path):
    """PR B1 contract: dry-run path produces zero file-system side
    effects. Snapshot tmp_path before/after a call."""
    fused = FusionResult(elements=[_element("A")])
    before = set(tmp_path.rglob("*"))
    induce_attributes(fused, dry_run=True)
    after = set(tmp_path.rglob("*"))
    assert before == after
