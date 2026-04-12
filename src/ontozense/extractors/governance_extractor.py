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
KNOWN_FIELDS = frozenset({
    "element_name",
    "domain_name",
    "definition",
    "is_critical",
    "citation",
})


@dataclass
class GovernanceRecord:
    """One governance entry from the curated reference file.

    Confidence is uniformly 0.95 because Source B reads structured input
    the human already curated — no LLM judgment, no hallucination risk.
    """
    element_name: str
    domain_name: str = ""
    definition: str = ""
    is_critical: bool = False
    citation: str = ""
    extra_fields: dict[str, Any] = field(default_factory=dict)
    source_file: str = ""
    confidence: float = 0.95

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
    """

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
            )
            result.records.append(record)

        return result
