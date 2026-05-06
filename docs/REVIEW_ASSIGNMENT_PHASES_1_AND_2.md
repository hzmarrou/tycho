# Independent Review Assignment — Phases 1 & 2: Profile System + Constrained Source A

**Review on:** branch `feat/phase-2-constrained-source-a` at HEAD `f2ec344`
**Repository:** `C:\Users\hzmarrou\OneDrive\python\projects\ontozense`
**Not yet merged to master.** Master is at `46e2e8d`. Your review gates the merge.

---

## 1. Why this review

We're 2 of 7 phases into adding **optional ontology-constrained
extraction** to Ontozense (PRD: `docs/PRD.txt`). This review covers
the combined Phase 1 + Phase 2 work as a single unit, because Phase 2
is what *uses* Phase 1 — reviewing them together gives you a working
end-to-end constrained pipeline to evaluate, not just a foundation in
isolation.

We want to know: **can we merge `feat/phase-2-constrained-source-a`
to master and confidently start Phase 3 (Sources B/C/D), or does
something need to change first?**

This review is scoped narrowly. We do **not** want a re-review of:
- The four-source pipeline architecture (reviewed 2026-04-10)
- The tester-readiness fixes (reviewed 2026-04-15)
- The PRD's overall direction
- The decision to ship a profile system at all

We **do** want a review of:
- Whether Phase 1's profile loader + identity generator are correct
  and complete
- Whether Phase 2's constrained Source A path actually constrains the
  LLM effectively, computes correct deterministic IDs, and applies
  alias/verb canonicalisation at the right point
- Whether the no-profile (unconstrained) path is **byte-identical** to
  the pre-Phase-1 baseline
- Whether the Phase 1+2 surface will hold up for Phases 3–7 without
  needing a refactor

---

## 2. The single most important constraint — verify first

**PRD Acceptance Criterion 1: Running without `--profile` must behave
exactly like the current baseline.** Non-negotiable.

Verify before reviewing anything else:

```bash
# Baseline
git checkout master                       # at 46e2e8d
pytest -q                                  # → 368 passed, 10 skipped

# Branch under review
git checkout feat/phase-2-constrained-source-a    # at f2ec344
pytest -q                                  # → 454 passed, 10 skipped
                                           #   (368 baseline + 70 Phase 1 + 16 Phase 2)
```

The 368 baseline tests must still pass byte-identical — no test was
modified, replaced, or reordered in any phase. If you find a single
pre-existing test whose behaviour or assertion changed, that's a
**blocker**.

Also try a no-profile end-to-end run on a fixture (no Azure key
needed if you stub the OntoGPT call) and confirm the output JSON has
empty values for `id`, `entity_type`, `extraction_mode`,
`profile_name`, `profile_version` on every concept and at the result
level — these are the new fields and they must be empty when no
profile is loaded.

---

## 3. What landed (your scope)

### Phase 1 — `df09147` Profile system foundation (~1,723 LOC, 70 tests)

| File | What |
|---|---|
| `src/ontozense/core/identity.py` | `normalize_label()`, `compute_id()`, `parse_id()`. Deterministic IDs of form `{type}_{normalized_label}_{hashN}`. Default `hash_length=6`. SHA-256 truncated. |
| `src/ontozense/core/profile.py` | `load_profile(path) → Profile` (frozen dataclass). Validates `schema.json` and optional sidecars. Raises `ProfileError`. |
| `docs/PROFILE_SPEC.md` | Authoring guide. ~300 lines. |
| `docs/profile-examples/esg/` | Reference ESG profile (5 entity types, 5 predicates) adapted from OntoMetric. |
| `tests/fixtures/profiles/minimal/schema.json` | Tiny test fixture. |
| `tests/test_identity.py` | 27 tests. |
| `tests/test_profile_loader.py` | 43 tests. |

### Phase 2 — `f2ec344` Constrained Source A extraction (~743 LOC, 16 tests)

| File | What |
|---|---|
| `src/ontozense/extractors/domain_doc_extractor.py` | `Concept` gets `id`, `entity_type` fields. `DomainDocumentExtractionResult` gets `extraction_mode`, `profile_name`, `profile_version`. `DomainDocumentExtractor.__init__` accepts `profile=None`. New `_generate_profile_template()` writes runtime LinkML template. New `_apply_profile()` post-processes with alias resolution, ID generation, verb canonicalisation. `_build_concept` parses 3-part `name :: TYPE :: definition` format when profile is set. |
| `src/ontozense/cli.py` | `extract-a` gets `--profile <path>` flag. Profile load failures surface clean errors. Mode announced at start (`Mode: unconstrained` or `Mode: constrained(profile=esg, version=1.0.0)`). |
| `tests/test_extract_a_constrained.py` | 16 tests covering constructor, constrained extraction, backward compat, ESG reference, CLI integration. |

### Out of scope (deferred to later phases)

- **Phase 3** — profile-aware Sources B (governance), C (schemas), D (code)
- **Phase 4** — `ontozense validate` CLI command, semantic + structural checks
- **Phase 5** — multi-doc + cross-source consolidation in fusion
- **Phase 6** — provenance granularity (segment/page/char-offset anchors)
- **Phase 7** — benchmark metrics

The Phase 2 result already carries the new metadata fields, but
**fusion / lint / query / file-back don't yet read them**. That's
intentional and not a defect — it's Phase 5+.

---

## 4. Three architectural decisions you should evaluate

These were locked before Phase 1 implementation. Tell us if you'd
push back now that you can see them in working code.

### Decision 1 — Single `schema.json` carrying everything

PRD §FR-2 originally suggested 5 separate files
(`schema.json`, `prompt.txt`, `alias_map.json`, `validation_rules.json`,
`relation_canonicalization.json`). We collapsed to 3:

- `schema.json` — entities, predicates, IDs, **plus** alias map and
  canonical verbs
- `prompt_fragment.md` — Source A only
- `alias_map.json` (optional sidecar) — overlays the schema's map
- `validation_rules.json` (optional, Phase 4)

**Question:** Does this make authoring easier or hurt separation of
concerns? The shipped ESG profile is your test case — open
`docs/profile-examples/esg/schema.json` and `prompt_fragment.md`. Is
it harder than it should be?

### Decision 2 — Deterministic ID format `{type}_{normalized_label}_{hashN}`

Hash is SHA-256 of `"{type_lower}|{normalized_label}"` truncated to
N hex chars. Default N=6 (24 bits).

**Question:** Imagine a domain with 5,000 entities across 50 documents.
At hash_length=6, what's your expected collision count? Should the
default be 8 (32 bits) for safety? The downside is uglier IDs
(`metric_carbon_emissions_8a4b3f01` vs `_8a4b3f`).

### Decision 3 — 3-part concept format `name :: TYPE :: definition` in profile mode

In unconstrained mode, the LLM emits `name :: definition` (today).
In profile mode, we generate a template that asks for `name :: TYPE
:: definition` with TYPE constrained to the profile's entity types.

**Question:** Is this format robust? Specifically: if the LLM forgets
the TYPE field and emits 2-part output anyway, we fall back to
parsing as 2-part with `entity_type=""`. Phase 4 will flag those.
But should Phase 2 do anything stronger at extraction time — re-prompt?
filter? warn loudly?

---

## 5. Specific things to evaluate

### 5.1 Phase 1: `identity.py` correctness

- `normalize_label()` handles Unicode (NFKD), case, whitespace,
  separators (`_-/.`), punctuation. Try a few realistic domain
  labels (banking, healthcare, financial). Anything you'd expect to
  fail?
- `compute_id()` is deterministic, case-insensitive, collision-resistant.
  The hash strategy uses `"{type_lower}|{normalized_label}"`. Could a
  label *literally containing* `|` cause issues? (Hint: pipe is
  punctuation so it normalises away. Verify.)
- `parse_id()` round-trip — does it hold for hex-looking labels like
  `"abc123"`? The current implementation uses `_is_hex` to identify
  the suffix, which could trip on labels that happen to be hex.

### 5.2 Phase 1: `profile.py` validation completeness

For each `ProfileError` path, ask: would a real authoring mistake hit
this?

| Validation | Triggered by |
|---|---|
| Profile directory not found | Bad `--profile` path |
| Profile path is not a directory | Pointing at a file |
| Missing required schema.json | Empty profile dir |
| schema.json not valid JSON | Authoring typo |
| Missing required top-level keys | Forgot `profile_name` etc. |
| `entity_types` non-empty | Empty profile |
| Predicate references undeclared type | Typo in subject_types/object_types |
| Cardinality not in {1:1, 1:N, N:1, N:N} | Wrote "many-to-many" |
| `id_format.strategy` not supported | Unknown strategy |
| `hash_length` >= 4 | Too-short hash |
| Non-string required field | Wrong type in JSON |

**Are there validation paths missing?** Specifically:
- What if `entity_types["X"]["required"]` and `["optional"]` overlap?
  We don't catch.
- What if a subtype name collides with a top-level entity type name?
  We don't catch.
- What if `subject_types` is empty? We allow it (predicate becomes
  applicable to any subject). Intentional?
- What if a profile name contains characters illegal in filesystem
  paths? We use `profile_name` in the temp template filename — could
  be a problem on Windows for certain values.

### 5.3 Phase 2: `_generate_profile_template()` — does it actually constrain?

Run `DomainDocumentExtractor(profile=load_profile("docs/profile-examples/esg/"))`,
then read `ext.template_path` content. The template is what SPIRES
hands to the LLM. Does it:

- Surface the prompt fragment verbatim in the description?
- List all allowed entity types (including subtypes)?
- List all allowed predicates?
- Surface required fields per type?
- Ask for the 3-part `name :: TYPE :: definition` format unambiguously?

If you saw this template as an LLM, would you understand the
constraints? Would you produce constrained output?

### 5.4 Phase 2: Order of operations in `_apply_profile()`

Current order:
1. Resolve concept name via alias_map (`carbon emissions` → `GHG Emissions`)
2. Compute ID using the *canonical* name + entity_type
3. For relationships: canonicalise predicate verb, resolve aliases on
   subject + object

**Question:** Is this the right order? Specifically, what if the LLM
emits a relationship `"carbon emissions -> emits -> CO2"` and the
profile doesn't have a canonical verb for "emits"? The relationship
keeps `predicate="emits"` (uncanonical). Is that the right behaviour
for Phase 2, or should we do something stronger?

### 5.5 Phase 2: Frozen-ness of `Profile`

`@dataclass(frozen=True)` — fields can't be reassigned. But
`alias_map`, `canonical_verbs`, `entity_types`, `predicates` are all
mutable types. A bad caller could `profile.alias_map["new"] = "value"`
and break determinism for downstream phases.

**Question:** Should we use `MappingProxyType` / `frozendict` to make
this airtight before Phase 3 starts consuming the profile from
multiple extractors in parallel?

### 5.6 Phase 2: CLI UX

- `Mode: unconstrained` vs `Mode: constrained(profile=esg, version=1.0.0)` —
  is this clear enough?
- Profile load failure message: `"[x] Profile load failed: <ProfileError>"`
  followed by a pointer to the spec doc. Is this actionable enough?
  Test `cli.py:382-388`.
- What happens when `--profile` points at a path the user can't read?
  We don't explicitly handle PermissionError — it'll bubble up as a
  ProfileError or OSError. Worth catching?

### 5.7 Test coverage of what matters

86 new tests across Phase 1+2. Specifically check:

- Are the **backward compat tests strong enough**? Look at
  `tests/test_extract_a_constrained.py::TestUnconstrainedUnchanged`.
  3 tests check that no-profile mode leaves the new fields empty.
  Anything else worth asserting?
- The ESG profile sanity tests — `tests/test_profile_loader.py::TestShippedEsgReference`
  and `tests/test_extract_a_constrained.py::TestEsgProfile` — exercise
  the shipped artifact. Are they covering the right surface?
- **Missing coverage I'd want to add**: collision behaviour at
  deliberately-low `hash_length=4`. The current test count says "no
  collisions for 100 distinct concepts at default 6". I haven't
  forced a collision and verified the system handles it gracefully.
  Worth adding?

---

## 6. Eight specific questions I want direct answers to

1. **Does the no-profile path produce byte-identical output to commit
   `46e2e8d`?** Run pytest on master, then on this branch — count
   passes, diff any unexpected output.

2. **Is `compute_id`'s hash length of 6 sufficient under realistic
   load?** Imagine 5,000 entities across 50 documents in a single
   domain. Expected collisions?

3. **Is `Profile` deeply frozen enough for Phases 3–7?** With Phase 3
   spinning up profile-aware extractors for B/C/D, the profile gets
   passed into 4+ codepaths. Should we add `MappingProxyType`?

4. **Is the generated LinkML template effective at constraining the
   LLM?** Read `_generate_profile_template()`'s output for the ESG
   profile and judge.

5. **Does the 3-part `name :: TYPE :: definition` parser handle the
   realistic edge cases?** Try a synthetic OntoGPT output where the
   LLM:
   - omits TYPE (2-part fallback should engage)
   - includes `::` literally inside the definition
   - emits an unknown TYPE the profile doesn't recognise
   - emits subtype names like "DirectMetric" (should be accepted)

6. **Are the validation paths in `profile.py` complete?** What's the
   single most likely authoring mistake we don't yet catch?

7. **Will Phase 3 (Sources B/C/D) hit any walls because of how Phase
   1+2 is shaped?** Specifically: the `Profile` dataclass, the
   `compute_id()` signature, the `Concept.id` / `Concept.entity_type`
   fields on the Source A output. Will B/C/D extractors find what
   they need?

8. **What's the one thing most likely to bite us in Phase 3 because
   of how Phase 2 is shaped?**

---

## 7. What the review output should look like

Write your review to `docs/REVIEW_PHASES_1_AND_2.md` in this repo.

```markdown
# Phases 1 & 2 Review — Profile System + Constrained Source A

## Verdict
One paragraph: is this ready to merge to master and proceed to Phase 3,
or does something need to change first?

## What works well
Specific wins. Brief.

## Issues
Numbered list. Severity: blocker / major / minor / nit.

## Answers to the 8 questions in §6
Number them 1–8.

## Recommended changes before Phase 3 starts
Concrete, ordered.
```

3–5 pages. 10+ is too much.

---

## 8. House rules

- **Run `pytest -q` first.** 454 passed + 10 skipped. If different,
  stop and report.
- **Read `docs/PROFILE_SPEC.md` once before reading any code.** The
  spec is the contract; the code implements it.
- **Try to author a tiny profile yourself** — the recipe example, or
  any domain you know — using only the spec doc, then load it via
  `load_profile()`. If you can't, that's a finding.
- **Run a profile-aware extraction** (or carefully read the test
  fixtures that mock OntoGPT). Specifically check that the generated
  template at `extractor.template_path` is what you'd want to send to
  an LLM.
- **Cite `file_path:line_number`** for every issue.
- **Severity matters.** Blocker = blocks Phase 3. Major = should fix
  before merge. Minor = follow-up. Nit = optional.
- **Do not propose features that aren't in the PRD.** Phases 1+2 are
  scoped tight.

---

Thank you. Phase 3 is gated on this review — focus on what makes the
combined Phase 1+2 surface hold up under the load of profile-aware
B/C/D extractors that will land next.
