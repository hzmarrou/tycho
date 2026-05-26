"""LLM SPIRES Pass-2 property induction — Phase B (PR B1 + PR B2).

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

PR B1 shipped the dry-run scaffold (eligibility + budget + console
plan; no cache; no LLM call). **PR B2 adds the real SPIRES Pass-2
LLM call, attribute parsing, merge into gate-eligible empty
attribute slots, and the discovery/source-a-properties.json
cache.** Cache is consulted and written only when
``--property-induction llm`` is explicitly set on the rerun —
default-flag runs of ``draft`` never read or write the cache, so
the Phase A "default output unchanged" guarantee holds.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .attribute import Attribute
    from .fusion import FusedElement, FusionResult

logger = logging.getLogger(__name__)


# Cache schema version. Bump if the on-disk shape of
# ``discovery/source-a-properties.json`` changes in a non-backwards-
# compatible way. Mirrors the convention used in
# :mod:`ontozense.core.source_c` and :mod:`ontozense.core.source_d`.
CACHE_SCHEMA_VERSION = "1.0"
CACHE_FILE_NAME = "source-a-properties.json"


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
    """The output of an induction run.

    PR B1 dry-run populates only ``eligible``, ``skipped``, and
    ``budget``. PR B2 real-run additionally populates ``per_class``
    (the induced attributes per class URI), ``model`` (the LLM
    model that produced them), ``cache_hits`` / ``cache_misses``
    (so the CLI can report cost), and ``refresh`` (whether the
    user forced cache misses).
    """

    eligible: list[EligibleConcept] = field(default_factory=list)
    skipped: list[tuple[EligibleConcept, str]] = field(default_factory=list)
    budget: Budget = field(default_factory=Budget)
    # PR B2 additions; default to "no LLM happened" for dry-run.
    per_class: dict[str, list[Any]] = field(default_factory=dict)
    model: str = ""
    cache_hits: int = 0
    cache_misses: int = 0
    refresh: bool = False


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
    discovery_dir: Path | None = None,
) -> InductionPlan:
    """Phase B entry point.

    ``dry_run=True`` (default) returns the eligibility plan, applies
    the budget, and stops. No file written. No LLM call. This is the
    PR B1 path the CLI uses for `--property-induction llm` when the
    user only wants to see what would happen.

    ``dry_run=False`` (PR B2) reads the cache at
    ``<discovery_dir>/source-a-properties.json`` (when
    ``discovery_dir`` is supplied), calls the LLM for cache misses,
    parses the response into typed ``Attribute`` records, merges
    them onto the matching FusedElement's ``attributes`` list (gate
    1 guarantees that slot is empty), and writes the updated cache
    back. ``refresh=True`` forces a cache miss for every eligible
    class.

    ``discovery_dir`` is required for ``dry_run=False`` — that's
    where the cache lives. When ``None``, callers run in
    no-persistence mode (PR B2 will use this from tests).
    """
    budget = budget or Budget()
    eligible = find_eligible_concepts(fused)
    enforcer = BudgetEnforcer(budget)
    kept, skipped = enforcer.apply(eligible)

    if dry_run:
        # `refresh` is accepted but ignored in dry-run (no cache to
        # refresh). `model` is accepted but unused. Both surface as
        # recorded plan metadata in the PR B2 cache write below.
        _ = model, refresh
        return InductionPlan(eligible=kept, skipped=skipped, budget=budget)

    # ── PR B2 real LLM call path ───────────────────────────────────
    cache = PropertyInductionCache(discovery_dir) if discovery_dir else None
    existing = (
        {} if (cache is None or refresh)
        else cache.load_per_class()
    )

    plan = InductionPlan(eligible=kept, skipped=skipped, budget=budget)
    plan.model = model
    plan.cache_hits = 0
    plan.cache_misses = 0
    plan.refresh = refresh

    for concept in kept:
        if concept.class_uri in existing:
            # Cache hit. Re-merge the cached attributes onto the
            # FusedElement so a rerun with the flag produces the
            # same OWL output. No LLM call.
            plan.cache_hits += 1
            cached_attrs = [
                _attribute_from_cache_dict(d)
                for d in existing[concept.class_uri].get("attributes", [])
            ]
            _merge_into_fused(fused, concept, cached_attrs)
            plan.per_class[concept.class_uri] = cached_attrs
            continue

        # Cache miss. Build the prompt, call the LLM, parse, merge,
        # record. _call_llm is the mockable seam for tests.
        plan.cache_misses += 1
        prompt = _generate_prompt(concept)
        raw = _call_llm(prompt=prompt, model=model)
        attrs = _parse_llm_response(raw)
        _merge_into_fused(fused, concept, attrs)
        plan.per_class[concept.class_uri] = attrs

    if cache is not None:
        cache.write(
            plan=plan,
            existing_per_class=existing,
        )

    return plan


# ─── Cache layer ────────────────────────────────────────────────────────────


@dataclass
class _CacheEntry:
    """In-memory shape of one per-class cache entry. Used internally
    by :class:`PropertyInductionCache`; not part of the public API.
    """

    attributes: list[dict]
    input_truncated: bool = False
    skipped_reason: str | None = None


class PropertyInductionCache:
    """Reader / writer for ``discovery/source-a-properties.json``.

    Cache is consulted and written only when the caller opts in
    (i.e. ``--property-induction llm`` on rerun). Default-flag
    ``draft`` runs never instantiate this class, so the cache file
    can sit on disk indefinitely without affecting downstream
    behaviour.

    Per design §5 Phase B contracts, the on-disk shape is:

    .. code-block:: json

       {
         "schema_version": "1.0",
         "model": "azure/gpt-5.4",
         "generated_at": "2026-...Z",
         "budget": {...},
         "usage": {...},
         "per_class": {
           "{class_uri}": {
             "attributes": [...Attribute serialised...],
             "input_truncated": false,
             "skipped_reason": null
           }
         },
         "skipped": [...]
       }
    """

    def __init__(self, discovery_dir: Path) -> None:
        self.discovery_dir = Path(discovery_dir)
        self.path = self.discovery_dir / CACHE_FILE_NAME

    def load_per_class(self) -> dict[str, dict]:
        """Return the ``per_class`` map from the cache file, or an
        empty dict when the file doesn't exist / is malformed.

        Malformed cache files are treated as empty rather than
        raising — Phase B contract is "cache is best-effort
        acceleration, never a correctness requirement". The
        warning is logged for the curator.

        Per-entry normalisation (Codex r1 blocker on PR B2):
        each ``per_class[class_uri]`` value is also validated as a
        dict. Non-dict entries are dropped from the returned map
        with a per-entry WARNING. This protects the cache-hit code
        path from raising ``AttributeError`` on ``.get(...)`` when
        a hand-edited or version-skewed cache file carries
        scalar / list values where a dict was expected.
        """
        if not self.path.exists():
            return {}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning(
                "Phase B cache at %s is unreadable (%s); treating "
                "as empty.", self.path, exc,
            )
            return {}
        per_class = raw.get("per_class")
        if not isinstance(per_class, dict):
            logger.warning(
                "Phase B cache at %s has unexpected shape; treating "
                "as empty.", self.path,
            )
            return {}

        # Per-entry normalisation: drop non-dict values rather than
        # letting the cache-hit path crash on .get(...).
        normalised: dict[str, dict] = {}
        for class_uri, entry in per_class.items():
            if not isinstance(entry, dict):
                logger.warning(
                    "Phase B cache entry for %r has unexpected "
                    "shape (%s); dropping. Cache miss will be "
                    "treated as required for this class.",
                    class_uri, type(entry).__name__,
                )
                continue
            normalised[class_uri] = entry
        return normalised

    def write(
        self,
        *,
        plan: "InductionPlan",
        existing_per_class: dict[str, dict],
    ) -> None:
        """Write the cache. Merges newly-induced attributes with the
        existing cache so unchanged classes' entries survive across
        runs. ``plan.per_class`` may include cache-hit entries that
        round-trip unchanged."""
        merged_per_class: dict[str, dict] = dict(existing_per_class)
        for class_uri, attrs in plan.per_class.items():
            merged_per_class[class_uri] = {
                "attributes": [a.to_json_dict() for a in attrs],
                "input_truncated": False,
                "skipped_reason": None,
            }
        # Record budget-skipped concepts so the curator can see what
        # didn't make it into the cache.
        for concept, reason in plan.skipped:
            merged_per_class.setdefault(concept.class_uri, {
                "attributes": [],
                "input_truncated": False,
                "skipped_reason": reason,
            })

        payload = {
            "schema_version": CACHE_SCHEMA_VERSION,
            "model": plan.model,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "budget": {
                "max_concepts": plan.budget.max_concepts,
                "max_calls": plan.budget.max_calls,
                "token_budget": plan.budget.token_budget,
            },
            "usage": {
                "concepts_processed": len(plan.per_class),
                "cache_hits": plan.cache_hits,
                "cache_misses": plan.cache_misses,
                "refresh": plan.refresh,
            },
            "per_class": merged_per_class,
            "skipped": [
                {"class_uri": c.class_uri, "reason": r}
                for c, r in plan.skipped
            ],
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )


# ─── Prompt + LLM seam ──────────────────────────────────────────────────────


_VALID_XSD_TYPES = frozenset({
    "xsd:string",
    "xsd:integer",
    "xsd:decimal",
    "xsd:double",
    "xsd:date",
    "xsd:dateTime",
    "xsd:boolean",
    "xsd:anyURI",
})


def _generate_prompt(concept: "EligibleConcept") -> str:
    """Build the per-class SPIRES-style prompt.

    Mirrors the simple ``litellm.completion``-based pattern used by
    ``ontozense.core.bridging._call_llm`` — a flat prompt + flat
    YAML-ish output is easier to parse + mock at test time than the
    full LinkML / OntoGPT pipeline. The output contract is one
    bullet per attribute on the format
    ``- name :: xsd_type :: description`` so the parser stays small.
    """
    return (
        f"You are extracting structured attributes for the class "
        f"\"{concept.element_name}\" from a domain document.\n"
        f"\n"
        f"Class context:\n"
        f"{concept.snippet}\n"
        f"\n"
        f"Return attributes as YAML, one per line, in the format:\n"
        f"  - name :: xsd_type :: description\n"
        f"\n"
        f"xsd_type must be one of: "
        f"{', '.join(sorted(_VALID_XSD_TYPES))}.\n"
        f"Description is one short sentence.\n"
        f"\n"
        f"Only include attributes the source text explicitly mentions or "
        f"strongly implies. Output only the YAML list. No prose, no "
        f"headers, no code fences."
    )


def _call_llm(*, prompt: str, model: str) -> str:
    """Call ``litellm.completion`` and return the content string.

    Single seam — tests mock this at the module path
    (``ontozense.core.property_induction._call_llm``). Mirrors the
    pattern :mod:`ontozense.core.bridging` already uses, including
    the import-inside-function pattern that keeps litellm out of
    the import graph for code paths that don't need it.
    """
    import litellm

    response = litellm.completion(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
        max_tokens=1500,
    )
    return response.choices[0].message.content


def _parse_llm_response(raw: str) -> list["Attribute"]:
    """Parse the per-class LLM output into typed Attribute records.

    Output format (per ``_generate_prompt``):

    .. code-block:: text

       - account_id :: xsd:string :: Unique customer identifier.
       - balance :: xsd:decimal :: Current outstanding balance.
       - opened_at :: xsd:dateTime :: Account creation timestamp.

    Lenient parser:

      * lines without leading ``-`` are skipped (no error)
      * fewer than 3 ``::``-separated tokens → line skipped
      * unknown xsd_type → defaults to ``xsd:string`` (per design
        Q12 fallback policy)
      * malformed lines logged at WARNING but never abort the run

    Returns the list of parsed ``Attribute`` records. Each carries
    ``source="B-LLM"`` and ``confidence=0.5`` per design §5.
    """
    from .attribute import Attribute, FieldProvenance

    out: list[Attribute] = []
    for line in (raw or "").splitlines():
        stripped = line.strip()
        if not stripped.startswith("-"):
            continue
        body = stripped.lstrip("-").strip()
        parts = [p.strip() for p in body.split("::")]
        if len(parts) < 3:
            logger.warning(
                "Phase B LLM line skipped (need 3 fields): %r", body,
            )
            continue
        name, xsd_type, description = parts[0], parts[1], "::".join(parts[2:]).strip()
        if not name:
            continue
        if xsd_type not in _VALID_XSD_TYPES:
            logger.warning(
                "Phase B LLM returned unrecognised xsd_type %r for "
                "attribute %r; defaulting to xsd:string.",
                xsd_type, name,
            )
            xsd_type = "xsd:string"
        out.append(Attribute(
            name=name,
            xsd_type=xsd_type,
            description=description,
            field_provenance=[FieldProvenance(
                source="B-LLM",
                artifact=f"discovery/{CACHE_FILE_NAME}",
                line=0,
                confidence=0.5,
                extractor="spires-pass2",
            )],
            confidence=0.5,
        ))
    return out


def _attribute_from_cache_dict(d: dict[str, Any]) -> "Attribute":
    """Reconstruct an Attribute from a cache-file dict.

    Thin wrapper around ``Attribute.from_json_dict`` so the cache
    layer doesn't need to know the Attribute import path.
    """
    from .attribute import Attribute

    return Attribute.from_json_dict(d)


def _merge_into_fused(
    fused: "FusionResult",
    concept: "EligibleConcept",
    attrs: list["Attribute"],
) -> None:
    """Attach ``attrs`` to the FusedElement whose name matches
    ``concept.element_name``.

    Gate 1 guard: this function only writes when the matching
    element's ``attributes`` is empty. The eligibility filter at the
    top of the pipeline already filters to ``attributes==[]``
    elements, so this is a defensive belt-and-braces check that
    protects against future code paths that mutate the list between
    eligibility and merge. Non-empty → no-op + WARNING log.
    """
    for el in fused.elements:
        if el.element_name == concept.element_name:
            if el.attributes:
                logger.warning(
                    "Phase B merge skipped — FusedElement %r already "
                    "carries attributes (gate 1 violation guard).",
                    el.element_name,
                )
                return
            el.attributes = list(attrs)
            return


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
