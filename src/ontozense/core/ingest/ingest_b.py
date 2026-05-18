"""Source B ingester — extracts candidates from governance JSON catalogues.

Mirror of the existing inline ingestion block in
``candidate_graph.build_candidate_graph`` (lines 203-217 at the v1.0
branch point). Each record carries a structured ``element_name`` plus
optional definition/entity_type — strong-but-not-source-authoritative,
so default strength is ``MEDIUM``.
"""

from __future__ import annotations

from typing import Any, Iterable

from .base import (
    ArtifactKind,
    IngestionPolicy,
    IntermediateCandidate,
    Strength,
)


class SourceBIngester(IngestionPolicy):
    """Ingester for Source B — governance JSON catalogue."""

    def ingest(self, raw_input: Any) -> Iterable[IntermediateCandidate]:
        if not isinstance(raw_input, dict):
            return
        for record in raw_input.get("records", []) or []:
            label = (record.get("element_name") or "").strip()
            if not label:
                continue
            yield IntermediateCandidate(
                label=label,
                definition=record.get("definition", "") or "",
                source_type="B",
                source_artifact=record.get("source_file", "") or "",
                raw_type=record.get("entity_type", "") or "",
                eid=record.get("id", "") or "",
                artifact_kind=ArtifactKind.ENTITY,
                strength=Strength.MEDIUM,
                promotion_reason=(
                    f"Source B (governance record from "
                    f"{record.get('source_file', 'unspecified file')})."
                ),
                suppression_reason=None,
                suppressed=False,
            )
