"""Procedural family — module-level functions, guard clauses, defaults.

Three patterns (spec §6.3, §9.1):
  - if <param>["<key>"] <op> <literal>: raise  ->  validation rule
  - if <param>.get("<key>") is None: <param>["<key>"] = <literal>  ->  defaulting rule
  - validate_*/check_*/assert_* functions with no extractable body  ->  weak rule

subject_entity is intentionally None at IR time; the anchor layer
(Task 13) resolves or suppresses. Bare ast.Name comparisons are NOT
extracted — that would over-promote local temporaries (same discipline
as model_extractor after Task 9 fix 82d5e12).
"""
from __future__ import annotations

import ast
from collections.abc import Iterable

from ontozense.core.ingest.filters import glob_match

from .ir import EvidenceSpan, RuleFact
from .parse import ParsedModule

_CMP_INVERSE = {
    ast.Lt: "gte",
    ast.LtE: "gt",
    ast.Gt: "lte",
    ast.GtE: "lt",
    ast.Eq: "neq",
    ast.NotEq: "eq",
}

_VALIDATE_PREFIXES = ("validate_", "check_", "assert_")

_ELIGIBILITY_PREFIXES = ("is_", "can_", "may_", "should_", "must_")

_MULTI_ELIGIBILITY_PREFIXES = _ELIGIBILITY_PREFIXES + (
    "classify_",
    "determine_",
    "predict_",
    "decide_",
    "evaluate_",
)

# Direct (NOT inverted) op mapping for eligibility return predicates.
# The function returns True when the comparison holds — that IS the
# eligibility condition. Same convention as pipeline boolean masks.
_DIRECT_CMP = {
    ast.Lt: "lt", ast.LtE: "lte", ast.Gt: "gt", ast.GtE: "gte",
    ast.Eq: "eq", ast.NotEq: "neq",
}

_TRANSITION_FIELD_NAMES = frozenset({"status", "state", "phase", "stage", "lifecycle_state"})

_UNRESOLVED = object()


def _collect_module_constants(pm: ParsedModule) -> dict[str, object]:
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


def _span(node: ast.AST, file: str, source: str) -> EvidenceSpan:
    start = getattr(node, "lineno", 1)
    end = getattr(node, "end_lineno", start)
    snippet = ast.get_source_segment(source, node) or ""
    return EvidenceSpan(file=file, start_line=start, end_line=end, snippet=snippet[:200])


def _key_from_subscript(node: ast.expr) -> str | None:
    """Extract the string key from `<obj>["<key>"]`. Returns None if shape
    doesn't match or the slice isn't a string literal."""
    if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant):
        return node.slice.value if isinstance(node.slice.value, str) else None
    return None


def _is_get_is_none(test: ast.expr) -> tuple[str, str] | None:
    """Detect `<obj>.get("<key>") is None`. Return ``(obj_repr, key)``
    or ``None``. The ``obj_repr`` is the ``ast.unparse`` of the receiver
    so the consumer can verify the assignment target is the SAME
    object indexed at the SAME key."""
    if not (isinstance(test, ast.Compare) and len(test.ops) == 1 and isinstance(test.ops[0], ast.Is)):
        return None
    left, right = test.left, test.comparators[0]
    if not (isinstance(right, ast.Constant) and right.value is None):
        return None
    if isinstance(left, ast.Call) and isinstance(left.func, ast.Attribute) and left.func.attr == "get":
        if left.args and isinstance(left.args[0], ast.Constant) and isinstance(left.args[0].value, str):
            obj_repr = ast.unparse(left.func.value)
            return obj_repr, left.args[0].value
    return None


def _extract_eligibility_return(func: ast.FunctionDef, source: str, file: str) -> "RuleFact | None":
    """If ``func`` has an eligibility-prefixed name AND its body is a single
    ``return <Compare>`` over a subscript or self-attribute with a literal RHS,
    return an eligibility RuleFact. Otherwise None."""
    if not func.name.startswith(_ELIGIBILITY_PREFIXES):
        return None
    # Body should be a single Return whose value is a Compare.
    # Allow leading docstring / module-level constants would be unusual
    # in a function body, so just check the last statement.
    if not func.body:
        return None
    last = func.body[-1]
    if not isinstance(last, ast.Return) or not isinstance(last.value, ast.Compare):
        return None
    cmp = last.value
    if len(cmp.ops) != 1:
        return None
    op = type(cmp.ops[0])
    if op not in _DIRECT_CMP:
        return None
    rhs = cmp.comparators[0]
    if not isinstance(rhs, ast.Constant):
        return None
    # LHS: subscript <param>["<field>"] — receiver must be a function parameter.
    # Module-level constants (e.g. THRESHOLDS["x"]) are rejected because THRESHOLDS
    # is not in param_names. self.config["x"] is also rejected because lhs.value is
    # ast.Attribute, not ast.Name. (Spec §4.4, §9.2.)
    lhs = cmp.left
    attr: str | None = None
    param_names = {a.arg for a in func.args.args}
    if (
        isinstance(lhs, ast.Subscript)
        and isinstance(lhs.slice, ast.Constant)
        and isinstance(lhs.slice.value, str)
        and isinstance(lhs.value, ast.Name)
        and lhs.value.id in param_names
    ):
        attr = lhs.slice.value
    # Skip bare-name LHS in procedural — same discipline as Task 9 fix.
    if attr is None:
        return None
    return RuleFact(
        rule_kind="eligibility",
        subject_entity=None,
        subject_attribute=attr,
        predicate=_DIRECT_CMP[op],
        object_value=rhs.value,
        expression=ast.unparse(cmp),
        evidence_span=_span(func, file, source),
        code_context=f"def {func.name}",
        confidence=0.85,
        extractor_family="procedural",
    )


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
) -> "RuleFact | None":
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


def _extract_function_rules(
    func: ast.FunctionDef,
    constants: dict[str, object],
    source: str,
    file: str,
) -> Iterable[RuleFact]:
    for node in ast.walk(func):
        if isinstance(node, ast.If) and node.body:
            test = node.test
            if isinstance(test, ast.Compare) and len(test.ops) == 1 and type(test.ops[0]) in _CMP_INVERSE:
                attr = _key_from_subscript(test.left)
                if attr is None:
                    continue
                rhs_value = _resolve_constant(test.comparators[0], constants)
                if rhs_value is _UNRESOLVED:
                    continue
                if isinstance(node.body[0], ast.Raise):
                    yield RuleFact(
                        rule_kind="validation",
                        subject_entity=None,
                        subject_attribute=attr,
                        predicate=_CMP_INVERSE[type(test.ops[0])],
                        object_value=rhs_value,
                        expression=ast.unparse(test),
                        evidence_span=_span(node, file, source),
                        code_context=f"def {func.name}",
                        confidence=0.8,
                        extractor_family="procedural",
                    )
            detected = _is_get_is_none(test)
            if detected is not None and node.body:
                obj_repr, key = detected
                first = node.body[0]
                if (
                    isinstance(first, ast.Assign)
                    and len(first.targets) == 1
                ):
                    default_value = _resolve_constant(first.value, constants)
                    if default_value is _UNRESOLVED:
                        continue
                    tgt = first.targets[0]
                    # Assignment target must be <same_obj>["<same_key>"]
                    # — otherwise the if-block is doing something other
                    # than defaulting the field that was tested.
                    if (
                        isinstance(tgt, ast.Subscript)
                        and isinstance(tgt.slice, ast.Constant)
                        and tgt.slice.value == key
                        and ast.unparse(tgt.value) == obj_repr
                    ):
                        yield RuleFact(
                            rule_kind="defaulting",
                            subject_entity=None,
                            subject_attribute=key,
                            predicate="default_to",
                            object_value=default_value,
                            expression=ast.unparse(first),
                            evidence_span=_span(node, file, source),
                            code_context=f"def {func.name}",
                            confidence=0.85,
                            extractor_family="procedural",
                        )


def _extract_transition_assigns_procedural(func: ast.FunctionDef, source: str, file: str):
    """Yield RuleFacts for `if <guard>: <obj>["<status_field>"] = <literal>`
    in procedural code. Status field name must match the closed list.
    The subscript receiver must be a function parameter — module-level
    constants (e.g. CONFIG["status"]) are rejected. (Spec §4.4, §9.2.)
    The guard expression is captured as `condition` so that different
    guards on the same field produce distinct merge_keys. (Spec §11.1.)"""
    param_names = {a.arg for a in func.args.args}  # compute once per function
    for node in ast.walk(func):
        if not (isinstance(node, ast.If) and node.body):
            continue
        for stmt in node.body:
            if not isinstance(stmt, ast.Assign) or len(stmt.targets) != 1:
                continue
            tgt = stmt.targets[0]
            if not (
                isinstance(tgt, ast.Subscript)
                and isinstance(tgt.slice, ast.Constant)
                and isinstance(tgt.slice.value, str)
                and tgt.slice.value in _TRANSITION_FIELD_NAMES
                and isinstance(tgt.value, ast.Name)
                and tgt.value.id in param_names
            ):
                continue
            if not isinstance(stmt.value, ast.Constant):
                continue
            yield RuleFact(
                rule_kind="transition",
                subject_entity=None,
                subject_attribute=tgt.slice.value,
                predicate="transitions_to",
                object_value=stmt.value.value,
                condition=ast.unparse(node.test),
                expression=ast.unparse(stmt),
                evidence_span=_span(node, file, source),
                code_context=f"def {func.name}",
                confidence=0.85,
                extractor_family="procedural",
            )


def extract_procedural(pm: ParsedModule, config: dict | None = None) -> Iterable[RuleFact]:
    config = config or {}
    exclude = list(config.get("exclude_functions", []) or [])
    force = list(config.get("force_rule", []) or [])
    file = str(pm.path)
    constants = _collect_module_constants(pm)
    for name, func in pm.functions.items():
        # Skip excluded functions entirely (consistent case-insensitive
        # glob behavior with other Source D config keys).
        if exclude and glob_match(name, exclude):
            continue
        # Pattern A + B: multi-condition bool-returning function.
        multi = list(_extract_multi_condition_returns(func, constants, pm.source, file))
        if multi:
            yield from multi
            yield from _extract_transition_assigns_procedural(func, pm.source, file)
            continue
        # Eligibility path: is_*/can_*/may_*/should_*/must_* with
        # simple `return <Compare>` body.
        elig = _extract_eligibility_return(func, pm.source, file)
        if elig is not None:
            yield elig
            continue
        yielded_any = False
        for r in _extract_function_rules(func, constants, pm.source, file):
            yielded_any = True
            yield r
        # Transition extraction runs alongside _extract_function_rules
        # (a function can have both `if amount <= 0: raise` AND
        # `if approved: payment["status"] = "PAID"`).
        for t in _extract_transition_assigns_procedural(func, pm.source, file):
            yielded_any = True
            yield t
        # Weak-rule fallback: validate_*/check_*/assert_* OR force_rule glob.
        if not yielded_any and (
            name.startswith(_VALIDATE_PREFIXES)
            or (force and glob_match(name, force))
        ):
            yield RuleFact(
                rule_kind="validation",
                subject_entity=None,
                subject_attribute=None,
                predicate="required",
                object_value=name,
                expression=name,
                evidence_span=_span(func, file, pm.source),
                code_context=f"def {name}",
                confidence=0.4,
                extractor_family="procedural",
            )
