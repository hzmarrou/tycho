"""Data Dictionary extractor — Pass 1 of the three-pass pipeline.

Extracts structured data dictionary elements from authoritative domain
documents (any prose-shaped artifact the domain experts treat as canonical:
formal regulations, internal policies, academic papers, industry standards,
vendor specifications, white papers) using OntoGPT's SPIRES methodology with
a purpose-built LinkML template.

The output mirrors the column structure of a typical enterprise data
dictionary: one row per data element, with definition, sub-domain,
criticality, citation, and data quality rules.

Each extracted field carries a confidence score and provenance back to the
source document. Empty fields are flagged for human review.

Domain-agnostic: works for any business domain. The LLM detects the domain
from the document content.

NOTE: This module is on its way to being replaced by `domain_doc_extractor.py`
(plan Step 2.2). It is kept for now to avoid breaking existing tests until
the rework lands.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from .ontogpt_extractor import OntoGPTExtractor

# The bundled LinkML template for data dictionary extraction
TEMPLATE_PATH = Path(__file__).parent.parent / "templates" / "data_dictionary.yaml"


# ─── Dataclasses ──────────────────────────────────────────────────────────────

@dataclass
class FieldConfidence:
    """Confidence score for a single extracted field."""
    field_name: str
    score: float          # 0.0 - 1.0
    reason: str           # "verbatim", "non_empty", "empty", "inferred"


@dataclass
class Provenance:
    """Tracks where an extraction came from."""
    source_document: str            # filename or path
    source_section: str = ""        # section heading or paragraph reference
    source_text_snippet: str = ""   # excerpt (truncated to 200 chars)
    extraction_timestamp: str = ""  # ISO datetime


# All non-name fields of DataElement (used for confidence scoring iteration)
DATA_ELEMENT_FIELDS = (
    "sub_domain",
    "definition",
    "term_definition",
    "is_critical",
    "citation",
    "mandatory_optional",
    "dq_completeness",
    "dq_accuracy",
    "dq_uniqueness",
    "dq_timeliness",
    "dq_consistency",
    "dq_validity",
)


@dataclass
class DataElement:
    """A single row in the data dictionary."""
    element_name: str
    sub_domain: str = ""
    definition: str = ""
    term_definition: str = ""
    is_critical: str = ""
    citation: str = ""
    mandatory_optional: str = ""
    dq_completeness: str = ""
    dq_accuracy: str = ""
    dq_uniqueness: str = ""
    dq_timeliness: str = ""
    dq_consistency: str = ""
    dq_validity: str = ""
    confidence: list[FieldConfidence] = field(default_factory=list)
    provenance: Optional[Provenance] = None
    merge_conflicts: list[str] = field(default_factory=list)

    def overall_confidence(self) -> float:
        """Average confidence across all populated fields."""
        if not self.confidence:
            return 0.0
        return sum(c.score for c in self.confidence) / len(self.confidence)

    def needs_review(self, threshold: float = 0.7) -> bool:
        """Whether this element needs human review."""
        return self.overall_confidence() < threshold or bool(self.merge_conflicts)


@dataclass
class DataDictionaryResult:
    """Result of extracting a data dictionary from one or more documents."""
    domain_name: str = ""
    elements: list[DataElement] = field(default_factory=list)
    source_documents: list[str] = field(default_factory=list)
    raw_outputs: list[str] = field(default_factory=list)
    extraction_timestamp: str = ""

    def get_element(self, name: str) -> Optional[DataElement]:
        """Look up an element by name (case-insensitive)."""
        target = name.lower().strip()
        for el in self.elements:
            if el.element_name.lower().strip() == target:
                return el
        return None


# ─── Extractor ────────────────────────────────────────────────────────────────

class DataDictionaryExtractor:
    """Extracts data dictionary elements from a document via OntoGPT."""

    def __init__(
        self,
        model: str = "azure/gpt-5.2",
        template_path: Optional[str | Path] = None,
    ):
        """
        Args:
            model: LiteLLM model identifier (e.g. "azure/gpt-5.2")
            template_path: Path to a custom LinkML template. Defaults to the
                bundled data_dictionary.yaml.
        """
        self.model = model
        self.template_path = Path(template_path) if template_path else TEMPLATE_PATH
        if not self.template_path.exists():
            raise FileNotFoundError(f"Template not found: {self.template_path}")
        # Reuse the existing OntoGPT subprocess wrapper
        self._ontogpt = OntoGPTExtractor(
            model=model,
            template_path=str(self.template_path),
        )

    def extract_from_file(self, file_path: str | Path) -> DataDictionaryResult:
        """Extract data dictionary elements from a single document.

        Args:
            file_path: Path to a plain-text document (.md, .txt). Confidence
                scoring and provenance lookup require a readable source text
                file. PDF/DOCX support is not yet implemented — those formats
                must be converted to text upstream.

        Returns:
            DataDictionaryResult with elements, confidence scores, provenance.
        """
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"Document not found: {file_path}")

        # Read source text once for confidence scoring
        try:
            source_text = file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            source_text = file_path.read_text(encoding="utf-8", errors="ignore")

        # Run OntoGPT and parse the JSON output
        raw_output = self._ontogpt._run_ontogpt(file_path, self.template_path)
        result = self._parse_ontogpt_output(raw_output, file_path, source_text)
        return result

    def extract_from_text(self, text: str, source_name: str = "inline") -> DataDictionaryResult:
        """Extract from a text string (writes a temp file)."""
        import tempfile
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, encoding="utf-8"
        ) as f:
            f.write(text)
            temp_path = f.name
        try:
            result = self.extract_from_file(temp_path)
            # Override source_document with the human-readable name
            for el in result.elements:
                if el.provenance:
                    el.provenance.source_document = source_name
            result.source_documents = [source_name]
            return result
        finally:
            os.unlink(temp_path)

    # ─── Output parsing ───────────────────────────────────────────────────

    def _parse_ontogpt_output(
        self,
        raw_output: str,
        source_path: Path,
        source_text: str,
    ) -> DataDictionaryResult:
        """Parse OntoGPT JSON/YAML output into a DataDictionaryResult."""
        result = DataDictionaryResult(
            source_documents=[str(source_path)],
            raw_outputs=[raw_output],
            extraction_timestamp=datetime.utcnow().isoformat(),
        )

        data = self._parse_raw(raw_output)
        if data is None:
            return result

        # Navigate OntoGPT's nested output structure
        extracted = data
        if isinstance(extracted, dict) and "results" in extracted:
            extracted = extracted["results"]
        if isinstance(extracted, dict) and "extracted_object" in extracted:
            extracted = extracted["extracted_object"]
        if not isinstance(extracted, dict):
            return result

        result.domain_name = extracted.get("domain_name", "") or ""
        elements_raw = extracted.get("data_elements", []) or []

        for el_dict in elements_raw:
            if not isinstance(el_dict, dict):
                continue
            element = self._build_element(el_dict, source_path, source_text)
            if element.element_name:
                result.elements.append(element)

        return result

    @staticmethod
    def _parse_raw(raw_output: str):
        """Parse OntoGPT output as JSON, falling back to YAML."""
        try:
            return json.loads(raw_output)
        except (json.JSONDecodeError, ValueError):
            pass
        try:
            import yaml
            return yaml.safe_load(raw_output)
        except Exception:
            return None

    def _build_element(
        self,
        el_dict: dict,
        source_path: Path,
        source_text: str,
    ) -> DataElement:
        """Build a DataElement from a parsed dict, scoring confidence per field."""
        element = DataElement(
            element_name=str(el_dict.get("element_name", "") or "").strip(),
            sub_domain=str(el_dict.get("sub_domain", "") or "").strip(),
            definition=str(el_dict.get("definition", "") or "").strip(),
            term_definition=str(el_dict.get("term_definition", "") or "").strip(),
            is_critical=str(el_dict.get("is_critical", "") or "").strip(),
            # Accept both new field name `citation` and legacy `regulation_reference`
            citation=str(
                el_dict.get("citation")
                or el_dict.get("regulation_reference")
                or ""
            ).strip(),
            mandatory_optional=str(el_dict.get("mandatory_optional", "") or "").strip(),
            dq_completeness=str(el_dict.get("dq_completeness", "") or "").strip(),
            dq_accuracy=str(el_dict.get("dq_accuracy", "") or "").strip(),
            dq_uniqueness=str(el_dict.get("dq_uniqueness", "") or "").strip(),
            dq_timeliness=str(el_dict.get("dq_timeliness", "") or "").strip(),
            dq_consistency=str(el_dict.get("dq_consistency", "") or "").strip(),
            dq_validity=str(el_dict.get("dq_validity", "") or "").strip(),
        )

        # Score confidence for each field
        for field_name in DATA_ELEMENT_FIELDS:
            value = getattr(element, field_name, "")
            score, reason = self._score_field(value, source_text, field_name)
            element.confidence.append(FieldConfidence(
                field_name=field_name,
                score=score,
                reason=reason,
            ))

        # Provenance — try multiple anchors so canonicalized names still
        # produce a useful snippet/section. We score each candidate by how
        # uniquely it locates a position in the source text.
        snippet = self._find_best_snippet(element, source_text)
        element.provenance = Provenance(
            source_document=str(source_path),
            source_section=self._find_section(snippet, source_text),
            source_text_snippet=snippet[:200] if snippet else "",
            extraction_timestamp=datetime.utcnow().isoformat(),
        )

        return element

    # Field-specific confidence rules. Different fields warrant different
    # scoring policies because their evidence patterns differ:
    #   - definitions: best evidence is a long verbatim quote from the source
    #   - flags (Y/N, M/O): only certain string values are valid
    #   - citations: should look like a section/paragraph/article reference pattern
    #   - DQ rules: usually paraphrased, partial-substring evidence is enough
    ENUM_FIELDS = {"is_critical", "mandatory_optional"}
    REFERENCE_FIELDS = {"citation"}
    NARRATIVE_FIELDS = {
        "definition",
        "term_definition",
        "dq_completeness",
        "dq_accuracy",
        "dq_uniqueness",
        "dq_timeliness",
        "dq_consistency",
        "dq_validity",
    }
    CATEGORICAL_FIELDS = {"sub_domain"}

    # Citation-like patterns (section/paragraph/article numbers, etc.).
    # Generic — works for any document with section numbering.
    REFERENCE_PATTERN = re.compile(
        r"(?:section|sec\.|paragraph|para\.|para|§|article|art\.|chapter|ch\.|p\.|page|fig\.|table)"
        r"\s*[\dA-Z][\d.A-Z-]*",
        re.IGNORECASE,
    )

    @classmethod
    def _score_field(
        cls,
        value: str,
        source_text: str,
        field_name: str,
    ) -> tuple[float, str]:
        """Score a single field's confidence using field-aware heuristics.

        Returns:
            (score, reason)
            score in [0.0, 1.0]; higher = more confident the value is grounded
            reason: short label explaining the score
        """
        if not value:
            return 0.0, "empty"

        normalized_source = " ".join(source_text.lower().split())

        # Enum-like flags: Y/N or M/O. Strict accept of valid values, low
        # confidence for anything else (LLM may have invented a variant).
        if field_name in cls.ENUM_FIELDS:
            v = value.strip().upper()
            valid = (
                {"Y", "N", "YES", "NO"} if field_name == "is_critical"
                else {"M", "O", "MANDATORY", "OPTIONAL"}
            )
            if v in valid:
                return 0.85, "valid_enum"
            return 0.3, "invalid_enum_value"

        # Reference fields must look like a citation
        if field_name in cls.REFERENCE_FIELDS:
            if cls.REFERENCE_PATTERN.search(value):
                # Bonus if the reference text itself appears in the source
                if " ".join(value.lower().split()) in normalized_source:
                    return 0.95, "verbatim_citation"
                return 0.7, "citation_pattern"
            # Non-empty but not citation-shaped — likely fabricated
            return 0.4, "non_citation_text"

        # Narrative fields (definitions, DQ rules) — favor verbatim or
        # high-overlap with source text
        if field_name in cls.NARRATIVE_FIELDS:
            normalized_value = " ".join(value.lower().split())
            if not normalized_value:
                return 0.0, "empty"
            if normalized_value in normalized_source:
                return 0.95, "verbatim"
            # Token overlap: at least half the value's words appear in source
            value_words = [w for w in normalized_value.split() if len(w) > 3]
            if value_words:
                hits = sum(1 for w in value_words if w in normalized_source)
                overlap = hits / len(value_words)
                if overlap >= 0.7:
                    return 0.75, "high_token_overlap"
                if overlap >= 0.4:
                    return 0.55, "partial_token_overlap"
            return 0.35, "low_evidence"

        # Categorical fields (sub_domain) — non-empty is acceptable since
        # the LLM is asked to assign a category, not quote one
        if field_name in cls.CATEGORICAL_FIELDS:
            return 0.7, "non_empty_category"

        # Anything else — be cautious by default
        if len(value) >= 10:
            return 0.5, "non_empty_unverified"
        return 0.5, "non_empty_unverified"

    def _find_best_snippet(
        self,
        element: DataElement,
        source_text: str,
    ) -> str:
        """Find the most informative source snippet for an element.

        Tries multiple anchors in order of specificity:
          1. Long verbatim phrases from definition / term_definition
          2. The element name
          3. The citation text
          4. The first significant n-gram of the definition

        Returns the snippet around the first successful match, or empty.
        """
        # Try long substrings of definitions first — they're the most
        # specific anchors and survive name canonicalization.
        for narrative_field in ("definition", "term_definition"):
            value = getattr(element, narrative_field, "")
            snippet = self._find_snippet_anywhere(value, source_text, min_length=20)
            if snippet:
                return snippet

        # Element name
        snippet = self._find_snippet_anywhere(element.element_name, source_text, min_length=4)
        if snippet:
            return snippet

        # Citation text
        ref = element.citation
        snippet = self._find_snippet_anywhere(ref, source_text, min_length=4)
        if snippet:
            return snippet

        # First significant n-gram of definition (handles paraphrased defs)
        for narrative_field in ("definition", "term_definition"):
            value = getattr(element, narrative_field, "")
            for ngram in self._significant_ngrams(value, n=5):
                snippet = self._find_snippet_anywhere(ngram, source_text, min_length=10)
                if snippet:
                    return snippet

        return ""

    @staticmethod
    def _find_snippet_anywhere(needle: str, source_text: str, min_length: int = 4) -> str:
        """Find a snippet of source text containing the needle (case-insensitive)."""
        if not needle or len(needle.strip()) < min_length or not source_text:
            return ""
        idx = source_text.lower().find(needle.lower())
        if idx < 0:
            return ""
        start = max(0, idx - 50)
        end = min(len(source_text), idx + len(needle) + 150)
        return source_text[start:end].strip()

    @staticmethod
    def _significant_ngrams(text: str, n: int = 5) -> list[str]:
        """Yield n-word substrings of `text`, skipping leading short/stopwords."""
        if not text:
            return []
        words = text.split()
        if len(words) < n:
            return []
        return [" ".join(words[i : i + n]) for i in range(len(words) - n + 1)]

    # Backwards-compat alias for callers that imported the old name
    @classmethod
    def _find_snippet(cls, needle: str, source_text: str) -> str:
        return cls._find_snippet_anywhere(needle, source_text, min_length=4)

    @staticmethod
    def _find_section(snippet: str, source_text: str) -> str:
        """Try to find the section heading containing this snippet."""
        if not snippet or not source_text:
            return ""
        idx = source_text.find(snippet)
        if idx < 0:
            return ""
        # Walk backwards to find the nearest markdown heading
        before = source_text[:idx]
        for line in reversed(before.split("\n")):
            stripped = line.strip()
            if stripped.startswith("#"):
                return stripped.lstrip("#").strip()
        return ""
