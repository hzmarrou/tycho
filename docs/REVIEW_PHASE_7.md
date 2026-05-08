# Phase 7 Review — Benchmark Metrics + Reporting

## Verdict
Phase 7 is functionally ready to merge to `master`, with one minor robustness caveat. I re-ran the gate on a clean clone: `master@1a9310a` = **567 passed, 14 skipped** and `feat/phase-7-benchmark-metrics@a8f5939` = **593 passed, 14 skipped** (delta **+26 / +0**). Diff scope is clean: only one additive `report` command in `src/ontozense/cli.py`, plus new `src/ontozense/core/benchmark.py` and `tests/test_phase7_benchmark.py`. AC1 (read-only benchmark computation) holds in current code, including nested `field_provenance` and `conflicts` structures. The only issue I found is corroboration bucket handling for invalid zero/negative counts.

## What works well
- Strong, typed report shape: six focused sections with sensible defaults and JSON-safe serialization (`src/ontozense/core/benchmark.py:49`, `src/ontozense/core/benchmark.py:117`).
- AC1 is honored in implementation: section computers read from fused structures without mutating sources, fields, conflicts, or extra fields (`src/ontozense/core/benchmark.py:159`, `src/ontozense/core/benchmark.py:173`, `src/ontozense/core/benchmark.py:201`, `src/ontozense/core/benchmark.py:214`, `src/ontozense/core/benchmark.py:237`, `src/ontozense/core/benchmark.py:257`).
- Profile coverage logic correctly includes subtype-aware entity coverage and case-insensitive predicate matching (`src/ontozense/core/benchmark.py:274`, `src/ontozense/core/benchmark.py:283`, `src/ontozense/core/benchmark.py:301`).
- CLI surface is coherent with existing verbs and behavior; `--profile`, `--output`, `--markdown`, and `--domain-dir` are practical and consistent (`src/ontozense/cli.py:1454`).

## Issues
1. **Minor** — Corroboration `count == 0` (or negative) is currently misclassified as `"3+_docs"`.
   - Evidence: `_compute_corroboration_stats()` treats any non-`1`/`2` value as `3+` via the `else` branch (`src/ontozense/core/benchmark.py:248`, `src/ontozense/core/benchmark.py:252`).
   - Impact: malformed or hand-edited fused JSON can overstate corroboration strength.
   - Fix: treat `count >= 3` as `3+`, and ignore or explicitly track invalid `count <= 0` values.

2. **Nit** — No regression test currently pins the invalid corroboration-count edge.
   - Evidence: corroboration tests cover `1`, `2`, `3`, and `7`, but not `0`/negative (`tests/test_phase7_benchmark.py:244`).
   - Impact: future refactors may keep or reintroduce the mis-bucket behavior unnoticed.

## Answers to the 8 questions in §6
1. **No-profile/no-report backward compatibility:** Yes. Baseline test gate met exactly (`567/14` on `master`, `593/14` on branch, delta `+26/+0`). Diff confirms only `cli.py` changed among existing files, and that change is one additive `@app.command()` block for `report`.
2. **Are the six sections the right set?** Yes. They are non-redundant, map to reviewer-facing health questions, and match Phase 7 scope. Validation embedding remains correctly separate per prior decision.
3. **Are bucket boundaries correct?** Confidence boundaries are implemented correctly for exact `0.5`, `0.7`, `0.9` in intended buckets (`src/ontozense/core/benchmark.py:189`). Corroboration boundaries are correct for `1`, `2`, `>=3`, but invalid `0` currently falls into `3+` (minor issue above).
4. **Is FieldProvenance-level anchor aggregation right?** Yes. It is the right primary aggregation for Phase 6 anchor quality and includes useful per-field breakdown (`src/ontozense/core/benchmark.py:221`).
5. **Is subtype-aware profile coverage right?** Yes. Parent type coverage via used subtypes matches expert expectations (e.g., `Metric` covered by `DirectMetric`) (`src/ontozense/core/benchmark.py:276`, `src/ontozense/core/benchmark.py:301`).
6. **Does markdown render contain enough?** Yes. It is review-friendly, includes all critical sections, and conditionally includes profile coverage only when applicable (`src/ontozense/core/benchmark.py:320`).
7. **Does CLI follow existing patterns?** Yes. Flag names and flow are consistent with `validate`/`lint` patterns, and `--markdown` is clearer than `--md` (`src/ontozense/cli.py:1475`).
8. **Most likely thing to bite in production:** invalid `corroborating_doc_count` values being silently reported as strong corroboration (`3+_docs`) (`src/ontozense/core/benchmark.py:252`).

## Recommended changes before the 7-phase upgrade is declared done
1. Harden `_compute_corroboration_stats()` so only `count >= 3` maps to `3+_docs`, and invalid `count <= 0` does not inflate corroboration.
2. Add one regression test for `count == 0` (and ideally negative) to lock this behavior.

