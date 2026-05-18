"""Tests for Source B ingestion (governance JSON catalogue)."""

from ontozense.core.ingest.base import ArtifactKind, Strength
from ontozense.core.ingest.ingest_b import SourceBIngester


def test_yields_one_intermediate_per_record():
    raw = {
        "records": [
            {
                "element_name": "Customer",
                "definition": "A person doing business with the bank.",
                "entity_type": "Entity",
                "source_file": "governance/glossary.json",
            },
            {
                "element_name": "Loan",
                "definition": "Money borrowed.",
                "entity_type": "Entity",
            },
        ],
    }
    candidates = list(SourceBIngester().ingest(raw))
    assert len(candidates) == 2

    labels = sorted(c.label for c in candidates)
    assert labels == ["Customer", "Loan"]

    for c in candidates:
        assert c.source_type == "B"
        assert c.artifact_kind == ArtifactKind.ENTITY
        assert c.strength == Strength.MEDIUM
        assert "Source B" in c.promotion_reason


def test_carries_source_artifact_from_record_source_file():
    raw = {
        "records": [
            {"element_name": "X", "source_file": "governance/glossary.json"},
        ],
    }
    candidates = list(SourceBIngester().ingest(raw))
    assert candidates[0].source_artifact == "governance/glossary.json"


def test_empty_input_yields_nothing():
    assert list(SourceBIngester().ingest({})) == []
    assert list(SourceBIngester().ingest({"records": []})) == []


def test_strips_empty_labels():
    raw = {"records": [{"element_name": ""}, {"element_name": "Customer"}]}
    candidates = list(SourceBIngester().ingest(raw))
    assert len(candidates) == 1
    assert candidates[0].label == "Customer"


def test_handles_non_dict_input_safely():
    """Anything that's not a dict (None, list, string, number) is
    treated as 'no records' — no exception."""
    ingester = SourceBIngester()
    assert list(ingester.ingest(None)) == []
    assert list(ingester.ingest([])) == []
    assert list(ingester.ingest("not a dict")) == []
    assert list(ingester.ingest(42)) == []
