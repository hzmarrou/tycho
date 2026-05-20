# Source D rich-extraction — design

**Status:** Draft, 2026-05-20. **Target release:** v1.2.1 (extractor enrichment patch on top of v1.2).
**Predecessor:** [2026-05-19-source-d-v1.2-executable-rule-extraction-design.md](2026-05-19-source-d-v1.2-executable-rule-extraction-design.md)

---

## 1. Problem statement

The Source D extractor delivered in v1.2 implements the six-stage pipeline and the closed `RuleKind` taxonomy correctly, but its **deterministic pattern coverage is narrower than the business code it is meant to ingest**. Running v1.2 against the existing NPL demo files (`domains/npl/sources/npl-code/{classification,forbearance,transitions}/`) produces **almost zero rule candidates**, even though those files express realistic Basel-D403 business logic in idiomatic Python.

The gap is structural, not domain-specific. v1.2 was scoped to single-statement bodies (`return <Compare>` for eligibility, `if <guard>: raise` for validation), but real production code expresses multi-condition predicates and uses module-level threshold constants rather than inline literals. Concretely:

| NPL file | Functions present | Patterns used | v1.2 extracts |
|---|---|---|---|
| `forbearance_validator.py` | `is_forbearance`, `validate_forbearance_event` | Multi-statement `if not X: return False` chain; `if X: errors.append(...)` | Only a weak `validate_*` fallback rule (confidence 0.4) |
| `upgrade_rules.py` | `can_upgrade_to_performing`, `can_exit_forborne_status` | Same multi-condition chains; comparisons against module-level constants | Nothing |
| `npe_classifier.py` | `classify_loan_as_npe`, `is_material_past_due` | Multi-statement `if X: return True` (disjunction); comparisons against module-level constants | Nothing |

This makes v1.2 release-correct but **release-unimpressive** for the very domain it was designed to demonstrate. The candidate-graph.json from a survey over the NPL fixture surfaces Source C structural truth and Source A/B stated truth, but the executable rule contribution from D — the v1.2 headline feature — is effectively invisible.

The underlying patterns the extractor must learn to read are not exotic. They are the dominant shapes of bool-returning business logic in any Python codebase: multi-condition guards in `is_*` / `can_*` functions, classification functions that return on the first matching criterion, and validators that accumulate errors rather than raising. Without coverage of these shapes, Source D can only contribute meaningful rules from code written specifically to be extracted — which is not how production Python is written.

---

## 2. Goal

Extend the deterministic procedural and model extractors so the existing NPL demo files (and equivalent idiomatic Python in other domains) produce rich `eligibility` and `validation` rule candidates without requiring code rewrites or LLM inference. The contract stays inside v1.2's "suppress ambiguity rather than over-promote noise" discipline — every new pattern must be detectable structurally, must anchor to a real parameter-borne subject, and must produce a `rule_payload` that validates against the existing `merge_key` identity.

**Out of scope:** dataflow / variable tracking (e.g. resolving `materiality = max(EUR, total * PCT)` before comparing), semantic inference from docstrings, any LLM-based extraction.

---

## 3. Patterns added

### Pattern A — Multi-condition eligibility (conjunction)

Functions prefixed `is_*` / `can_*` / `may_*` / `should_*` / `must_*` whose body is a chain of `if <guard>: return False` (or `if not <guard>: return False`) statements ending in `return True` (or a final return-with-bool expression).

Example, from `forbearance_validator.py`:

```python
def is_forbearance(loan_modification, counterparty_status) -> bool:
    if not counterparty_status.is_in_financial_difficulty:
        return False
    if not loan_modification.is_concessionary:
        return False
    return True
```

Each `if not X: return False` is a **required condition** — the function returns True only when all of them hold. Each becomes one `eligibility` rule.

### Pattern B — Multi-condition classification (disjunction)

Functions prefixed `is_*` / `can_*` / `may_*` / `should_*` / `must_*` AND additionally `classify_*` / `determine_*` / `predict_*` / `decide_*` / `evaluate_*`, whose body is a chain of `if <guard>: return True` statements ending in `return False`. Each `if X: return True` is a **sufficient trigger** — any one match makes the function return True. Each becomes one `eligibility` rule.

Example, from `npe_classifier.py`:

```python
def classify_loan_as_npe(loan, exposure_amount, asset_class) -> bool:
    ...
    if loan.days_past_due > threshold:
        return True
    if loan.ifrs_stage == IFRS_STAGE_IMPAIRED:
        return True
    if loan.is_defaulted:
        return True
    ...
    return False
```

### Pattern C — `validate_*` with `errors.append(...)`

Functions prefixed `validate_*` / `check_*` / `assert_*` whose body uses `if <guard>: errors.append(...)` instead of `raise`. Mirrors v1.2's existing `if <guard>: raise` extraction — same semantics, different syntactic shape.

Example, from `forbearance_validator.py`:

```python
def validate_forbearance_event(forbearance_event, loan) -> list[str]:
    errors = []
    if forbearance_event.start_date < loan.origination_date:
        errors.append("Forbearance start_date predates loan origination_date ...")
    ...
    return errors
```

Each `if X: errors.append(...)` becomes one `validation` rule on the negation of X.

### Pattern D — Module-level constant resolution

When a comparison's right-hand side is an `ast.Name` matching a module-level `ast.Assign(targets=[Name], value=Constant)`, substitute the constant's value for `object_value`. The original symbolic name is preserved in `expression` for traceability.

Example, from `npe_classifier.py`:

```python
NPE_DPD_THRESHOLD = 90
...
if loan.days_past_due > NPE_DPD_THRESHOLD:
    return True
```

Pattern D resolves `NPE_DPD_THRESHOLD` to `90`, allowing Patterns A/B/C (which require literal RHS) to fire on the original code without a rewrite. Without D, this entire branch would be skipped because `NPE_DPD_THRESHOLD` is an `ast.Name`, not an `ast.Constant`.

---

## 4. Subject resolution

The new patterns accept these LHS shapes inside multi-condition / errors.append bodies, in addition to the v1.2 `<param>["<key>"]` subscript path:

| LHS shape | Example | `subject_attribute` |
|---|---|---|
| `<param>.<attr>` | `counterparty_status.is_in_financial_difficulty` | `is_in_financial_difficulty` |
| `<param>["<key>"]` | `payment["amount"]` | `amount` |
| Bare `<param>` | `if has_active_forbearance:` | `has_active_forbearance` |

In every case the receiver (`<param>`, the subscript target, or the bare name itself) must be **in the function's parameter list**. Module-level constants and class-level attribute lookups stay rejected — same discipline as PR #6 introduced for eligibility/transition. `subject_entity` stays `None`; the anchor layer resolves it via in-module `AttributeFact` lookup or routes to fusion-time anchoring.

Polarity is preserved in the predicate:

| Pattern | Source shape | `predicate` | `object_value` |
|---|---|---|---|
| A | `if not X: return False` | `required` | `True` |
| A | `if X: return False` | `required` | `False` |
| A | `if X <op> lit: return False` | inverted(op) | lit |
| B | `if X: return True` | `required` | `True` |
| B | `if X <op> lit: return True` | op (direct) | lit |
| C | `if X: errors.append(...)` | `required` | `False` |
| C | `if X <op> lit: errors.append(...)` | inverted(op) | lit |

---

## 5. Rule grouping (hybrid model)

Per-condition rules are emitted independently — they merge naturally with C/D fusion (a Source C `NOT NULL` on `is_in_financial_difficulty` fuses with the corresponding Pattern A rule). To preserve the source function for audit grouping, each rule's `code_context` is set to `f"def {func_name}"`. Downstream audit consumers can group rules by `code_context` to reconstruct the original predicate's conjunction/disjunction structure.

This matches v1.2's existing behaviour for inline `__init__` and validator rules — granular emission, contextual provenance.

---

## 6. Confidence

- **Pattern A / B**: 0.75 (slightly below the 0.85 used for single-return eligibility — multi-condition functions are noisier and the conjunction/disjunction polarity is inferred from the return statement, not stated).
- **Pattern C**: 0.8 (matches existing `if/raise` validation confidence).
- **Pattern D**: confidence inherited from the calling pattern; resolution itself does not adjust confidence.

---

## 7. Files touched

- **Modify**: `src/ontozense/core/ingest/source_d/procedural_extractor.py`
  - Add `_collect_module_constants(pm)` pre-pass.
  - Add `_extract_multi_condition_eligibility(func, constants, source, file)` for Patterns A and B.
  - Add `_extract_errors_append_validations(func, constants, source, file)` for Pattern C.
  - Extend the prefix lists for Pattern B (`classify_*`, `determine_*`, `predict_*`, `decide_*`, `evaluate_*`).
  - Extend `_extract_function_rules` to consult `constants` when the RHS is an `ast.Name` (Pattern D).
- **Modify**: `src/ontozense/core/ingest/source_d/model_extractor.py`
  - Mirror the multi-condition extractor for class methods (Patterns A and B inside `def is_*(self)` / `def can_*(self)`).
  - Apply the same constant resolution for module-level constants referenced inside class methods.
- **Modify**: `tests/test_source_d_procedural_extractor.py` — A / B / C / D coverage with positive and negative regression tests.
- **Modify**: `tests/test_source_d_model_extractor.py` — A / B inside class methods.
- **Modify**: `tests/test_source_d_acceptance.py` — end-to-end check that the NPL demo fixture now produces non-trivial rule sets per file.

---

## 8. Acceptance criteria

These ACs reflect what the *extractor* can recover from each function. Conditions whose RHS is a local variable, whose LHS is a method call, or whose comparison uses an operator outside `_CMP` are skipped — those would require dataflow tracking or richer operator support, both deferred. The honest improvement is **~10 deterministic rules across the six NPL functions, vs 1 weak fallback rule in v1.2**.

- **AC-R1.** `is_forbearance` produces **2 eligibility rules**: `(is_in_financial_difficulty, required, True)` and `(is_concessionary, required, True)`. Both via `<param>.<attr>` LHS, both via `if not X: return False` polarity.
- **AC-R2.** `can_upgrade_to_performing` produces **3 eligibility rules**:
  - `(is_non_performing, required, True)` — from `if not loan.is_non_performing: return False`.
  - `(has_active_forbearance, required, False)` — from `if has_active_forbearance: return False` (bare-param subject).
  - `(improved_repayment_likelihood, required, True)` — from `if not payment_history.improved_repayment_likelihood: return False`.
  The `days_since_default < PROBATION_PERIOD_DAYS` branch is **not** extracted because `days_since_default` is a local variable (computed inline) — dataflow is out of scope (§10). The `if not payment_history.continuous_timely_repayments(...)` branch is **not** extracted because its LHS is a method call (extractor scope: `<param>.<attr>` only, no `<param>.<method>()`).
- **AC-R3.** `classify_loan_as_npe` produces **3 eligibility rules**:
  - `(ifrs_stage, eq, "ifrs_stage_3_impaired")` — Pattern D resolves `IFRS_STAGE_IMPAIRED` against the module constant.
  - `(is_defaulted, required, True)` — from `if loan.is_defaulted: return True`.
  - `(unlikeliness_to_pay_flag, required, True)` — from `if loan.unlikeliness_to_pay_flag: return True`.
  The `loan.days_past_due > threshold` branch is **not** extracted because `threshold` is a local variable computed from a conditional expression — dataflow is out of scope.
- **AC-R4.** `validate_forbearance_event` produces **1 validation rule**: `(classification, neq, "performing_forborne")` — from the nested `if forbearance_event.classification == "performing_forborne": errors.append(...)`. The other two `errors.append` sites compare two attribute accesses or use `is not None` / method calls; non-literal RHS and operator-out-of-scope cases stay skipped.
- **AC-R5.** `can_exit_forborne_status` produces **1 eligibility rule**: `(counterparty_still_in_difficulty, required, False)` from the bare-param attribute `forbearance.counterparty_still_in_difficulty:`.
- **AC-R6.** `is_material_past_due` produces **0 rules** — its single `return past_due_amount > materiality` has a local-variable RHS. This is the canonical case demonstrating the v1.2.1 / dataflow boundary.
- **AC-R7.** No `subject_entity` or `subject_attribute` is fabricated from non-parameter receivers; module-level constants used as subjects continue to be rejected (PR #6 discipline preserved).
- **AC-R8.** All existing v1.2 tests stay green. The new patterns are additive; they do not remove, weaken, or alter any v1.2 rule emission.
- **AC-R9.** No new LLM dependency. Extraction stays fully deterministic.

---

## 9. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Over-extraction on unrelated control flow that happens to return bool | Prefix-list filter on Pattern A/B; shape requirements (single `return False`/`return True` body per branch); receiver-must-be-parameter discipline preserved |
| Constant-resolution scope creeps into dataflow | Pattern D limited to top-level `ast.Assign(targets=[Name], value=Constant)` only. No tracking through function-scope assignments, no `__init__` resolution, no class-level constants. |
| Polarity mistakes silently invert rules | Each polarity row has a dedicated regression test in `test_source_d_procedural_extractor.py` |
| New patterns flood the audit block with low-value rules | Confidence calibrated below single-return paths (0.75 vs 0.85); existing strength mapping in `emit.py` maps 0.6-0.85 to `Strength.MEDIUM` so these rules don't get STRONG-tier treatment unless cross-source corroboration boosts them |

---

## 10. Out of scope (for the avoidance of doubt)

- **Dataflow analysis** for intermediate variables. Examples we cannot resolve: `materiality = max(EUR, total * PCT); return amount > materiality`; `days_since_default = (date.today() - loan.default_date).days; if days_since_default < THRESHOLD`; `threshold = X if cond else Y; if loan.attr > threshold`.
- **Method-call LHS or RHS.** `if payment_history.continuous_timely_repayments(months=3):` and `if loan.was_non_performing_at(forbearance_event.start_date):` stay unextracted — the extractor does not recurse into method calls or trace their return values.
- **Operators outside `_CMP`.** `is not None`, `in`, `not in`, `is`, boolean `and` / `or`, and chained comparisons (`0 < x < 10`) are not handled in this batch. The seven supported ops stay: `Lt, LtE, Gt, GtE, Eq, NotEq` plus the truthiness paths covered in section 4.
- **Outer-guard context for nested `if` blocks.** A pattern like `if outer_cond: if inner_cond <op> lit: errors.append(...)` emits a rule on the *inner* condition only — the outer guard is dropped. Audit consumers receive the inner rule with `code_context` pointing at the enclosing function. Capturing outer-guard composition would require structured `condition` serialization, which is deferred.
- **Class-level constants** and `self`-bound attributes used as comparison RHS.
- **Constant resolution across import boundaries.** Pattern D scans only the current module's top-level `ast.Assign(targets=[Name], value=Constant)` nodes.
- **LLM-based** normalization, classification, or rule discovery.
- **No change to** `merge_key`, `_normalize_subject`, anchor semantics, or fusion rules.
- **No change to** Source A, B, or C ingesters.
- **No change to** OWL emission, the `draft` command, or `survey` CLI.

---

## 11. Migration / compatibility

This is a pure additive extension to the deterministic extractors. No public API changes, no candidate envelope changes, no merge semantics changes. Re-running survey on existing domains produces more rule candidates than before, all of which flow through the same anchor / emit / fusion path. No downstream code requires modification.
