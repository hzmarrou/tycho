"""Dispatch stage — pick which extractor families to run for a parsed module."""
from __future__ import annotations

import ast

from .parse import ParsedModule

# Permissive set: the dispatcher flags pipeline-shaped modules even if
# we don't fully extract from non-pandas frameworks yet. v1.2's
# pipeline_extractor (Task 11) only handles pandas patterns; PySpark/
# Polars/Dask awareness is here so future tasks can extend without
# re-touching dispatch.
PANDAS_IMPORTS = {"pandas", "pyspark", "polars", "dask"}

_SQL_KEYWORDS = {"SELECT", "WITH", "CREATE", "INSERT", "UPDATE", "DELETE"}


def _looks_like_sql(value: str) -> bool:
    """Cheap heuristic: string starts with a top-level SQL keyword.

    Used by the dispatcher to decide whether to run the pipeline
    extractor. The pipeline extractor itself (Task 12) re-validates
    with sqlglot — false positives here are cheap (extra extractor
    call), false negatives skip extraction silently, so we err on
    the permissive side.
    """
    if not isinstance(value, str):
        return False
    head = value.strip().split(None, 1)
    return bool(head) and head[0].upper() in _SQL_KEYWORDS


def _module_has_sql_string(pm: ParsedModule) -> bool:
    for node in ast.walk(pm.tree):
        if isinstance(node, ast.Constant) and _looks_like_sql(node.value):
            return True
    return False


def select_families(pm: ParsedModule) -> list[str]:
    """Return the ordered list of extractor families to run for this module.

    A module may match multiple families (e.g. a class file that also
    contains pandas calls runs both 'model' and 'pipeline'). Order is
    deterministic: model → pipeline → procedural.

    Pipeline selection fires on either:
      - imports of a DataFrame library (PANDAS_IMPORTS), or
      - a string literal in the module body that looks like SQL
        (matched by the _looks_like_sql heuristic; the pipeline
        extractor re-validates with sqlglot).
    """
    fams: list[str] = []
    if pm.classes:
        fams.append("model")
    if (pm.imports & PANDAS_IMPORTS) or _module_has_sql_string(pm):
        fams.append("pipeline")
    if pm.functions:
        fams.append("procedural")
    return fams
