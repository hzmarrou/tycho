"""Tests for Source A ingestion (LLM-extracted concepts and relationships)."""

from ontozense.core.ingest.base import ArtifactKind, Strength
from ontozense.core.ingest.ingest_a import SourceAIngester


def test_yields_one_intermediate_per_concept():
    raw = {
        "concepts": [
            {
                "name": "Customer",
                "definition": "A person doing business with the bank.",
                "entity_type": "Entity",
                "provenance": {"source_document": "docs/policy.md"},
            },
            {
                "name": "Loan",
                "definition": "Money borrowed.",
                "entity_type": "Entity",
            },
        ],
        "relationships": [],  # ingester yields concepts only; rels stay in orchestrator
    }
    candidates = list(SourceAIngester().ingest(raw))
    assert len(candidates) == 2

    labels = sorted(c.label for c in candidates)
    assert labels == ["Customer", "Loan"]

    for c in candidates:
        assert c.source_type == "A"
        assert c.artifact_kind == ArtifactKind.ENTITY
        assert c.strength == Strength.MEDIUM    # Source A default
        assert "Source A" in c.promotion_reason


def test_carries_source_artifact_from_provenance():
    raw = {
        "concepts": [
            {
                "name": "X",
                "provenance": {"source_document": "docs/policy.md"},
            },
        ],
    }
    candidates = list(SourceAIngester().ingest(raw))
    assert candidates[0].source_artifact == "docs/policy.md"


def test_empty_input_yields_nothing():
    assert list(SourceAIngester().ingest({})) == []
    assert list(SourceAIngester().ingest({"concepts": []})) == []


def test_strips_empty_labels():
    raw = {"concepts": [{"name": ""}, {"name": "  "}, {"name": "Customer"}]}
    candidates = list(SourceAIngester().ingest(raw))
    assert len(candidates) == 1
    assert candidates[0].label == "Customer"


def test_carries_eid_when_provided():
    raw = {"concepts": [{"name": "Customer", "id": "FIBO_Customer"}]}
    candidates = list(SourceAIngester().ingest(raw))
    assert candidates[0].eid == "FIBO_Customer"


def test_carries_raw_type():
    raw = {"concepts": [{"name": "Customer", "entity_type": "FibroEntity"}]}
    candidates = list(SourceAIngester().ingest(raw))
    assert candidates[0].raw_type == "FibroEntity"
