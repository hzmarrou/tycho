# Independent Review Assignment — Phase 5: Fusion Consolidation

**Review on:** branch `feat/phase-5-fusion-consolidation` at HEAD `11c2559`
**Repository:** `C:\Users\hzmarrou\OneDrive\python\projects\ontozense`
**Master is at:** `986ad76` (Phase 4 merge `9fc7124` + a one-line
chore fix to make a developer-only test path env-driven so the
baseline test count is now stable across OSes — see §2).
**Not yet merged to master.** Your verdict gates the merge.

---

## 1. Why this review

You cleared Phase 4 last round (`docs/REVIEW_PHASE_4.md`), then we
fixed the VR001/VR002/VR004 filter-mode dataclass-equality defect you
flagged and merged. Phase 5 is the payoff for the cross-source ID
alignment contract from Phases 2/3: fusion now uses those deterministic
IDs to consolidate concepts that span multiple authoritative documents
or multiple sources.

| Layer | Pre-Phase-5 | Phase 5 |
|---|---|---|
| Fusion index | Single dict keyed by ``normalise_name(name)`` | Name index + ``id_lookup`` map for profile-mode id-first resolution |
| Multi-doc Source A | Concat then merge by name (lossy: lost which doc each concept came from) | Per-doc consolidation with ``corroborating_doc_count`` and ``source_documents`` list tracked in ``extra_fields`` |
| Cross-source enrichment | B/C/D matched A by name only | B/C/D try id first, fall back to name (handles surface-form drift across sources) |
| ``FusionEngine.fuse()`` API | ``source_a: DomainDocumentExtractionResult \| None`` | ``source_a: DomainDocumentExtractionResult \| list[...] \| None`` (single-result callers unchanged) |
| ``ontozense fuse`` CLI | ``--source-a`` once | ``--source-a`` repeatable; once-per-document fusion |

The core invariant: **same canonical (entity_type, label) tuple across
N sources/docs → ONE fused element**, regardless of surface-name drift.
This is what the cross-source ID alignment contract was built for.

We want to know: **can we merge `feat/phase-5-fusion-consolidation` to
master and confidently start Phase 6 (provenance granularity)?**

This review is scoped narrowly. We do **not** want re-review of:
- Phases 1–4 (profile loader, identity, constrained Sources A/B/C/D,
  validation stage)
- The PRD direction
- The cross-source ID alignment contract itself (already cleared)

We **do** want a review of:
- Whether the dual-keyed index correctly handles all four mode-mix
  combos (A-profile + B-profile, A-profile + B-unconstrained, etc.)
- Whether the **id-collision** logic is right: distinct ids sharing
  a normalised name must stay separate (no silent merges)
- Whether ``corroborating_doc_count`` is computed correctly across
  edge cases (same doc appearing twice, missing provenance, etc.)
- Whether **AC1** (no-profile byte-identity) actually holds under the
  refactored ``_get_or_create``
- Whether the CLI's repeatable ``--source-a`` is shaped well

---

## 2. The single most important constraint — verify first

**PRD AC1: no-profile behaviour must be byte-identical.** Non-negotiable.

```bash
# Baseline (post-Phase-4 + chore fix)
git checkout master                            # at 986ad76
pytest -q                                       # → 518 passed, 14 skipped

# Branch under review
git checkout feat/phase-5-fusion-consolidation  # at 11c2559
pytest -q                                       # → 538 passed, 14 skipped
                                                #   (518 baseline + 20 new)
```

The 518 baseline tests must still pass byte-identical — no
pre-existing test was modified, replaced, or reordered. The Phase 5
delta is exactly **+20 passed, +0 skipped**. If your env produces a
different absolute count but the same +20 / +0 delta between master
and the branch, the gate is met. If you see ANY pre-existing test
flip from passing to failing, or any pre-existing skipped test
unexpectedly pass / vice-versa, that's a **blocker**.

### Note on the master `986ad76` chore fix

Your prior Phase 5 baseline run reported `538 passed, 14 skipped`
where the original assignment expected `542 passed, 10 skipped`.
That delta was caused by `tests/test_npl_pipeline.py:150` hardcoding
a developer-specific Windows path (`C:\Users\hzmarrou\OneDrive\...`)
that resolved on the original developer's machine but skipped
silently in WSL / Linux / non-Windows. The chore commit `986ad76`
on master replaces it with an `ONTOZENSE_COMBINED_EXTRACTION_JSON`
env var: when unset (which is the case in CI / clean-checkout review
envs), the four `TestConvertExistingExtraction` tests skip
deterministically. Counts are now stable across OSes — your earlier
delta finding was correct and is now resolved upstream of Phase 5.

### Phase 5 changes two pre-Phase-5 modules:
- ``core/fusion.py``: ``_get_or_create`` rewritten, ``_lookup`` and
  ``_track_corroboration`` added, all four ``_merge_source_X`` methods
  modified to thread ``id_lookup`` and use the new helpers.
- ``cli.py``: ``fuse --source-a`` switched from ``Path`` to
  ``list[Path]`` (typer-repeatable), reconstruction logic factored
  into ``_load_source_a_json()``.

The extractors and the validation module are **untouched** — Phase 5
is a fusion-layer change.

---

## 3. What landed (your scope)

### Single commit `0827815` — ~907 LOC across 3 files, 20 new tests

| File | Change |
|---|---|
| `src/ontozense/core/fusion.py` | ``FusionEngine.fuse()`` accepts list-or-single ``source_a``. New ``id_lookup: dict[str, str]`` alongside the name-keyed index. New ``_lookup`` (id-first read-only), ``_track_corroboration`` (per-doc tracking), and rewritten ``_get_or_create`` (handles direct id hit, name match with id promotion, name match with id collision, fresh creation). All four ``_merge_source_X`` methods updated. |
| `src/ontozense/cli.py` | ``fuse --source-a`` now ``list[Path] = typer.Option(None, "--source-a", ...)`` so the flag is repeatable. New ``_load_source_a_json()`` helper preserves profile-mode ``id`` and ``entity_type`` from the JSON. |
| `tests/test_phase5_fusion_consolidation.py` | **New test file.** 20 tests across 8 test classes covering backward compat, multi-doc consolidation (unconstrained + profile), cross-source id-first lookup for B/C/D, mixed-mode tolerance, and the CLI multi-flag end-to-end. |

### Out of scope (deferred)

- **Phase 6** — Provenance granularity (segment/page/char-offset
  anchors so reviewers can jump from a fused field to the exact
  source location). Phase 5's ``source_documents`` list tracks the
  filename only; finer-grained anchors are Phase 6's job.
- **Phase 7** — Benchmark metrics + reporting.

---

## 4. Three architectural decisions you should evaluate

These were locked before Phase 5 implementation. Tell us if you'd
push back now that you can see them in working code.

### Decision 1 — Dual key strategy: id-first with name fallback

The index uses **two keys** in concert:
- ``index: dict[str, FusedElement]`` — keyed by normalised name (and
  occasionally by ``"<name>#id:<eid>"`` collision keys, see Decision 2).
- ``id_lookup: dict[str, str]`` — maps deterministic id → key in
  ``index``.

A profile-mode lookup tries ``id_lookup[eid]`` first; if no hit, falls
back to ``normalise_name(name)``. An unconstrained lookup goes
straight to name.

**Argument for:** AC1 holds trivially because unconstrained mode never
populates ``id_lookup`` — the engine reduces to today's name-keyed
behaviour. Mixed-mode is also handled gracefully: an unconstrained
Source A element gets adopted by a later profile-mode Source B record
that shares its name (B's id is registered against A's existing
element).

**Argument against:** two data structures held in sync mean a class of
bugs (forgotten registration, stale entries) that a single-structure
design would prevent. A wrapper class around both would be safer but
more invasive.

**Question:** Is the dual-map approach the right shape, or would you
push for a wrapper class (``_FusionIndex``) that encapsulates both?

### Decision 2 — Id-collision via composite key, not separate registry

When two profile-mode entities have **distinct ids but the same
normalised name** (e.g. two different "Customer" entities each with
their own deterministic id), they must stay separate. The chosen
mechanism is a composite index key:

```python
# When name_key already exists with a different id:
collision_key = f"{name_key}#id:{eid}"
index[collision_key] = FusedElement(element_name=name.strip())
id_lookup[eid] = collision_key
```

**Argument for:** keeps the index a flat ``dict[str, FusedElement]``,
preserves "find by name" semantics for the first occurrence, and
isolates collisions deterministically by id.

**Argument against:** the composite key is a "magic string". A
downstream consumer iterating ``index.keys()`` might assume each key
is a clean normalised name. Currently ``index.values()`` is the only
external use, so this is internal — but if Phase 6/7 grows the API,
the magic key shape could leak.

**Question:** Is the composite-key collision strategy acceptable, or
should we introduce a typed ``_IndexEntry`` to make it explicit?

### Decision 3 — `--source-a` as repeatable flag, not new positional

The CLI extends ``fuse --source-a`` from a single ``Path`` option to a
repeatable ``list[Path]`` option. Multi-document fusion looks like:

```bash
ontozense fuse --source-a doc1.json --source-a doc2.json --source-a doc3.json \
               --source-b governance.json --output fused.json
```

**Argument for:** the existing single-flag form keeps working
unchanged (typer's ``list[Path]`` accepts a single ``--source-a``
fine), so nobody's existing scripts break. Repeatable flags also
compose naturally with shell loops (``for f in *.json; do args+=" --source-a $f"; done``).

**Argument against:** discovery is poor — a user reading
``--source-a`` help expecting a single path may not realise it's
repeatable. An alternative is positional varargs (``ontozense fuse
*.json --output fused.json``) but that conflicts with the current
optional-flag style of all other sources.

**Question:** Is the repeatable-flag pattern the right CLI surface,
or should we make multi-doc more discoverable (e.g. a
``--source-a-glob`` or ``--source-a-dir`` shortcut)?

---

## 5. Specific things to evaluate

### 5.1 The dual-keyed index — does it actually do what the docstring claims?

Read ``src/ontozense/core/fusion.py:_get_or_create`` end to end. Walk
through the four documented cases:

1. Direct id hit (same eid seen before).
2. Name match + same id (or one side unclaimed) → merge.
3. Name match + distinct id → composite key.
4. Fresh creation → register name-key + id_lookup if eid.

Trace each case manually against the test fixtures:
- Case 1: ``test_same_id_collapses_even_when_names_differ``
- Case 2 (id promotion): ``test_unconstrained_a_then_profile_b_propagates_id``
- Case 3: ``test_different_ids_keep_separate_even_with_same_normalised_name``
- Case 4 (registration): ``test_source_b_only_record_creates_new_element``

Specific concern: in ``_merge_source_a``, the line
``el.extra_fields.setdefault("id", concept.id)`` runs **after**
``_get_or_create`` returns. So between concept #1 and concept #2 in
the same loop, the id of element #1 is already set in
``extra_fields["id"]``, and the collision check in ``_get_or_create``
(``existing.extra_fields.get("id", "")``) sees the right value. But
what if the order of operations were reversed somewhere? Read the
fusion engine's pass methods and verify the invariant holds for
B, C, D too.

### 5.2 Corroboration tracking — edge cases

Read ``_track_corroboration`` (around line ~590) and verify:

- A concept with no provenance does not raise — silent skip.
- A concept with empty ``source_document`` string also skips.
- Same ``source_document`` appearing twice in the same fusion (e.g.
  two concepts in the same doc both named "Customer") deduplicates
  and only counts once.
- ``corroborating_doc_count`` always equals
  ``len(source_documents)``.
- The ``source_documents`` list preserves insertion order (so the
  reviewer can tell which doc first introduced the term).

The covering tests are in ``TestMultiDocUnconstrained`` (5 tests).
Anything you'd add?

### 5.3 Cross-source id-first lookup

Read ``_merge_source_b``, ``_merge_source_c``, ``_merge_source_d``.
Each switched from ``if key in index: el = index[key]`` to
``el = self._lookup(index, id_lookup, eid=..., name=...)``.

Verify:
- Source B's record id ``rec.id`` is passed correctly. (Phase 3
  populates this on profile-mode records.)
- Source C's field id ``sf.id`` is passed correctly. (Phase 3
  populates this on profile-mode SchemaField.)
- Source D's ``rule.attached_to_entity_id`` is the right attribute
  to use (Phase 3 populates this on rules attached to a profile
  entity).
- The fallback path (no id hit, falls back to name) actually runs
  when the record has no id.

Specific concern: Source D's referenced-symbols loop still uses
name-only matching:
```python
for sym in rule.referenced_symbols:
    sym_el = self._lookup(index, id_lookup, name=sym.split(".")[-1])
```
This is intentional — referenced symbols are arbitrary code-name
tokens and don't have profile-mode ids. But verify no path leaks an
id into ``sym`` that should have been resolved differently.

### 5.4 AC1 byte-identity under the refactor

The 522 baseline tests passing is necessary but not sufficient — many
of them don't exercise the fused-element ``extra_fields`` shape.
Specific concern: ``el.extra_fields["source_documents"]`` and
``corroborating_doc_count`` are NEW keys that get populated whenever
a Source A concept has provenance. Even in unconstrained mode, if
the test fixture provides a concept with ``provenance.source_document``
set, the fused element now has these extra keys.

**Verify:** find a pre-Phase-5 fusion test that builds Source A
concepts with provenance, run it, and check the asserted shape of
``extra_fields`` is unchanged. If any pre-existing test asserts
``len(el.extra_fields) == N`` or ``el.extra_fields == {...}``
literally, it would break. Spot-check ``tests/test_fusion*.py`` and
``tests/test_pipeline*.py``.

### 5.5 The CLI shape

Read ``cli.py:fuse`` and ``cli.py:_load_source_a_json``.

- Does ``--source-a`` with a single value still work? Test by
  re-running an existing single-source command.
- What happens with ``--source-a a.json --source-a a.json`` (same
  file twice)? This shouldn't crash, but it would inflate
  ``corroborating_doc_count``. Acceptable, or worth deduplicating?
- What if one of the files is missing or unreadable? The helper
  raises an unhandled exception today. Should it surface a clean
  error (like ``--profile`` does)?
- Does ``_load_source_a_json`` correctly preserve ``id`` and
  ``entity_type`` from the JSON? Test by calling extract-a with
  ``--profile`` and ``--json``, then fusing the result and checking
  the fused output retains the ids.

### 5.6 Test coverage

20 new tests in ``tests/test_phase5_fusion_consolidation.py``.
Specifically check:

- ``TestBackwardCompatApi`` (4) — single, None, empty list, list-of-1.
  Anything missing? (e.g. mixing None for some sources, empty list
  for source_a, results vs no results comparison.)
- ``TestMultiDocUnconstrained`` (5) — collapse, count, dedup, no
  provenance, normalisation. Missing: ordering of source_documents
  when concepts arrive from docs in non-alphabetical order. Worth
  pinning?
- ``TestMultiDocProfileMode`` (3) — id-collapse, id-collision-stays-
  separate, first-doc-wins. Missing: a test with profile-mode in
  some docs and unconstrained in others (mixed-mode within Source A
  itself).
- ``TestSourceB/C/DIdFirstLookup`` (5) — covers id-first + name
  fallback for each. Missing: combined A+B+C+D where A is profile
  and B/C/D each use id-first to find A's element.
- ``TestMixedModeTolerance`` (1) — only one test. Worth a second
  showing the reverse direction (profile-A + unconstrained-B + ...).
- ``TestCliMultiSourceA`` (1) — basic two-flag smoke. Missing:
  three-flag, single-flag (backward compat), broken file path.

---

## 6. Eight specific questions I want direct answers to

1. **Does the no-profile path produce output byte-identical to commit
   `9fc7124`?** Run pytest on master, then on this branch — count
   passes, diff any unexpected output. Pay particular attention to
   any pre-Phase-5 test that asserts the precise shape of
   ``extra_fields`` on fused elements.

2. **Is the dual-key strategy (name index + id_lookup) sound?**
   Specifically: are the four cases in ``_get_or_create`` exhaustive,
   or is there a fifth I missed? (e.g. an entity that was registered
   without an id, then a later record adds the id, then a third
   record with a *different* id and the same name — does this end
   up correctly split or wrongly merged?)

3. **Is the id-collision logic (composite key) correct?** What's
   the most likely realistic scenario where two distinct profile-mode
   entities legitimately share a name? Does Phase 5 handle it
   correctly?

4. **Is the corroboration tracking correct?** Specifically: trace
   through a scenario where the same doc appears in two concepts
   (e.g. doc1 has both "Customer" and "Customer Order" — both
   should contribute "doc1.md" to their respective elements'
   ``source_documents`` lists). Does the dedup logic handle that
   correctly?

5. **Is `--source-a` repeatable the right CLI surface?** Or should
   discovery be improved (e.g. a ``--source-a-dir`` shortcut, or
   prose in the help text)?

6. **Are id and entity_type propagation rules correct under
   mixed-mode?** When unconstrained-A meets profile-B, B's id should
   be propagated to A's element. When profile-A meets unconstrained-B,
   A's id stays put. Verify both directions.

7. **What happens when a Source A list is given but every element
   is empty / has zero concepts?** Does the engine cope gracefully
   (no elements, but Source A still listed in sources_used)?

8. **What's the one thing most likely to bite us in Phase 6 because
   of how Phase 5 is shaped?** (Phase 6 wants to add per-field
   provenance anchors — segment / page / char-offset.)

---

## 7. What the review output should look like

Write your review to `docs/REVIEW_PHASE_5.md` in this repo.

```markdown
# Phase 5 Review — Fusion Consolidation

## Verdict
One paragraph: is this ready to merge to master and proceed to Phase 6,
or does something need to change first?

## What works well
Specific wins. Brief.

## Issues
Numbered list. Severity: blocker / major / minor / nit.

## Answers to the 8 questions in §6
Number them 1–8.

## Recommended changes before Phase 6 starts
Concrete, ordered.
```

3 pages is fine. Don't over-write.

---

## 8. House rules

- **Run `pytest -q` first.** 542 passed + 10 skipped. If different,
  stop and report.
- **Read `docs/PROFILE_SPEC.md`** if anything about the schema shape
  is unclear — it's still the contract for Phase 5.
- **Run a multi-doc fusion by hand** if you can: pick two of the
  ESG or NPL example docs, extract each with ``ontozense extract-a
  --profile <profile-dir> --json doc1.json``, then fuse with
  ``ontozense fuse --source-a doc1.json --source-a doc2.json --output
  fused.json``. Inspect ``fused.json`` for ``corroborating_doc_count``
  and ``source_documents`` on the consolidated elements.
- **Trace ``_get_or_create`` manually** for each of its four cases.
  This is the load-bearing function.
- **Cite `file_path:line_number`** for every issue.
- **Severity matters.** Blocker = blocks Phase 6. Major = should fix
  before merge. Minor = follow-up. Nit = optional.
- **Do not propose features that aren't in the PRD.** Phase 5 is
  scoped tight; Phase 6's provenance anchors are explicitly deferred.

---

Thank you. Phase 6 is gated on this review. The id-collision logic
in ``_get_or_create`` and AC1 byte-identity under the
``extra_fields`` shape change from §5.4 are the load-bearing pieces —
focus there.
