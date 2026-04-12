"""Tests for LLM-suggested bridging concepts.

All tests mock litellm.completion so no real LLM calls are made.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from ontozense.core.bridging import (
    BridgeSuggestion,
    suggest_bridges,
    format_suggestions_markdown,
    _parse_response,
)


WELL_FORMED_RESPONSE = """\
### Suggestion 1
- **Concept**: Liquidation Process
- **Definition**: The process of converting collateral assets into cash to recover loan losses.
- **Relationships**:
  - Default --[triggers]--> Liquidation Process
  - Liquidation Process --[applies_to]--> Collateral
- **Rationale**: When a borrower defaults, the lender may liquidate collateral to recover losses. This concept naturally bridges the default/NPE cluster with the collateral/property cluster.
"""

MALFORMED_RESPONSE = """\
I think you should connect these clusters by adding a concept about
risk assessment that links both groups together. This would involve
looking at how defaults relate to collateral valuation.
"""


class TestSuggestBridges:
    @patch("ontozense.core.bridging._call_llm", return_value=WELL_FORMED_RESPONSE)
    def test_happy_path_returns_parsed_suggestion(self, mock_llm):

        result = suggest_bridges(
            holes=[
                (["Default", "NPE"], ["Collateral", "Property"]),
            ],
            element_definitions={
                "Default": "Inability to pay.",
                "NPE": "Non-performing exposure.",
                "Collateral": "Pledged asset.",
                "Property": "Real estate collateral.",
            },
        )

        assert len(result) == 1
        s = result[0]
        assert s.suggested_concept == "Liquidation Process"
        assert len(s.suggested_relationships) >= 1
        assert any("Default" in r for r in s.suggested_relationships)
        assert s.rationale
        assert s.raw_response == WELL_FORMED_RESPONSE

    @patch("ontozense.core.bridging._call_llm", return_value=WELL_FORMED_RESPONSE)
    def test_multiple_gaps_produce_multiple_calls(self, mock_llm):

        result = suggest_bridges(
            holes=[
                (["A", "B"], ["X", "Y"]),
                (["C", "D"], ["Z", "W"]),
            ],
            element_definitions={},
        )

        assert len(result) == 2
        assert mock_llm.call_count == 2

    @patch("ontozense.core.bridging._call_llm", return_value=MALFORMED_RESPONSE)
    def test_malformed_response_graceful_degradation(self, mock_llm):

        result = suggest_bridges(
            holes=[(["A"], ["B"])],
            element_definitions={},
        )

        assert len(result) == 1
        s = result[0]
        # Parsing fails — concept and relationships may be empty
        # but raw_response is preserved
        assert s.raw_response == MALFORMED_RESPONSE
        assert s.community_a == ["A"]
        assert s.community_b == ["B"]

    @patch("ontozense.core.bridging._call_llm", return_value=WELL_FORMED_RESPONSE)
    def test_model_parameter_forwarded(self, mock_llm):
        suggest_bridges(
            holes=[(["A"], ["B"])],
            element_definitions={},
            model="openai/gpt-4o",
        )

        # _call_llm is called with (prompt, model)
        call_args = mock_llm.call_args
        assert call_args[0][1] == "openai/gpt-4o"

    def test_empty_holes_returns_empty(self):
        result = suggest_bridges(holes=[], element_definitions={})
        assert result == []


class TestParseResponse:
    def test_extracts_concept_and_relationships(self):
        s = _parse_response(WELL_FORMED_RESPONSE, ["A"], ["B"])
        assert s.suggested_concept == "Liquidation Process"
        assert len(s.suggested_relationships) >= 1
        assert s.rationale

    def test_preserves_raw_on_malformed(self):
        s = _parse_response(MALFORMED_RESPONSE, ["A"], ["B"])
        assert s.raw_response == MALFORMED_RESPONSE
        assert s.community_a == ["A"]


class TestFormatMarkdown:
    def test_produces_valid_markdown(self):
        suggestions = [
            BridgeSuggestion(
                community_a=["Default", "NPE"],
                community_b=["Collateral"],
                suggested_concept="Liquidation",
                suggested_relationships=["Default --[triggers]--> Liquidation"],
                rationale="Connects the two clusters.",
                raw_response="raw text",
            ),
        ]
        md = format_suggestions_markdown(suggestions)
        assert "# Bridge Suggestions" in md
        assert "Liquidation" in md
        assert "Default --[triggers]--> Liquidation" in md
        assert "Connects the two clusters" in md

    def test_empty_suggestions(self):
        md = format_suggestions_markdown([])
        assert "No structural gaps" in md
