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
from typing import Any, Optional


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
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"Governance file not found: {file_path}")

        try:
            raw = json.loads(file_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            return GovernanceExtractionResult(
                source_file=str(file_path),
                warnings=[f"Invalid JSON: {e}"],
                extraction_timestamp=datetime.utcnow().isoformat(),
            )

        # Accept single object or array
        entries = raw if isinstance(raw, list) else [raw]

        result = GovernanceExtractionResult(
            source_file=str(file_path),
            extraction_timestamp=datetime.utcnow().isoformat(),
        )

        for idx, entry in enumerate(entries):
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

            record = GovernanceRecord(
                element_name=str(element_name).strip(),
                domain_name=str(entry.get("domain_name", "")).strip(),
                definition=str(entry.get("definition", "")).strip(),
                is_critical=is_critical,
                citation=str(entry.get("citation", "")).strip(),
                extra_fields=extras,
                source_file=str(file_path),
                entity_type=str(entry.get("entity_type", "")).strip(),
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
