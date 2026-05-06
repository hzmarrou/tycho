# Independent Review Assignment — Phase 7: Benchmark Metrics + Reporting

**Review on:** branch `feat/phase-7-benchmark-metrics` at HEAD `e78796d`
**Repository:** `C:\Users\hzmarrou\OneDrive\python\projects\ontozense`
**Master is at:** `1a9310a` (Phase 6 merged after your prior review).
**Not yet merged to master.** Your verdict gates the merge.

---

## 1. Why this review

You cleared Phase 6 last round (`docs/REVIEW_PHASE_6.md`). Phase 7
is the **final** entry in the PRD's 7-phase ontology-extraction
upgrade. Once it merges, the entire upgrade is done.

Phase 7 introduces a typed pipeline-health snapshot computed from a
fused output, and an `ontozense report` CLI verb that emits both a
machine-diffable JSON snapshot and a human-readable markdown
digest. The point of Phase 7: give the user one place to ask "is
my run any good?" without curating a gold-standard reference
dictionary.

| Layer | Pre-Phase-7 | Phase 7 |
|---|---|---|
| Where pipeline metrics live | Scattered: `extract-a` prints LLM/regex counts; `fuse` prints conflict counts; `validate` prints VR findings; `lint` prints lint categories | Centralised in `core/benchmark.py` — one typed `BenchmarkReport` with six per-section dataclasses |
| Run-vs-run comparison | Manual diff of console output | `ontozense report --output snapshot.json` → diff two JSONs |
| Profile coverage | Implicit in fusion stats | Explicit: declared-vs-used breakdown of entity_types and predicates (when `--profile` given) |
| Anchor visibility (Phase 6 thread) | Only inside conflict provenance entries | First-class anchor coverage section; per-field anchored vs unanchored breakdown |
| Multi-doc corroboration (Phase 5 thread) | Only `extra_fields["corroborating_doc_count"]` per element | Distribution buckets (1 / 2 / 3+) plus tracked-element count |

The core invariant: **the report is read-only on the fused output**.
Computing a benchmark must never mutate the FusionResult, never
trigger a re-extraction, never write back to upstream extractor
state. AC1 in Phase 7 is therefore stronger than the byte-identity
contract of earlier phases — it's a *side-effect-free* contract on
the metrics computation itself.

**Reference-benchmark mode** (precision/recall/F1 vs a curated
reference dictionary) is intentionally **out of scope** for Phase 7.
The data shape is extensible enough to slot a future
`ReferenceComparison` block in without breaking existing consumers,
but Phase 7 self-benchmarks only.

We want to know: **can we merge `feat/phase-7-benchmark-metrics`
to master and call the 7-phase PRD upgrade done?**

This review is scoped narrowly. We do **not** want re-review of:
- Phases 1–6 (profile loader, identity, constrained Sources A/B/C/D,
  validation stage, multi-doc + cross-source consolidation, typed
  provenance anchors)
- The PRD direction
- The cross-source ID alignment / corroboration / anchor contracts
  (already cleared in earlier phases)

We **do** want a review of:
- Whether the six metric sections are the right set (none missing,
  none redundant)
- Whether the bucket boundaries (confidence: 0.5/0.7/0.9; doc count:
  1/2/3+) are sensible
- Whether `_compute_anchor_coverage` aggregates at the right level
  (per FieldProvenance entry) and the per-field breakdown is useful
- Whether profile coverage handles subtype matching and case-
  insensitive predicate lookup correctly
- Whether the markdown rendering is the right shape for a reviewer
  glancing at the output (and not, say, missing critical info)
- Whether AC1 (no mutation of FusionResult) actually holds across
  all six section computers

---

## 2. The single most important constraint — verify first

**Phase 7 AC1: `compute_benchmark()` must be side-effect-free on
the input FusionResult.** Non-negotiable.

```bash
# Baseline (post-Phase-6 merge)
git checkout master                          # at 1a9310a
pytest -q                                     # → 567 passed, 14 skipped

# Branch under review
git checkout feat/phase-7-benchmark-metrics   # at e78796d
pytest -q                                     # → 593 passed, 14 skipped
                                              #   (567 baseline + 26 new)
```

The 567 baseline tests must still pass byte-identical. The Phase 7
delta is exactly **+26 passed, +0 skipped**. If your env produces
different absolute counts but the same +26 / +0 delta between
master and the branch, the gate is met.

Phase 7 changes one pre-Phase-7 module:
- `src/ontozense/cli.py`: new `report` command inserted between
  `lint` and `fuse`. **Existing commands untouched** — verify the
  diff is purely additive (one new `@app.command()` block).

The fusion engine, validation module, extractors are all
**untouched** — Phase 7 is a read-only consumer of the existing
fused output shape.

### The Phase 7 AC1 contract

`compute_benchmark()` reads `fusion_result.elements`,
`fusion_result.relationships`, and `fusion_result.sources_used` —
and **never writes** to any of them. The same FusionResult passed
to `compute_benchmark()` should produce identical lint output,
identical validate output, identical query output before and after
the call. Verify by reading the section computers in
`src/ontozense/core/benchmark.py`.

---

## 3. What landed (your scope)

### Single commit `e78796d` — ~1030 LOC across 3 files, 26 new tests

| File | Change |
|---|---|
| `src/ontozense/core/benchmark.py` | **New module.** Seven typed dataclasses (`BenchmarkReport` + 6 nested per-section: `ElementCounts`, `ConfidenceStats`, `ConflictStats`, `AnchorCoverage`, `CorroborationStats`, `ProfileCoverage`). Public `compute_benchmark(fusion_result, profile=None)` entry point. Six private section computers. `render_markdown(report)` renderer. |
| `src/ontozense/cli.py` | New `report` command (≈110 lines) inserted between `lint` and `fuse`. Pattern: load fused JSON → optional profile load → `compute_benchmark` → emit markdown (file or stdout) and JSON snapshot (when `--output`). `--domain-dir` integration: log + auto file-back of markdown under `derived/reports/`. |
| `tests/test_phase7_benchmark.py` | **New test file.** 26 tests across 9 test classes covering each section computer, markdown rendering, AC1 read-only contract, and end-to-end CLI integration. |

### Out of scope (deferred)

- **Reference-benchmark mode** — precision/recall/F1 against a
  curated reference dictionary. Per the agreed Q1 design decision,
  Phase 7 is self-benchmark only. The data shape is extensible
  enough to add a `ReferenceComparison` block later.
- **Trend / time-series visualization** — runs accumulating over
  time, plotted. Phase 7 produces snapshots; comparing two
  snapshots is `diff snapshot1.json snapshot2.json`. Anything more
  visual is a downstream tool.
- **Validation findings embedded in the report** — `ontozense
  validate` is a separate command. The report could in principle
  embed a validate findings section, but that would couple the two
  commands; current shape is "user runs validate then report" or
  "user runs report alone for self-health."

### Three Q1/Q2/Q3 design decisions locked before implementation

1. **Q1 (chose A — self-benchmark)** — No reference dictionary
   required. The report computes metrics directly from the fused
   output and (optionally) the profile.
2. **Q2 (chose A — single `report` command)** — Mirrors the
   existing pattern (`fuse`, `validate`, `lint`, `query`). Sub-flags
   for profile, output, markdown, domain-dir integration.
3. **Q3 (chose C — both JSON and Markdown)** — JSON for run-vs-run
   diffing, Markdown for human review. Single source of truth (the
   `BenchmarkReport` dataclass) renders to both.

---

## 4. Three architectural decisions you should evaluate

These were locked before Phase 7 implementation. Tell us if you'd
push back now that you can see them in working code.

### Decision 1 — Six metric sections, no validation embedding

The benchmark report has six per-section blocks: ElementCounts,
ConfidenceStats, ConflictStats, AnchorCoverage, CorroborationStats,
ProfileCoverage (optional, requires `--profile`).

**Argument for the chosen six:** each section corresponds to one
concrete question a reviewer might ask ("how many elements?", "how
confident?", "how often did sources disagree?", "how many fields
have anchor data?", "how many docs corroborate each entity?", "what
% of the profile schema did we actually populate?"). Validation
findings live in `ontozense validate` — a separate verb.

**Argument against:** a user running `report` to get a single
go-no-go signal still has to run `validate` separately. Embedding
validation pass-rate would make the report a one-stop quality
check.

**Question:** Should the report optionally embed validation
findings (e.g. `ontozense report --validate` runs validation
inline and includes the summary)? Or is keeping the two verbs
strictly separate the right separation of concerns?

### Decision 2 — Bucket boundaries on confidence and doc count

Confidence histogram: `[0.0-0.5, 0.5-0.7, 0.7-0.9, 0.9-1.0]`.
Doc-count distribution: `[1_doc, 2_docs, 3+_docs]`.

**Argument for:** the confidence boundaries match the
"needs_review" threshold (0.7 by default in `FusedElement`), so the
0.7-0.9 bucket is "above review threshold but not high-confidence."
The 0.9 cut is "high-confidence." The 0.5 cut is "below mid." Doc
counts are intuitively binned: single doc / two-doc corroboration /
three-or-more = stronger.

**Argument against:** the boundaries are domain-dependent. An ESG
pipeline at 0.65 average might be normal; an NPL pipeline at the
same number might indicate a bad run. Hard-coded boundaries make
cross-domain comparison harder. Alternatively: configurable per
profile.

**Question:** Are the hard-coded boundaries the right shape, or
should they be profile-configurable (e.g. `profile.report_buckets`
in the schema)?

### Decision 3 — Profile coverage uses subtype awareness + case-insensitive predicate match

`_has_used_subtype()`: a parent type counts as covered if any
declared subtype appears. Predicate match: `rel.predicate.lower()`
vs `profile.predicates` keys lowered.

**Argument for:** mirrors what Phase 4 validation does (`is_known_type`
is subtype-aware; predicate lookup is case-insensitive after the
Phase 3 review fix). Coverage shouldn't say "Metric is unused" when
DirectMetric / CalculatedMetric appear — they ARE Metric.

**Argument against:** there's now a gentle inconsistency: a profile
declaring Metric with subtypes [Direct, Calculated] and seeing only
Direct + Calculated will report "Metric covered" but won't list
which subtypes are unused (only top-level types appear in
`entity_types_unused`). A reviewer wanting subtype-level coverage
would have to compute it themselves.

**Question:** Should `entity_types_unused` include both unused
top-level types AND unused subtypes? Or is top-level-only the right
abstraction?

---

## 5. Specific things to evaluate

### 5.1 BenchmarkReport shape

Read `src/ontozense/core/benchmark.py:46-110`. Verify:

- All six section dataclasses have sensible defaults (empty list,
  zero count, empty dict).
- `BenchmarkReport.profile_coverage` is `Optional` and defaults to
  None (so consumers can distinguish "no profile supplied" from
  "profile supplied with zero coverage").
- `to_dict()` produces a JSON-friendly nested structure (try
  `json.dumps(report.to_dict())` should not raise).

Anything missing? Should `BenchmarkReport` carry the input fused
JSON path / hash for traceability? Is the field ordering inside
each dataclass consistent (e.g. counts first, distributions last)?

### 5.2 Element counts

Read `_compute_element_counts`. Verify:

- `by_source_combination` key format: sorted `set(el.sources)` joined
  by `+`. Two elements with `sources=["B","A"]` and `sources=["A","B"]`
  should produce the same key `"A+B"`.
- An element with empty sources produces key `"(none)"` — sentinel
  to surface a bug in the upstream pipeline.
- `multi_source` counts elements with `len(set(el.sources)) >= 2`
  (so duplicates in the sources list don't inflate).

Specifically check: what happens when an element appears with
sources `["A", "A"]` (duplicate)? The set dedup handles it, but is
that the right policy? (Yes — sources is a set semantically.)

### 5.3 Confidence stats

Read `_compute_confidence_stats`. Verify:

- Empty input → all zeros, no division-by-zero.
- Histogram boundaries: `c < 0.5` → "0.0-0.5"; `0.5 <= c < 0.7` →
  "0.5-0.7"; `0.7 <= c < 0.9` → "0.7-0.9"; `0.9 <= c <= 1.0` →
  "0.9-1.0". Verify exactly 0.5, 0.7, 0.9 (the boundaries) land in
  the right bucket.
- `needs_review` counts elements via `el.needs_review()` —
  delegated to FusedElement's existing method which considers both
  confidence threshold and unresolved conflicts. Right delegation?

### 5.4 Anchor coverage aggregation

Read `_compute_anchor_coverage`. Verify the aggregation level:

- Counts every entry in every element's `field_provenance` dict.
  Multi-element fused outputs sum across all elements.
- An element with definition + citation + element_name in
  `field_provenance` → 3 entries counted.
- Per-field breakdown is keyed by field name, not field index,
  so "definition" across 100 elements aggregates to one row.

The `with_anchor` count is "anchor is not None" (presence of the
nested struct, regardless of content). The `with_non_empty_anchor`
count is the stricter "anchor is populated with at least one
non-default value." Both are useful: presence vs meaningfulness.

Question: should there be a third stat — "% of fields where every
element has a non-empty anchor"? (i.e. per-field coverage rate, not
per-FieldProvenance count.) That'd answer "is my pipeline
consistently anchoring all definitions?" vs "did any one of them
get anchored at some point?"

### 5.5 Corroboration distribution

Read `_compute_corroboration_stats`. Verify:

- Only counts elements where `extra_fields["corroborating_doc_count"]`
  is set (which is profile-mode or multi-doc fusion only — Phase 5
  AC1 contract).
- Three buckets: `"1_doc"`, `"2_docs"`, `"3+_docs"`.
- `count >= 3` falls into `"3+_docs"`.

What about `count == 0`? Fusion shouldn't produce that (corroboration
tracking is only triggered when at least one doc is recorded), but
if it did, it'd fall into `"3+_docs"` because of the else branch.
Is that a bug? (Probably YAGNI — but worth flagging.)

### 5.6 Profile coverage subtype + predicate logic

Read `_compute_profile_coverage` and `_has_used_subtype`. Verify:

- Subtype awareness: when profile declares `Metric` with subtypes
  `[DirectMetric, CalculatedMetric]`, a fused output containing
  only `entity_type=DirectMetric` reports `Metric` as covered.
- The unused-types list reflects this: `Metric` does NOT appear
  in `entity_types_unused`.
- Predicate matching is case-insensitive: a relationship with
  `predicate="appliesto"` matches a profile predicate `"AppliesTo"`.
- The `predicates_unused` list preserves the canonical case
  (profile's declared form), not the lowercased form.

### 5.7 Markdown render

Read `render_markdown`. Verify:

- All six always-on sections have a heading and at least a count.
- Profile coverage section appears only when `report.profile_coverage
  is not None`.
- Tables use the standard pipe format and the column counts match
  (especially for the source-combination breakdown which is
  variable-width).
- Newlines are consistent — the function strips trailing newlines
  and adds exactly one final newline.

### 5.8 CLI surface

Read the `report` command in `src/ontozense/cli.py`:

- Arg shape mirrors `validate` and `lint`: positional `fused_json`,
  optional `--profile`, optional `--output`, optional
  `--domain-dir`.
- Adds `--markdown` for an explicit markdown file path; if not
  supplied, markdown goes to stdout.
- `--domain-dir` integration: appends to log.md AND auto-files-back
  the markdown report under `derived/reports/` (only when
  `--markdown` is also supplied — otherwise nothing to file back).
- Profile load uses the same `ProfileError` / `OSError` clean-error
  pattern as `extract-a` and `validate`.

Specific concern: what happens with `--domain-dir` but NO
`--markdown`? Currently the log entry is appended but no file is
filed back (the markdown went to stdout, ephemeral). Is that the
right policy or should the CLI auto-create a markdown file in the
domain dir?

### 5.9 AC1 read-only contract

Read every section computer (`_compute_*`). Each takes the
FusionResult / elements list as input and produces a new dataclass.
Verify NONE of them mutate:
- `el.extra_fields` (e.g. by writing to a new key)
- `el.field_provenance` (e.g. by appending an anchor)
- `el.sources` (e.g. by sorting in place)
- `el.conflicts` (e.g. by indexing into a sub-attribute)

The test `TestReportIsReadOnly::test_compute_does_not_mutate_input`
covers `extra_fields`, `confidence`, `sources`. Is that enough?
What about `field_provenance` (which is a dict mutation surface)?

### 5.10 Test coverage

26 new tests in `tests/test_phase7_benchmark.py`. Specifically check:

- `TestElementCounts` (4) — empty, governance-validated, multi-source,
  source combination. Missing: an element with empty `sources` list
  yields the `"(none)"` sentinel key.
- `TestConfidenceStats` (3) — empty, arithmetic, buckets. Missing:
  exact boundary values (a confidence of exactly 0.5 must land in
  "0.5-0.7", not "0.0-0.5"; same for 0.7 and 0.9).
- `TestConflictStats` (2) — no conflicts, breakdown. Missing:
  multiple conflicts on the same element (`elements_with_conflicts`
  should still be 1).
- `TestAnchorCoverage` (2) — all-unanchored, mixed. Missing:
  per-field aggregation across multiple elements.
- `TestCorroborationStats` (2) — no tracking, distribution. Missing:
  the count==0 edge case (does it fall into 3+ or is it a bug?).
- `TestProfileCoverage` (4) — no profile, zero, partial, case-
  insensitive predicate. Missing: explicit subtype-coverage test
  (DirectMetric appears, Metric reported as covered).
- `TestMarkdownRender` (3) — empty, all sections, profile section.
  Missing: a snapshot-style test on the exact output of a known
  report (catches accidental shape changes).
- `TestReportIsReadOnly` (1) — only one test. Missing: read-only
  check on field_provenance; on conflicts.
- `TestCli` (5) — markdown stdout, JSON output, markdown file,
  with-profile, missing-file. Missing: `--domain-dir` integration
  (log entry + file-back behaviour).

---

## 6. Eight specific questions I want direct answers to

1. **Does the no-profile / no-report path produce JSON byte-
   identical to commit `1a9310a`?** Run pytest on master, then on
   this branch — verify the +26 / +0 delta. Confirm by reading the
   diff that no pre-Phase-7 file other than `cli.py` was modified
   (and that the `cli.py` change is purely additive: one new
   `@app.command()` block).

2. **Are the six sections the right set?** Are any missing (e.g.
   relationship density, source-coverage ratio, lint-finding
   counts), are any redundant?

3. **Are the bucket boundaries correct?** Specifically: do exact
   boundary values (0.5, 0.7, 0.9 for confidence; 1, 2, 3 for doc
   count) land in the intended buckets per the docstring's
   stated semantics?

4. **Is anchor coverage at the FieldProvenance level the right
   aggregation?** Or should it be per-element (% of elements with
   any anchor) or per-field (% of definition fields with anchor)?

5. **Is profile coverage subtype-aware in the right way?** A
   parent type with no direct usage but used subtypes counts as
   covered — does this match how a domain expert would think
   about coverage?

6. **Does the markdown render contain enough for a quick review?**
   Or is there a shape (a table column, a sub-heading) you'd add /
   remove?

7. **Does the CLI surface follow existing patterns?** Compare
   `report` to `validate` / `lint` / `query`. Are the flag names
   consistent? Is `--markdown` the right name (vs `--md`)?

8. **What's the one thing most likely to bite us when Phase 7
   gets used in anger?** (E.g. the bucket boundaries on a domain
   where confidences cluster at 0.85; the AC1 contract under a
   future Phase 7.1 that adds a section computer that DOES need
   mutation.)

---

## 7. What the review output should look like

Write your review to `docs/REVIEW_PHASE_7.md` in this repo.

```markdown
# Phase 7 Review — Benchmark Metrics + Reporting

## Verdict
One paragraph: is this ready to merge to master and call the 7-phase
PRD upgrade complete, or does something need to change first?

## What works well
Specific wins. Brief.

## Issues
Numbered list. Severity: blocker / major / minor / nit.

## Answers to the 8 questions in §6
Number them 1–8.

## Recommended changes before the 7-phase upgrade is declared done
Concrete, ordered. Empty list is fine.
```

3 pages is fine. Don't over-write.

---

## 8. House rules

- **Run `pytest -q` first.** 593 passed + 14 skipped on the branch,
  567 + 14 on master. Delta `+26 passed, +0 skipped`. If different,
  stop and report.
- **Read `docs/PROFILE_SPEC.md`** if anything about the profile
  schema is unclear — it's still the contract.
- **Run `ontozense report` by hand** if you can: pick any existing
  fused JSON (e.g. from a prior fuse run), execute
  `ontozense report fused.json --output report.json --markdown
  report.md` (optionally with `--profile docs/profile-examples/esg`),
  and inspect the output. Markdown should be a clean digest;
  JSON should round-trip through `json.dumps(json.loads(...))`.
- **Trace the AC1 read-only contract** for each of the six section
  computers. This is the load-bearing piece — Phase 7's whole
  premise is "compute, don't mutate."
- **Cite `file_path:line_number`** for every issue.
- **Severity matters.** Blocker = blocks the 7-phase upgrade
  declaration. Major = should fix before merge. Minor = follow-up.
  Nit = optional.
- **Do not propose features that aren't in the PRD.** Phase 7 is
  scoped tight; reference-benchmark mode and time-series viz are
  explicitly deferred.

---

Thank you. **This is the final review of the 7-phase PRD upgrade.**
The AC1 read-only contract from §5.9 and the profile-coverage
subtype logic from §5.6 are the load-bearing pieces — focus there.
