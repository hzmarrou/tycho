# Re-verification prompt — round-4 fixes (Tycho)

Paste everything below this line into GPT 5.5.

---

You reviewed two commits on Tycho — `abeea81` (typed BusinessRule)
and `8103235` (reference-benchmark mode) — and flagged three
majors plus one minor in your last review. This is a quick
re-verification: confirm each repro is now closed.

The fix landed on `https://github.com/hzmarrou/tycho` (branch
`main`) at commit **`9e856d3`** with message
*"fix: address GPT 5.5 round-4 review (BusinessRule + reference)"*.

## What changed

| Your finding | Fix in `9e856d3` |
|---|---|
| **Major** — Relationship matching ignored profile-mode IDs | New `_build_endpoint_resolver(elements)` builds a per-side `normalised-name → match-key` map; `_rel_key()` now resolves endpoints through it so ID-aware identity applies to relationships. Falls back to normalised names when an endpoint has no ID. |
| **Major** — Unconstrained element matching falsely matched different-type entities sharing a name | `_element_match_key()` resolution order now: `id` → `name:type:name` → `name:name`. Type qualifies the fallback when at least one side declares `entity_type`. Plain-name match remains for fully typeless legacy payloads. |
| **Major** — `--reference` validated JSON syntax but not shape; `{"elements":[123]}` crashed with AttributeError | New `ReferenceContractError` exception + `validate_reference_shape()` function in `core.benchmark`. Called BEFORE `_reconstruct_fusion_result`. CLI catches it separately and prints a clean message. Mirrors the `SourceCContractError` pattern. |
| **Minor** — `BusinessRule.value` flattened to `str()` | `BusinessRule.value` annotation changed to `Optional[Any]`; `_build_business_rule()` no longer calls `str()`. Original `int` / `bool` / `list` / `dict` types preserved. |

## Files to look at

1. `src/ontozense/core/benchmark.py`:
   - `_element_match_key()` — type-qualified fallback (new lines)
   - `_build_endpoint_resolver()` — new helper
   - `_rel_key()` inside `_compute_reference_comparison` — now uses resolver
   - `ReferenceContractError` class + `validate_reference_shape()` function
2. `src/ontozense/cli.py` — search for `validate_reference_shape`; the
   `report` command now calls it before reconstruction and catches
   `ReferenceContractError` separately.
3. `src/ontozense/core/fusion.py`:
   - `BusinessRule.value: Optional[Any]` (was `Optional[str]`)
   - `_build_business_rule()` — no more `str()` cast on value
4. `tests/test_phase7_benchmark.py`:
   - `TestRound4ReviewRegressions` — 8 tests covering all three majors
   - `TestCliReferenceFlag::test_structurally_malformed_reference_clean_error`
5. `tests/test_business_rules.py`:
   - `TestQueryRendering::test_value_preserves_non_string_types`
   - Updated `test_code_rule_with_provenance_yields_anchored_business_rule`
     now asserts `isinstance(br.value, int)`.

## Verify these specific things

1. **Run the focused regressions:**
   ```bash
   pytest tests/test_phase7_benchmark.py::TestRound4ReviewRegressions tests/test_business_rules.py::TestQueryRendering::test_value_preserves_non_string_types -v
   ```
   You should see all 9 PASSED. (8 in the regression class + 1 value-preservation.)

2. **Reproduce your three majors against `9e856d3`** to confirm
   they no longer reproduce:
   - Different-type same-name elements: a fused Rule "Default" + a
     reference Concept "Default" should now produce TP=0, FP=1, FN=1
     (not TP=1).
   - Same endpoint IDs, different endpoint names in relationships:
     should now produce TP=1 for the relationship layer (not TP=0).
   - `{"elements":[123],"relationships":[]}` as a `--reference`
     payload: should exit 1 with a clean message containing
     `"Reference JSON contract error"` and `"elements[0] must be an
     object"` (not an AttributeError traceback).

3. **Sanity check the minor:** a `CodeRule(value=90)` (int) should
   now produce a `BusinessRule` whose `.value == 90` and
   `isinstance(.value, int)` — not `"90"`.

4. **Baseline gate** — full suite on `9e856d3` should be
   `671 passed, 14 skipped` (was 661+14 on `8103235`, so the delta
   is **+10 / +0**, all from the new regression / verification
   tests).

## Output format

Short reply this time, ~1 page:

```
## Verdict
"Cleared, round-4 fixes verified" / "Still some concern: …"

## Verified
For each of the four findings: confirm fixed (with the test name
or the manual repro you re-ran).

## Anything outstanding
n/a is fine.
```

If you can't access the repo at commit `9e856d3`, say so up front.
