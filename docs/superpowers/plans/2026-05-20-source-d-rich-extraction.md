# Source D Rich Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the deterministic Source D extractors (procedural + model) with four new pattern shapes (A multi-condition eligibility, B multi-condition classification, C `errors.append` validation, D module-level constant resolution) so idiomatic Python business code produces rich rule candidates without rewriting.

**Architecture:** Additive on top of v1.2's `procedural_extractor.py` and `model_extractor.py`. New helpers extract from top-level `if` chains only (nested-under-guard cases are skipped to avoid false promotion). A new module-level constant pre-pass resolves `ast.Name` RHS values. Subject discipline from PR #6 stays in force — only function parameters are valid subjects.

**Tech Stack:** Python 3.11+, `ast` module, existing v1.2 IR dataclasses (`RuleFact`, `EvidenceSpan`), pytest.

**Spec:** `docs/superpowers/specs/2026-05-20-source-d-rich-extraction-design.md`

---

## File Structure

### Files to modify

| File | What's added |
|---|---|
| `src/ontozense/core/ingest/source_d/procedural_extractor.py` | `_collect_module_constants`, `_resolve_constant`, `_resolve_subject`, `_extract_multi_condition_returns`, `_extract_errors_append_validations`; widened prefix list `_MULTI_ELIGIBILITY_PREFIXES`; updated `_extract_function_rules` to use `_resolve_constant`; updated `extract_procedural` to call the new helpers |
| `src/ontozense/core/ingest/source_d/model_extractor.py` | Same helpers (duplicated locally per existing v1.2 convention); `_extract_multi_condition_method` for class methods; updated `extract_model` to call it |

### Files to create

| File | Purpose |
|---|---|
| `tests/test_source_d_rich_extraction.py` | Unit tests for the new helpers (subject resolution, constant resolution, polarity, top-level-only-walk) |
| `tests/test_source_d_npl_acceptance.py` | NPL fixture acceptance test — per-function rule counts matching spec §8 ACs |

### Files to leave alone

- `src/ontozense/core/ingest/source_d/ir.py` — no IR changes
- `src/ontozense/core/ingest/source_d/rule_payload.py` — no `merge_key` changes
- `src/ontozense/core/ingest/source_d/anchor.py` — no anchor changes
- `src/ontozense/core/ingest/source_d/emit.py` — no emit changes
- `src/ontozense/core/candidate_graph.py` — no fusion changes
- All Source A / B / C code

---

## Helper signatures (locked-in for cross-task consistency)

All helpers below appear in **both** `procedural_extractor.py` and `model_extractor.py` with **identical signatures and behaviour** (duplication matches the existing v1.2 convention of paired helpers).

```python
def _collect_module_constants(pm: ParsedModule) -> dict[str, object]:
    """Return {name: value} for top-level `<Name> = <Constant>` assignments.

    Scans only direct children of pm.tree.body. Nested assignments,
    tuple-unpacking targets, and non-Constant values are ignored.
    """


def _resolve_constant(node: ast.expr, constants: dict[str, object]) -> object | _UNRESOLVED:
    """Return the constant value for an ast.Constant or for an ast.Name
    that maps to a module-level constant. Returns _UNRESOLVED for any
    other shape (so callers can reject the case).
    """


def _resolve_subject(expr: ast.expr, param_names: set[str]) -> str | None:
    """Return the subject_attribute name for a valid LHS shape, else None.

    Accepts:
      - <param>.<attr>   -> returns <attr>
      - <param>["<key>"] -> returns <key> (key must be a string literal)
      - bare <param>     -> returns <param> (when <param> is in param_names)

    Rejects (returns None):
      - module-level names, locals not in param_names
      - method calls (<obj>.<method>())
      - chained attribute access (<a>.<b>.<c>)
      - any other shape
    """


_UNRESOLVED = object()  # sentinel for _resolve_constant
```

```python
_MULTI_ELIGIBILITY_PREFIXES = (
    "is_", "can_", "may_", "should_", "must_",
    "classify_", "determine_", "predict_", "decide_", "evaluate_",
)
```

```python
def _extract_multi_condition_returns(
    func: ast.FunctionDef,
    constants: dict[str, object],
    source: str,
    file: str,
) -> Iterable[RuleFact]:
    """Pattern A + B. Emit eligibility rules for multi-condition
    bool-returning functions named with `_MULTI_ELIGIBILITY_PREFIXES`.

    Walks ONLY top-level `if` statements (direct children of func.body),
    NOT nested ifs. Skips functions whose name doesn't match the prefix
    list or whose body has no `if X: return False/True` pattern.

    Termination contract (narrow, deterministic):
      - The function's LAST statement must be `return <ast.Constant>`
        with value `True` (Pattern A) or `False` (Pattern B). Any other
        terminal form (computed return like `return all(...)`, no return,
        raise) is skipped. This is the v1.2.1 boundary — handling computed
        bool returns would require dataflow analysis (deferred per spec §10).

    Polarity:
      - Pattern A (function ends with `return True` as ast.Constant):
        `if X: return False`     -> (required, False) on X
        `if not X: return False` -> (required, True)  on X
        `if X <op> lit: return False` -> (inverted(op), lit) on X
      - Pattern B (function ends with `return False` as ast.Constant):
        `if X: return True`      -> (required, True)  on X
        `if X <op> lit: return True`  -> (op, lit) on X

    Returns empty iterable if the function shape doesn't match.
    """


def _extract_errors_append_validations(
    func: ast.FunctionDef,
    constants: dict[str, object],
    source: str,
    file: str,
) -> Iterable[RuleFact]:
    """Pattern C. Emit validation rules for `errors.append(...)` sites
    in functions named with `_VALIDATE_PREFIXES`.

    Walks ONLY top-level `if` statements. Nested `if` blocks are
    SKIPPED entirely (no inner-only rule emission) per spec §10.

    Each top-level `if <guard>: errors.append(...)` emits one rule:
      - `if X: errors.append(...)`         -> (required, False) on X
      - `if X <op> lit: errors.append(...)` -> (inverted(op), lit) on X

    Returns empty iterable if the function name doesn't match or no
    qualifying top-level `if/append` site exists.
    """
```

For `model_extractor.py`, the multi-condition helper is parameterised by class name:

```python
def _extract_multi_condition_method(
    cls_name: str,
    method: ast.FunctionDef,
    constants: dict[str, object],
    source: str,
    file: str,
) -> Iterable[RuleFact]:
    """Class-method analogue of _extract_multi_condition_returns.
    subject_entity is set to cls_name (anchored). Otherwise identical
    pattern matching and polarity logic.

    Subject discipline — `self` is INCLUDED in param_names so that
    `self.<attr>` is a valid LHS. This is the canonical anchored
    subject form for class methods and matches v1.2's existing
    _extract_eligibility_method contract (model_extractor.py:264).
    Bare-param subjects on other method parameters also work.
    """
```

---

## Confidence and rule_kind assignment

Locked-in across all new helpers:

| Pattern | rule_kind | confidence | subject_entity |
|---|---|---|---|
| A (procedural) | `eligibility` | 0.75 | `None` |
| B (procedural) | `eligibility` | 0.75 | `None` |
| C (procedural) | `validation` | 0.8 | `None` |
| A (model) | `eligibility` | 0.75 | `cls_name` |
| B (model) | `eligibility` | 0.75 | `cls_name` |
| Pattern D (resolution) | — | inherited | inherited |

All rules carry `code_context = f"def {func_name}"` (or `f"class {cls_name}, def {method.name}"` for model).

---

### Task 1: Add `_resolve_subject` helper to procedural_extractor

**Files:**
- Modify: `src/ontozense/core/ingest/source_d/procedural_extractor.py:36-44` (add helper at module scope, alongside `_TRANSITION_FIELD_NAMES`)
- Test: `tests/test_source_d_rich_extraction.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/test_source_d_rich_extraction.py`:

```python
"""Unit tests for v1.2.1 rich-extraction helpers."""
import ast

from ontozense.core.ingest.source_d.procedural_extractor import _resolve_subject


def _expr(src: str) -> ast.expr:
    """Parse a single expression string into its ast.expr."""
    module = ast.parse(src, mode="eval")
    return module.body


def test_resolve_subject_param_attribute_access():
    expr = _expr("loan.is_non_performing")
    assert _resolve_subject(expr, {"loan"}) == "is_non_performing"


def test_resolve_subject_param_string_subscript():
    expr = _expr("payment['amount']")
    assert _resolve_subject(expr, {"payment"}) == "amount"


def test_resolve_subject_bare_param():
    expr = _expr("has_active_forbearance")
    assert _resolve_subject(expr, {"has_active_forbearance"}) == "has_active_forbearance"


def test_resolve_subject_rejects_module_level_name():
    expr = _expr("THRESHOLDS")
    assert _resolve_subject(expr, {"loan"}) is None


def test_resolve_subject_rejects_method_call():
    expr = _expr("payment_history.continuous_repayments()")
    assert _resolve_subject(expr, {"payment_history"}) is None


def test_resolve_subject_rejects_chained_attribute():
    expr = _expr("self.config.threshold")
    assert _resolve_subject(expr, {"self"}) is None


def test_resolve_subject_rejects_non_string_subscript():
    expr = _expr("loan[0]")
    assert _resolve_subject(expr, {"loan"}) is None


def test_resolve_subject_rejects_subscript_on_non_param():
    expr = _expr("CONFIG['key']")
    assert _resolve_subject(expr, {"loan"}) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_source_d_rich_extraction.py -v`

Expected: FAIL with `ImportError: cannot import name '_resolve_subject'`.

- [ ] **Step 3: Implement `_resolve_subject` in procedural_extractor.py**

In `src/ontozense/core/ingest/source_d/procedural_extractor.py`, add after the existing module-scope constants (after `_TRANSITION_FIELD_NAMES`, around line 44):

```python
def _resolve_subject(expr: ast.expr, param_names: set[str]) -> str | None:
    """Return the subject_attribute name for a valid LHS shape, else None.

    Accepts:
      - <param>.<attr>        -> returns <attr>
      - <param>["<key>"]      -> returns <key>
      - bare <param>          -> returns <param>

    Rejects everything else, including chained attribute access,
    method calls, module-level constants, and subscripts on non-param
    receivers. The receiver must be a direct ast.Name in param_names.
    """
    if isinstance(expr, ast.Attribute):
        if isinstance(expr.value, ast.Name) and expr.value.id in param_names:
            return expr.attr
        return None
    if isinstance(expr, ast.Subscript):
        if not isinstance(expr.value, ast.Name) or expr.value.id not in param_names:
            return None
        slice_node = expr.slice
        if isinstance(slice_node, ast.Constant) and isinstance(slice_node.value, str):
            return slice_node.value
        return None
    if isinstance(expr, ast.Name):
        if expr.id in param_names:
            return expr.id
        return None
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_source_d_rich_extraction.py -v`

Expected: 8 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ontozense/core/ingest/source_d/procedural_extractor.py tests/test_source_d_rich_extraction.py
git commit -m "feat(source-d): add _resolve_subject helper for v1.2.1 LHS shapes"
```

---

### Task 2: Add `_collect_module_constants` and `_resolve_constant` (Pattern D foundation)

**Files:**
- Modify: `src/ontozense/core/ingest/source_d/procedural_extractor.py` (add helpers near `_resolve_subject`)
- Test: `tests/test_source_d_rich_extraction.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_source_d_rich_extraction.py`:

```python
from ontozense.core.ingest.source_d.parse import parse_module
from ontozense.core.ingest.source_d.procedural_extractor import (
    _UNRESOLVED,
    _collect_module_constants,
    _resolve_constant,
)


def test_collect_module_constants_picks_up_simple_assigns(tmp_path):
    src = tmp_path / "m.py"
    src.write_text(
        "NPE_DPD_THRESHOLD = 90\n"
        "MATERIALITY = 100\n"
        "IFRS_STAGE_IMPAIRED = 'ifrs_stage_3_impaired'\n"
    )
    pm = parse_module(src)
    constants = _collect_module_constants(pm)
    assert constants["NPE_DPD_THRESHOLD"] == 90
    assert constants["MATERIALITY"] == 100
    assert constants["IFRS_STAGE_IMPAIRED"] == "ifrs_stage_3_impaired"


def test_collect_module_constants_ignores_non_constant_values(tmp_path):
    src = tmp_path / "m.py"
    src.write_text(
        "FOO = some_func()\n"
        "BAR = 1 + 2\n"
        "OK = 5\n"
    )
    pm = parse_module(src)
    constants = _collect_module_constants(pm)
    assert "FOO" not in constants
    assert "BAR" not in constants
    assert constants["OK"] == 5


def test_collect_module_constants_ignores_tuple_unpacking(tmp_path):
    src = tmp_path / "m.py"
    src.write_text("A, B = 1, 2\nC = 3\n")
    pm = parse_module(src)
    constants = _collect_module_constants(pm)
    assert "A" not in constants
    assert "B" not in constants
    assert constants["C"] == 3


def test_resolve_constant_returns_literal_value_for_ast_constant():
    node = ast.parse("42", mode="eval").body
    assert _resolve_constant(node, {}) == 42


def test_resolve_constant_resolves_name_from_constants_map():
    node = ast.parse("NPE_DPD_THRESHOLD", mode="eval").body
    assert _resolve_constant(node, {"NPE_DPD_THRESHOLD": 90}) == 90


def test_resolve_constant_returns_unresolved_for_unknown_name():
    node = ast.parse("UNKNOWN", mode="eval").body
    assert _resolve_constant(node, {"OTHER": 1}) is _UNRESOLVED


def test_resolve_constant_returns_unresolved_for_other_shapes():
    node = ast.parse("some_func()", mode="eval").body
    assert _resolve_constant(node, {}) is _UNRESOLVED
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_source_d_rich_extraction.py -v -k "constants or resolve_constant"`

Expected: FAIL with `ImportError: cannot import name '_UNRESOLVED'`.

- [ ] **Step 3: Implement helpers in procedural_extractor.py**

Add to `src/ontozense/core/ingest/source_d/procedural_extractor.py`, near `_resolve_subject` (place these before `_resolve_subject` so they're available to later helpers):

```python
_UNRESOLVED = object()


def _collect_module_constants(pm: "ParsedModule") -> dict[str, object]:
    """Return {name: value} for top-level `<Name> = <Constant>` assignments.

    Scans only direct children of pm.tree.body. Ignores:
      - Tuple-unpacking targets (`A, B = 1, 2`).
      - Non-Constant RHS values (`X = func()`, `Y = 1 + 2`).
      - Annotated assignments without a value.
      - Nested assignments inside functions or classes.
    """
    out: dict[str, object] = {}
    for stmt in pm.tree.body:
        if not isinstance(stmt, ast.Assign):
            continue
        if len(stmt.targets) != 1:
            continue
        target = stmt.targets[0]
        if not isinstance(target, ast.Name):
            continue
        if not isinstance(stmt.value, ast.Constant):
            continue
        out[target.id] = stmt.value.value
    return out


def _resolve_constant(node: ast.expr, constants: dict[str, object]) -> object:
    """Return the constant value for an ast.Constant or for an ast.Name
    that maps to a module-level constant. Returns _UNRESOLVED for any
    other shape (so callers can reject the case)."""
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name) and node.id in constants:
        return constants[node.id]
    return _UNRESOLVED
```

Note: the `"ParsedModule"` forward-string annotation is to avoid an unused import if `ParsedModule` isn't already imported. Check the file head — if `from .parse import ParsedModule` is already present, drop the quotes.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_source_d_rich_extraction.py -v -k "constants or resolve_constant"`

Expected: 7 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ontozense/core/ingest/source_d/procedural_extractor.py tests/test_source_d_rich_extraction.py
git commit -m "feat(source-d): add _collect_module_constants and _resolve_constant for Pattern D"
```

---

### Task 3: Wire Pattern D into existing `_extract_function_rules`

**Files:**
- Modify: `src/ontozense/core/ingest/source_d/procedural_extractor.py:134-189` (the existing `_extract_function_rules` function)
- Modify: `src/ontozense/core/ingest/source_d/procedural_extractor.py:232-272` (`extract_procedural` — pass `constants` through)
- Test: `tests/test_source_d_rich_extraction.py` (append)

- [ ] **Step 1: Write the failing test**

Append:

```python
from ontozense.core.ingest.source_d.ir import RuleFact
from ontozense.core.ingest.source_d.procedural_extractor import extract_procedural


def test_pattern_d_resolves_module_constant_rhs_in_existing_extractor(tmp_path):
    """An `if x['amount'] <= THRESHOLD: raise` rule must resolve
    THRESHOLD against the module-level constant."""
    src = tmp_path / "m.py"
    src.write_text(
        "THRESHOLD = 100\n"
        "def validate_payment(payment):\n"
        "    if payment['amount'] <= THRESHOLD:\n"
        "        raise ValueError('too low')\n"
    )
    pm = parse_module(src)
    facts = list(extract_procedural(pm))
    rules = [r for r in facts if isinstance(r, RuleFact) and r.subject_attribute == "amount"]
    assert len(rules) == 1
    assert rules[0].object_value == 100
    assert rules[0].predicate == "gt"  # inverted from <=


def test_pattern_d_skips_when_constant_unknown(tmp_path):
    """An unresolved Name RHS still skips emission (the v1.2 behavior)."""
    src = tmp_path / "m.py"
    src.write_text(
        "def validate_payment(payment):\n"
        "    if payment['amount'] <= UNKNOWN_THRESHOLD:\n"
        "        raise ValueError\n"
    )
    pm = parse_module(src)
    facts = list(extract_procedural(pm))
    rules = [r for r in facts if isinstance(r, RuleFact)]
    # No structured rule; only the weak validate_* fallback fires.
    structured = [r for r in rules if r.subject_attribute == "amount"]
    assert structured == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_source_d_rich_extraction.py -v -k "pattern_d"`

Expected: 2 FAIL (no rule emitted for resolved-constant case).

- [ ] **Step 3: Modify `_extract_function_rules` to consult constants**

In `procedural_extractor.py`, change the function signature and the RHS check.

Current signature (line 134):
```python
def _extract_function_rules(func: ast.FunctionDef, source: str, file: str) -> Iterable[RuleFact]:
```

New signature:
```python
def _extract_function_rules(
    func: ast.FunctionDef,
    constants: dict[str, object],
    source: str,
    file: str,
) -> Iterable[RuleFact]:
```

Inside the function, the existing block (around lines 140-160) reads:
```python
            if isinstance(test, ast.Compare) and len(test.ops) == 1 and type(test.ops[0]) in _CMP_INVERSE:
                attr = _key_from_subscript(test.left)
                if attr is None:
                    continue
                rhs = test.comparators[0]
                if not isinstance(rhs, ast.Constant):
                    continue
                if isinstance(node.body[0], ast.Raise):
                    yield RuleFact(
                        ...
                        object_value=rhs.value,
                        ...
                    )
```

Replace the RHS resolution to use `_resolve_constant`:

```python
            if isinstance(test, ast.Compare) and len(test.ops) == 1 and type(test.ops[0]) in _CMP_INVERSE:
                attr = _key_from_subscript(test.left)
                if attr is None:
                    continue
                rhs_value = _resolve_constant(test.comparators[0], constants)
                if rhs_value is _UNRESOLVED:
                    continue
                if isinstance(node.body[0], ast.Raise):
                    yield RuleFact(
                        ...
                        object_value=rhs_value,
                        ...
                    )
```

(Apply the same `_resolve_constant` substitution to the defaulting path further down in the same function — `first.value` becomes `_resolve_constant(first.value, constants)` and the `_UNRESOLVED` guard short-circuits emission.)

- [ ] **Step 4: Update `extract_procedural` to compute and pass `constants`**

In `extract_procedural` (around line 232), at the top of the function body (after `config = config or {}`), add:

```python
    constants = _collect_module_constants(pm)
```

Update the call sites:
- `_extract_function_rules(func, pm.source, file)` → `_extract_function_rules(func, constants, pm.source, file)`

- [ ] **Step 5: Run tests to verify pass**

Run: `pytest tests/test_source_d_rich_extraction.py -v -k "pattern_d"`

Expected: 2 PASS.

- [ ] **Step 6: Run existing procedural tests for no regression**

Run: `pytest tests/test_source_d_procedural_extractor.py -v`

Expected: all existing tests still PASS (the new `constants` argument defaults to an empty dict implicitly through the upstream call site; existing tests don't use module constants).

- [ ] **Step 7: Commit**

```bash
git add src/ontozense/core/ingest/source_d/procedural_extractor.py tests/test_source_d_rich_extraction.py
git commit -m "feat(source-d): _extract_function_rules resolves module-constant RHS (Pattern D)"
```

---

### Task 4: Pattern A + B — multi-condition extractor (procedural)

**Files:**
- Modify: `src/ontozense/core/ingest/source_d/procedural_extractor.py` (add `_MULTI_ELIGIBILITY_PREFIXES` constant + `_extract_multi_condition_returns` helper; wire into `extract_procedural`)
- Test: `tests/test_source_d_rich_extraction.py` (append)

- [ ] **Step 1: Write the failing tests for Pattern A**

Append:

```python
def test_pattern_a_emits_eligibility_per_required_condition(tmp_path):
    """`if not X: return False` chain → one eligibility rule per condition
    with (required, True) polarity."""
    src = tmp_path / "m.py"
    src.write_text(
        "def is_forbearance(loan_modification, counterparty_status):\n"
        "    if not counterparty_status.is_in_financial_difficulty:\n"
        "        return False\n"
        "    if not loan_modification.is_concessionary:\n"
        "        return False\n"
        "    return True\n"
    )
    pm = parse_module(src)
    facts = list(extract_procedural(pm))
    elig = [r for r in facts if isinstance(r, RuleFact) and r.rule_kind == "eligibility"]
    assert len(elig) == 2
    subjects = {(r.subject_attribute, r.predicate, r.object_value) for r in elig}
    assert ("is_in_financial_difficulty", "required", True) in subjects
    assert ("is_concessionary", "required", True) in subjects


def test_pattern_a_bare_param_truthiness_polarity(tmp_path):
    """`if has_X: return False` (no `not`) → bare-param subject with
    (required, False) polarity."""
    src = tmp_path / "m.py"
    src.write_text(
        "def can_upgrade(loan, has_active_forbearance):\n"
        "    if has_active_forbearance:\n"
        "        return False\n"
        "    if not loan.is_non_performing:\n"
        "        return False\n"
        "    return True\n"
    )
    pm = parse_module(src)
    facts = list(extract_procedural(pm))
    elig = [r for r in facts if isinstance(r, RuleFact) and r.rule_kind == "eligibility"]
    triples = {(r.subject_attribute, r.predicate, r.object_value) for r in elig}
    assert ("has_active_forbearance", "required", False) in triples
    assert ("is_non_performing", "required", True) in triples


def test_pattern_a_skips_nested_ifs(tmp_path):
    """Nested `if/if return False` patterns must NOT contribute rules
    — outer-guard context can't be serialised faithfully."""
    src = tmp_path / "m.py"
    src.write_text(
        "def is_eligible(loan):\n"
        "    if loan.flag_a:\n"
        "        if loan.flag_b:\n"
        "            return False\n"
        "    return True\n"
    )
    pm = parse_module(src)
    facts = list(extract_procedural(pm))
    elig = [r for r in facts if isinstance(r, RuleFact) and r.rule_kind == "eligibility"]
    # The OUTER if doesn't have `return False` directly; its body has
    # only a nested if. Neither layer should emit a standalone rule.
    assert elig == []


def test_pattern_a_skips_when_lhs_is_method_call(tmp_path):
    """`if not payment_history.continuous_repayments(): return False`
    must be skipped — method call LHS is not a subject-bearing
    reference."""
    src = tmp_path / "m.py"
    src.write_text(
        "def can_upgrade(loan, payment_history):\n"
        "    if not payment_history.continuous_repayments():\n"
        "        return False\n"
        "    return True\n"
    )
    pm = parse_module(src)
    facts = list(extract_procedural(pm))
    elig = [r for r in facts if isinstance(r, RuleFact) and r.rule_kind == "eligibility"]
    assert elig == []


def test_pattern_a_skips_when_rhs_is_local_variable(tmp_path):
    """`if loan.dpd < threshold: return False` where `threshold` is a
    local must be skipped — dataflow is out of scope."""
    src = tmp_path / "m.py"
    src.write_text(
        "def can_upgrade(loan):\n"
        "    threshold = 90\n"
        "    if loan.dpd < threshold:\n"
        "        return False\n"
        "    return True\n"
    )
    pm = parse_module(src)
    facts = list(extract_procedural(pm))
    elig = [r for r in facts if isinstance(r, RuleFact) and r.rule_kind == "eligibility"]
    assert elig == []
```

- [ ] **Step 2: Write the failing tests for Pattern B**

Append:

```python
def test_pattern_b_emits_eligibility_per_sufficient_trigger(tmp_path):
    """`if X: return True; ...; return False` → one eligibility rule
    per trigger with direct (not inverted) polarity."""
    src = tmp_path / "m.py"
    src.write_text(
        "def classify_loan_as_npe(loan):\n"
        "    if loan.ifrs_stage == 'ifrs_stage_3_impaired':\n"
        "        return True\n"
        "    if loan.is_defaulted:\n"
        "        return True\n"
        "    return False\n"
    )
    pm = parse_module(src)
    facts = list(extract_procedural(pm))
    elig = [r for r in facts if isinstance(r, RuleFact) and r.rule_kind == "eligibility"]
    triples = {(r.subject_attribute, r.predicate, r.object_value) for r in elig}
    assert ("ifrs_stage", "eq", "ifrs_stage_3_impaired") in triples
    assert ("is_defaulted", "required", True) in triples


def test_pattern_b_resolves_constant_rhs(tmp_path):
    """Pattern B + Pattern D: `if X == IFRS_STAGE_IMPAIRED` resolves
    the constant to its literal value."""
    src = tmp_path / "m.py"
    src.write_text(
        "IFRS_STAGE_IMPAIRED = 'ifrs_stage_3_impaired'\n"
        "def classify(loan):\n"
        "    if loan.ifrs_stage == IFRS_STAGE_IMPAIRED:\n"
        "        return True\n"
        "    return False\n"
    )
    pm = parse_module(src)
    facts = list(extract_procedural(pm))
    elig = [r for r in facts if isinstance(r, RuleFact) and r.rule_kind == "eligibility"]
    assert len(elig) == 1
    assert elig[0].object_value == "ifrs_stage_3_impaired"


def test_pattern_b_only_fires_on_extended_prefix_set(tmp_path):
    """`classify_*`, `determine_*`, etc. trigger Pattern B; plain
    function names don't."""
    src = tmp_path / "m.py"
    src.write_text(
        "def helper(loan):\n"  # not a recognised prefix
        "    if loan.is_defaulted:\n"
        "        return True\n"
        "    return False\n"
    )
    pm = parse_module(src)
    facts = list(extract_procedural(pm))
    elig = [r for r in facts if isinstance(r, RuleFact) and r.rule_kind == "eligibility"]
    assert elig == []
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_source_d_rich_extraction.py -v -k "pattern_a or pattern_b"`

Expected: all 8 new tests FAIL (no `_extract_multi_condition_returns` exists yet).

- [ ] **Step 4: Add the prefix constant and helper**

In `procedural_extractor.py`, near `_ELIGIBILITY_PREFIXES` (around line 34), add:

```python
_MULTI_ELIGIBILITY_PREFIXES = (
    "is_", "can_", "may_", "should_", "must_",
    "classify_", "determine_", "predict_", "decide_", "evaluate_",
)
```

Add the helper after `_extract_eligibility_return`:

```python
def _extract_multi_condition_returns(
    func: ast.FunctionDef,
    constants: dict[str, object],
    source: str,
    file: str,
) -> Iterable[RuleFact]:
    """Pattern A + B: multi-condition bool-returning functions.

    Walks ONLY top-level `if` statements (direct children of func.body)
    to avoid nested-under-guard false promotion (spec §10).

    Pattern A (conjunction): function body ends with `return True`.
    Each top-level `if X: return False` is a required condition.

    Pattern B (disjunction): function body ends with `return False`.
    Each top-level `if X: return True` is a sufficient trigger.

    Both patterns require the function name to start with one of
    _MULTI_ELIGIBILITY_PREFIXES.
    """
    if not func.name.startswith(_MULTI_ELIGIBILITY_PREFIXES):
        return
    if not func.body:
        return
    # Determine pattern direction from the terminal return.
    last = func.body[-1]
    if not isinstance(last, ast.Return) or not isinstance(last.value, ast.Constant):
        return
    if last.value.value is True:
        target_return = False   # Pattern A: if X -> return False
    elif last.value.value is False:
        target_return = True    # Pattern B: if X -> return True
    else:
        return

    param_names = {a.arg for a in func.args.args}

    for stmt in func.body:  # TOP-LEVEL ONLY — no ast.walk()
        if not isinstance(stmt, ast.If):
            continue
        if len(stmt.body) != 1:
            continue
        inner = stmt.body[0]
        if not isinstance(inner, ast.Return):
            continue
        if not isinstance(inner.value, ast.Constant) or inner.value.value is not target_return:
            continue

        # Extract subject + predicate + object_value from stmt.test.
        rule = _multi_condition_rule_from_test(
            stmt.test, target_return, param_names, constants, stmt, func, source, file,
        )
        if rule is not None:
            yield rule


def _multi_condition_rule_from_test(
    test: ast.expr,
    target_return: bool,
    param_names: set[str],
    constants: dict[str, object],
    if_node: ast.If,
    func: ast.FunctionDef,
    source: str,
    file: str,
) -> RuleFact | None:
    """Turn a single top-level `if <test>: return <target_return>` into a RuleFact.

    Polarity table for target_return=False (Pattern A, conjunction):
      - `if X: return False`         -> (required, False) on X (must be falsy)
      - `if not X: return False`     -> (required, True)  on X (must be truthy)
      - `if X <op> lit: return False` -> (inverted(op), lit) on X

    For target_return=True (Pattern B, disjunction):
      - `if X: return True`          -> (required, True)
      - `if X <op> lit: return True` -> (op, lit) direct
    """
    # Handle `if not X:` by stripping UnaryOp(Not, ...).
    negated = False
    raw = test
    if isinstance(raw, ast.UnaryOp) and isinstance(raw.op, ast.Not):
        negated = True
        raw = raw.operand

    # Case 1: bare subject (truthiness check).
    if not isinstance(raw, ast.Compare):
        subject = _resolve_subject(raw, param_names)
        if subject is None:
            return None
        # target_return=False, negated: `if not X: return False` -> X must be True
        # target_return=False, plain  : `if X: return False`     -> X must be False
        # target_return=True,  plain  : `if X: return True`      -> X must be True
        # target_return=True,  negated: `if not X: return True`  -> X must be False
        if target_return is False:
            object_value = True if negated else False
        else:
            object_value = False if negated else True
        return RuleFact(
            rule_kind="eligibility",
            subject_entity=None,
            subject_attribute=subject,
            predicate="required",
            object_value=object_value,
            expression=ast.unparse(test),
            evidence_span=_span(if_node, file, source),
            code_context=f"def {func.name}",
            confidence=0.75,
            extractor_family="procedural",
        )

    # Case 2: comparison <subject> <op> <lit>.
    if negated:
        # `if not (X <op> lit): return ...` — rare pattern, defer.
        return None
    if len(raw.ops) != 1:
        return None
    op_type = type(raw.ops[0])
    subject = _resolve_subject(raw.left, param_names)
    if subject is None:
        return None
    rhs_value = _resolve_constant(raw.comparators[0], constants)
    if rhs_value is _UNRESOLVED:
        return None

    if target_return is False:
        # Conjunction: if X <op> lit triggers FAIL, so X must satisfy NOT(op).
        if op_type not in _CMP_INVERSE:
            return None
        predicate = _CMP_INVERSE[op_type]
    else:
        # Disjunction: if X <op> lit triggers SUCCESS, so X satisfies (op) directly.
        if op_type not in _DIRECT_CMP:
            return None
        predicate = _DIRECT_CMP[op_type]

    return RuleFact(
        rule_kind="eligibility",
        subject_entity=None,
        subject_attribute=subject,
        predicate=predicate,
        object_value=rhs_value,
        expression=ast.unparse(test),
        evidence_span=_span(if_node, file, source),
        code_context=f"def {func.name}",
        confidence=0.75,
        extractor_family="procedural",
    )
```

- [ ] **Step 5: Wire into `extract_procedural`**

In `extract_procedural` (around line 232), modify the per-function loop to call the multi-condition extractor BEFORE the existing single-return eligibility / function-rules path. If multi-condition fires, skip the rest for that function to avoid double-emission.

Current loop structure (around lines 246-272):

```python
    for name, func in pm.functions.items():
        if exclude and glob_match(name, exclude):
            continue
        elig = _extract_eligibility_return(func, pm.source, file)
        if elig is not None:
            yield elig
            continue
        yielded_any = False
        for r in _extract_function_rules(func, pm.source, file):
            yielded_any = True
            yield r
        ...
```

Updated:

```python
    constants = _collect_module_constants(pm)  # already added in Task 3
    for name, func in pm.functions.items():
        if exclude and glob_match(name, exclude):
            continue
        # Pattern A + B: multi-condition bool-returning function.
        multi = list(_extract_multi_condition_returns(func, constants, pm.source, file))
        if multi:
            yield from multi
            yield from _extract_transition_assigns_procedural(func, pm.source, file)
            continue
        # Pattern: single-return eligibility (v1.2).
        elig = _extract_eligibility_return(func, pm.source, file)
        if elig is not None:
            yield elig
            continue
        # Existing v1.2 paths (function rules, transitions, weak fallback).
        yielded_any = False
        for r in _extract_function_rules(func, constants, pm.source, file):
            yielded_any = True
            yield r
        # ... rest unchanged
```

(The `yield from _extract_transition_assigns_procedural(...)` after the multi-condition yield ensures transitions inside the same function are still extracted — they live at a different AST shape and don't conflict with eligibility.)

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/test_source_d_rich_extraction.py -v -k "pattern_a or pattern_b"`

Expected: 8 PASS.

- [ ] **Step 7: Run existing procedural tests**

Run: `pytest tests/test_source_d_procedural_extractor.py -v`

Expected: no regressions. (Single-return eligibility still fires for `def is_eligible(b): return b["x"] >= 5`-style functions, which don't have a multi-condition body.)

- [ ] **Step 8: Commit**

```bash
git add src/ontozense/core/ingest/source_d/procedural_extractor.py tests/test_source_d_rich_extraction.py
git commit -m "feat(source-d): Pattern A + B multi-condition eligibility extraction (procedural)"
```

---

### Task 5: Pattern C — `errors.append` validation extraction (procedural)

**Files:**
- Modify: `src/ontozense/core/ingest/source_d/procedural_extractor.py` (add `_extract_errors_append_validations`, wire into `extract_procedural`)
- Test: `tests/test_source_d_rich_extraction.py` (append)

- [ ] **Step 1: Write the failing tests**

Append:

```python
def test_pattern_c_emits_validation_per_top_level_errors_append(tmp_path):
    """`if X <op> lit: errors.append(...)` at top level emits a
    validation rule with the inverted predicate."""
    src = tmp_path / "m.py"
    src.write_text(
        "def validate_payment(payment):\n"
        "    errors = []\n"
        "    if payment['amount'] <= 0:\n"
        "        errors.append('amount must be positive')\n"
        "    return errors\n"
    )
    pm = parse_module(src)
    facts = list(extract_procedural(pm))
    vals = [r for r in facts if isinstance(r, RuleFact) and r.rule_kind == "validation"]
    assert len(vals) == 1
    r = vals[0]
    assert r.subject_attribute == "amount"
    assert r.predicate == "gt"  # inverted from <=
    assert r.object_value == 0


def test_pattern_c_bare_param_attribute_truthiness(tmp_path):
    """`if X: errors.append(...)` with bare-attr LHS emits
    (required, False) — X must NOT be truthy."""
    src = tmp_path / "m.py"
    src.write_text(
        "def validate(event):\n"
        "    errors = []\n"
        "    if event.is_suspicious:\n"
        "        errors.append('suspicious')\n"
        "    return errors\n"
    )
    pm = parse_module(src)
    facts = list(extract_procedural(pm))
    vals = [r for r in facts if isinstance(r, RuleFact) and r.rule_kind == "validation"]
    assert len(vals) == 1
    assert vals[0].subject_attribute == "is_suspicious"
    assert vals[0].predicate == "required"
    assert vals[0].object_value is False


def test_pattern_c_skips_nested_under_guard(tmp_path):
    """`if outer: if inner: errors.append(...)` is SKIPPED entirely
    — neither inner nor outer rule is emitted (false-promotion
    avoidance per spec §10)."""
    src = tmp_path / "m.py"
    src.write_text(
        "def validate(event, loan):\n"
        "    errors = []\n"
        "    if loan.was_non_performing_at(event.start_date):\n"
        "        if event.classification == 'performing_forborne':\n"
        "            errors.append('illegal')\n"
        "    return errors\n"
    )
    pm = parse_module(src)
    facts = list(extract_procedural(pm))
    vals = [r for r in facts if isinstance(r, RuleFact) and r.rule_kind == "validation"]
    assert vals == []


def test_pattern_c_skips_non_validate_function_name(tmp_path):
    """Functions outside _VALIDATE_PREFIXES don't trigger Pattern C
    even if they use errors.append."""
    src = tmp_path / "m.py"
    src.write_text(
        "def normalize(payment):\n"
        "    errors = []\n"
        "    if payment['amount'] <= 0:\n"
        "        errors.append('bad')\n"
        "    return errors\n"
    )
    pm = parse_module(src)
    facts = list(extract_procedural(pm))
    vals = [r for r in facts if isinstance(r, RuleFact) and r.rule_kind == "validation"]
    assert vals == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_source_d_rich_extraction.py -v -k "pattern_c"`

Expected: 4 FAIL (no `_extract_errors_append_validations` exists).

- [ ] **Step 3: Implement the helper**

Add to `procedural_extractor.py` after `_extract_multi_condition_returns`:

```python
def _extract_errors_append_validations(
    func: ast.FunctionDef,
    constants: dict[str, object],
    source: str,
    file: str,
) -> Iterable[RuleFact]:
    """Pattern C: `if <guard>: errors.append(...)` validation pattern.

    Mirrors the existing `if <guard>: raise` extraction in
    _extract_function_rules but with errors.append as the violation
    signal. Top-level ifs ONLY — nested ifs are skipped (spec §10).

    Function name must match _VALIDATE_PREFIXES.
    """
    if not func.name.startswith(_VALIDATE_PREFIXES):
        return
    param_names = {a.arg for a in func.args.args}

    for stmt in func.body:  # TOP-LEVEL ONLY
        if not isinstance(stmt, ast.If):
            continue
        if not _body_is_single_errors_append(stmt.body):
            continue
        rule = _validation_rule_from_test(
            stmt.test, param_names, constants, stmt, func, source, file,
        )
        if rule is not None:
            yield rule


def _body_is_single_errors_append(body: list[ast.stmt]) -> bool:
    """Return True if body is exactly one Expression node whose value
    is a Call to `<name>.append(...)`."""
    if len(body) != 1:
        return False
    stmt = body[0]
    if not isinstance(stmt, ast.Expr):
        return False
    call = stmt.value
    if not isinstance(call, ast.Call):
        return False
    if not isinstance(call.func, ast.Attribute):
        return False
    return call.func.attr == "append"


def _validation_rule_from_test(
    test: ast.expr,
    param_names: set[str],
    constants: dict[str, object],
    if_node: ast.If,
    func: ast.FunctionDef,
    source: str,
    file: str,
) -> RuleFact | None:
    """Turn an `if <test>: errors.append(...)` into a validation RuleFact.

    Polarity (validation = the negation must hold):
      - `if X: errors.append(...)`          -> (required, False) on X
      - `if X <op> lit: errors.append(...)` -> (inverted(op), lit) on X
    """
    # Bare-subject truthiness branch.
    if not isinstance(test, ast.Compare):
        subject = _resolve_subject(test, param_names)
        if subject is None:
            return None
        return RuleFact(
            rule_kind="validation",
            subject_entity=None,
            subject_attribute=subject,
            predicate="required",
            object_value=False,
            expression=ast.unparse(test),
            evidence_span=_span(if_node, file, source),
            code_context=f"def {func.name}",
            confidence=0.8,
            extractor_family="procedural",
        )

    # Comparison branch.
    if len(test.ops) != 1:
        return None
    op_type = type(test.ops[0])
    if op_type not in _CMP_INVERSE:
        return None
    subject = _resolve_subject(test.left, param_names)
    if subject is None:
        return None
    rhs_value = _resolve_constant(test.comparators[0], constants)
    if rhs_value is _UNRESOLVED:
        return None
    return RuleFact(
        rule_kind="validation",
        subject_entity=None,
        subject_attribute=subject,
        predicate=_CMP_INVERSE[op_type],
        object_value=rhs_value,
        expression=ast.unparse(test),
        evidence_span=_span(if_node, file, source),
        code_context=f"def {func.name}",
        confidence=0.8,
        extractor_family="procedural",
    )
```

- [ ] **Step 4: Wire into `extract_procedural`**

Inside the per-function loop in `extract_procedural`, ADD the Pattern C extraction (after multi-condition, before single-return eligibility):

```python
        # Pattern C: validate_*/check_*/assert_* with errors.append(...) sites.
        for r in _extract_errors_append_validations(func, constants, pm.source, file):
            yield r
```

Place this RIGHT BEFORE the existing single-return eligibility check (`elig = _extract_eligibility_return(...)`). Pattern C and the existing `if/raise` validation path are non-overlapping by function body shape (raise vs errors.append), so they can both fire on the same function without double-emission.

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_source_d_rich_extraction.py -v -k "pattern_c"`

Expected: 4 PASS.

- [ ] **Step 6: Run existing procedural tests**

Run: `pytest tests/test_source_d_procedural_extractor.py -v`

Expected: no regressions.

- [ ] **Step 7: Commit**

```bash
git add src/ontozense/core/ingest/source_d/procedural_extractor.py tests/test_source_d_rich_extraction.py
git commit -m "feat(source-d): Pattern C errors.append validation extraction"
```

---

### Task 6: Patterns A + B (model) — multi-condition class methods

**Files:**
- Modify: `src/ontozense/core/ingest/source_d/model_extractor.py` (add `_MULTI_ELIGIBILITY_PREFIXES`, `_resolve_subject`, `_collect_module_constants`, `_resolve_constant`, `_UNRESOLVED`, `_extract_multi_condition_method`, `_multi_condition_rule_from_test_method`; wire into `extract_model`)
- Test: `tests/test_source_d_rich_extraction.py` (append)

- [ ] **Step 1: Write the failing tests**

Append:

```python
from ontozense.core.ingest.source_d.model_extractor import extract_model


def test_pattern_a_in_class_method_anchors_to_class(tmp_path):
    """Multi-condition eligibility in a class method: subject_entity
    is set to the enclosing class name (anchored)."""
    src = tmp_path / "m.py"
    src.write_text(
        "class LoanChecker:\n"
        "    def is_eligible(self, loan):\n"
        "        if not loan.is_non_performing:\n"
        "            return False\n"
        "        if loan.has_active_forbearance:\n"
        "            return False\n"
        "        return True\n"
    )
    pm = parse_module(src)
    facts = list(extract_model(pm))
    elig = [
        f for f in facts
        if isinstance(f, RuleFact) and f.rule_kind == "eligibility"
    ]
    assert len(elig) == 2
    for r in elig:
        assert r.subject_entity == "LoanChecker"


def test_pattern_b_in_class_method_anchors_to_class(tmp_path):
    """Pattern B classification inside a class method anchors to
    the class."""
    src = tmp_path / "m.py"
    src.write_text(
        "class Classifier:\n"
        "    def classify_npe(self, loan):\n"
        "        if loan.is_defaulted:\n"
        "            return True\n"
        "        if loan.ifrs_stage == 'impaired':\n"
        "            return True\n"
        "        return False\n"
    )
    pm = parse_module(src)
    facts = list(extract_model(pm))
    elig = [
        f for f in facts
        if isinstance(f, RuleFact) and f.rule_kind == "eligibility"
    ]
    assert len(elig) == 2
    for r in elig:
        assert r.subject_entity == "Classifier"


def test_class_method_pattern_d_resolves_module_constant(tmp_path):
    """Pattern D resolution works from inside class methods."""
    src = tmp_path / "m.py"
    src.write_text(
        "IFRS_IMPAIRED = 'impaired'\n"
        "class Classifier:\n"
        "    def classify_npe(self, loan):\n"
        "        if loan.ifrs_stage == IFRS_IMPAIRED:\n"
        "            return True\n"
        "        return False\n"
    )
    pm = parse_module(src)
    facts = list(extract_model(pm))
    elig = [
        f for f in facts
        if isinstance(f, RuleFact) and f.rule_kind == "eligibility"
    ]
    assert len(elig) == 1
    assert elig[0].object_value == "impaired"


def test_pattern_a_class_method_extracts_self_attribute(tmp_path):
    """`self.<attr>` is the canonical anchored subject form for class
    methods. Mirrors v1.2's _extract_eligibility_method contract.
    This test pins that `self` is INCLUDED in param_names so
    `self.is_non_performing` resolves correctly (Codex Finding 1)."""
    src = tmp_path / "m.py"
    src.write_text(
        "class Loan:\n"
        "    def is_eligible(self):\n"
        "        if not self.is_non_performing:\n"
        "            return False\n"
        "        if self.has_active_forbearance:\n"
        "            return False\n"
        "        return True\n"
    )
    pm = parse_module(src)
    facts = list(extract_model(pm))
    elig = [
        f for f in facts
        if isinstance(f, RuleFact) and f.rule_kind == "eligibility"
    ]
    assert len(elig) == 2
    triples = {(r.subject_attribute, r.predicate, r.object_value) for r in elig}
    assert ("is_non_performing", "required", True) in triples
    assert ("has_active_forbearance", "required", False) in triples
    for r in elig:
        assert r.subject_entity == "Loan"


def test_pattern_b_class_method_extracts_self_attribute_with_constant(tmp_path):
    """Pattern B + self.<attr> + Pattern D constant resolution
    all compose inside a class method."""
    src = tmp_path / "m.py"
    src.write_text(
        "STATUS_ACTIVE = 'active'\n"
        "class Loan:\n"
        "    def is_active(self):\n"
        "        if self.status == STATUS_ACTIVE:\n"
        "            return True\n"
        "        return False\n"
    )
    pm = parse_module(src)
    facts = list(extract_model(pm))
    elig = [
        f for f in facts
        if isinstance(f, RuleFact) and f.rule_kind == "eligibility"
    ]
    assert len(elig) == 1
    r = elig[0]
    assert r.subject_entity == "Loan"
    assert r.subject_attribute == "status"
    assert r.predicate == "eq"
    assert r.object_value == "active"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_source_d_rich_extraction.py -v -k "class_method or in_class_method"`

Expected: 5 FAIL.

- [ ] **Step 3: Add helpers to `model_extractor.py`**

In `model_extractor.py`, add at module scope alongside the existing v1.2 constants (around line 247):

```python
_MULTI_ELIGIBILITY_PREFIXES = (
    "is_", "can_", "may_", "should_", "must_",
    "classify_", "determine_", "predict_", "decide_", "evaluate_",
)

_UNRESOLVED = object()


def _collect_module_constants(pm: "ParsedModule") -> dict[str, object]:
    """Identical to procedural_extractor's helper — duplicated per v1.2
    convention. Future v1.3 may consolidate into a shared module."""
    out: dict[str, object] = {}
    for stmt in pm.tree.body:
        if not isinstance(stmt, ast.Assign):
            continue
        if len(stmt.targets) != 1:
            continue
        target = stmt.targets[0]
        if not isinstance(target, ast.Name):
            continue
        if not isinstance(stmt.value, ast.Constant):
            continue
        out[target.id] = stmt.value.value
    return out


def _resolve_constant(node: ast.expr, constants: dict[str, object]) -> object:
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name) and node.id in constants:
        return constants[node.id]
    return _UNRESOLVED


def _resolve_subject(expr: ast.expr, param_names: set[str]) -> str | None:
    if isinstance(expr, ast.Attribute):
        if isinstance(expr.value, ast.Name) and expr.value.id in param_names:
            return expr.attr
        return None
    if isinstance(expr, ast.Subscript):
        if not isinstance(expr.value, ast.Name) or expr.value.id not in param_names:
            return None
        slice_node = expr.slice
        if isinstance(slice_node, ast.Constant) and isinstance(slice_node.value, str):
            return slice_node.value
        return None
    if isinstance(expr, ast.Name):
        if expr.id in param_names:
            return expr.id
        return None
    return None
```

- [ ] **Step 4: Add `_extract_multi_condition_method` and its helper**

Add after `_extract_eligibility_method`:

```python
def _extract_multi_condition_method(
    cls_name: str,
    method: ast.FunctionDef,
    constants: dict[str, object],
    source: str,
    file: str,
) -> Iterable[RuleFact]:
    """Class-method analogue of procedural_extractor._extract_multi_condition_returns.

    subject_entity is set to cls_name (anchored). Otherwise identical
    pattern matching and polarity logic.
    """
    if not method.name.startswith(_MULTI_ELIGIBILITY_PREFIXES):
        return
    if not method.body:
        return
    last = method.body[-1]
    if not isinstance(last, ast.Return) or not isinstance(last.value, ast.Constant):
        return
    if last.value.value is True:
        target_return = False
    elif last.value.value is False:
        target_return = True
    else:
        return

    # INCLUDE `self` in param_names so `self.<attr>` resolves as a
    # valid LHS — this is the canonical anchored subject form for
    # class methods and matches v1.2's _extract_eligibility_method.
    # Other method parameters work the same way as procedural.
    param_names = {a.arg for a in method.args.args}

    for stmt in method.body:  # TOP-LEVEL ONLY
        if not isinstance(stmt, ast.If):
            continue
        if len(stmt.body) != 1:
            continue
        inner = stmt.body[0]
        if not isinstance(inner, ast.Return):
            continue
        if not isinstance(inner.value, ast.Constant) or inner.value.value is not target_return:
            continue

        rule = _multi_condition_rule_from_test_method(
            stmt.test, target_return, cls_name, param_names, constants,
            stmt, method, source, file,
        )
        if rule is not None:
            yield rule


def _multi_condition_rule_from_test_method(
    test: ast.expr,
    target_return: bool,
    cls_name: str,
    param_names: set[str],
    constants: dict[str, object],
    if_node: ast.If,
    method: ast.FunctionDef,
    source: str,
    file: str,
) -> RuleFact | None:
    """Per-condition rule builder for class methods. subject_entity is
    cls_name (anchored). Otherwise mirrors the procedural builder."""
    negated = False
    raw = test
    if isinstance(raw, ast.UnaryOp) and isinstance(raw.op, ast.Not):
        negated = True
        raw = raw.operand

    if not isinstance(raw, ast.Compare):
        subject = _resolve_subject(raw, param_names)
        if subject is None:
            return None
        if target_return is False:
            object_value = True if negated else False
        else:
            object_value = False if negated else True
        return RuleFact(
            rule_kind="eligibility",
            subject_entity=cls_name,
            subject_attribute=subject,
            predicate="required",
            object_value=object_value,
            expression=ast.unparse(test),
            evidence_span=_span(if_node, file, source),
            code_context=f"class {cls_name}, def {method.name}",
            confidence=0.75,
            extractor_family="model",
        )

    if negated:
        return None
    if len(raw.ops) != 1:
        return None
    op_type = type(raw.ops[0])
    subject = _resolve_subject(raw.left, param_names)
    if subject is None:
        return None
    rhs_value = _resolve_constant(raw.comparators[0], constants)
    if rhs_value is _UNRESOLVED:
        return None
    if target_return is False:
        if op_type not in _CMP_INVERSE:
            return None
        predicate = _CMP_INVERSE[op_type]
    else:
        if op_type not in _DIRECT_CMP:
            return None
        predicate = _DIRECT_CMP[op_type]
    return RuleFact(
        rule_kind="eligibility",
        subject_entity=cls_name,
        subject_attribute=subject,
        predicate=predicate,
        object_value=rhs_value,
        expression=ast.unparse(test),
        evidence_span=_span(if_node, file, source),
        code_context=f"class {cls_name}, def {method.name}",
        confidence=0.75,
        extractor_family="model",
    )
```

- [ ] **Step 5: Wire into `extract_model`**

In `extract_model` (around line 102), at the top of the function compute `constants` once per module:

```python
def extract_model(pm: ParsedModule, config: dict | None = None) -> Iterable[object]:
    ...
    constants = _collect_module_constants(pm)
    ...
```

Inside the per-class-method walk (find the place where `_extract_eligibility_method` is currently called for each method), ADD a call to `_extract_multi_condition_method` BEFORE the single-return eligibility check. If multi-condition fires, skip the single-return path for that method:

```python
                # Pattern A + B (multi-condition).
                multi = list(_extract_multi_condition_method(
                    cls_name, item, constants, pm.source, file,
                ))
                if multi:
                    yield from multi
                    continue
                # Single-return eligibility (v1.2).
                elig = _extract_eligibility_method(cls_name, item, pm.source, file)
                if elig is not None:
                    yield elig
                    continue
```

(Inspect the existing `extract_model` body to find the exact loop structure; the contract is: try multi-condition first, fall through to the existing v1.2 path if it doesn't fire.)

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/test_source_d_rich_extraction.py -v -k "class_method or in_class_method"`

Expected: 5 PASS.

- [ ] **Step 7: Run existing model tests**

Run: `pytest tests/test_source_d_model_extractor.py -v`

Expected: no regressions.

- [ ] **Step 8: Commit**

```bash
git add src/ontozense/core/ingest/source_d/model_extractor.py tests/test_source_d_rich_extraction.py
git commit -m "feat(source-d): Pattern A + B multi-condition extraction for class methods"
```

---

### Task 7: NPL acceptance test — end-to-end against spec ACs

**Files:**
- Create: `tests/test_source_d_npl_acceptance.py`

- [ ] **Step 1: Write the acceptance test**

Create `tests/test_source_d_npl_acceptance.py`:

```python
"""End-to-end acceptance test for v1.2.1 rich extraction against the
NPL demo fixtures at domains/npl/sources/npl-code/.

Pins the per-function rule counts from the spec §8 ACs:
- AC-R1: is_forbearance -> 2 eligibility rules
- AC-R2: can_upgrade_to_performing -> 3 eligibility rules
- AC-R3: classify_loan_as_npe -> 3 eligibility rules (incl. Pattern D)
- AC-R4: validate_forbearance_event -> 0 rules (nested-under-guard)
- AC-R5: can_exit_forborne_status -> 1 eligibility rule
- AC-R6: is_material_past_due -> 0 rules (local-var RHS)
"""
from pathlib import Path

from ontozense.core.ingest.ingest_d import SourceDIngester
from ontozense.core.ingest.base import ArtifactKind


NPL_CODE = Path(__file__).parent.parent / "domains" / "npl" / "sources" / "npl-code"


def _run_one(filename: str) -> list:
    """Run SourceDIngester on a single NPL file and return its candidate list."""
    path = NPL_CODE / filename
    return list(SourceDIngester().ingest({"files": [str(path)]}))


def _rules_for_function(cands: list, func_name: str) -> list:
    """Filter to non-suppressed RULE candidates emitted from a specific function."""
    return [
        c for c in cands
        if c.artifact_kind == ArtifactKind.RULE
        and not c.suppressed
        and c.rule_payload
        and c.rule_payload.get("code_context") == f"def {func_name}"
    ]


def test_ac_r1_is_forbearance_emits_two_eligibility_rules():
    cands = _run_one("forbearance/forbearance_validator.py")
    rules = _rules_for_function(cands, "is_forbearance")
    assert len(rules) == 2, f"expected 2 rules; got {len(rules)}: {[r.label for r in rules]}"
    subjects = {r.rule_payload["subject_attribute"] for r in rules}
    assert subjects == {"is_in_financial_difficulty", "is_concessionary"}
    for r in rules:
        assert r.rule_payload["rule_kind"] == "eligibility"
        assert r.rule_payload["predicate"] == "required"
        assert r.rule_payload["object_value"] is True


def test_ac_r2_can_upgrade_to_performing_emits_three_eligibility_rules():
    cands = _run_one("transitions/upgrade_rules.py")
    rules = _rules_for_function(cands, "can_upgrade_to_performing")
    assert len(rules) == 3, f"expected 3 rules; got {len(rules)}: {[r.label for r in rules]}"
    subjects = {r.rule_payload["subject_attribute"] for r in rules}
    assert subjects == {
        "is_non_performing",
        "has_active_forbearance",
        "improved_repayment_likelihood",
    }
    # Polarities:
    pred_by_subj = {r.rule_payload["subject_attribute"]: r.rule_payload for r in rules}
    assert pred_by_subj["is_non_performing"]["object_value"] is True
    assert pred_by_subj["has_active_forbearance"]["object_value"] is False
    assert pred_by_subj["improved_repayment_likelihood"]["object_value"] is True


def test_ac_r3_classify_loan_as_npe_emits_three_rules_with_constant_resolution():
    cands = _run_one("classification/npe_classifier.py")
    rules = _rules_for_function(cands, "classify_loan_as_npe")
    assert len(rules) == 3, f"expected 3 rules; got {len(rules)}"
    by_subj = {r.rule_payload["subject_attribute"]: r.rule_payload for r in rules}

    # Pattern D — IFRS_STAGE_IMPAIRED constant resolved.
    assert by_subj["ifrs_stage"]["object_value"] == "ifrs_stage_3_impaired"
    assert by_subj["ifrs_stage"]["predicate"] == "eq"

    # Bare-param truthiness checks (sufficient triggers for Pattern B).
    assert by_subj["is_defaulted"]["object_value"] is True
    assert by_subj["is_defaulted"]["predicate"] == "required"
    assert by_subj["unlikeliness_to_pay_flag"]["object_value"] is True


def test_ac_r4_validate_forbearance_event_emits_zero_structured_rules():
    """Nested-under-guard validation is skipped to avoid false promotion."""
    cands = _run_one("forbearance/forbearance_validator.py")
    rules = _rules_for_function(cands, "validate_forbearance_event")
    # The function itself still emits the weak validate_* fallback for
    # the function name. We assert NO structured validation rules
    # (i.e. no rule with a non-None subject_attribute).
    structured = [r for r in rules if r.rule_payload.get("subject_attribute") is not None]
    assert structured == [], f"expected 0 structured rules; got {[r.label for r in structured]}"


def test_ac_r5_can_exit_forborne_status_emits_one_eligibility_rule():
    cands = _run_one("transitions/upgrade_rules.py")
    rules = _rules_for_function(cands, "can_exit_forborne_status")
    assert len(rules) == 1, f"expected 1 rule; got {len(rules)}"
    r = rules[0]
    assert r.rule_payload["subject_attribute"] == "counterparty_still_in_difficulty"
    assert r.rule_payload["object_value"] is False  # `if X: return False` -> required not-X


def test_ac_r6_is_material_past_due_emits_zero_rules():
    """Single-return body but RHS is a local variable (dataflow OOS)."""
    cands = _run_one("classification/npe_classifier.py")
    rules = _rules_for_function(cands, "is_material_past_due")
    structured = [r for r in rules if r.rule_payload.get("subject_attribute") is not None]
    assert structured == []


def test_total_npl_rule_count_is_at_least_nine():
    """Aggregate AC: 9 deterministic rules across the six functions."""
    all_files = [
        "classification/npe_classifier.py",
        "forbearance/forbearance_validator.py",
        "transitions/upgrade_rules.py",
    ]
    total = 0
    for f in all_files:
        cands = _run_one(f)
        # Count non-suppressed RULE candidates with a structured subject.
        total += sum(
            1 for c in cands
            if c.artifact_kind == ArtifactKind.RULE
            and not c.suppressed
            and c.rule_payload
            and c.rule_payload.get("subject_attribute") is not None
        )
    assert total >= 9, f"expected ≥9 NPL rules across the three files; got {total}"
```

- [ ] **Step 2: Run the acceptance test**

Run: `pytest tests/test_source_d_npl_acceptance.py -v`

Expected: 7 PASS.

If any test fails, the most likely cause is a polarity or LHS-shape edge case in `_multi_condition_rule_from_test`. Re-check against the spec table in §4 before patching.

- [ ] **Step 3: Run the full suite for no regressions**

Run: `pytest --tb=no -q`

Expected: all green; total count up by ~41 tests (8 in Task 1, 7 in Task 2, 2 in Task 3, 8 in Task 4, 4 in Task 5, 5 in Task 6, 7 in Task 7 = 41 new tests total; existing 1000+ tests still pass).

- [ ] **Step 4: Commit**

```bash
git add tests/test_source_d_npl_acceptance.py
git commit -m "test(source-d): NPL fixture acceptance — 9 rules across 3 files (AC-R1..R7)"
```

---

### Task 8: Integration check — survey produces enriched candidate-graph

**Files:**
- No code changes — verification only.

- [ ] **Step 1: Run survey against the NPL domain**

Verify that running the existing NPL survey produces an enriched `candidate-graph.json`:

```powershell
ontozense survey --domain-dir domains/npl --source-d domains/npl/sources/npl-code
```

(Or invoke the equivalent build_candidate_graph call from Python if the CLI requires Source A.)

- [ ] **Step 2: Inspect the candidate-graph.json**

Open `domains/npl/discovery/candidate-graph.json` and verify:
- Multiple RULE concepts now appear with `rule_payload.rule_kind == "eligibility"`.
- The `code_context` field on each rule references the source NPL function (e.g. `"def is_forbearance"`, `"def classify_loan_as_npe"`).
- At least one rule has `object_value = 90` or `"ifrs_stage_3_impaired"` (Pattern D resolution working).

- [ ] **Step 3: No commit required**

This task is a manual verification step. If the JSON output looks correct, the v1.2.1 patch is functionally complete.

- [ ] **Step 4: Optional — record the survey output as a snapshot**

If desired, capture the survey's stderr output (including the new `Rules:` line introduced in v1.2 Task 27) as a sample for documentation:

```powershell
ontozense survey --domain-dir domains/npl --source-d domains/npl/sources/npl-code 2>&1 | Out-File domains/npl/discovery/survey-output.txt
```

Don't commit the survey-output.txt — it's a sanity check, not a deliverable.

---

## Self-Review

**Spec coverage:**
- AC-R1 — covered in Task 7 (`test_ac_r1_*`).
- AC-R2 — covered in Task 7 (`test_ac_r2_*`).
- AC-R3 — covered in Task 7 (`test_ac_r3_*`).
- AC-R4 — covered in Task 7 (`test_ac_r4_*`).
- AC-R5 — covered in Task 7 (`test_ac_r5_*`).
- AC-R6 — covered in Task 7 (`test_ac_r6_*`).
- AC-R7 (subject discipline preserved) — covered in Tasks 1, 4, 5, 6 (negative tests for module-level constants, method calls, locals).
- AC-R8 (existing tests stay green) — verified after every step's pytest run.
- AC-R9 (no LLM) — implicit; no `from openai` or LLM SDK imports added in any task.

**Pattern coverage:**
- Pattern A — implemented in Task 4 (procedural), Task 6 (model).
- Pattern B — implemented in Task 4 (procedural, shared with A), Task 6 (model).
- Pattern C — implemented in Task 5 (procedural only — no class-method `errors.append` pattern in spec).
- Pattern D — implemented in Tasks 2 (helpers), 3 (wired into existing extractor), 4 (consumed by multi-condition), 5 (consumed by validation), 6 (model).

**No placeholders.** Every step has executable code or an explicit command.

**Type consistency:** Helper signatures defined in the "Helper signatures" section are used consistently across Tasks 1–6. The `_UNRESOLVED` sentinel is defined once per module in Task 2 (procedural) and Task 6 (model).

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-20-source-d-rich-extraction.md`. Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
