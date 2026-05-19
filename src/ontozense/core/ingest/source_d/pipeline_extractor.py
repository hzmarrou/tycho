"""Pipeline family — pandas DataFrame operations.

v1.2 supports pandas only. PySpark / Polars / Dask are deferred to a
later release. The dispatcher in source_d/dispatch.py recognises those
import names so a future task can light up adapters without revisiting
dispatch.
"""
from __future__ import annotations

import ast
from collections.abc import Iterable

import sqlglot
import sqlglot.expressions as exp

from .ir import AttributeFact, EvidenceSpan, RuleFact
from .parse import ParsedModule

# Direct mapping (NOT inverted): a boolean mask `df[df["x"] > 0]`
# expresses the kept-rows condition. The procedural / model extractors
# invert because they handle if/raise guards; here, the comparison is
# already the validation predicate.
_CMP = {
    ast.Lt: "lt", ast.LtE: "lte", ast.Gt: "gt", ast.GtE: "gte",
    ast.Eq: "eq", ast.NotEq: "neq",
}

_SQL_CMP = {
    exp.GT: "gt", exp.GTE: "gte", exp.LT: "lt", exp.LTE: "lte",
    exp.EQ: "eq", exp.NEQ: "neq",
}


def _span(node: ast.AST, file: str, source: str) -> EvidenceSpan:
    start = getattr(node, "lineno", 1)
    end = getattr(node, "end_lineno", start)
    snippet = ast.get_source_segment(source, node) or ""
    return EvidenceSpan(file=file, start_line=start, end_line=end, snippet=snippet[:200])


def _is_dataframe_annotation(node: ast.expr | None) -> bool:
    """Recognise `pd.DataFrame`, `pandas.DataFrame`, or bare `DataFrame`
    as a parameter annotation."""
    if node is None:
        return False
    if isinstance(node, ast.Attribute) and node.attr == "DataFrame":
        return True
    if isinstance(node, ast.Name) and node.id == "DataFrame":
        return True
    return False


def _function_df_names(func: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    """Return parameter names in ``func`` annotated as ``pd.DataFrame``
    or bare ``DataFrame``. Empty set means the function has no
    DataFrame-annotated params — callers should fall back to the
    enclosing scope."""
    return {
        arg.arg for arg in func.args.args
        if _is_dataframe_annotation(arg.annotation)
    }


def _strict_df_column(node: ast.expr, df_names: set[str]) -> str | None:
    """Return the column name for ``<receiver>["<col>"]`` only when
    ``<receiver>`` is an ``ast.Name`` in ``df_names``. Returns None for
    any other shape, including subscripts on non-DataFrame receivers
    like ``config["x"]``."""
    col = _df_subscript_column(node)
    if col is None:
        return None
    if not (isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name)):
        return None
    if node.value.id not in df_names:
        return None
    return col


def _df_subscript_column(node: ast.expr) -> str | None:
    """Return column name for `<df>["<col>"]` shaped as `ast.Subscript`
    with a string-literal slice. Returns None for non-string slices,
    non-subscripts, or computed keys."""
    if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant):
        return node.slice.value if isinstance(node.slice.value, str) else None
    return None


def _extract_boolean_mask(node: ast.Subscript, df_names: set[str], source: str, file: str) -> Iterable[RuleFact]:
    """df[df["col"] <op> <literal>] -> validation rule on <col>."""
    # Outer receiver must be a DataFrame name (e.g. df[...]).
    if not (isinstance(node.value, ast.Name) and node.value.id in df_names):
        return
    sl = node.slice
    if not isinstance(sl, ast.Compare) or len(sl.ops) != 1:
        return
    col = _strict_df_column(sl.left, df_names)
    if col is None:
        return
    op = type(sl.ops[0])
    if op not in _CMP:
        return
    rhs = sl.comparators[0]
    if not isinstance(rhs, ast.Constant):
        return
    yield RuleFact(
        rule_kind="validation",
        subject_entity=None,
        subject_attribute=col,
        predicate=_CMP[op],
        object_value=rhs.value,
        expression=ast.unparse(sl),
        evidence_span=_span(node, file, source),
        code_context="dataframe filter",
        confidence=0.85,
        extractor_family="pipeline",
    )


def _extract_derived_column(stmt: ast.Assign, df_names: set[str], source: str, file: str) -> Iterable[object]:
    """df["new"] = <expr> -> AttributeFact + derivation rule."""
    if len(stmt.targets) != 1:
        return
    tgt = stmt.targets[0]
    col = _strict_df_column(tgt, df_names)
    if col is None:
        return
    yield AttributeFact(
        name=col,
        evidence_span=_span(stmt, file, source),
        extractor_family="pipeline",
    )
    deps: list[str] = []
    for node in ast.walk(stmt.value):
        c = _strict_df_column(node, df_names)
        if c:
            deps.append(c)
    yield RuleFact(
        rule_kind="derivation",
        subject_entity=None,
        subject_attribute=col,
        predicate="derived_from",
        object_value=ast.unparse(stmt.value),
        condition=None,
        depends_on=deps,
        expression=f"{col} = {ast.unparse(stmt.value)}",
        evidence_span=_span(stmt, file, source),
        code_context="derived column",
        confidence=0.8,
        extractor_family="pipeline",
    )


def _extract_dropna(call: ast.Call, df_names: set[str], source: str, file: str) -> Iterable[RuleFact]:
    """df.dropna(subset=["col", ...]) -> validation required rules.

    Receiver must be a tracked DataFrame name — otherwise a custom
    class that happens to expose `.dropna(subset=...)` would leak
    required rules into the candidate graph.
    """
    if not (isinstance(call.func, ast.Attribute) and call.func.attr == "dropna"):
        return
    if not (isinstance(call.func.value, ast.Name) and call.func.value.id in df_names):
        return
    for kw in call.keywords:
        if kw.arg == "subset" and isinstance(kw.value, ast.List):
            for item in kw.value.elts:
                if isinstance(item, ast.Constant) and isinstance(item.value, str):
                    yield RuleFact(
                        rule_kind="validation",
                        subject_entity=None,
                        subject_attribute=item.value,
                        predicate="required",
                        object_value=True,
                        expression=ast.unparse(call),
                        evidence_span=_span(call, file, source),
                        code_context="dropna(subset=...)",
                        confidence=0.9,
                        extractor_family="pipeline",
                    )


def _looks_like_sql(s: str) -> bool:
    """Cheap heuristic mirroring the dispatcher: string starts with a
    top-level SQL keyword. Prevents calling sqlglot.parse_one on every
    string literal in the module."""
    head = s.strip().split(None, 1)
    # Must stay in sync with dispatch._SQL_KEYWORDS.
    return bool(head) and head[0].upper() in {"SELECT", "WITH", "CREATE", "INSERT", "UPDATE", "DELETE"}


def _extract_embedded_sql(node: ast.Constant, source: str, file: str) -> Iterable[RuleFact]:
    """String literal -> sqlglot parse -> validation rules from WHERE.

    Subject_entity is the FROM table — unlike the pandas extractors,
    embedded SQL gives us explicit table anchoring, so the rules
    emitted here are anchored at IR time.
    """
    if not isinstance(node.value, str) or not _looks_like_sql(node.value):
        return
    try:
        parsed = sqlglot.parse_one(node.value)
    except Exception:
        return
    table_name: str | None = None
    for t in parsed.find_all(exp.Table):
        table_name = t.name
        break
    where = parsed.find(exp.Where)
    if not where:
        return
    for cmp_node in where.find_all(tuple(_SQL_CMP.keys())):
        left, right = cmp_node.this, cmp_node.expression
        if not isinstance(left, exp.Column) or not isinstance(right, exp.Literal):
            continue
        try:
            value = int(right.this) if right.is_int else float(right.this)
        except (TypeError, ValueError):
            value = right.this
        yield RuleFact(
            rule_kind="validation",
            subject_entity=table_name,
            subject_attribute=left.name,
            predicate=_SQL_CMP[type(cmp_node)],
            object_value=value,
            expression=cmp_node.sql(),
            evidence_span=_span(node, file, source),
            code_context="embedded SQL WHERE",
            confidence=0.85,
            extractor_family="pipeline",
        )


def _extract_apply_lambda(call: ast.Call, df_names: set[str], source: str, file: str) -> Iterable[RuleFact]:
    """``df["<col>"].apply(lambda p: <a> if <cond> else <b>)`` -> validation rule.

    The lambda's condition is interpreted as a domain-meaningful
    threshold on the source column (the lambda param is implicitly
    bound to the column's values). Confidence is intentionally lower
    than the boolean-mask path (0.7 vs 0.85) because the lambda's
    semantic intent is inferred, not stated.
    """
    if not (isinstance(call.func, ast.Attribute) and call.func.attr == "apply"):
        return
    col = _strict_df_column(call.func.value, df_names)
    if col is None:
        return
    if not (call.args and isinstance(call.args[0], ast.Lambda)):
        return
    lam = call.args[0]
    if not lam.args.args:
        return
    param_name = lam.args.args[-1].arg
    if not isinstance(lam.body, ast.IfExp):
        return
    cond = lam.body.test
    if not (isinstance(cond, ast.Compare) and len(cond.ops) == 1):
        return
    op = type(cond.ops[0])
    if op not in _CMP:
        return
    lhs = cond.left
    if not (isinstance(lhs, ast.Name) and lhs.id == param_name):
        return
    rhs = cond.comparators[0]
    if not isinstance(rhs, ast.Constant):
        return
    yield RuleFact(
        rule_kind="validation",
        subject_entity=None,
        subject_attribute=col,
        predicate=_CMP[op],
        object_value=rhs.value,
        expression=ast.unparse(cond),
        evidence_span=_span(call, file, source),
        code_context=f"apply lambda on {col}",
        confidence=0.7,
        extractor_family="pipeline",
    )


def _walk_with_scope(
    node: ast.AST,
    df_names: set[str],
    source: str,
    file: str,
) -> Iterable[object]:
    """Recursively walk ``node``, switching ``df_names`` scope on
    function entry. Function-scoped tracking prevents cross-function
    name collisions (one function's annotated ``frame: DataFrame``
    must not pollute another function's local ``frame`` dict).
    """
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        local = _function_df_names(node)
        # No DataFrame-annotated params → inherit parent scope.
        # Empty inherited scope is fine; the receiver check still fails.
        scope = local if local else df_names
        for stmt in node.body:
            yield from _walk_with_scope(stmt, scope, source, file)
        return

    if isinstance(node, ast.Subscript):
        yield from _extract_boolean_mask(node, df_names, source, file)
    elif isinstance(node, ast.Assign):
        yield from _extract_derived_column(node, df_names, source, file)
    elif isinstance(node, ast.Call):
        yield from _extract_dropna(node, df_names, source, file)
        yield from _extract_apply_lambda(node, df_names, source, file)
    elif isinstance(node, ast.Constant):
        yield from _extract_embedded_sql(node, source, file)

    for child in ast.iter_child_nodes(node):
        yield from _walk_with_scope(child, df_names, source, file)


def extract_pipeline(pm: ParsedModule) -> Iterable[object]:
    """Walk the module recursively, tracking DataFrame names per function.

    Module-level scope falls back to the ``"df"`` convention so bare-
    pandas code (no type annotations) still produces extractions.
    Function-scoped overrides happen inside ``_walk_with_scope``.
    """
    file = str(pm.path)
    initial = {"df"}
    for stmt in pm.tree.body:
        yield from _walk_with_scope(stmt, initial, pm.source, file)
