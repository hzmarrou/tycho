"""LLM-suggested bridging concepts for structural gaps.

When the lint layer identifies structural holes (disconnected concept
clusters in the fused knowledge graph), this module asks an LLM to
suggest bridging relationships or concepts that would connect them.

This is intentionally separate from lint.py because it makes LLM calls
(slow, non-deterministic, requires API key). It is invoked by the
``ontozense suggest-bridges`` CLI command, not by the fast lint flow.

The output is markdown suitable for ``ontozense file-back`` — so the
expert can review the suggestions, approve/reject, and file them back
into the knowledge base. This completes the Karpathy feedback loop:
Lint finds gaps → LLM suggests bridges → Expert reviews → File-back.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


# ─── Dataclasses ─────────────────────────────────────────────────────────────


@dataclass
class BridgeSuggestion:
    """One LLM-suggested bridging concept or relationship."""
    community_a: list[str]
    community_b: list[str]
    suggested_concept: str = ""
    suggested_relationships: list[str] = field(default_factory=list)
    rationale: str = ""
    raw_response: str = ""


# ─── Prompt template ────────────────────────────────────────────────────────

_BRIDGE_PROMPT = """\
You are a domain ontology expert. You have been given two clusters of \
concepts from a domain ontology that have no (or very weak) connections \
between them. Your task is to suggest bridging concepts or relationships \
that would meaningfully connect these clusters.

## Cluster A
{cluster_a}

## Cluster B
{cluster_b}

## Instructions
1. Identify 1-3 bridging concepts that would naturally connect Cluster A \
to Cluster B. A bridging concept may already exist in one cluster but \
lack a relationship to the other, or it may be a new concept entirely.
2. For each bridging concept, suggest specific relationships using the \
format: Subject --[predicate]--> Object
3. Provide a brief rationale for each suggestion.

## Output format
For each suggestion, use this exact format:

### Suggestion 1
- **Concept**: <concept name>
- **Definition**: <one-sentence definition>
- **Relationships**:
  - <Subject> --[<predicate>]--> <Object>
- **Rationale**: <why this bridge makes sense>
"""


# ─── Core functions ──────────────────────────────────────────────────────────


def suggest_bridges(
    holes: list[tuple[list[str], list[str]]],
    element_definitions: dict[str, str],
    *,
    model: str = "azure/gpt-5.4",
) -> list[BridgeSuggestion]:
    """Ask an LLM to suggest bridging concepts for structural gaps.

    Args:
        holes: List of (community_a_names, community_b_names) pairs
            representing structural holes found by lint.
        element_definitions: Dict mapping element name to its definition.
        model: litellm model identifier.

    Returns:
        One BridgeSuggestion per hole.
    """
    if not holes:
        return []

    suggestions = []
    for community_a, community_b in holes:
        prompt = _BRIDGE_PROMPT.format(
            cluster_a=_format_cluster(community_a, element_definitions),
            cluster_b=_format_cluster(community_b, element_definitions),
        )
        raw = _call_llm(prompt, model)
        suggestion = _parse_response(raw, community_a, community_b)
        suggestions.append(suggestion)

    return suggestions


def format_suggestions_markdown(suggestions: list[BridgeSuggestion]) -> str:
    """Format bridge suggestions as markdown suitable for file-back."""
    if not suggestions:
        return "No structural gaps found — no bridging suggestions needed.\n"

    lines = ["# Bridge Suggestions\n"]

    for i, s in enumerate(suggestions, 1):
        a_str = ", ".join(s.community_a[:5])
        b_str = ", ".join(s.community_b[:5])
        lines.append(f"## Gap {i}: {{{a_str}}} <-> {{{b_str}}}\n")

        if s.suggested_concept:
            lines.append(f"**Suggested concept:** {s.suggested_concept}\n")
        if s.suggested_relationships:
            lines.append("**Suggested relationships:**")
            for rel in s.suggested_relationships:
                lines.append(f"- {rel}")
            lines.append("")
        if s.rationale:
            lines.append(f"**Rationale:** {s.rationale}\n")

        lines.append("### Raw LLM response\n")
        lines.append("```")
        lines.append(s.raw_response)
        lines.append("```\n")

    return "\n".join(lines)


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _format_cluster(names: list[str], definitions: dict[str, str]) -> str:
    """Format a cluster's concepts for the LLM prompt."""
    lines = []
    for name in sorted(names):
        defn = definitions.get(name, "(no definition)")
        lines.append(f"- **{name}**: {defn}")
    return "\n".join(lines)


def _call_llm(prompt: str, model: str) -> str:
    """Call litellm.completion and return the content string."""
    import litellm

    response = litellm.completion(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
        max_tokens=2000,
    )
    return response.choices[0].message.content


def _parse_response(
    raw: str,
    community_a: list[str],
    community_b: list[str],
) -> BridgeSuggestion:
    """Parse the LLM response into a BridgeSuggestion.

    Deliberately lenient — if parsing fails, the raw response is still
    returned so the expert can interpret it manually.
    """
    suggestion = BridgeSuggestion(
        community_a=list(community_a),
        community_b=list(community_b),
        raw_response=raw,
    )

    # Try to extract the first suggestion block
    concept_match = re.search(
        r"\*\*Concept\*\*:\s*(.+?)(?:\n|$)", raw
    )
    if concept_match:
        suggestion.suggested_concept = concept_match.group(1).strip()

    # Extract relationships
    rel_matches = re.findall(
        r"[-*]\s+(.+?--\[.+?\]-->.+?)(?:\n|$)", raw
    )
    if rel_matches:
        suggestion.suggested_relationships = [r.strip() for r in rel_matches]

    # Extract rationale
    rationale_match = re.search(
        r"\*\*Rationale\*\*:\s*(.+?)(?:\n\n|\n###|\Z)", raw, re.DOTALL
    )
    if rationale_match:
        suggestion.rationale = rationale_match.group(1).strip()

    return suggestion
