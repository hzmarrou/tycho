"""Dispatch stage — pick which extractor families to run for a parsed module."""
from __future__ import annotations

from .parse import ParsedModule

# Permissive set: the dispatcher flags pipeline-shaped modules even if
# we don't fully extract from non-pandas frameworks yet. v1.2's
# pipeline_extractor (Task 11) only handles pandas patterns; PySpark/
# Polars/Dask awareness is here so future tasks can extend without
# re-touching dispatch.
PANDAS_IMPORTS = {"pandas", "pyspark", "polars", "dask"}


def select_families(pm: ParsedModule) -> list[str]:
    """Return the ordered list of extractor families to run for this module.

    A module may match multiple families (e.g. a class file that also
    contains pandas calls runs both 'model' and 'pipeline'). Order is
    deterministic: model → pipeline → procedural.
    """
    fams: list[str] = []
    if pm.classes:
        fams.append("model")
    if pm.imports & PANDAS_IMPORTS:
        fams.append("pipeline")
    if pm.functions:
        fams.append("procedural")
    return fams
