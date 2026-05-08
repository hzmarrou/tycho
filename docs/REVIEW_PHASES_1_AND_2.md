# Phases 1 & 2 Review — Profile System + Constrained Source A

## Verdict
Not ready to merge yet. The core design is viable and most of the implementation is solid, but there is one blocker and several pre-merge majors that directly affect deterministic-ID correctness and constrained-mode reliability under real Phase 3 load. The blocker is that `id_format.hash_length` from profiles is parsed but ignored in Source A ID generation, so users cannot actually mitigate collision risk by increasing hash length. Once that and the listed major validation/UX gaps are fixed, this branch is a good base for Phase 3.

## What works well
- Backward-compat baseline check passes exactly as required: `f2ec344` gives `454 passed, 10 skipped`; `46e2e8d` gives `368 passed, 10 skipped`.
- Baseline test integrity is preserved: no pre-existing tests were modified/replaced; new tests were added only.
- Constrained template generation is generally strong: it includes prompt fragment content, allowed types (including subtypes), allowed predicates, required fields, and unambiguous 3-part concept formatting instructions (`src/ontozense/extractors/domain_doc_extractor.py:205`, `src/ontozense/extractors/domain_doc_extractor.py:251`, `src/ontozense/extractors/domain_doc_extractor.py:285`).
- Alias resolution before ID generation is the correct order for canonical identity collapse (`src/ontozense/extractors/domain_doc_extractor.py:373`, `src/ontozense/extractors/domain_doc_extractor.py:382`).
- Profile authoring from `docs/PROFILE_SPEC.md` is workable; I authored a small “recipe” profile from the spec alone and `load_profile()` accepted it.

## Issues
1. **blocker** — `id_format.hash_length` is ignored during constrained extraction.
   - `load_profile()` parses and stores profile hash length (`src/ontozense/core/profile.py:351`).
   - `_apply_profile()` calls `compute_id()` without passing that hash length (`src/ontozense/extractors/domain_doc_extractor.py:382`), so IDs always use default 6-char suffix (`src/ontozense/core/identity.py:87`).
   - This breaks the profile contract in the spec where hash length is user-configurable (`docs/PROFILE_SPEC.md:84`, `docs/PROFILE_SPEC.md:154`).

2. **major** — profile name is not validated/sanitized before using it in temp filename prefix; constrained mode can fail on Windows for valid JSON profiles.
   - `profile_name` validation only enforces non-empty string (`src/ontozense/core/profile.py:274`).
   - Template generation embeds raw `profile_name` in `NamedTemporaryFile(prefix=...)` (`src/ontozense/extractors/domain_doc_extractor.py:320`).
   - In Windows probing, names containing `*`, `|`, `<`, `>`, `?`, `"`, `/`, `\` fail with `OSError`/`FileNotFoundError` at extractor construction time.

3. **major** — schema validation misses subtype/type-name collisions, producing ambiguous type resolution.
   - Entity parsing accepts both top-level type names and subtype lists without collision checks (`src/ontozense/core/profile.py:287`).
   - Type lookup returns first match (name or subtype) (`src/ontozense/core/profile.py:130`), so a top-level type can be shadowed by another type’s subtype name.
   - Probe example: top-level `DirectMetric` plus `Metric.subtypes=["DirectMetric"]` resolves `get_entity_type("DirectMetric")` to `Metric`, not `DirectMetric`.

4. **major** — CLI clean-error path does not handle unreadable profile files/directories.
   - `load_profile()` only wraps JSON decode errors for schema parsing (`src/ontozense/core/profile.py:215`), but file permission/IO errors can raise raw `OSError`.
   - CLI catches only `ProfileError` during profile loading (`src/ontozense/cli.py:377`), so unreadable-path cases can bypass the clean UX and surface traceback/fatal exception behavior.

5. **minor** — profile frozen-ness is shallow, not deep.
   - `@dataclass(frozen=True)` is used (`src/ontozense/core/profile.py:101`), but nested structures are mutable dictionaries/lists (`src/ontozense/core/profile.py:112`, `src/ontozense/core/profile.py:115`), so callers can mutate profile state after load.
   - This is a determinism risk once one profile instance is shared across multiple extractor paths in Phase 3.

6. **minor** — constrained parser preserves `::` inside definitions but collapses spacing around delimiters.
   - In constrained mode, concept parsing strips each split segment (`src/ontozense/extractors/domain_doc_extractor.py:569`) and rejoins extras with bare `"::"` (`src/ontozense/extractors/domain_doc_extractor.py:577`), changing text like `"a :: b"` to `"a::b"`.
   - Not correctness-critical for IDs, but it can degrade definition readability.

## Answers to the 8 questions in §6
1. **Does the no-profile path produce byte-identical output to commit `46e2e8d`?**
   - Baseline test gate passes exactly: `368 passed, 10 skipped` on `46e2e8d`, `454 passed, 10 skipped` on `f2ec344`.
   - Baseline tests were not modified/replaced (only new tests were added in this branch).
   - `TestUnconstrainedUnchanged` passes and explicitly verifies new fields stay empty in no-profile mode (`tests/test_extract_a_constrained.py:254`).
   - Conclusion: within the test-locked surface, yes.

2. **Is `compute_id` hash length of 6 sufficient for 5,000 entities?**
   - With 24-bit space (`16^6 = 16,777,216`), expected collision pairs are approximately `m(m-1)/(2N) = 0.7449` for `m=5000`.
   - Approximate probability of at least one collision is `1 - exp(-0.7449) ≈ 52.5%`.
   - At 8 hex chars (32-bit), expected collision pairs drop to `0.00291`, with approximately `0.29%` probability of at least one collision.
   - Conclusion: default 6 is risky at this scale; default 8 is safer.

3. **Is `Profile` deeply frozen enough for Phases 3–7?**
   - No. Frozen dataclass is shallow in this implementation (mutable nested dict/list fields).
   - Recommendation: freeze nested maps/lists at load-time (e.g., mapping proxies / immutable containers) before Phase 3 parallel extractor consumption.

4. **Is generated LinkML template effective at constraining the LLM?**
   - Mostly yes. It clearly carries profile prompt, allowed entity types/subtypes, allowed predicates, required-field reminders, and explicit 3-part concept format guidance (`src/ontozense/extractors/domain_doc_extractor.py:244`).
   - The load-bearing constrained prompt path is sound.

5. **Does the 3-part parser handle edge cases?**
   - TYPE omitted: yes, 2-part fallback engages and `entity_type=""` (`src/ontozense/extractors/domain_doc_extractor.py:579`).
   - `::` inside definition: yes, parser keeps content, but spacing around internal `::` is normalized away (`src/ontozense/extractors/domain_doc_extractor.py:577`).
   - Unknown TYPE: accepted silently; no type validation at extraction-time, ID still computed if non-empty (`src/ontozense/extractors/domain_doc_extractor.py:380`).
   - Subtype TYPE (e.g., `DirectMetric`): accepted (no early rejection); consistent with Phase 2 defer-to-validation design.

6. **Are `profile.py` validation paths complete? Most likely missed authoring mistake?**
   - Not complete.
   - Most likely missed mistake: overlap between `required` and `optional` fields in an entity spec is not checked (`src/ontozense/core/profile.py:292`). This is a realistic copy/paste error and currently loads silently.
   - Additional missed checks: subtype/type-name collisions and profile-name path-safety.

7. **Will Phase 3 hit walls because of current Phase 1+2 shape?**
   - The overall shape is good enough for Phase 3 (profile object, concept fields, constrained template approach).
   - However, the ignored `hash_length` and validation gaps will cause avoidable reliability problems once B/C/D start producing larger combined entity sets.

8. **One thing most likely to bite in Phase 3 due to Phase 2 shape?**
   - Deterministic ID quality under load: with default 6-char hashes and no actual use of profile-configured `hash_length`, cross-source consolidation can merge distinct entities by collision with no available profile-level mitigation.

## Recommended changes before Phase 3 starts
1. Fix `_apply_profile()` to pass `self.profile.id_format.hash_length` into `compute_id()`, and add tests proving 6/8/custom lengths propagate.
2. Validate/sanitize `profile_name` for filesystem-safe temp-template prefixes on Windows (or sanitize in template generation), with tests for illegal characters.
3. Add profile-schema validation for:
   - overlap between `required` and `optional`
   - subtype names colliding with top-level entity type names
4. Broaden profile-load error handling in CLI so `PermissionError`/`OSError` still produce clean tester-facing errors (no traceback path).
5. Harden profile immutability (deep freeze nested maps/lists) before Source B/C/D share profile state in parallel paths.
6. Optional polish: preserve spacing around literal `::` inside definition text in constrained parser to avoid readability degradation.
