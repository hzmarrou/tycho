# Phase 6 Review — Provenance Granularity

## Verdict
Ready to merge to `master` and proceed to Phase 7.

Recheck target: `089a1f1` on `feat/phase-6-provenance-granularity`.

Baseline/recheck gate passed:
- `master@c6477cf`: `548 passed, 14 skipped`
- `branch@089a1f1`: `567 passed, 14 skipped`
- Delta: `+19 passed, +0 skipped`

The three prior findings are fixed and pinned by targeted regressions.

## What works well
- Source B additive citation merge now preserves existing Source A citation anchor instead of dropping it (`src/ontozense/core/fusion.py:424-444`).
- Source A anchor builder now strips whitespace and treats whitespace-only section/snippet as empty, preventing synthetic anchors (`src/ontozense/core/fusion.py:790-807`).
- `test_frozen` is now specific and checks `FrozenInstanceError` directly (`tests/test_phase6_provenance_anchors.py:95-100`).
- Targeted verification command passes all four intended tests:
  - `TestConflictWinnerAnchor::test_source_b_citation_merge_preserves_source_a_anchor`
  - `TestSourceAAnchorThreading::test_whitespace_only_section_is_treated_as_empty`
  - `TestSourceAAnchorThreading::test_section_is_stripped_when_real_content_present`
  - `TestFieldAnchorShape::test_frozen`

## Issues
None remaining (prior major/minor/nit are closed in `089a1f1`).

## Answers to the 8 questions in §6
1. **No-profile / no-anchor byte-identity vs `c6477cf`?**
Yes for the load-bearing conflict shape. In no-anchor conditions, serialized conflict provenance remains `{source, value}` with no `anchor` key; baseline gate also passes.

2. **Is the 8-field `FieldAnchor` shape right?**
Yes for Phase 6 scope. No new design change landed in `089a1f1`; nothing new to push back on.

3. **Is `is_empty()` correct?**
Yes in current behavior, and whitespace input handling now avoids false non-empty anchors via pre-strip normalization in Source A mapping.

4. **Is Source A → FieldAnchor mapping right?**
No new mapping design changed in the fix commit; behavior is now cleaner due to strip/empty handling and remains acceptable for Phase 6 scope.

5. **Is keeping `_anchor_from_code_provenance` non-threaded helper the right call?**
No change from prior accepted scope. Still reasonable as a documented deferred hook.

6. **Does conflict resolution preserve winner’s anchor across paths?**
Yes for the previously failing additive citation path after fix (`fusion.py:424-444`), and targeted regression now enforces it.

7. **Does JSON round-trip preserve anchor data?**
Yes. Existing Phase 6 round-trip tests still pass, and the recheck introduced no regressions.

8. **Most likely Phase 7 risk from current shape?**
No new Phase 6 blocker after fixes. The main Phase 7 consideration remains reporting-layer consumption of anchors, not fusion correctness.

## Recommended changes before Phase 7 starts
1. Merge `feat/phase-6-provenance-granularity`.
2. Keep the three new regression tests as permanent guardrails.
3. In Phase 7 reporting work, explicitly decide how anchor-rich provenance appears in benchmark outputs (tables/JSON summaries) so the new anchor signal is actually surfaced.
