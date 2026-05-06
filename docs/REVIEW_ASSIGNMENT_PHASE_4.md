# Independent Review Assignment — Phase 4: Validation Stage

**Review on:** branch `feat/phase-4-validation-stage` at HEAD `f4a5f5f`
**Repository:** `C:\Users\hzmarrou\OneDrive\python\projects\ontozense`
**Master is at:** `cac424e` (Phase 3 merged after your prior review).
**Not yet merged to master.** Your verdict gates the merge.

---

## 1. Why this review

You cleared Phase 3 last round (`docs/REVIEW_PHASE_3.md`). That gave us
profile-aware Sources B, C, D, with the cross-source ID alignment
contract holding end-to-end. Phase 4 puts a structural validation
stage between fusion and lint, in profile mode only:

| Stage  | Job                                                              |
|--------|------------------------------------------------------------------|
| Fuse   | Combine A/B/C/D into a single rich data dictionary               |
| **Validate** | **Run 6 OntoMetric-inspired structural rules against the profile** |
| Lint   | Higher-level consistency / orphan / coverage analysis            |

The point of Phase 4: catch structural defects (unknown types, missing
required fields, predicate domain mismatches, cardinality violations)
**deterministically and without an LLM**, before any downstream
artifact is produced. Semantic validation (LLM-as-judge) is a deferred
follow-up.

We want to know: **can we merge `feat/phase-4-validation-stage` to
master and confidently start Phase 5 (multi-doc + cross-source
consolidation in fusion)?**

This review is scoped narrowly. We do **not** want re-review of:
- Phases 1–3 (profile loader, identity, constrained Sources A/B/C/D)
- The PRD direction
- The cross-source ID alignment contract (already cleared)

We **do** want a review of:
- Whether the 6 rules (VR001–VR006) implement what their names claim
- Whether `flag` and `filter` modes are correctly distinguished
- Whether cascade filtering does the right thing under filter mode
- Whether the no-profile (unconstrained) path is byte-identical
- Whether subtype matching (used in VR002 and VR005) is consistent
- Whether the CLI surface is well-shaped for downstream tooling
  (lint after validate; consumers of `validation_summary`)

---

## 2. The single most important constraint — verify first

**PRD AC1: no-profile behaviour must be byte-identical.** Non-negotiable.

```bash
# Baseline (post-Phase-3)
git checkout master                          # at cac424e
pytest -q                                     # → 485 passed, 10 skipped

# Branch under review
git checkout feat/phase-4-validation-stage    # at f4a5f5f
pytest -q                                     # → 516 passed, 10 skipped
                                              #   (485 baseline + 31 new)
```

The 485 baseline tests must still pass byte-identical — no test was
modified, replaced, or reordered. If you find a single pre-existing
test whose behaviour or assertion changed, that's a **blocker**.

Phase 4 changes one piece of pre-Phase-4 code: `core/fusion.py` now
threads `concept.id`, `rec.id`, `concept.entity_type`, `rec.entity_type`
into `el.extra_fields["id"]` and `el.extra_fields["entity_type"]` — but
**only when those upstream values are non-empty**, which means
unconstrained-mode FusionResults have empty profile metadata, and any
fusion test that asserts `len(extra_fields) == N` for a no-profile
input is unaffected. Verify this claim by inspecting the diff to
`fusion.py` (≈19 lines, three `setdefault` blocks).

Note on **domain neutrality**: the validation module is profile-driven
and contains no domain-specific terms. Re-verify
`tests/test_domain_neutrality.py` passes anyway.

---

## 3. What landed (your scope)

### Single commit `f4a5f5f` — ~1646 LOC across 4 files, 31 new tests

| File | Change |
|---|---|
| `src/ontozense/core/validation.py` | **New module.** `ValidationFinding`, `ValidationResult` dataclasses. `validate(fusion_result, profile, *, mode)` entry point. Six rule implementations (`_check_vr001…vr006`). Helpers `_entity_id`, `_entity_id_only`, `_fallback_id`, `_resolve_endpoint_id`, `_entity_type_for`, `_is_or_extends`, `_field_value_present`. |
| `src/ontozense/cli.py` | New `validate` command (≈244 lines). Flags: `--profile` (required), `--mode` (`flag`/`filter`, default `flag`), `--output`, `--domain-dir`. Exit code 3 on errors, 1 on bad usage. Output JSON includes `validation_summary` block. |
| `src/ontozense/core/fusion.py` | +19 lines: thread `concept.id`/`rec.id`/`entity_type` into `el.extra_fields` via `setdefault` (Source A wins for id/type). |
| `tests/test_phase4_validation.py` | **New test file.** 31 tests across 9 test classes covering all 6 rules, both modes, cascade filtering, the result API, and CLI integration. |

### Out of scope (deferred)

- **Semantic validation (LLM-as-judge)** — deliberately deferred per
  the agreed Phase 4 scope. The 6 rules in this PR are all
  structural / deterministic.
- **Phase 5** — fusion-time consolidation using deterministic IDs
- **Phase 6** — provenance granularity
- **Phase 7** — benchmark metrics

---

## 4. Three architectural decisions you should evaluate

These were locked before Phase 4 implementation. Tell us if you'd
push back now that you can see them in working code.

### Decision 1 — `flag` is the default mode, not `filter`

Running `ontozense validate fused.json --profile <dir>` without a
`--mode` flag uses `flag`, which annotates findings but never drops
data. To drop, the user must opt in with `--mode filter`.

**Argument for `flag` default:** validate is a diagnostic step. Users
who pipe validate → lint → file-back want to see all findings without
losing data. Filter mode is destructive; making it opt-in matches
Unix conventions (`--force`, `--prune`).

**Argument against:** in CI-like contexts, defaulting to flag means
broken outputs may slip downstream and only fail at lint or beyond.
A `strict` default could catch issues earlier.

**Question:** Is `flag` the right default for Phase 4, or should we
revisit?

### Decision 2 — Validate **requires** `--profile`

There is no fallback "validate without a profile" path. The CLI exits
with code 1 and a clear message when called without `--profile`. The
validation rules are profile-defined; without a profile there is
nothing to validate against.

**Question:** Is this the right contract? An alternative is to allow
profile-less validate that runs only profile-independent checks (e.g.
duplicate-name detection). We chose hard-required; argue if you
disagree.

### Decision 3 — `id` and `entity_type` live in `extra_fields`, not as typed `FusedElement` attributes

`FusedElement` does NOT gain `id` or `entity_type` typed attributes in
Phase 4. Instead, the upstream Source A/B IDs and entity_types are
threaded into `extra_fields["id"]` and `extra_fields["entity_type"]`
during fusion. Validation reads them from there.

**Argument for:** keeps `FusedElement`'s typed shape stable across
constrained and unconstrained modes. AC1 byte-identity is preserved
trivially because `extra_fields` only gains keys when the upstream
values are non-empty (i.e. profile mode).

**Argument against:** `id` is conceptually first-class — having it as
a typed field would make downstream consumers' lives easier. Phase 5
may want this.

**Question:** Should we promote `id` / `entity_type` to typed
`FusedElement` attributes now (in Phase 4) or defer to Phase 5?

---

## 5. Specific things to evaluate

### 5.1 The 6 validation rules — do they match their names?

Read `src/ontozense/core/validation.py` end to end. For each rule,
verify the implementation matches what the docstring claims:

- **VR001 uniqueness** (`_check_vr001_uniqueness`): error per duplicate
  ID. In filter mode, **first occurrence wins**, rest are dropped.
  Verify: what happens if two duplicates have different element_names?
  (See `tests/test_phase4_validation.py:TestVr001Uniqueness`.)
- **VR002 type membership** (`_check_vr002_type_membership`): empty
  entity_type → error; unknown entity_type → error. Subtypes count
  via `profile.is_known_type` (Phase 1 made this case-insensitive).
  Verify: does an empty `extra_fields["entity_type"]` correctly trip
  the "no entity_type" branch?
- **VR003 required fields** (`_check_vr003_required_fields`): warning
  per missing required field. Looks at typed FusedElement attrs first
  (`definition`, `is_critical`, etc.) then in `extra_fields`. Verify:
  is `is_critical: bool = False` correctly counted as "set"?
  (See the `_field_value_present` helper at line ~609.)
- **VR004 predicate vocabulary** (`_check_vr004_predicate_vocabulary`):
  unknown predicate → error. In filter mode, drop the relationship.
  Verify: is the lookup case-insensitive (matching VR002's behaviour)?
- **VR005 predicate domains** (`_check_vr005_predicate_domains`):
  warning if subject/object types don't match the predicate's
  declared domain. Subtype-aware via `_is_or_extends`. Verify: does
  `_is_or_extends` correctly handle the case where `type_name` is a
  subtype's own name (e.g. `"DirectMetric"` and the parent
  `"Metric"` is in `allowed_types`)?
- **VR006 cardinality** (`_check_vr006_cardinality`): four shapes
  (1:1, 1:N, N:1, N:N). The semantics are documented in the rule's
  docstring. **Verify each shape independently** by reading the
  conditional logic at lines ~498 and ~524. Are 1:N and N:1 actually
  the right way around? (1:N = each B traces back to one A; N:1 =
  each A maps to one B.)

### 5.2 Cascade filtering

In `filter` mode, after VR001/VR002 drop entities, any relationship
whose subject or object references a dropped entity must also be
dropped. This is the cascade filter in `validate()` at lines ~163–170.

Specifically check:
- Does the cascade comparison work when a relationship endpoint is an
  entity ID vs an element_name? (See `_resolve_endpoint_id`.)
- What if an entity has no profile-mode `id` (e.g. unconstrained
  fragment that slipped through)? The fallback is `_fallback_id` =
  `normalise_name(element_name)`. Verify both endpoints and surviving
  entities use the same fallback.
- Are `cascade_filtered_relationships` and `cascade_filtered_entities`
  counted correctly when both VR001 AND VR002 drop entities?

### 5.3 The `flag` vs `filter` semantic

- **flag**: no drops. `result.elements == fusion_result.elements` and
  `result.relationships == fusion_result.relationships`. All findings
  are recorded but data flows through unchanged.
- **filter**: VR001 drops duplicate entities, VR002 drops
  unknown-type entities, VR004 drops unknown-predicate relationships,
  AND cascade filter drops dangling relationships.

Verify these by reading `validate()` and the relevant test cases:
`TestVr001Uniqueness::test_filter_mode_drops_duplicates`,
`TestVr002TypeMembership::test_filter_mode_drops_unknown_types`,
`TestVr004PredicateVocabulary::test_filter_mode_drops_unknown_predicate_relationship`,
`TestCascadeFiltering::*`.

### 5.4 Subtype matching consistency

Two places use subtype semantics:

- **VR002**: `profile.is_known_type(entity_type)` — does this return
  True if `entity_type` is declared as a subtype of a top-level type?
  (Phase 1 added this; verify Phase 4 relies on it correctly.)
- **VR005**: `_is_or_extends(type_name, allowed_types, profile)` —
  does this return True when `type_name` is a subtype name and the
  parent is in `allowed_types`?

Are these two paths consistent? If you find a case where VR002 says
"known" but VR005 says "doesn't match domain", that's a bug.

### 5.5 CLI surface

Read `src/ontozense/cli.py` for the new `validate` command (≈244 lines
inserted before `lint`):

- Profile loading: catches both `ProfileError` and `OSError` with
  distinct messages. Right pattern? (We added `OSError` after a Phase
  1+2 review finding.)
- Mode validation: the CLI rejects unknown `--mode` values with a
  clean error before constructing any objects. Verify there is no
  traceback leak.
- Exit codes: 0 on no errors, 3 on validation errors, 1 on bad usage.
  Right pattern for downstream CI integration?
- Output JSON: includes `validation_summary` block with profile name,
  version, mode, finding counts, cascade stats. Does the shape match
  what a downstream consumer (or lint) would want?
- `--domain-dir` integration: validate logs go to the same
  `<domain>/_logs/` directory as fuse, lint, etc. Verify by inspection.

### 5.6 Test coverage

31 new tests in `tests/test_phase4_validation.py`. Specifically check:

- `TestModes` (3) — invalid mode raises, default is `flag`. Anything
  missing? (e.g. None mode? empty string?)
- `TestVr001Uniqueness` (4) — covers happy path + duplicate detection
  + filter mode + flag mode. Missing: 3+ duplicates of the same ID.
  Worth adding?
- `TestVr002TypeMembership` (5) — happy path + empty type + unknown
  type + filter + subtype. Missing: case-insensitive type matching
  (does `entity_type="concept"` match `Concept`?).
- `TestVr003RequiredFields` (3) — missing field warning + happy path
  + extra_fields lookup. Missing: bool required field (is `is_critical=False`
  correctly counted as "set"?).
- `TestVr004` (3), `TestVr005` (2), `TestVr006` (2) — coverage is
  thinner here than VR001/VR002. Worth a third VR005 test for the
  subtype-allowed case?
- `TestCascadeFiltering` (2) — happy path + flag-mode-no-cascade.
  Missing: cascade triggered by VR001 (duplicate drop) followed by
  cascade. Worth adding?
- `TestCli` (5) — requires-profile + clean + errors-exit-3 +
  output-file + invalid-mode. Missing: filter-mode CLI smoke test.
  Worth adding?

---

## 6. Eight specific questions I want direct answers to

1. **Does the no-profile path produce byte-identical output to commit
   `cac424e`?** Run pytest on master, then on this branch — count
   passes, diff any unexpected output. Read the `fusion.py` diff to
   confirm the only behavioural change is `setdefault` of two keys
   conditional on non-empty upstream values.

2. **Are the 6 rules implemented as advertised?** Specifically: read
   each `_check_vrNNN` and verify the conditions match the rule
   docstring. Flag any mismatch.

3. **Is VR006 cardinality semantics correct?** 1:N vs N:1 is easy to
   transpose. Read the constraint blocks at lines ~498 (subject side)
   and ~524 (object side). Are they on the right cardinalities?

4. **Is cascade filtering complete and correct?** The contract: any
   relationship whose either endpoint references a dropped entity is
   also dropped. Find the loop in `validate()`. Does it use the same
   ID resolution as the surviving-IDs set?

5. **Is `flag` the right default for `--mode`?** Or should `filter`
   (or even a new `strict` mode that exits 3 on warnings too) be the
   default?

6. **Should `--profile` really be required for validate?** Or should
   profile-less validate run a reduced rule set (e.g. just VR001
   uniqueness)?

7. **Are `id` / `entity_type` in `extra_fields` (not typed
   FusedElement attributes) the right shape for Phase 5?** Or should
   we promote them now while we're already touching fusion.py?

8. **What's the one thing most likely to bite us in Phase 5 because
   of how Phase 4 is shaped?**

---

## 7. What the review output should look like

Write your review to `docs/REVIEW_PHASE_4.md` in this repo.

```markdown
# Phase 4 Review — Validation Stage

## Verdict
One paragraph: is this ready to merge to master and proceed to Phase 5,
or does something need to change first?

## What works well
Specific wins. Brief.

## Issues
Numbered list. Severity: blocker / major / minor / nit.

## Answers to the 8 questions in §6
Number them 1–8.

## Recommended changes before Phase 5 starts
Concrete, ordered.
```

3 pages is fine. Don't over-write.

---

## 8. House rules

- **Run `pytest -q` first.** 516 passed + 10 skipped. If different,
  stop and report.
- **Read `docs/PROFILE_SPEC.md`** if anything about the schema shape
  is unclear — it's still the contract for Phase 4.
- **Read the OntoMetric inspiration** if you want context on why
  these 6 rules in this order: <https://github.com/Inspiring-Ming/OntoMetric>.
  Phase 4 borrows the structural-validation philosophy, not the code.
- **Run a profile-aware validation by hand** if you can: pick the
  ESG or NPL profile in `docs/profile-examples/`, fuse a small
  fixture, validate it in `flag` mode and `filter` mode, and read
  the output JSON. (Tests cover this, but eyeballing it once finds
  shape issues that tests miss.)
- **Cite `file_path:line_number`** for every issue.
- **Severity matters.** Blocker = blocks Phase 5. Major = should fix
  before merge. Minor = follow-up. Nit = optional.
- **Do not propose features that aren't in the PRD.** Phase 4 is
  scoped tight; semantic validation is explicitly deferred.

---

Thank you. Phase 5 is gated on this review. The cascade filtering
correctness and the VR006 cardinality semantics from §5 are the
load-bearing pieces — focus there.
