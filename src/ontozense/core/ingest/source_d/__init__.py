"""Source D v1.2 — shape-adaptive executable rule extractor.

Six-stage pipeline: parse -> dispatch -> lift to IR -> anchor/filter -> emit -> optional LLM normalize.
See docs/superpowers/specs/2026-05-19-source-d-v1.2-executable-rule-extraction-design.md.

``run()`` is the public entry point used by SourceDIngester (Task 15).
"""
from __future__ import annotations

import logging
from collections.abc import Iterable
from pathlib import Path

logger = logging.getLogger(__name__)

from ontozense.core.ingest.base import IntermediateCandidate

from .anchor import anchor_facts
from .dispatch import select_families
from .emit import emit_candidates
from .model_extractor import extract_model
from .parse import parse_module
from .pipeline_extractor import extract_pipeline
from .procedural_extractor import extract_procedural

_EXTRACTORS = {
    "pipeline": extract_pipeline,
}


def run(
    path: Path,
    config: dict | None = None,
    llm=None,
) -> Iterable[IntermediateCandidate]:
    """Run the six-stage Source D pipeline against a single Python file.

    parse -> dispatch -> extract per family -> anchor -> emit -> optional LLM normalize.

    ``llm`` is the optional rephraser. When None (the default),
    normalize_labels is a no-op and the deterministic extraction
    is unchanged (AC9).

    SyntaxError or UnicodeDecodeError on parse: log a warning and skip
    the file (matches v1.1 SourceDIngester tolerance).
    """
    config = config or {}
    try:
        pm = parse_module(path)
    except (SyntaxError, UnicodeDecodeError) as exc:
        # Match v1.1 SourceDIngester tolerance: log and skip on any
        # parse/decode failure rather than abort the whole batch. The
        # `parse_module` contract leaves error policy to the caller.
        logger.warning("Source D: skipping %s (%s)", path, exc)
        return
    families = select_families(pm)
    if config.get("rule_extractors"):
        families = [f for f in families if f in set(config["rule_extractors"])]
    facts: list[object] = []
    for fam in families:
        if fam == "model":
            facts.extend(extract_model(pm, config))
        elif fam == "procedural":
            facts.extend(extract_procedural(pm, config))
        else:
            facts.extend(_EXTRACTORS[fam](pm))
    anchored, suppressed = anchor_facts(facts)
    candidates = emit_candidates(anchored, suppressed)
    from .normalize import normalize_labels
    yield from normalize_labels(candidates, llm=llm)
