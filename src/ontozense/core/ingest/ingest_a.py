"""Source A ingester — extracts candidates from LLM-extracted
concept/relationship JSON (the output of ``extract-a``).

Mirror of the existing inline ingestion block in
``candidate_graph.build_candidate_graph`` (lines 183-201 at the
v1.0 branch point). The ingester is pure-extraction: it yields
:class:`IntermediateCandidate` records for each concept the LLM
produced. Relationships stay in the orchestrator since they require
candidate-id resolution that's only available after merge.

Default strength for Source A candidates is ``MEDIUM`` — the LLM is
authoritative for prose-defined concepts but its output benefits from
cross-source corroboration before being promoted to ``STRONG``.
"""

from __future__ import annotations

from typing import Any, Iterable

from .base import (
    ArtifactKind,
    IngestionPolicy,
    IntermediateCandidate,
    Strength,
)


class SourceAIngester(IngestionPolicy):
    """Ingester for Source A — LLM-extracted concepts from prose."""

    def ingest(self, raw_input: Any) -> Iterable[IntermediateCandidate]:
        if not isinstance(raw_input, dict):
            return
        for concept in raw_input.get("concepts", []) or []:
            label = (concept.get("name") or "").strip()
            if not label:
                continue

            artifact = ""
            prov_obj = concept.get("provenance")
            if isinstance(prov_obj, dict):
                artifact = prov_obj.get("source_document", "") or ""

            yield IntermediateCandidate(
                label=label,
                definition=concept.get("definition", "") or "",
                source_type="A",
                source_artifact=artifact,
                raw_type=concept.get("entity_type", "") or "",
                eid=concept.get("id", "") or "",
                artifact_kind=ArtifactKind.ENTITY,
                strength=Strength.MEDIUM,
                promotion_reason=(
                    f"Source A (LLM-extracted from "
                    f"{artifact or 'unspecified document'})."
                ),
                suppression_reason=None,
                suppressed=False,
            )
