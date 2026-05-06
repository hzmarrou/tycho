# Independent Review Assignment — Phase 3: Profile-Aware Sources B, C, D

**Review on:** branch `feat/phase-3-profile-aware-sources-bcd` at HEAD `2236b6f`
**Repository:** `C:\Users\hzmarrou\OneDrive\python\projects\ontozense`
**Master is at:** `5551925` (Phases 1+2 merged after your prior review).
**Not yet merged to master.** Your verdict gates the merge.

---

## 1. Why this review

You cleared Phases 1+2 last round (`docs/REVIEW_PHASES_1_AND_2.md`).
That gave us the profile loader, deterministic ID generator, and
constrained Source A extraction. Phase 3 mirrors the Phase 2 pattern
across the other three sources:

| Source | Phase 2 (Source A) | Phase 3 (Sources B/C/D) |
|---|---|---|
| Profile constraint | LLM prompt is constrained at extraction time | Each extractor validates its outputs against the profile schema |
| Deterministic ID | computed post-hoc from extracted (type, name) | computed post-hoc from extracted (type, name) — **same algorithm** |
| Backward compat | byte-identical no-profile path | byte-identical no-profile path |

The whole point of Phase 3: when a profile is loaded, all four
sources produce the **same deterministic ID for the same canonical
(entity_type, label) tuple**, so Phase 5 consolidation becomes a
trivial `dict[id]` group-by — no fuzzy matching needed.

We want to know: **can we merge `feat/phase-3-profile-aware-sources-bcd`
to master and confidently start Phase 4 (validation stage)?**

This review is scoped narrowly. We do **not** want re-review of:
- Phase 1's profile loader / identity generator (already cleared)
- Phase 2's Source A constrained extraction (already cleared)
- The PRD direction
- The cross-source ID alignment principle (already accepted)

We **do** want a review of:
- Whether each of Sources B/C/D applies the profile correctly
- Whether the heuristics for entity_type inference (especially
  Source D's name-prefix matching) are sound and won't surprise users
- Whether the no-profile (unconstrained) path on each extractor is
  byte-identical to the pre-Phase-3 baseline
- Whether the cross-source ID alignment contract actually holds end-
  to-end (Phase 5 depends on this)

---

## 2. The single most important constraint — verify first

**PRD AC1: no-profile behaviour must be byte-identical.** Non-negotiable.

```bash
# Baseline (post-Phase-2)
git checkout master                              # at 5551925
pytest -q                                         # → 459 passed, 10 skipped

# Branch under review
git checkout feat/phase-3-profile-aware-sources-bcd    # at 2236b6f
pytest -q                                         # → 475 passed, 10 skipped
                                                  #   (459 baseline + 16 new)
```

The 459 baseline tests must still pass byte-identical — no test was
modified, replaced, or reordered. If you find a single pre-existing
test whose behaviour or assertion changed, that's a **blocker**.

Three specific backward-compat tests in the new file pin this for
each extractor:
- `test_no_profile_records_have_empty_profile_fields` (Source B)
- `test_no_profile_models_have_empty_profile_fields` (Source C)
- `test_no_profile_rules_have_empty_profile_fields` (Source D)

Verify these all pass on the branch.

Note on **domain neutrality regression**: I tripped this once during
implementation (used "borrower" in a docstring example) and fixed
before committing. The shipped code passes
`tests/test_domain_neutrality.py`. Re-verify just in case.

---

## 3. What landed (your scope)

### Single commit `2236b6f` — ~700 LOC, 16 new tests

| File | Change |
|---|---|
| `src/ontozense/extractors/governance_extractor.py` | `GovernanceRecord` gains `id`, `entity_type` fields. `KNOWN_FIELDS` includes `"entity_type"`. `GovernanceExtractor.__init__(profile=None)`. New `_apply_profile()` does alias resolution + ID generation + unknown-type quarantine. |
| `src/ontozense/extractors/django_schema.py` | `SchemaModel`, `SchemaField` gain `id`, `entity_type`. `DjangoSchemaParser.__init__(profile=None)`. New `_apply_profile()` maps model.name → entity_type via profile, computes IDs for models and fields. |
| `src/ontozense/extractors/code_extractor.py` | `CodeRule` gains `attached_to_entity_id`, `attached_to_entity_type`. `CodeExtractor.__init__(profile=None)`. New `_apply_profile()` infers entity_type via two-step heuristic, computes IDs. |
| `tests/test_phase3_sources_bcd_profile.py` | 16 tests covering Source B/C/D profile awareness + cross-source ID alignment. |

### Out of scope (deferred to later phases)

- **Phase 4** — `ontozense validate` CLI command (consumes the
  quarantined `profile_warning` entries Phase 3 produces, decides
  cascade-filter behaviour)
- **Phase 5** — multi-doc + cross-source consolidation in fusion
  (uses Phase 3's deterministic IDs to dedupe by `dict[id]` group-by)
- **Phase 6** — provenance granularity
- **Phase 7** — benchmark metrics

The Phase 3 result already carries `profile_warning` entries on
quarantined records, but **Phase 4's validate command doesn't yet
read them**. That's intentional and not a defect.

---

## 4. Three architectural decisions you should evaluate

These were locked before Phase 3 implementation. Tell us if you'd
push back now that you can see them in working code.

### Decision 1 — Quarantine, don't drop

When Source B receives a record with an unknown `entity_type`, or
Source D can't infer an attachment type, the record is **kept** with
empty profile fields plus a warning entry, not dropped.

```python
# Source B example: unknown type → kept, warning recorded
record.extra_fields["profile_warning"] = "entity_type 'Unknown' not declared..."
result.warnings.append("Entry 0: entity_type 'Unknown' unknown to profile 'esg'")
```

**Question:** Is quarantine the right default for Phase 3, or should
unknown types be dropped at extraction time? The argument for
quarantine: Phase 4's validation stage owns the "what to do with
these" decision (filter / warn / fail-fast per profile). The argument
against: noisy output if many records fail the type check.

### Decision 2 — Source D's heuristic for entity_type inference

Two-step, in order:

1. Walk `rule.referenced_symbols` (e.g. `"loan.days_past_due"`,
   `"validate"`). For each, take the leading token before `.`. Check
   alias_map → known_types, then direct match. First match wins.

2. Match `rule.name`'s leading token against known types.
   Tokenise on `_-.`. Try longest prefix first (so
   `CUSTOMER_ID_THRESHOLD` would match `Customer` before `Customer_id`
   — wait, the order is wrong. **Verify yourself:** does the longest-
   first match actually work, or does it greedily match too much?)

**Question:** Is this heuristic sound? Two specific concerns:
- A constant like `MAX_ATTEMPTS` doesn't reference any entity. The
  heuristic correctly leaves it empty. But what about `THRESHOLD`
  shared across multiple entity types? It also stays empty — no
  match — which means it's never attached. Is that acceptable?
- A function `validate_concept(concept)` should attach to `Concept`
  via referenced_symbols. Verify by reading
  `code_extractor.py:_infer_entity_type`.

### Decision 3 — Field ID format `"<model_name>:<field_name>"`

Source C's field IDs use a colon-separated label so two same-named
fields (e.g. both have `name`) on different models get distinct IDs:

```python
compute_id("Concept", "Concept:name")        # → concept_concept_name_X
compute_id("Concept", "OtherEntity:name")    # → concept_otherentity_name_Y
```

But... `compute_id` normalises `:` to `_` (the colon falls into the
"drop unknown punctuation" path of `normalize_label`). So in
practice, `"Concept:name"` and `"Concept_name"` produce the same ID.
This means the disambiguation only works if the model names differ.

**Question:** Is this a real bug or acceptable? Two same-named fields
on the same model would still collide (but Django models don't
allow that). Two same-named fields on different models DO get
different IDs because the model name is different. So I believe it
works for the realistic case but is fragile.

---

## 5. Specific things to evaluate

### 5.1 Source B — quarantine + alias + ID

- Read `governance_extractor.py:_apply_profile()`. Does the order of
  operations make sense? (alias resolve → ID compute, with
  quarantine warning if unknown type)
- Try a record without `entity_type` declared — verify `id` stays
  empty (no inferring; we don't make up types).
- Try a record with `is_critical: "Yes"` (string, not bool). Should
  still parse correctly. The boolean-coercion logic predates Phase 3
  but verify Phase 3 didn't break it.

### 5.2 Source C — Django schema parsing edge cases

- Read `django_schema.py:_apply_profile()`. The model name is
  used both as the entity_type AND as part of the ID label. Is that
  the right shape?
- What if a model name is in the alias_map (e.g. profile maps
  `"users"` → `"Customer"`)? Verify the canonical name is used for
  both entity_type lookup AND ID computation, so all consumers see
  `"Customer"`, not `"users"`.
- Field IDs concatenate `"<model>:<field>"`. With colon normalisation
  to underscore (per Decision 3 above), `"Concept:name"` and
  `"Concept_name"` produce the same ID. Devise a realistic case where
  this could cause a collision and check the system handles it.

### 5.3 Source D — code extractor heuristic

The two-step heuristic has subtle ordering and casing rules. Test it
against:
- A constant `CUSTOMER_DPD_THRESHOLD = 90` (should attach to
  `Customer` via name-prefix, if `Customer` is declared)
- A function `def validate(record)` with `record.amount` in the
  body (should attach via referenced_symbols if `record` is a known
  type alias)
- A SQL `CREATE VIEW customer_summary AS ...` (rule.name might be
  `customer_summary`, which doesn't directly match a type)

Read `_infer_entity_type` carefully. Does the longest-prefix-first
loop actually work? (n=len(tokens), n=len-1, ..., n=1.)

### 5.4 Cross-source ID alignment

This is the load-bearing contract. Two specific tests:

- `test_same_type_and_name_produces_same_id_across_sources` — Source
  B record vs `compute_id` direct call → same ID.
- `test_alias_collapsed_before_id_so_synonyms_match` — alias 'co1'
  resolves to 'Concept One', then ID is computed on the canonical
  form.

**Question:** Is this contract strong enough? Specifically:
- What if Source A extracts `entity_type="Concept"` but Source C's
  Django model is named `concept` (lowercase)? `is_known_type`
  treats type names case-sensitively (does it?). Verify.
- What if Source D infers `entity_type="Concept"` but Source A's LLM
  emitted the type as `"concepts"` (plural)? They'd get different
  IDs. Is the profile expected to declare plural aliases?

### 5.5 Test coverage

16 new tests. Specifically check:

- `TestSourceBProfileAware` — 6 tests including alias resolution, ID
  computation, unknown-type quarantine, missing-type-no-ID. Anything
  missing? (e.g. is_critical bool/string normalisation interaction
  with profile mode?)
- `TestSourceCProfileAware` — 4 tests. Missing: a model in the alias
  map, a model with FK relationships (do FK targets get IDs too?
  No — `SchemaRelationship` wasn't extended; should it have been?).
- `TestSourceDProfileAware` — 4 tests. Missing: SQL extraction with
  profile (only Python code is tested). Worth adding?
- `TestCrossSourceIdAlignment` — 2 tests. The strongest contract,
  thinly tested. Worth a third test that simulates Source A + B + C
  + D all producing the same ID for `("Concept", "Customer One")`?

---

## 6. Eight specific questions I want direct answers to

1. **Does the no-profile path produce byte-identical output to commit
   `5551925`?** Run pytest on master, then on this branch — count
   passes, diff any unexpected output.

2. **Is Source D's heuristic sound for realistic codebases?**
   Specifically: does the longest-prefix-first matching loop in
   `_infer_entity_type` actually work as intended? Read it carefully.

3. **Is the field ID collision in Source C (colon normalises to
   underscore) a real defect, or acceptable?** Devise a realistic
   case where it would bite.

4. **Is the cross-source ID alignment contract strong enough for
   Phase 5?** What's the most likely way two sources would produce
   different IDs for what the user means as the same entity?

5. **Should `SchemaRelationship` (Source C FKs) also gain id /
   entity_type fields, or is that out of scope for Phase 3?**

6. **Should SQL extraction get profile-aware tests?** (Currently only
   Python AST extraction has profile tests in `TestSourceDProfileAware`.)

7. **Are the validation paths in `governance_extractor._apply_profile`
   complete?** What's the most likely authoring mistake we don't yet
   catch?

8. **What's the one thing most likely to bite us in Phase 4 because
   of how Phase 3 is shaped?**

---

## 7. What the review output should look like

Write your review to `docs/REVIEW_PHASE_3.md` in this repo.

```markdown
# Phase 3 Review — Profile-Aware Sources B, C, D

## Verdict
One paragraph: is this ready to merge to master and proceed to Phase 4,
or does something need to change first?

## What works well
Specific wins. Brief.

## Issues
Numbered list. Severity: blocker / major / minor / nit.

## Answers to the 8 questions in §6
Number them 1–8.

## Recommended changes before Phase 4 starts
Concrete, ordered.
```

3 pages is fine. Don't over-write.

---

## 8. House rules

- **Run `pytest -q` first.** 475 passed + 10 skipped. If different,
  stop and report.
- **Read the existing `docs/PROFILE_SPEC.md`** if anything about the
  schema shape is unclear — it was the contract for Phases 1+2 and
  is still the contract for Phase 3.
- **Run a profile-aware extraction** on all three sources if you can
  (or carefully read the test fixtures that exercise them). Verify
  the cross-source ID alignment by hand: pick a (type, label) tuple,
  compute the expected ID via `compute_id(type, label)`, then check
  Source B and Source C produce that same ID for that pair.
- **Cite `file_path:line_number`** for every issue.
- **Severity matters.** Blocker = blocks Phase 4. Major = should fix
  before merge. Minor = follow-up. Nit = optional.
- **Do not propose features that aren't in the PRD.** Phase 3 is
  scoped tight.

---

Thank you. Phase 4 is gated on this review. The cross-source ID
alignment contract from §4 is the load-bearing piece — focus there.
