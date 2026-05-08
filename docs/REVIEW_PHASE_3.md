# Phase 3 Review — Profile-Aware Sources B, C, D

## Verdict
Not ready to merge yet. Backward compatibility is intact and Source B/C core wiring is mostly correct, but Source D has a load-bearing inference defect: multi-word profile types (typical PascalCase types like `ReportingFramework` / `CustomerIdentifier`) are not matched reliably from code-style snake-case rule names, and can be silently mis-attached to a broader type. That is a blocker for Phase 4 because validation will trust these attachments.

## What works well
- Baseline gate passes exactly: `2236b6f` => `475 passed, 10 skipped`; `master@5551925` => `459 passed, 10 skipped`.
- Baseline test integrity is preserved: only one new test file was added (`tests/test_phase3_sources_bcd_profile.py`), no existing tests changed.
- No-profile AC1 behavior is preserved across B/C/D via targeted tests (`tests/test_phase3_sources_bcd_profile.py:47`, `tests/test_phase3_sources_bcd_profile.py:190`, `tests/test_phase3_sources_bcd_profile.py:255`).
- Hand-check cross-source alignment for the same tuple works for B and C: `(Concept, Concept)` produced identical IDs and matched `compute_id(...)`.
- Governance bool coercion still behaves correctly in profile mode (`is_critical="Yes"` becomes `True`) (`src/ontozense/extractors/governance_extractor.py:170`).

## Issues
1. **blocker** — Source D heuristic fails for common multi-word type names and can silently attach to the wrong type.
   - `known_types` keys are raw lowercased type names (e.g. `customeridentifier`) (`src/ontozense/extractors/code_extractor.py:624`).
   - Prefix candidates from rule names are underscored tokens (e.g. `customer_identifier`) (`src/ontozense/extractors/code_extractor.py:679`, `src/ontozense/extractors/code_extractor.py:681`).
   - Direct lookup compares underscored candidate to non-underscored keys (`src/ontozense/extractors/code_extractor.py:682`), so `CUSTOMER_IDENTIFIER_THRESHOLD` misses `CustomerIdentifier`. If `Customer` also exists, fallback can wrongly attach to `Customer`.
   - This is not currently covered: tests only exercise single-word type `Concept` for name-prefix matching (`tests/test_phase3_sources_bcd_profile.py:298`).

2. **major** — Governance type validation is case-sensitive while ID generation is case-insensitive, causing false unknown-type warnings for semantically equivalent types.
   - Type check uses `is_known_type(record.entity_type)` (`src/ontozense/extractors/governance_extractor.py:223`), which is case-sensitive in `Profile.get_entity_type()` (`src/ontozense/core/profile.py:131`).
   - `compute_id()` lowercases type internally (`src/ontozense/core/identity.py:134`).
   - Result: `entity_type="concept"` is warned as unknown but yields the same ID as `Concept`, producing noisy quarantine signals that can mislead Phase 4.

3. **minor** — No profile-aware SQL-path tests for Source D.
   - `CodeExtractor` applies profile inference to both `.py` and `.sql` outputs (`src/ontozense/extractors/code_extractor.py:590`, `src/ontozense/extractors/code_extractor.py:603`).
   - Phase 3 tests for Source D only use Python fixtures (`tests/test_phase3_sources_bcd_profile.py:250`) and do not assert attachment behavior for `sql_view` / `sql_where` / `sql_check`.

## Answers to the 8 questions in §6
1. **Does the no-profile path produce byte-identical output to commit `5551925`?**
   - Yes, based on the assignment gates: `master@5551925` = `459 passed, 10 skipped`; `2236b6f` = `475 passed, 10 skipped`, with only one added test file and no modified baseline tests.

2. **Is Source D's heuristic sound for realistic codebases?**
   - Not fully. The longest-prefix loop itself is implemented in the right direction (`n -> 1`) (`src/ontozense/extractors/code_extractor.py:680`), but normalization is inconsistent (underscored candidates vs non-underscored PascalCase known types), so realistic constants like `REPORTING_FRAMEWORK_LIMIT` fail to attach, and `CUSTOMER_IDENTIFIER_THRESHOLD` can mis-attach to `Customer`.

3. **Is Source C field ID collision (`:` normalizes) a real defect or acceptable?**
   - Acceptable for current realistic scope. Django model classes must have distinct names and fields must be unique per model; with `id_type` scoped per model/entity and label containing model+field (`src/ontozense/extractors/django_schema.py:215`), practical collisions are low-risk. The colon normalization is somewhat fragile but not a merge blocker in this phase.

4. **Is cross-source ID alignment contract strong enough for Phase 5?**
   - Strong enough for B/C when `(type,label)` truly matches; I verified by hand for `(Concept, Concept)` using direct `compute_id` plus B/C outputs.
   - Most likely divergence: type-string drift and heuristic drift, especially Source D inferred types and governance type casing/pluralization.

5. **Should `SchemaRelationship` gain id/entity_type now?**
   - Out of scope for Phase 3. Current scope is entity-like outputs in B/C/D; relationship-level profile fields can be deferred to a later phase if Phase 5/6 proves they are needed.

6. **Should SQL extraction get profile-aware tests?**
   - Yes. Not a blocker by itself, but should be added pre-merge or immediately after merge as targeted regression protection for Source D profile mode on SQL artifacts.

7. **Are validation paths in `governance_extractor._apply_profile` complete? Most likely missed authoring mistake?**
   - Not complete. Most likely missed real-world mistake: casing variance in `entity_type` values from governance JSON (`concept` vs `Concept`) being treated as unknown even though IDs normalize to the same value.

8. **One thing most likely to bite in Phase 4 due to Phase 3 shape?**
   - Silent mis-attachment in Source D due to heuristic normalization mismatch for multi-word types. This will produce structurally valid but semantically wrong attachments that Phase 4 may not catch if the wrong attached type is still “known”.

## Recommended changes before Phase 4 starts
1. Fix Source D matching normalization in `_infer_entity_type`: compare normalized forms consistently (e.g., normalize both known type keys and candidates with the same canonicalizer) so snake-case rule names match PascalCase profile types reliably.
2. Add tests proving correct/incorrect disambiguation for overlapping types (e.g., `Customer` vs `CustomerIdentifier`) and multi-word types (e.g., `ReportingFramework`) in Source D.
3. Make governance `entity_type` validation case-insensitive (or canonicalize before lookup), while preserving canonical case in output.
4. Add profile-aware SQL tests for Source D (`sql_view`, `sql_where`, `sql_check`) to close the current test gap.
