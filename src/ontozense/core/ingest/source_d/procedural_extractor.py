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

# Direct (NOT inverted) op mapping for eligibility return predicates.
# The function returns True when the comparison holds — that IS the
# eligibility condition. Same convention as pipeline boolean masks.
_DIRECT_CMP = {
    ast.Lt: "lt", ast.LtE: "lte", ast.Gt: "gt", ast.GtE: "gte",
    ast.Eq: "eq", ast.NotEq: "neq",
}

_TRANSITION_FIELD_NAMES = frozenset({"status", "state", "phase", "stage", "lifecycle_state"})


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
    # LHS: subscript <param>["<field>"] OR bare ast.Name (param name).
    lhs = cmp.left
    attr: str | None = None
    if isinstance(lhs, ast.Subscript) and isinstance(lhs.slice, ast.Constant) and isinstance(lhs.slice.value, str):
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


def _extract_function_rules(func: ast.FunctionDef, source: str, file: str) -> Iterable[RuleFact]:
    for node in ast.walk(func):
        if isinstance(node, ast.If) and node.body:
            test = node.test
            if isinstance(test, ast.Compare) and len(test.ops) == 1 and type(test.ops[0]) in _CMP_INVERSE:
                attr = _key_from_subscript(test.left)
                if attr is None:
                    continue
                rhs = test.comparators[0]
                if not isinstance(rhs, ast.Constant):
                    continue
                if isinstance(node.body[0], ast.Raise):
                    yield RuleFact(
                        rule_kind="validation",
                        subject_entity=None,
                        subject_attribute=attr,
                        predicate=_CMP_INVERSE[type(test.ops[0])],
                        object_value=rhs.value,
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
                    and isinstance(first.value, ast.Constant)
                ):
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
                            object_value=first.value.value,
                            expression=ast.unparse(first),
                            evidence_span=_span(node, file, source),
                            code_context=f"def {func.name}",
                            confidence=0.85,
                            extractor_family="procedural",
                        )


def _extract_transition_assigns_procedural(func: ast.FunctionDef, source: str, file: str):
    """Yield RuleFacts for `if <guard>: <obj>["<status_field>"] = <literal>`
    in procedural code. Status field name must match the closed list."""
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
    for name, func in pm.functions.items():
        # Skip excluded functions entirely (consistent case-insensitive
        # glob behavior with other Source D config keys).
        if exclude and glob_match(name, exclude):
            continue
        # Eligibility path: is_*/can_*/may_*/should_*/must_* with
        # simple `return <Compare>` body.
        elig = _extract_eligibility_return(func, pm.source, file)
        if elig is not None:
            yield elig
            continue
        yielded_any = False
        for r in _extract_function_rules(func, pm.source, file):
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
