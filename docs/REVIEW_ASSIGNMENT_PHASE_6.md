# Independent Review Assignment — Phase 6: Provenance Granularity

**Review on:** branch `feat/phase-6-provenance-granularity` at HEAD `18b1a06`
**Repository:** `C:\Users\hzmarrou\OneDrive\python\projects\ontozense`
**Master is at:** `c6477cf` (Phase 5 merged after your prior review).
**Not yet merged to master.** Your verdict gates the merge.

---

## 1. Why this review

You cleared Phase 5 last round (`docs/REVIEW_PHASE_5.md`). Your §6 Q8
flagged that ``extra_fields`` was becoming a junk drawer for
provenance metadata (``source_documents``, ``corroborating_doc_count``,
``id``, ``entity_type``, schema/governance extras) — and that Phase 6
per-field anchors would be harder to add cleanly without typed
structure. Phase 6 introduces that typed structure for the
*per-field* anchor case, deliberately scoped narrowly.

| Layer | Pre-Phase-6 | Phase 6 |
|---|---|---|
| FieldProvenance shape | ``(source, confidence, original_value)`` | + ``anchor: Optional[FieldAnchor] = None`` |
| Anchor representation | None — only doc-level filename in extra_fields | Typed ``FieldAnchor`` dataclass with 8 optional fields |
| Source A → fused | Provenance fields ignored beyond ``source_document`` | ``source_section`` → ``segment_id``, ``source_text_snippet`` → ``snippet`` (when present) |
| Conflict resolution | Winner's value kept | Winner's value AND winner's anchor kept; loser's anchor dropped |
| JSON shape (no anchors) | Conflict winner / rejected = ``{source, value}`` | **Identical** — anchor key suppressed when None / empty |
| JSON shape (with anchors) | n/a | Conflict winner / rejected = ``{source, value, anchor: {…8 fields…}}`` |

The core invariant: **a typed anchor coordinate that round-trips
through JSON and survives conflict resolution, while pre-Phase-6
unanchored output stays byte-identical.**

We want to know: **can we merge `feat/phase-6-provenance-granularity`
to master and confidently start Phase 7 (benchmark metrics)?**

This review is scoped narrowly. We do **not** want re-review of:
- Phases 1–5 (profile loader, identity, constrained Sources A/B/C/D,
  validation stage, multi-doc + cross-source consolidation)
- The PRD direction
- The per-source extractor logic itself (Phase 6 is a fusion-shape
  change; extractors aren't modified)

We **do** want a review of:
- Whether the ``FieldAnchor`` 8-field shape covers the realistic
  anchor cases without redundancy
- Whether ``is_empty()`` correctly gates the JSON serialisation so
  AC1 byte-identity holds for unanchored output
- Whether the Source A ``Provenance`` → ``FieldAnchor`` mapping is
  the right contract (segment_id from section, snippet from
  text_snippet, no page/line yet)
- Whether conflict resolution actually preserves the right anchor
  (winner's, not loser's; not silently lost on ties)
- Whether the JSON round-trip works in both directions
  (pre-Phase-6 read, Phase-6 write/read)

---

## 2. The single most important constraint — verify first

**PRD AC1: no-profile / no-anchor behaviour must be byte-identical.**
Non-negotiable.

```bash
# Baseline (post-Phase-5 merge)
git checkout master                           # at c6477cf
pytest -q                                      # → 548 passed, 14 skipped

# Branch under review
git checkout feat/phase-6-provenance-granularity  # at 18b1a06
pytest -q                                      # → 564 passed, 14 skipped
                                               #   (548 baseline + 16 new)
```

The 548 baseline tests must still pass byte-identical. The Phase 6
delta is exactly **+16 passed, +0 skipped**. If your env produces
different absolute counts but the same +16 / +0 delta between master
and the branch, the gate is met. Anything else is a halt.

Phase 6 changes two pre-Phase-6 modules:
- ``src/ontozense/core/fusion.py``: new ``FieldAnchor`` dataclass,
  ``FieldProvenance`` extended with ``anchor: Optional[FieldAnchor] =
  None``, ``_set_field`` gains optional anchor param,
  ``_anchor_from_concept_provenance`` and
  ``_anchor_from_code_provenance`` helpers.
- ``src/ontozense/cli.py``: new ``_serialize_field_provenance`` helper;
  conflict serialisation in ``_serialize_element`` and the inline
  fuse output routed through it; ``_reconstruct_fusion_result`` reads
  ``anchor`` back when present (tolerates missing).

The extractors and validation module are **untouched** — Phase 6 is
a fusion-shape change.

### The AC1 contract for serialised JSON

Pre-Phase-6 conflict shape:
```json
{
  "field": "definition",
  "winner": {"source": "A", "value": "..."},
  "rejected": [{"source": "B", "value": "..."}],
  "resolution": "priority"
}
```

Phase 6 with anchors absent (the default):
```json
{
  "field": "definition",
  "winner": {"source": "A", "value": "..."},
  "rejected": [{"source": "B", "value": "..."}],
  "resolution": "priority"
}
```
**Byte-identical** — the ``anchor`` key is only emitted when the
provenance carries a non-empty ``FieldAnchor``. This is the AC1
load-bearing piece you should verify by spot-check, not just by
trusting the test suite.

---

## 3. What landed (your scope)

### Single commit `18b1a06` — ~546 LOC across 3 files, 16 new tests

| File | Change |
|---|---|
| `src/ontozense/core/fusion.py` | New ``FieldAnchor`` (frozen dataclass, 8 optional fields, ``is_empty()`` helper). ``FieldProvenance`` gains ``anchor: Optional[FieldAnchor] = None``. ``_set_field`` accepts optional ``anchor`` and threads to FieldProvenance. ``_anchor_from_concept_provenance`` and ``_anchor_from_code_provenance`` helpers. ``_merge_source_a`` calls ``_anchor_from_concept_provenance`` once per concept and passes the result to ``_set_field`` for element_name / definition / citation / domain_name. |
| `src/ontozense/cli.py` | New ``_serialize_field_provenance(fp)`` helper. ``_serialize_element`` and the inline fuse output route conflict winner/rejected through it. ``_reconstruct_fusion_result`` accepts pre-Phase-6 conflict entries (no ``anchor`` key) and reconstructs ``FieldAnchor`` when present. |
| `tests/test_phase6_provenance_anchors.py` | **New test file.** 16 tests across 6 test classes covering FieldAnchor shape (5), FieldProvenance.anchor (2), Source A threading (3), conflict winner anchor preservation (1), AC1 serialised shape (3), JSON round-trip (2). |

### Out of scope (deferred)

- **Source D structured business rules** — Phase 6 defines
  ``_anchor_from_code_provenance`` but doesn't thread it. Today's
  ``business_rules`` field is ``list[str]`` (human-readable
  descriptions with file:line embedded in the string). Threading
  per-rule anchors would mean restructuring this list shape, which is
  larger than Phase 6's "shape-only" scope per the agreed Q3 design
  decision. The helper exists so the contract is documented and ready
  for the eventual structured-rule pipeline.
- **Sources B and C anchors** — neither has anchor-shaped data in its
  current upstream representation (governance JSON has no offsets;
  Django field introspection doesn't expose source line numbers from
  a JSON dump). Adding extractor-level anchor capture is a downstream
  per-source enhancement.
- **Phase 7** — Benchmark metrics + reporting.

### Three Q1/Q2/Q3 design decisions locked before implementation

1. **Q1 (chose C)** — Anchor lives as a nested ``Optional[FieldAnchor]``
   on ``FieldProvenance``, not as a separate ``field_anchors`` sidecar
   on ``FusedElement`` and not as flattened fields directly on
   ``FieldProvenance``.
2. **Q2 (medium granularity)** — 8 fields: page, char_offset,
   char_length, line, end_line, column, segment_id, snippet. All
   optional. Different upstream extractors populate different subsets.
3. **Q3 (shape-only)** — No extractor changes. The typed contract is
   established and threaded through fusion; real-world anchor
   population grows extractor-by-extractor over time.

---

## 4. Three architectural decisions you should evaluate

These were locked before Phase 6 implementation. Tell us if you'd
push back now that you can see them in working code.

### Decision 1 — Anchor nested on FieldProvenance, not a sidecar

The anchor lives at:
``FusedElement.field_provenance["definition"].anchor``

Alternatives considered:
- **Sidecar:** ``FusedElement.field_anchors: dict[str, FieldAnchor]``
  separate from ``field_provenance``. Two places to look up "where
  did field X come from?", but cleaner separation of concerns.
- **Flattened:** add page/line/segment_id directly to FieldProvenance
  (no nested struct). Simpler shape, but bloats FieldProvenance with
  many usually-zero fields and makes the conflict resolver touch
  anchor data inadvertently.

**Argument for nested:** keeps "where field X came from" in one
place (provenance has source, confidence, value, anchor — all the
provenance context), and the typed Optional makes "no anchor"
trivially distinguishable from "anchor with all defaults". Conflict
resolution stays simple — winner's whole FieldProvenance carries
forward, anchor included.

**Argument against:** ``FieldProvenance`` is now a heavier object;
mutating an anchor requires constructing a new FieldProvenance (the
anchor itself is frozen). May be friction for downstream tools that
want to add an anchor to a provenance after the fact.

**Question:** Is the nested approach the right shape, or would you
push for a sidecar?

### Decision 2 — `is_empty()` as the AC1 gate

``FieldAnchor.is_empty()`` returns True when all 8 fields carry their
default (0 / empty). The CLI serialiser only emits the ``anchor``
key when ``anchor is not None and not anchor.is_empty()``.

**Argument for:** preserves AC1 byte-identity trivially. Pre-Phase-6
callers don't pass anchor → it's None → no key. Phase 6 callers who
build an empty anchor for some reason → still no key. Phase 6
callers who put real anchor data in any of the 8 fields → key
emitted.

**Argument against:** an explicit "no anchor" carries the same JSON
shape as "anchor with all defaults". A future bug where a real
anchor accidentally has all-zero fields would be silently dropped
from the JSON. Mitigation: the dataclass default values are 0 / "",
so this is only a problem if someone constructs a meaningful
``FieldAnchor()`` that intentionally has all defaults — which is
indistinguishable from no anchor anyway.

**Question:** Is the ``is_empty()`` gate the right contract, or
should we always serialise the anchor key when ``anchor is not
None`` (and accept the AC1 shape change for empty anchors)?

### Decision 3 — Source A anchor mapping uses section + snippet only

``_anchor_from_concept_provenance`` returns ``None`` unless the
upstream ``Provenance`` has at least one of ``source_section`` or
``source_text_snippet``. ``source_document`` alone does NOT trigger
anchor creation (it's tracked separately via Phase 5
``corroborating_doc_count`` / ``source_documents``).

**Argument for:** ``source_document`` is element-level metadata
(which doc this concept appeared in), not field-level location.
Putting it in the anchor would be redundant with the corroboration
list. Section + snippet are real coordinates inside the document.

**Argument against:** in some pipelines, ``source_document`` IS the
anchor (e.g. a single-page PDF where the doc identifies the
location). A reviewer using the anchor JSON can't tell which doc
the anchor refers to without cross-referencing the corroboration
list.

**Question:** Is the section+snippet-only contract the right
abstraction, or should ``source_document`` also be carried into the
anchor for self-contained provenance?

---

## 5. Specific things to evaluate

### 5.1 FieldAnchor shape

Read ``src/ontozense/core/fusion.py:73-117``. Verify:

- All 8 fields have sensible defaults (``page=0``, ``segment_id=""``,
  etc.) so a partially-anchored field round-trips.
- ``is_empty()`` returns True only when every field is its default.
  Try a manual probe: ``FieldAnchor(page=0).is_empty()`` → True.
  ``FieldAnchor(line=1).is_empty()`` → False.
- ``frozen=True`` actually prevents mutation. Confirm the test
  ``test_frozen`` passes for the right reason (``FrozenInstanceError``).

Anything missing? Is there a 9th field you'd add (e.g. ``href`` for
a stable URL anchor)? Is one of the 8 redundant?

### 5.2 Source A threading

Read ``_anchor_from_concept_provenance`` and the call in
``_merge_source_a``. Trace:

- Concept with ``provenance=None`` → anchor returned is None →
  ``_set_field`` stores None → no anchor in fused field_provenance.
- Concept with ``provenance.source_document="doc1.md"`` only →
  anchor is None (the helper requires section or snippet).
- Concept with ``provenance.source_section="3.2"`` →
  ``FieldAnchor(segment_id="3.2", snippet="")``.
- Concept with both section and snippet → both populated.

The same anchor is reused for element_name / definition / citation
/ domain_name — they share an extraction context. Is this right, or
should each field get its own anchor (e.g. citation might be a
different sentence than definition)? See Q4 in §6.

### 5.3 Source D not threaded — is the rationale sound?

``_anchor_from_code_provenance`` is defined but never called.
Reason: today's ``business_rules`` is ``list[str]`` with no
per-element anchor slot, and changing that to ``list[BusinessRule]``
would be a bigger refactor than Phase 6's shape-only scope.

Read the helper docstring at ``src/ontozense/core/fusion.py``
(``_anchor_from_code_provenance``). Is the rationale documented well
enough that a future contributor knows what to do? Should we have
deleted the helper instead of keeping it as a documented stub?

### 5.4 Conflict resolution preserves winner's anchor

Read ``_set_field``. The new FieldProvenance is constructed with
``anchor=anchor``. ``_resolve_conflict`` returns
``(winner, loser, reason)`` — the winner is the FieldProvenance
returned, including its anchor. Verify by reading the code that no
path constructs a fresh FieldProvenance and drops the winner's
anchor.

Specifically check the "same value from different source" branch
(line ~880 — ``if existing.original_value.strip().lower() ==
value.strip().lower(): return``): the existing prov is kept and the
new prov's anchor is dropped. Is that right? (Argument for: existing
already has an anchor, no need to overwrite.) Argument against: if
the new source has a richer anchor than existing, we lose it.

### 5.5 AC1 serialisation contract

Trace ``_serialize_field_provenance`` end to end:

- ``FieldProvenance`` with ``anchor=None`` → output dict has only
  ``{source, value}`` → byte-identical to pre-Phase-6.
- ``FieldProvenance`` with ``anchor=FieldAnchor()`` (all-defaults) →
  ``is_empty() == True`` → no ``anchor`` key.
- ``FieldProvenance`` with ``anchor=FieldAnchor(line=42)`` → key
  emitted with all 8 fields (including the 7 that are 0 / empty).

Verify the second case is what you'd expect. The argument is that
an "empty anchor" is functionally the same as no anchor; the
JSON shape parity is the AC1 contract.

### 5.6 JSON round-trip

Read ``_reconstruct_fusion_result`` for the new ``_anchor_from_dict``
helper. Verify:

- Pre-Phase-6 JSON (no ``anchor`` key on conflict entries) → all
  reconstructed FieldProvenance have ``anchor=None``. No crash.
- Phase-6 JSON with anchor → reconstructed FieldAnchor has the right
  field values.
- Pre-Phase-6 JSON missing some anchor fields (e.g. only
  ``{"page": 5}``) → reconstructed anchor has page=5 and other
  fields at default. (This is the forward-compat scenario where a
  future Phase 6.1 might emit only the populated fields.)

### 5.7 Test coverage

16 new tests in ``tests/test_phase6_provenance_anchors.py``.
Specifically check:

- ``TestFieldAnchorShape`` (5) — defaults, is_empty, frozen,
  equality, default field values. Missing: would it be worth a
  test for hashability (since FieldAnchor is frozen, it should be
  hashable — useful if anchors land in sets / dict keys later)?
- ``TestFieldProvenanceAnchor`` (2) — defaults to None, can be
  set. Anything missing?
- ``TestSourceAAnchorThreading`` (3) — section yields anchor, no
  anchor data → None, no provenance → None. Missing: snippet-only
  (no section) yields anchor with empty segment_id.
- ``TestConflictWinnerAnchor`` (1) — only one test. Missing:
  same-value-different-source dedup branch (what happens to the
  anchor when no real conflict?), confidence-based winner (not
  priority), recency-based winner.
- ``TestAc1SerialisedShape`` (3) — no anchor, empty anchor,
  non-empty anchor. Missing: a check that the serialised key
  ordering / dict shape is otherwise unchanged from pre-Phase-6.
- ``TestJsonRoundTrip`` (2) — non-empty anchor round-trips,
  pre-Phase-6 JSON without anchor key reads cleanly. Missing: a
  full fuse-→-write-→-read end-to-end pipeline test, not just
  manual dict construction.

---

## 6. Eight specific questions I want direct answers to

1. **Does the no-profile / no-anchor path produce JSON byte-identical
   to commit ``c6477cf``?** Run pytest on master, then on this branch.
   Pick a fixture-driven fusion test that produces a conflict (e.g.
   in ``tests/test_fusion*.py``), inspect its asserted JSON shape,
   and verify Phase 6 doesn't add an ``anchor`` key under any
   pre-Phase-6 conditions.

2. **Is the 8-field FieldAnchor shape right?** Are any redundant
   (e.g. could ``end_line`` be derived from ``line + char_length``)?
   Are any missing (e.g. ``href`` for stable URL fragments,
   ``revision_hash`` for source artifacts that change)?

3. **Is ``is_empty()`` correct?** Specifically: are all 8 fields
   considered, and are the defaults right? Is there a case where an
   anchor with one field set to zero (e.g. a real ``page=0``
   meaning "front matter") would be incorrectly suppressed?

4. **Is the Source A → FieldAnchor mapping right?** Specifically:
   should the same anchor apply to all of element_name / definition
   / citation / domain_name, or do these fields plausibly come from
   different sentences in the source and deserve separate anchors?

5. **Is keeping ``_anchor_from_code_provenance`` as a documented
   non-threaded helper the right call,** or should we have either
   threaded it (broader scope) or deleted it (cleaner code)?

6. **Is conflict resolution actually preserving the winner's
   anchor?** Trace the four conflict paths (priority, confidence,
   recency, same-value-different-source) and confirm each one
   carries the right anchor forward.

7. **Does the JSON round-trip preserve everything?** Run a full
   fuse → write JSON → read JSON pipeline by hand and compare
   FieldProvenance.anchor on both sides.

8. **What's the one thing most likely to bite us in Phase 7 because
   of how Phase 6 is shaped?** (Phase 7 is benchmark metrics +
   reporting; how anchors flow into reports is a likely vector.)

---

## 7. What the review output should look like

Write your review to `docs/REVIEW_PHASE_6.md` in this repo.

```markdown
# Phase 6 Review — Provenance Granularity

## Verdict
One paragraph: is this ready to merge to master and proceed to Phase 7,
or does something need to change first?

## What works well
Specific wins. Brief.

## Issues
Numbered list. Severity: blocker / major / minor / nit.

## Answers to the 8 questions in §6
Number them 1–8.

## Recommended changes before Phase 7 starts
Concrete, ordered.
```

3 pages is fine. Don't over-write.

---

## 8. House rules

- **Run `pytest -q` first.** 564 passed + 14 skipped on the branch,
  548 + 14 on master. Delta `+16 passed, +0 skipped`. If different,
  stop and report.
- **Read `docs/PROFILE_SPEC.md`** if anything about the schema shape
  is unclear — it's still the contract (Phase 6 doesn't change it).
- **Run a fuse + read-back manually** if you can: pick any existing
  fuse fixture, run ``ontozense fuse --source-a ...`` on master and
  on the branch, diff the output JSONs. They should be byte-identical
  unless the input concept's Provenance carries a section or snippet.
- **Trace ``_serialize_field_provenance``** for each of the three
  cases (None, empty, populated). This is the AC1 load-bearing
  function.
- **Cite ``file_path:line_number``** for every issue.
- **Severity matters.** Blocker = blocks Phase 7. Major = should fix
  before merge. Minor = follow-up. Nit = optional.
- **Do not propose features that aren't in the PRD.** Phase 6 is
  scoped tight; Source D structured business rules and Source B/C
  anchor extraction are explicitly deferred.

---

Thank you. Phase 7 is gated on this review. The AC1 ``is_empty()``
suppression contract from §5.5 and the conflict resolution anchor
preservation from §5.4 are the load-bearing pieces — focus there.
