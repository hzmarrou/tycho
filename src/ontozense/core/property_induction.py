"""LLM SPIRES Pass-2 property induction — Phase B scaffold (PR B1).

Phase B (per
``docs/PROPERTY_EXTRACTION_DESIGN.md §4 Phase B``) populates
``FusedElement.attributes`` for doc-only domains where Phase A and
Phase D produced nothing. The 5-gate scope lock baked into the
design constrains this module:

  1. Eligibility — only elements with ``attributes == []`` AND at
     least one Source A ``field_provenance`` entry are considered.
  2. Opt-in only — triggered via ``--property-induction llm`` on
     ``draft``. Default off.
  3. No Phase C validation — does not consult profile schemas.
  4. No Phase E rule semantics — extracts attributes, not rules.
  5. Backlog isolation — does not touch the fusion-layer
     unmatched-rules concern.

**PR B1 ships the dry-run path only.** No cache file, no LLM call,
no new disk artifacts. The entry point ``induce_attributes(...,
dry_run=True)`` returns the eligible-concept plan plus the budget
summary so the CLI can print it. ``dry_run=False`` raises
``NotImplementedError("queued for PR B2")``.

PR B2 will add the real SPIRES Pass-2 call, attribute parsing,
``Attribute`` merge onto FusedElements, and the
``discovery/source-a-properties.json`` cache.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .fusion import FusedElement, FusionResult


# Per-class input cap for SPIRES (per design §5). Concatenated
# Source A snippets are truncated at this many characters before the
# template is sent to the LLM. Default sized for English prose so the
# input fits comfortably inside any modern Azure / OpenAI model
# context without forcing aggressive per-snippet selection.
MAX_SPIRES_INPUT_CHARS = 8000


# ─── Data carriers ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class EligibleConcept:
    """A FusedElement that passes Phase B gate 1 and would be sent
    to the LLM (in PR B2). PR B1 surfaces these to the console but
    does not call the LLM."""

    element_name: str
    class_uri: str               # `{base}/{class_fragment}`-style; resolved by caller
    confidence: float            # Source A best-of confidence; drives sort order
    snippet_chars: int           # length of the concatenated Source A snippets
    snippet: str                 # the truncated text that would be sent to the LLM


@dataclass
class Budget:
    """Hard caps for a Phase B run. Defaults match design §4 Cost
    Controls. ``token_budget=None`` disables the token cap entirely."""

    max_concepts: int = 50
    max_calls: int = 100
    token_budget: int | None = None


@dataclass
class InductionPlan:
    """The output of a dry-run (PR B1). Carries the eligible-concept
    list, the budget that would have been enforced, and the per-
    budget skipped subset. PR B2 will extend this with a per-class
    ``Attribute`` payload from the real LLM."""

    eligible: list[EligibleConcept] = field(default_factory=list)
    skipped: list[tuple[EligibleConcept, str]] = field(default_factory=list)
    budget: Budget = field(default_factory=Budget)


# ─── Public API ─────────────────────────────────────────────────────────────


def find_eligible_concepts(fused: "FusionResult") -> list[EligibleConcept]:
    """Apply gate 1. Walk ``fused.elements`` and return the
    subset that passes:

      * ``attributes == []`` after Phase A + Phase D, AND
      * at least one ``field_provenance`` entry from Source A
        (the element was discovered in a doc, not synthesised from
        B/C/D alone).

    Returns the list sorted by Source A confidence descending so
    budget skipping is deterministic and reviewer-predictable.
    Element name ties broken by name alphabetical for total
    determinism across Python runs (set iteration is unstable).
    """
    out: list[EligibleConcept] = []
    for el in fused.elements:
        if el.attributes:
            continue
        source_a_provs = [
            fp for fp in el.field_provenance.values()
            if fp.source == "A"
        ]
        if not source_a_provs:
            continue
        # Best-of Source A confidence across all field-level provs.
        confidence = max(fp.confidence for fp in source_a_provs)
        snippet_text = _collect_source_a_snippets(el)
        truncated = _truncate(snippet_text, MAX_SPIRES_INPUT_CHARS)
        # class_uri is a string here so this module stays
        # rdflib-free; OWL emission resolves the proper URIRef.
        out.append(EligibleConcept(
            element_name=el.element_name,
            class_uri=_id_fragment(el.element_name),
            confidence=confidence,
            snippet_chars=len(truncated),
            snippet=truncated,
        ))
    out.sort(key=lambda c: (-c.confidence, c.element_name.lower()))
    return out


def select_input_text(element: "FusedElement") -> str:
    """Public wrapper around the per-element snippet selection +
    truncation rule. Surfaced so tests can exercise the cap
    independently of the eligibility walk.
    """
    return _truncate(_collect_source_a_snippets(element), MAX_SPIRES_INPUT_CHARS)


class BudgetEnforcer:
    """Apply a :class:`Budget` to a list of ``EligibleConcept``s,
    returning the kept subset + per-skip reason for the dropped
    ones.

    Order of application (matches what the user-facing CLI prints):

      1. ``max_concepts`` — trim the list to N highest-confidence
         entries. Concepts beyond the cap get
         ``"skipped:budget:max_concepts"``.
      2. ``max_calls`` — trim further if the survivor count is still
         above the call cap. (At one call per concept the two caps
         are functionally equivalent here; max_calls becomes
         meaningful in PR B2 when retries cost additional calls.)
      3. ``token_budget`` — if set, cumulatively count
         ``snippet_chars`` (proxy for token count at the spec stage
         — PR B2 may swap in a real tokenizer count) and stop
         admitting concepts once the budget is exceeded. Concepts
         beyond budget get ``"skipped:budget:token_budget"``.

    Returns ``(kept, skipped)``.
    """

    def __init__(self, budget: Budget) -> None:
        self.budget = budget

    def apply(
        self, eligible: list[EligibleConcept],
    ) -> tuple[list[EligibleConcept], list[tuple[EligibleConcept, str]]]:
        kept: list[EligibleConcept] = []
        skipped: list[tuple[EligibleConcept, str]] = []

        # max_concepts pass.
        for i, concept in enumerate(eligible):
            if i >= self.budget.max_concepts:
                skipped.append((concept, "skipped:budget:max_concepts"))
            else:
                kept.append(concept)

        # max_calls pass. At one call per concept in PR B1 these are
        # the same cap; recorded separately so the reason string is
        # always accurate when the two caps differ in PR B2.
        if len(kept) > self.budget.max_calls:
            for concept in kept[self.budget.max_calls:]:
                skipped.append((concept, "skipped:budget:max_calls"))
            kept = kept[: self.budget.max_calls]

        # token_budget pass.
        if self.budget.token_budget is not None:
            cumulative = 0
            within: list[EligibleConcept] = []
            for concept in kept:
                if cumulative + concept.snippet_chars > self.budget.token_budget:
                    skipped.append((concept, "skipped:budget:token_budget"))
                else:
                    within.append(concept)
                    cumulative += concept.snippet_chars
            kept = within

        return kept, skipped


def induce_attributes(
    fused: "FusionResult",
    *,
    model: str = "azure/gpt-5.4",
    budget: Budget | None = None,
    dry_run: bool = True,
    refresh: bool = False,
) -> InductionPlan:
    """Phase B entry point.

    PR B1 supports only ``dry_run=True``: returns the eligibility
    plan, applies the budget, and that's it. No file written. No
    LLM call. PR B2 will implement ``dry_run=False`` with the real
    SPIRES Pass-2 invocation + cache.

    ``refresh`` is accepted in PR B1 for forward-compat with the
    cache-aware PR B2 implementation, but is a no-op here — there
    is no cache to refresh. The CLI prints an explicit note when
    the user passes ``--property-induction-refresh`` in B1.
    """
    if not dry_run:
        raise NotImplementedError(
            "Real LLM induction is queued for PR B2. "
            "PR B1 ships only the dry-run scaffold."
        )

    budget = budget or Budget()
    eligible = find_eligible_concepts(fused)
    enforcer = BudgetEnforcer(budget)
    kept, skipped = enforcer.apply(eligible)
    # `refresh` is accepted but ignored in PR B1 (no cache exists).
    # `model` is accepted but unused in PR B1 (no LLM call). Both
    # surface as recorded plan metadata in the future PR B2 cache.
    _ = model, refresh
    return InductionPlan(eligible=kept, skipped=skipped, budget=budget)


# ─── Helpers ────────────────────────────────────────────────────────────────


def _collect_source_a_snippets(element: "FusedElement") -> str:
    """Concatenate the ``anchor.snippet`` text from every Source A
    ``field_provenance`` entry on ``element``. Snippets joined with
    blank-line separators so the LLM sees them as distinct excerpts.
    Returns ``""`` when no Source A provenance is anchored.
    """
    parts: list[str] = []
    for fp in element.field_provenance.values():
        if fp.source != "A":
            continue
        anchor = fp.anchor
        if anchor is None:
            continue
        text = anchor.snippet or ""
        if text:
            parts.append(text)
    return "\n\n".join(parts)


def _truncate(text: str, limit: int) -> str:
    """Cap ``text`` at ``limit`` chars; append ``"..."`` when
    truncated. Mirrors the truncation idiom in
    :mod:`ontozense.core.rule_projection` for consistency."""
    if len(text) <= limit:
        return text
    if limit <= 3:
        return text[:limit]
    return text[: limit - 3] + "..."


def _id_fragment(label: str) -> str:
    """URI fragment for an element name — kept local so the module
    stays free of rdflib / owl_export imports. Matches the helper
    in owl_export.py for cross-module URI consistency."""
    return label.strip().lower().replace(" ", "_").replace("/", "_")
