# Phase 5 Review — Resume Instructions

**To the reviewer:** thank you for halting at the baseline gate and
documenting the discrepancy in `docs/REVIEW_PHASE_5.md`. You did
exactly the right thing — the assignment specified an exact count
and your env produced a different one. Halting was the correct call.

The discrepancy was **not a Phase 5 defect**. It was a pre-existing
hardcoded developer-only Windows path in `tests/test_npl_pipeline.py`
that resolved on the original developer's Windows machine but
skipped silently in any other environment. That issue is now fixed
upstream of Phase 5.

This document tells you what to do next.

---

## What changed since you halted

| Commit | Branch | What it does |
|---|---|---|
| `986ad76` | master | chore: replaces the hardcoded Windows path in `tests/test_npl_pipeline.py:150` with an `ONTOZENSE_COMBINED_EXTRACTION_JSON` env var. When unset (which is the case in CI / clean-checkout review envs), the four `TestConvertExistingExtraction` tests skip deterministically on every OS. |
| `11c2559` | feat/phase-5-fusion-consolidation | merge of `986ad76` into the branch. |
| `84eb9e0` | feat/phase-5-fusion-consolidation | updates `docs/REVIEW_ASSIGNMENT_PHASE_5.md` — new gate counts (518 / 14 master, 538 / 14 branch), branch HEAD pointer, and a §2 note explaining the chore fix. The gate is now framed around the **+20 passed / +0 skipped delta** between master and branch, so it's env-resilient. |

The Phase 5 implementation itself (engine + CLI + new tests) is
**unchanged**. Only the assignment document and the test-fixture
plumbing changed.

---

## What you do now

### Step 1 — Re-baseline (fast)

```bash
git fetch
git checkout master                                 # at 986ad76
pytest -q                                           # → 518 passed, 14 skipped

git checkout feat/phase-5-fusion-consolidation      # at 84eb9e0 (or later)
pytest -q                                           # → 538 passed, 14 skipped
```

If your env produces those exact numbers, the gate is met and you
can proceed. If your env produces different absolute numbers but
the **delta** between master and branch is `+20 passed, +0 skipped`,
the gate is also met (any pre-existing fixture-detection difference
on your host is acceptable as long as it shifts both branches by
the same amount). Anything else is a halt.

### Step 2 — Run the full scoped Phase 5 review

Open `docs/REVIEW_ASSIGNMENT_PHASE_5.md` (now refreshed at `84eb9e0`)
and execute the review as specified there. Sections to cover:

- **§4** — three architectural decisions to push back on (dual-key
  strategy, composite-key id-collision handling, repeatable
  `--source-a` CLI shape)
- **§5** — six specific things to evaluate, in particular:
  - 5.1 dual-keyed index and the four cases of `_get_or_create`
  - 5.2 corroboration tracking edge cases
  - 5.3 cross-source id-first lookup for B/C/D
  - 5.4 AC1 byte-identity under the new `extra_fields` keys
  - 5.5 CLI shape of repeatable `--source-a`
  - 5.6 test coverage gaps
- **§6** — answer all 8 specific questions

### Step 3 — Write the verdict

Replace the contents of `docs/REVIEW_PHASE_5.md` (which currently
contains your halt report) with the full review using the §7
template:

```markdown
# Phase 5 Review — Fusion Consolidation

## Verdict
One paragraph. Ready to merge to master and proceed to Phase 6,
or what needs to change first?

## What works well
Specific wins. Brief.

## Issues
Numbered list. Severity: blocker / major / minor / nit.
Cite file_path:line_number for every issue.

## Answers to the 8 questions in §6
Number them 1–8.

## Recommended changes before Phase 6 starts
Concrete, ordered.
```

3 pages is fine. Don't over-write.

---

## Notes for this round

- **Load-bearing pieces** the assignment flags for focused attention:
  - `_get_or_create`'s four-case logic (esp. the id-collision
    composite-key handling — distinct profile-mode entities sharing a
    normalised name must stay separate)
  - AC1 under the new `extra_fields["source_documents"]` /
    `corroborating_doc_count` keys (additive in profile mode +
    multi-doc — should not affect any pre-existing test, but worth
    spot-checking pre-Phase-5 fusion tests that assert `extra_fields`
    literally)
  - VR006-style cardinality-of-edge-cases reasoning for the
    consolidation logic (what should happen with `len(source_a) == 0`,
    `source_a = [empty_result]`, two docs with the same ID but
    different domain_names, etc.)

- **Out of scope**: do not re-review Phases 1–4 or the chore fix in
  `986ad76`. The cross-source ID alignment contract is also
  out-of-scope (already cleared in Phase 3).

- **Format**: the assignment caps the review at three pages.
  Cite `file_path:line_number` for every issue. Severity matters
  (blocker / major / minor / nit). Write to
  `docs/REVIEW_PHASE_5.md` so it's easy to find.

Thank you. Phase 6 is gated on this review.
