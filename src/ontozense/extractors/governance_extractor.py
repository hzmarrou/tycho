"""Governance extractor — Source B of the four-source pipeline.

**STATUS: TBD scaffold.** This module declares the dataclasses and the
public API surface for Source B but the parser implementation is left as a
placeholder for the next iteration. The shape is locked so the fusion
layer (Step 6) can be designed against it.

Source B reads governance / data quality dictionaries that have been
converted to the canonical CSV format defined in
``docs/CANONICAL_GOVERNANCE_FORMAT.md``. The contract:

  - Input: ONE CSV file in canonical format
  - Output: ``GovernanceExtractionResult`` with one ``GovernanceRecord``
    per data row
  - No Excel reading, no fuzzy header matching, no LLM
  - Customer is responsible for converting their existing dictionaries to
    the canonical format before upload

Why this is a separate Source from A:

  - Source A extracts from prose (regulations, policies, papers) using an
    LLM. Output has confidence scores reflecting how grounded the LLM
    extractions are in the source text.
  - Source B reads structured tabular data the human already produced.
    Confidence is uniformly high (the human typed it; we just parse it).
    No hallucination risk.

The fusion layer (Step 6) will merge Source A and Source B records on the
``element_name`` field, taking governance fields (criticality, M/O, DQ
rules) from Source B because Source A can rarely extract those reliably
from prose.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional


# ─── Canonical column names ──────────────────────────────────────────────────
#
# These are the ONLY column names Source B accepts. Customers convert their
# existing dictionaries to a CSV with these column headers (case-insensitive,
# leading/trailing whitespace ignored). See
# ``docs/CANONICAL_GOVERNANCE_FORMAT.md`` for the full spec.

REQUIRED_COLUMNS = ("element_name",)

OPTIONAL_COLUMNS = (
    "domain",
    "sub_domain",
    "definition",
    "term_definition",
    "is_critical",
    "mandatory_optional",
    "citation",
    "dq_completeness",
    "dq_accuracy",
    "dq_uniqueness",
    "dq_timeliness",
    "dq_consistency",
    "dq_validity",
)

CANONICAL_COLUMNS = REQUIRED_COLUMNS + OPTIONAL_COLUMNS


# ─── Dataclasses ─────────────────────────────────────────────────────────────


@dataclass
class GovernanceRecord:
    """One row from a canonical governance CSV.

    Confidence is uniformly 0.95 because Source B reads structured input the
    human already produced — there is no LLM judgment, no hallucination risk.
    The 0.95 (rather than 1.0) leaves a small margin for "the human might
    have made a typo," which is the only realistic failure mode.
    """
    element_name: str
    domain: str = ""
    sub_domain: str = ""
    definition: str = ""
    term_definition: str = ""
    is_critical: str = ""
    mandatory_optional: str = ""
    citation: str = ""
    dq_completeness: str = ""
    dq_accuracy: str = ""
    dq_uniqueness: str = ""
    dq_timeliness: str = ""
    dq_consistency: str = ""
    dq_validity: str = ""
    source_file: str = ""
    source_row_number: int = 0  # 1-indexed row in the CSV
    confidence: float = 0.95  # uniform; structured human input

    def needs_review(self, threshold: float = 0.7) -> bool:
        return self.confidence < threshold


@dataclass
class GovernanceExtractionResult:
    """Result of parsing one canonical governance CSV file."""
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


# ─── Extractor ───────────────────────────────────────────────────────────────


class GovernanceExtractor:
    """Reads governance dictionaries in the canonical CSV format.

    **STATUS: TBD scaffold.** Public API is locked so downstream callers
    (the fusion layer) can be designed against it. Implementation is the
    next iteration.
    """

    def __init__(self) -> None:
        pass

    def extract_from_file(self, file_path: str | Path) -> GovernanceExtractionResult:
        """Parse a canonical governance CSV file.

        Args:
            file_path: Path to a CSV file in the canonical format defined
                in ``docs/CANONICAL_GOVERNANCE_FORMAT.md``.

        Returns:
            A ``GovernanceExtractionResult`` with one record per valid data
            row, plus per-row warnings for invalid rows.

        Raises:
            FileNotFoundError: if ``file_path`` does not exist.
            NotImplementedError: until Step 4 implementation lands.
        """
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"Governance CSV not found: {file_path}")
        # TBD — actual parser implementation comes in the next iteration.
        # The current placeholder returns an empty result with a warning so
        # the fusion layer can be designed against the shape.
        raise NotImplementedError(
            "GovernanceExtractor is currently a TBD scaffold. The dataclasses "
            "and public API are locked so the fusion layer can be designed "
            "against this shape. Implementation lands in the next iteration. "
            "See docs/CANONICAL_GOVERNANCE_FORMAT.md for the input contract."
        )
