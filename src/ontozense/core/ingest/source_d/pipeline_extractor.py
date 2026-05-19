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


def _collect_df_names(pm: ParsedModule) -> set[str]:
    """Build the set of identifiers in the module that are known
    DataFrame-typed via parameter annotations. Falls back to {"df"}
    if no annotations are present so the conventional naming still
    works for unannotated pandas code.

    This is a conservative scope guard: the pipeline extractors only
    emit facts when the subscript receiver is in this set, preventing
    `config["x"] = "y"` style dict assignments from being treated as
    DataFrame derived columns.
    """
    names: set[str] = set()
    for node in ast.walk(pm.tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for arg in node.args.args:
            if _is_dataframe_annotation(arg.annotation):
                names.add(arg.arg)
    if not names:
        names.add("df")
    return names


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


def _extract_dropna(call: ast.Call, source: str, file: str) -> Iterable[RuleFact]:
    """df.dropna(subset=["col", ...]) -> validation required rules."""
    if not (isinstance(call.func, ast.Attribute) and call.func.attr == "dropna"):
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


def extract_pipeline(pm: ParsedModule) -> Iterable[object]:
    file = str(pm.path)
    df_names = _collect_df_names(pm)
    for node in ast.walk(pm.tree):
        if isinstance(node, ast.Subscript):
            yield from _extract_boolean_mask(node, df_names, pm.source, file)
        elif isinstance(node, ast.Assign):
            yield from _extract_derived_column(node, df_names, pm.source, file)
        elif isinstance(node, ast.Call):
            yield from _extract_dropna(node, pm.source, file)
        elif isinstance(node, ast.Constant):
            yield from _extract_embedded_sql(node, pm.source, file)
