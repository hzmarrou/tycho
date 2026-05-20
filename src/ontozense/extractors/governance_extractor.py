"""Governance extractor — Source B of the four-source pipeline.

Source B reads a curated governance reference file (JSON) that contains
canonical terms with their definitions, criticality flags, and citations
to authoritative systems (Collibra, A-LEX, OpenMetadata, etc.).

Its role in the pipeline is **validation, not extraction**: the fusion
layer uses Source B to confirm that concepts extracted by Source A
(domain documents) actually exist in the governance system, to prefer
governance definitions when they're richer, and to flag governance-only
terms that Source A missed.

Source B is **optional**. The fusion layer works without it — concepts
from Source A simply won't have governance validation.

Input format: a JSON file containing either a single object or an array
of objects. Each object has ``element_name`` (required) plus optional
fields (``domain_name``, ``definition``, ``is_critical``, ``citation``).
Any extra fields are preserved in ``extra_fields``.

Example input::

    [
      {
        "domain_name": "Customer Management",
        "element_name": "Customer Identifier",
        "definition": "A unique alphanumeric code assigned to each customer record.",
        "is_critical": true,
        "citation": "Collibra, OpenMetadata"
      }
    ]
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

# FieldAnchor is imported inside extract_from_file() at use time to
# avoid a circular import: ontozense.core.fusion already imports
# domain_doc / governance / schema dataclasses at module load. The
# annotation below stays a string at runtime via the
# ``from __future__ import annotations`` future, so the type checker
# still sees the right reference.
if TYPE_CHECKING:
    from ..core.fusion import FieldAnchor


# The fields we recognise and map to typed GovernanceRecord attributes.
# Anything else the JSON contains gets carried in extra_fields.
# ``entity_type`` is a profile-mode extension — a user authoring a
# governance JSON for a profile-aware run can declare each record's
# type so it aligns with the profile's entity_types.
KNOWN_FIELDS = frozenset({
    "element_name",
    "domain_name",
    "definition",
    "is_critical",
    "citation",
    "entity_type",
})


@dataclass
class GovernanceRecord:
    """One governance entry from the curated reference file.

    Confidence is uniformly 0.95 because Source B reads structured input
    the human already curated — no LLM judgment, no hallucination risk.

    The ``id`` and ``entity_type`` fields are populated only when a profile
    is loaded (constrained mode). In unconstrained mode they remain empty
    strings — preserving byte-identical output for callers that don't use
    profiles.
    """
    element_name: str
    domain_name: str = ""
    definition: str = ""
    is_critical: bool = False
    citation: str = ""
    extra_fields: dict[str, Any] = field(default_factory=dict)
    source_file: str = ""
    confidence: float = 0.95
    # Profile-mode fields (empty in unconstrained mode):
    id: str = ""
    entity_type: str = ""
    # Source B anchor — line + char_offset of this record's opening
    # ``{`` in the governance JSON file, plus a snippet of the
    # serialised entry. Populated by ``extract_from_file()``; left
    # ``None`` for records constructed directly in tests / programmatic
    # callers.
    source_anchor: Optional[FieldAnchor] = None

    def needs_review(self, threshold: float = 0.7) -> bool:
        return self.confidence < threshold


@dataclass
class GovernanceExtractionResult:
    """Result of parsing a governance reference file."""
    source_file: str = ""
    records: list[GovernanceRecord] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    extraction_timestamp: str = ""

    def get_record(self, element_name: str) -> Optional[GovernanceRecord]:
        target = element_name.lower().strip()
        for r in self.records:
            if r.element_name.lower().strip() == target:
                return r
        return None


class GovernanceExtractor:
    """Reads a curated governance reference file (JSON).

    The input is a JSON file containing either a single object or an
    array of objects. Each object must have at least ``element_name``.

    When a ``profile`` is provided (Phase 3 constrained mode), each
    record gets:
      * its ``element_name`` resolved through the profile's alias_map
        so synonymous names collapse to the canonical form
      * a deterministic ``id`` computed via
        :func:`ontozense.core.identity.compute_id` using the record's
        declared ``entity_type``
      * a warning in ``extra_fields["profile_warning"]`` if the
        declared ``entity_type`` isn't in the profile's known types
        (Phase 4 validation will decide what to do with it)

    When ``profile`` is None (default), behaviour is byte-identical to
    pre-Phase-3 commits — ``id`` and ``entity_type`` remain empty.
    """

    def __init__(self, profile=None):
        # Optional Profile from ontozense.core.profile.
        self.profile = profile

    def extract_from_file(
        self, file_path: str | Path
    ) -> GovernanceExtractionResult:
        # Deferred import: avoid module-load-time cycle with core.fusion.
        from ..core.fusion import FieldAnchor

        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"Governance file not found: {file_path}")

        text = file_path.read_text(encoding="utf-8")

        try:
            entries_with_pos = _parse_with_positions(text)
        except (json.JSONDecodeError, ValueError) as e:
            return GovernanceExtractionResult(
                source_file=str(file_path),
                warnings=[f"Invalid JSON: {e}"],
                extraction_timestamp=datetime.utcnow().isoformat(),
            )

        result = GovernanceExtractionResult(
            source_file=str(file_path),
            extraction_timestamp=datetime.utcnow().isoformat(),
        )

        # Pre-compute line-start offsets so we can convert character
        # offsets to (line, column) cheaply for each record.
        line_starts = _compute_line_starts(text)

        for idx, (start_offset, entry) in enumerate(entries_with_pos):
            if not isinstance(entry, dict):
                result.warnings.append(
                    f"Entry {idx}: expected an object, got {type(entry).__name__}"
                )
                continue

            element_name = entry.get("element_name", "")
            if not element_name or not str(element_name).strip():
                result.warnings.append(
                    f"Entry {idx}: missing or empty 'element_name', skipped"
                )
                continue

            # Separate known fields from extras
            extras = {
                k: v for k, v in entry.items() if k not in KNOWN_FIELDS
            }

            # is_critical can be bool, string, or absent
            is_critical_raw = entry.get("is_critical", False)
            if isinstance(is_critical_raw, bool):
                is_critical = is_critical_raw
            elif isinstance(is_critical_raw, str):
                is_critical = is_critical_raw.strip().lower() in (
                    "true", "yes", "y", "1",
                )
            else:
                is_critical = bool(is_critical_raw)

            # Compute the anchor for this record from its position in
            # the source text. (line, column) are 1-indexed; snippet
            # captures up to ~120 chars from the entry's opening brace
            # for human verification.
            line, column = _offset_to_line_column(start_offset, line_starts)
            snippet_end = min(start_offset + 120, len(text))
            snippet = text[start_offset:snippet_end].replace("\n", " ").strip()
            anchor = FieldAnchor(
                line=line,
                column=column,
                char_offset=start_offset,
                char_length=0,
                snippet=snippet,
                segment_id=file_path.name,
            )

            record = GovernanceRecord(
                element_name=str(element_name).strip(),
                domain_name=str(entry.get("domain_name", "")).strip(),
                definition=str(entry.get("definition", "")).strip(),
                is_critical=is_critical,
                citation=str(entry.get("citation", "")).strip(),
                extra_fields=extras,
                source_file=str(file_path),
                entity_type=str(entry.get("entity_type", "")).strip(),
                source_anchor=anchor,
            )

            # Profile-aware post-processing: applied only when a profile
            # is set. In unconstrained mode this branch is skipped and
            # the record is byte-identical to pre-Phase-3 output.
            if self.profile is not None:
                self._apply_profile(record, idx, result)

            result.records.append(record)

        return result

    def _apply_profile(
        self,
        record: GovernanceRecord,
        idx: int,
        result: GovernanceExtractionResult,
    ) -> None:
        """Resolve aliases, compute deterministic ID, validate entity_type.

        Mutates ``record`` in place. Records with declared types not in
        the profile schema get a ``profile_warning`` entry in
        ``extra_fields`` so Phase 4's validation stage can act on them
        — they are NOT dropped at extraction time.
        """
        from ..core.identity import compute_id

        # Resolve alias on the element_name so synonymous spellings
        # collapse to the canonical form before ID computation.
        record.element_name = self.profile.resolve_alias(record.element_name)

        # If the user declared a type, validate against the profile.
        if record.entity_type:
            if not self.profile.is_known_type(record.entity_type):
                record.extra_fields["profile_warning"] = (
                    f"entity_type {record.entity_type!r} is not declared "
                    f"in profile {self.profile.profile_name!r}. Phase 4 "
                    f"validation will decide whether to keep this record."
                )
                result.warnings.append(
                    f"Entry {idx}: entity_type {record.entity_type!r} "
                    f"unknown to profile {self.profile.profile_name!r}"
                )
            # Compute ID even with unknown type so consolidation can
            # still see it. Phase 4 may filter it.
            try:
                record.id = compute_id(
                    record.entity_type,
                    record.element_name,
                    hash_length=self.profile.id_format.hash_length,
                )
            except ValueError:
                # Label normalises to empty (e.g. all-punctuation):
                # leave id="" so validation catches it.
                record.id = ""


# ─── Position-tracking JSON parser (for Source B anchors) ───────────────────


def _parse_with_positions(text: str) -> list[tuple[int, dict]]:
    """Parse a JSON file containing one object or an array of objects,
    returning ``[(start_offset, parsed_dict), ...]``.

    Source B anchors need to know WHERE in the source file each entry
    started so reviewers can jump from a fused field back to the
    governance JSON line. ``json.loads`` discards positional info, so
    we walk the top-level structure manually using
    ``json.JSONDecoder.raw_decode`` to parse one entry at a time.

    Single-object inputs (the common case for one-entry governance
    files) return a length-1 list with offset=0 (after leading
    whitespace).

    JSON-strictness: empty input, trailing garbage, and trailing
    commas in arrays are all rejected. The post-Phase-7 review
    flagged that an over-permissive parser was silently accepting
    malformed governance files.
    """
    decoder = json.JSONDecoder()

    # Skip leading whitespace
    i = 0
    while i < len(text) and text[i].isspace():
        i += 1

    if i >= len(text):
        raise ValueError("Empty JSON file")

    # Single object → wrap as length-1 list, then verify nothing
    # significant follows (trailing garbage check).
    if text[i] == "{":
        entry, end = decoder.raw_decode(text, i)
        _require_only_whitespace_after(text, end)
        return [(i, entry)]

    # Array
    if text[i] != "[":
        raise ValueError(
            f"Expected JSON array or object at top level, got "
            f"{text[i]!r} at offset {i}"
        )

    i += 1  # skip the opening '['
    results: list[tuple[int, dict]] = []

    # Skip whitespace inside the array
    while i < len(text) and text[i].isspace():
        i += 1
    # Empty array short-circuit
    if i < len(text) and text[i] == "]":
        _require_only_whitespace_after(text, i + 1)
        return results

    # Element / comma loop. Each iteration parses exactly one
    # element, then expects either ``]`` (end) or ``,`` (next
    # element). Trailing comma — i.e. ``,]`` — is rejected.
    while True:
        if i >= len(text):
            raise ValueError("Unterminated JSON array (no closing ']').")
        entry, end = decoder.raw_decode(text, i)
        results.append((i, entry))
        i = end

        # Skip whitespace after element
        while i < len(text) and text[i].isspace():
            i += 1
        if i >= len(text):
            raise ValueError("Unterminated JSON array (no closing ']').")

        if text[i] == "]":
            i += 1
            break
        if text[i] != ",":
            raise ValueError(
                f"Expected ',' or ']' in JSON array at offset {i}, "
                f"got {text[i]!r}."
            )
        i += 1  # consume comma

        # Skip whitespace; reject trailing comma
        while i < len(text) and text[i].isspace():
            i += 1
        if i >= len(text) or text[i] == "]":
            raise ValueError(
                f"Trailing comma in JSON array at offset {i}."
            )

    _require_only_whitespace_after(text, i)
    return results


def _require_only_whitespace_after(text: str, offset: int) -> None:
    """After consuming the top-level JSON value at ``offset``,
    everything that follows must be whitespace. Any non-whitespace
    character is trailing garbage and means the file is malformed."""
    j = offset
    while j < len(text):
        if not text[j].isspace():
            raise ValueError(
                f"Unexpected trailing content at offset {j}: "
                f"{text[j:j+20]!r}"
            )
        j += 1


def _compute_line_starts(text: str) -> list[int]:
    """Return a list of character offsets where each line starts.

    Line N (1-indexed) starts at offset ``line_starts[N-1]``. Used
    to convert character offsets to (line, column) for anchors.
    """
    starts = [0]
    for i, ch in enumerate(text):
        if ch == "\n":
            starts.append(i + 1)
    return starts


def _offset_to_line_column(offset: int, line_starts: list[int]) -> tuple[int, int]:
    """Convert a character offset to (1-indexed line, 1-indexed column)
    using a precomputed list of line-start offsets.

    Uses ``bisect_right`` for O(log N) lookup so this stays cheap on
    larger governance files.
    """
    import bisect
    # bisect_right returns the index of the first line_start > offset;
    # the line containing ``offset`` is one before that (1-indexed).
    line_idx = bisect.bisect_right(line_starts, offset) - 1
    line_idx = max(line_idx, 0)
    line = line_idx + 1
    column = (offset - line_starts[line_idx]) + 1
    return line, column
