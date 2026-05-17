"""Tests for the ingester base types."""

import pytest


def test_artifact_kind_is_closed_enum():
    from ontozense.core.ingest.base import ArtifactKind

    expected = {"entity", "attribute", "relationship", "vocabulary",
                "behavior", "rule"}
    assert set(k.value for k in ArtifactKind) == expected


def test_strength_is_three_tier_enum():
    from ontozense.core.ingest.base import Strength

    assert Strength.STRONG.value == "strong"
    assert Strength.MEDIUM.value == "medium"
    assert Strength.WEAK.value == "weak"


def test_intermediate_candidate_dataclass():
    from ontozense.core.ingest.base import (
        IntermediateCandidate, ArtifactKind, Strength,
    )

    c = IntermediateCandidate(
        label="Customer",
        definition="A person doing business with the bank.",
        source_type="C",
        source_artifact="schemas/core.sql:42",
        raw_type="table",
        eid="",
        artifact_kind=ArtifactKind.ENTITY,
        strength=Strength.STRONG,
        promotion_reason="Table 'customers' classified as entity.",
        suppression_reason=None,
        suppressed=False,
    )
    assert c.label == "Customer"
    assert c.artifact_kind == ArtifactKind.ENTITY
    assert c.strength == Strength.STRONG


def test_intermediate_candidate_is_frozen():
    from ontozense.core.ingest.base import (
        IntermediateCandidate, ArtifactKind, Strength,
    )

    c = IntermediateCandidate(
        label="X", definition="", source_type="A",
        source_artifact="", raw_type="", eid="",
        artifact_kind=ArtifactKind.ENTITY, strength=Strength.MEDIUM,
        promotion_reason="", suppression_reason=None, suppressed=False,
    )
    with pytest.raises(Exception):
        c.label = "Y"  # type: ignore[misc]


def test_suppressed_candidate_carries_reason():
    from ontozense.core.ingest.base import (
        IntermediateCandidate, ArtifactKind, Strength,
    )

    c = IntermediateCandidate(
        label="created_at",
        definition="",
        source_type="C",
        source_artifact="schemas/core.sql:9",
        raw_type="column",
        eid="",
        artifact_kind=ArtifactKind.ATTRIBUTE,
        strength=Strength.WEAK,
        promotion_reason="",
        suppression_reason="Column 'created_at' matches default noise filter 'timestamp without domain prefix'.",
        suppressed=True,
    )
    assert c.suppressed is True
    assert c.suppression_reason and "noise filter" in c.suppression_reason
