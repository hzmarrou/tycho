"""Definitions extractor — regex-based pattern matching for explicit definitions.

A second-pass companion to ``domain_doc_extractor.py``. Scans authoritative
domain documents for definitional patterns that the LLM extraction may miss
or paraphrase. Each pattern matches a common authoring convention used in
prose-shaped documents:

  - **Term**: definition                  (markdown bold + colon)
  - `Term`: definition                    (markdown code + colon)
  - "Term": definition                    (quoted + colon)
  - Term — definition                     (em-dash separator)
  - Term is defined as definition         (defining clause)
  - Term means definition                 (definitional verb)
  - 1. Term: definition                   (numbered definition list)

Returns a list of ``DefinitionMatch`` records: ``(term, definition,
source_section, pattern_name, char_offset)``. Used to enrich LLM-extracted
concepts with definitions the LLM may have missed, or to surface terms the
LLM didn't extract at all.

Models the user's prior ``extract_definitions_from_text.py`` and
``extract_clean_definitions.py`` scripts, but generalised away from any
specific domain — every pattern here works on any prose document.

Domain-agnostic: zero hardcoded vocabulary terms. The patterns match
structural authoring conventions, not domain content.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class DefinitionMatch:
    """A regex-discovered definition in a source document."""
    term: str
    definition: str
    source_section: str = ""
    pattern_name: str = ""
    char_offset: int = 0


# Compiled patterns. Each is a (name, regex, term_group, def_group) tuple.
# Patterns are ordered from most specific (least likely to false-positive) to
# least specific.
#
# Length filters in the regex bodies (e.g. {2,80}, {10,400}) are intentional:
# - Terms shorter than 2 chars are usually single letters or noise
# - Terms longer than 80 chars are usually full sentences misidentified as terms
# - Definitions shorter than 10 chars are too short to be useful
# - Definitions longer than 400 chars are usually multi-sentence paragraphs
#   where the first sentence is probably the definition

# Separator class for "Term <SEP> definition" patterns.
# We deliberately do NOT include the ASCII hyphen ``-`` here because terms
# legitimately contain hyphens (e.g. "non-performing exposure"), and including
# it as a separator causes catastrophic false-positives where the regex
# splits "non-performing" as "non" + "performing exposures...".
# Real prose authors use one of: colon, em-dash, en-dash.
_SEP_CLASS = r"[:\u2014\u2013]"


_PATTERNS: list[tuple[str, re.Pattern, int, int]] = [
    # **Term**: definition  (markdown bold)
    (
        "bold_colon",
        re.compile(
            r"\*\*([^*\n]{2,80})\*\*\s*" + _SEP_CLASS + r"\s*([^\n]{10,400})",
            re.MULTILINE,
        ),
        1,
        2,
    ),
    # `Term`: definition  (markdown code span)
    (
        "code_colon",
        re.compile(
            r"`([^`\n]{2,80})`\s*" + _SEP_CLASS + r"\s*([^\n]{10,400})",
            re.MULTILINE,
        ),
        1,
        2,
    ),
    # "Term": definition  (quoted)
    (
        "quoted_colon",
        re.compile(
            r'"([^"\n]{2,80})"\s*' + _SEP_CLASS + r"\s*([^\n]{10,400})",
            re.MULTILINE,
        ),
        1,
        2,
    ),
    # Term is defined as definition.  (definition can span single-newlines
    # within a paragraph, but not across blank lines)
    (
        "is_defined_as",
        re.compile(
            r"\b([A-Z][\w\-\s]{1,80}?)\s+is\s+defined\s+as\s+((?:[^\n.]|\n(?!\n)){10,400}\.)",
            re.IGNORECASE,
        ),
        1,
        2,
    ),
    # Term means definition.
    (
        "means",
        re.compile(
            r"\b([A-Z][\w\-\s]{2,80}?)\s+means\s+((?:[^\n.]|\n(?!\n)){10,400}\.)",
        ),
        1,
        2,
    ),
    # Term refers to definition.
    (
        "refers_to",
        re.compile(
            r"\b([A-Z][\w\-\s]{2,80}?)\s+refers\s+to\s+((?:[^\n.]|\n(?!\n)){10,400}\.)",
        ),
        1,
        2,
    ),
    # Numbered list: "1. Term: definition" or "1) Term: definition"
    (
        "numbered_list",
        re.compile(
            r"^\s*\d+[.)]\s+([A-Z][\w\-\s]{1,80}?)\s*" + _SEP_CLASS + r"\s*([^\n]{10,400})",
            re.MULTILINE,
        ),
        1,
        2,
    ),
]


# Sentence-starter words that disqualify a "term" — if a candidate term
# starts with one of these, it is almost certainly a sentence fragment, not
# a noun-phrase concept name. Domain-agnostic.
_TERM_BLOCKLIST_PREFIXES = {
    "the", "an", "a", "this", "that", "these", "those",
    "many", "some", "all", "any", "each", "every", "few", "most",
    "our", "their", "its", "his", "her",
    "in", "on", "at", "by", "for", "to", "from", "with", "without",
    "if", "when", "while", "where", "because", "although", "since",
    "and", "or", "but", "however", "therefore", "thus", "hence",
    "is", "are", "was", "were", "be", "been", "being",
    "do", "does", "did", "have", "has", "had",
    "can", "could", "should", "would", "may", "might", "must", "shall", "will",
    "as", "such", "what", "which", "who", "whom", "whose",
    "early", "later", "earlier", "now", "then", "today", "yesterday",
    "possible", "likely", "unlikely", "perhaps", "maybe",
}


def _is_plausible_term(term: str) -> bool:
    """Return True if ``term`` looks like a noun-phrase concept name.

    Filters out sentence fragments that the regex patterns occasionally
    capture (e.g. "The definition of non", "An exposure ceases to be non",
    "Many jurisdictions use a mix of criteria with the objective criteria").

    Heuristics:
      - Must not be empty
      - Must not start with a sentence-starter word (the, an, this, ...)
      - Must not contain more than 8 words (concepts are short noun phrases)
      - Must not end with a hanging hyphen (artifact of the old buggy split)
      - Must not contain mid-sentence punctuation (commas, semicolons)
    """
    if not term:
        return False
    stripped = term.strip()
    if not stripped:
        return False
    # First word check
    first_word = stripped.split()[0].lower().rstrip(",.;:")
    if first_word in _TERM_BLOCKLIST_PREFIXES:
        return False
    # Length cap (concepts are short noun phrases)
    word_count = len(stripped.split())
    if word_count > 8:
        return False
    # Hanging hyphen at end (e.g. "Early non" was a hyphen-split artifact)
    if stripped.endswith("-"):
        return False
    # Mid-sentence punctuation indicates a sentence fragment
    if "," in stripped or ";" in stripped:
        return False
    return True


def extract_definitions_from_text(text: str) -> list[DefinitionMatch]:
    """Find definitional patterns in a document text.

    Returns one ``DefinitionMatch`` per pattern hit, deduplicated by
    (lowercase term, lowercase definition prefix). The list is in document
    order (not pattern order).

    Args:
        text: The full source text of the document.

    Returns:
        Ordered list of matches. May be empty if no patterns hit.
    """
    matches_with_offset: list[tuple[int, DefinitionMatch]] = []
    seen: set[tuple[str, str]] = set()

    for name, pattern, term_grp, def_grp in _PATTERNS:
        for m in pattern.finditer(text):
            term = m.group(term_grp).strip().rstrip(".,;:")
            # Collapse all internal whitespace (including embedded newlines
            # from multi-line patterns like ``means``) to single spaces.
            definition = " ".join(m.group(def_grp).split()).rstrip(".,;:")

            # Sanity filters
            if len(term) < 2 or len(definition) < 10:
                continue
            if len(term) > 100 or len(definition) > 500:
                continue
            # Skip terms that are obviously sentences (contain a period
            # in the middle, etc.)
            if "." in term[:-1] or "?" in term or "!" in term:
                continue
            # Skip sentence fragments masquerading as terms (the main
            # source of regex false positives)
            if not _is_plausible_term(term):
                continue

            # Dedupe by (lowercase term, first 50 chars of definition)
            key = (term.lower(), definition.lower()[:50])
            if key in seen:
                continue
            seen.add(key)

            section = _find_containing_section(text, m.start())

            match = DefinitionMatch(
                term=term,
                definition=definition,
                source_section=section,
                pattern_name=name,
                char_offset=m.start(),
            )
            matches_with_offset.append((m.start(), match))

    # Sort by document position
    matches_with_offset.sort(key=lambda x: x[0])
    return [m for _, m in matches_with_offset]


def extract_definitions_from_file(file_path: str | Path) -> list[DefinitionMatch]:
    """Convenience: read a file and extract definitions from its text."""
    file_path = Path(file_path)
    try:
        text = file_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = file_path.read_text(encoding="utf-8", errors="ignore")
    return extract_definitions_from_text(text)


def _find_containing_section(text: str, offset: int) -> str:
    """Find the nearest preceding markdown heading before ``offset``."""
    before = text[:offset]
    for line in reversed(before.split("\n")):
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip()
    return ""
