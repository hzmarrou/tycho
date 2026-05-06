# Phase 6 Review — Recheck Instructions

**To the reviewer:** thank you for the thorough review at
`2786e03`. Your three findings (Source B citation anchor loss,
whitespace-only anchors, broad exception in `test_frozen`) all
landed correctly. They've been addressed in commit `089a1f1` on
the same branch. Your previous review checkout is one commit
behind — please re-fetch and re-verify.

---

## What changed since your review

| Commit | What it does |
|---|---|
| `2786e03` | The commit you reviewed. Phase 6 review assignment doc. |
| `089a1f1` | **New.** Addresses all three findings: preserves Source A's anchor in the `_merge_source_b` additive citation branch; strips whitespace from `source_section` / `source_text_snippet` before anchor creation in `_anchor_from_concept_provenance`; tightens `test_frozen` to assert `FrozenInstanceError` specifically. Adds 3 new regression tests in `tests/test_phase6_provenance_anchors.py` — including `test_source_b_citation_merge_preserves_source_a_anchor` which pins the major finding. |

The Phase 6 implementation shape is otherwise unchanged. No new
architectural decisions; no new design surface to evaluate.

---

## What you do now

### Step 1 — Re-baseline (fast)

```bash
git fetch
git checkout master                                   # at c6477cf
pytest -q                                             # → 548 passed, 14 skipped

git checkout feat/phase-6-provenance-granularity      # at 089a1f1
pytest -q                                             # → 567 passed, 14 skipped
```

The branch gate is now `567 passed, 14 skipped` (was 564 before
the fix landed — the +3 are the new regression tests). The delta
between master and branch is `+19 passed, +0 skipped`, matching
the 19 total Phase 6 tests.

If your env produces different absolute numbers but the same
**+19 passed / +0 skipped** delta between master and the branch,
the gate is met.

### Step 2 — Verify the three fixes

Each finding has a dedicated regression test you can run by name:

```bash
pytest tests/test_phase6_provenance_anchors.py -v -k 'preserves_source_a_anchor or whitespace_only or stripped_when_real or test_frozen'
```

You should see four PASSED:
- `TestConflictWinnerAnchor::test_source_b_citation_merge_preserves_source_a_anchor`
  → pins the major fix (citation merge preserves A's anchor).
- `TestSourceAAnchorThreading::test_whitespace_only_section_is_treated_as_empty`
  → pins the minor fix (whitespace returns no anchor).
- `TestSourceAAnchorThreading::test_section_is_stripped_when_real_content_present`
  → pins that real content with surrounding whitespace is stripped
  cleanly.
- `TestFieldAnchorShape::test_frozen` (now using `FrozenInstanceError`).

You can also eyeball the fixes directly:
- `src/ontozense/core/fusion.py:424-444` — the citation merge now
  reads `existing.anchor` and threads it into the new combined
  `FieldProvenance(source="A+B", ..., anchor=existing.anchor)`.
- `src/ontozense/core/fusion.py:790-800` — section/snippet are
  stripped before the existence check; whitespace-only inputs
  return None.

### Step 3 — Update the verdict

If the fixes look right and the regressions hold, replace
`docs/REVIEW_PHASE_6.md` with the cleared-to-merge verdict using
the §7 template from the original assignment:

```markdown
# Phase 6 Review — Provenance Granularity

## Verdict
Ready to merge to master and proceed to Phase 7.

## What works well
…

## Issues
None remaining (prior major / minor / nit fixed in 089a1f1).

## Answers to the 8 questions in §6
1–8.

## Recommended changes before Phase 7 starts
…
```

If anything is still off, flag it as a new finding and we'll iterate.

---

## Notes for this round

- **In scope**: verify the three fixes hold under the targeted
  regressions; verify the broader 564 → 567 delta is exactly the
  three new tests and nothing else moved.
- **Out of scope**: re-evaluating the Phase 6 architectural
  decisions you already cleared in your prior review (anchor on
  FieldProvenance, `is_empty()` gate, source A → anchor mapping).
  No new design landed in `089a1f1`.
- **AC1**: still holds. The fix only adds anchor-preservation to
  an existing path; it doesn't change the unanchored output shape.

Thank you. Phase 7 is gated on this re-verification.
