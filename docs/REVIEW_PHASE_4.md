# Phase 4 Review — Validation Stage

## Verdict
Ready to merge to master and proceed to Phase 5.

Re-review of `4f13a62` confirms the previously reported filter-mode correctness bug is fixed, baseline compatibility still holds, and the added regression coverage is appropriate for the failure mode.

## What works well
- Baseline gates still hold exactly:
  - `4f13a62`: `522 passed, 10 skipped`
  - `cac424e`: `485 passed, 10 skipped`
- The VR001/VR002/VR004 filter paths now use object identity (`id(...)`) instead of dataclass value-equality, preventing accidental removal of kept rows when duplicates are field-identical.
- Six targeted regression tests were added and pass, including:
  - VR001 identical duplicate and 3-way duplicate cases
  - defensive VR002/VR004 identical-entry cases
  - cascade-from-VR001 behavior
  - filter-mode CLI smoke test
- No changes were made to unconstrained-mode behavior; AC1 remains intact.

## Issues
No blocker/major/minor findings remain for Phase 4 scope.

## Answers to the 8 questions in §6
1. Yes. No-profile path remains byte-identical to `cac424e` under the test gate (`485 passed, 10 skipped`) and baseline tests were not modified/replaced.
2. Yes. The 6 rules match their advertised behavior in code after this fix.
3. Yes. VR006 1:N and N:1 semantics are implemented on the correct sides.
4. Yes. Cascade filtering uses consistent endpoint/ID resolution and behaves correctly in `filter` mode.
5. Yes. `flag` remains the right default for Phase 4; destructive filtering is opt-in.
6. Yes. `--profile` should remain required for validate in this phase.
7. Acceptable for now. `id`/`entity_type` in `extra_fields` remains a reasonable Phase 4 shape.
8. The prior Phase 5 risk (VR001 identical-duplicate drop) is now closed by this fix.

## Recommended changes before Phase 5 starts
1. Merge `feat/phase-4-validation-stage` into master.
2. Keep the new regression tests as mandatory gate coverage for future validation refactors.
