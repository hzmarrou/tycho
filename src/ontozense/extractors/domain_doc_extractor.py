"""Domain document extractor — Source A of the four-source pipeline.

Extracts concepts (with optional inline definitions) and subject-predicate-
object relationships from authoritative domain documents — any prose-shaped
artifact the domain experts treat as canonical (formal regulations, internal
policies, academic papers, industry standards, vendor specifications, white
papers, technical guidelines).

Wraps OntoGPT/SPIRES but BYPASSES SPIRES's structured-output parser, which
is incompatible with our use case ("many independent items extracted from a
long document"; see ``docs/PLAYBOOK.md`` and the investigation summary in
``docs/SPIRES.md``). Instead, this module:

  1. Calls OntoGPT to run the LLM with our ``domain_doc_extraction`` template
  2. Reads the LLM's ``raw_completion_output`` (the actual text response)
  3. Parses concepts and relationships from the raw text directly
  4. Falls back to SPIRES's ``extracted_object`` only if raw parsing fails

The LLM's raw text contains the full list. SPIRES's structured parser only
captures the first item — that is the bug we are routing around. The user
already pioneered this technique with their regex post-processing scripts
(``extract_concepts.py`` + ``extract_clean_definitions.py`` +
``combine_extraction.py``).

Output shape (per the A2 format choice):
  - Each ``Concept`` has an optional inline ``definition`` and ``citation``
  - ``relationships`` is a separate top-level list of triples
  - There is no separate ``definitions`` list — definitions live on the
    concept they describe

Domain-agnostic: works for any business domain. The LLM detects the domain
from the document content. The synonym map / domain-specific configuration
is the responsibility of the fusion layer, not this extractor.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from .ontogpt_extractor import OntoGPTExtractor

TEMPLATE_PATH = Path(__file__).parent.parent / "templates" / "domain_doc_extraction.yaml"


# ─── Dataclasses ──────────────────────────────────────────────────────────────


@dataclass
class FieldConfidence:
    """Confidence score for a single extracted field."""
    field_name: str
    score: float
    reason: str


@dataclass
class Provenance:
    """Tracks where an extraction came from."""
    source_document: str
    source_section: str = ""
    source_text_snippet: str = ""
    extraction_timestamp: str = ""


@dataclass
class Concept:
    """A concept extracted from an authoritative domain document.

    Per the A2 format choice: ``definition`` is an optional inline field of
    the concept itself, not a separate top-level list.

    The ``id`` and ``entity_type`` fields are populated only when a profile
    is loaded (constrained mode). In unconstrained mode they remain empty
    strings — preserving byte-identical output for callers that don't use
    profiles.
    """
    name: str
    definition: str = ""
    citation: str = ""
    confidence: list[FieldConfidence] = field(default_factory=list)
    provenance: Optional[Provenance] = None
    # Profile-mode fields (empty in unconstrained mode):
    id: str = ""
    entity_type: str = ""

    def overall_confidence(self) -> float:
        if not self.confidence:
            return 0.0
        return sum(c.score for c in self.confidence) / len(self.confidence)

    def needs_review(self, threshold: float = 0.7) -> bool:
        return self.overall_confidence() < threshold


@dataclass
class Relationship:
    """A subject-predicate-object triple extracted from a domain document."""
    subject: str
    predicate: str
    object: str
    confidence: list[FieldConfidence] = field(default_factory=list)
    provenance: Optional[Provenance] = None

    def overall_confidence(self) -> float:
        if not self.confidence:
            return 0.0
        return sum(c.score for c in self.confidence) / len(self.confidence)


@dataclass
class DomainDocumentExtractionResult:
    """Result of extracting concepts and relationships from one or more documents.

    The ``extraction_mode``, ``profile_name``, and ``profile_version`` fields
    are populated only when a profile is loaded. In unconstrained mode they
    remain empty strings — preserving byte-identical output for callers that
    don't use profiles.
    """
    domain_name: str = ""
    concepts: list[Concept] = field(default_factory=list)
    relationships: list[Relationship] = field(default_factory=list)
    source_documents: list[str] = field(default_factory=list)
    raw_outputs: list[str] = field(default_factory=list)
    extraction_timestamp: str = ""
    # Profile-mode metadata (empty in unconstrained mode):
    extraction_mode: str = ""
    profile_name: str = ""
    profile_version: str = ""

    def get_concept(self, name: str) -> Optional[Concept]:
        target = name.lower().strip()
        for c in self.concepts:
            if c.name.lower().strip() == target:
                return c
        return None

    def get_concept_by_id(self, entity_id: str) -> Optional[Concept]:
        """Look up a concept by deterministic ID (profile mode only)."""
        for c in self.concepts:
            if c.id == entity_id:
                return c
        return None


# ─── Extractor ────────────────────────────────────────────────────────────────


class DomainDocumentExtractor:
    """Extracts concepts and relationships from authoritative domain documents.

    When ``profile`` is provided (Phase 2 constrained mode), the extractor:
      * generates a profile-aware LinkML template at runtime that injects
        the profile's prompt fragment, allowed entity types, and allowed
        predicates into the LLM prompt
      * parses extracted concepts as ``name :: type :: definition``
        triplets (3-part instead of unconstrained 2-part)
      * applies the profile's alias_map to canonicalise names
      * computes deterministic IDs via :func:`ontozense.core.identity.compute_id`
      * canonicalises relationship predicates via the profile's
        canonical_verbs map

    When ``profile`` is None (default, backward-compatible mode), behaviour
    is byte-identical to commit 46e2e8d. The ``id`` and ``entity_type``
    fields remain empty on every Concept; ``extraction_mode`` etc. remain
    empty on the result.
    """

    def __init__(
        self,
        model: str = "azure/gpt-5.4",
        template_path: Optional[str | Path] = None,
        profile=None,
    ):
        # Default is gpt-5.4 — see PLAYBOOK §12 for the gpt-5.2 vs gpt-5.4
        # comparison. gpt-5.4 produces ~2.4× more LLM-validated concepts
        # than gpt-5.2 on regulatory text at the same cost. The CLI default
        # was already gpt-5.4; this constructor default used to lag behind
        # and silently downgraded non-CLI callers.
        self.model = model
        self.profile = profile  # Optional Profile from ontozense.core.profile

        # If user passed a custom template path, that always wins. Otherwise
        # in profile mode we generate a profile-aware template; in
        # unconstrained mode we use the bundled default.
        if template_path is not None:
            self.template_path = Path(template_path)
        elif profile is not None:
            self.template_path = self._generate_profile_template(profile)
        else:
            self.template_path = TEMPLATE_PATH

        if not self.template_path.exists():
            raise FileNotFoundError(f"Template not found: {self.template_path}")
        self._ontogpt = OntoGPTExtractor(
            model=model,
            template_path=str(self.template_path),
        )

    @staticmethod
    def _generate_profile_template(profile) -> Path:
        """Write a profile-aware LinkML template to a temp file.

        The template embeds the profile's prompt fragment plus explicit
        lists of allowed entity types and predicates in the SPIRES
        descriptions, asking the LLM to format concepts as a 3-part
        ``name :: type :: definition`` triplet.

        Returns the path to the generated template.
        """
        import tempfile

        # Build allowed-types list (entities + their subtypes, all in one set)
        type_names: list[str] = []
        for et in profile.entity_types.values():
            type_names.append(et.name)
            type_names.extend(et.subtypes)

        types_block = "\n".join(f"  - {t}" for t in type_names)
        predicates_block = "\n".join(
            f"  - {p}" for p in profile.predicates.keys()
        ) or "  (no predicates declared)"

        # Profile prompt fragment is rendered as-is in the top-level
        # description so SPIRES surfaces it verbatim to the LLM.
        prompt_section = profile.prompt_fragment.strip() or (
            f"Domain profile: {profile.profile_name} "
            f"(version {profile.profile_version})"
        )

        # Required-field rules per type — surfaced so the LLM emits them
        required_rules = []
        for et in profile.entity_types.values():
            if et.required_fields:
                required_rules.append(
                    f"  - {et.name}: requires {', '.join(et.required_fields)}"
                )
        required_block = "\n".join(required_rules) or "  (no required fields)"

        template_yaml = f"""\
id: http://w3id.org/ontozense/profile_constrained_extraction
name: profile_constrained_extraction
title: Profile-constrained Domain Document Extraction ({profile.profile_name})
description: |-
  {prompt_section}

  Allowed entity types (use exactly these names — do not invent types):
{types_block}

  Allowed relationship predicates (use exactly these names):
{predicates_block}

  Required fields per entity type:
{required_block}

prefixes:
  rdf: http://www.w3.org/1999/02/22-rdf-syntax-ns#
  ddoc: http://w3id.org/ontozense/domain_doc_extraction/
  linkml: https://w3id.org/linkml/

default_prefix: ddoc
default_range: string

imports:
  - linkml:types

classes:
  DomainDocumentExtraction:
    tree_root: true
    description: >-
      Knowledge extracted from one authoritative domain document under
      the {profile.profile_name} profile. Use only the entity types and
      predicates declared above. Do not invent new ones.
    attributes:
      domain_name:
        description: >-
          The high-level business domain or sub-domain this document
          describes.

      concepts:
        description: |-
          A list of distinct concepts found in the source document. Each
          item must be a single line in the THREE-part format:

             concept name :: ENTITY_TYPE :: definition text

          ENTITY_TYPE must be exactly one of the allowed types listed in
          the top-level description. The definition text is required when
          the document explicitly defines the concept; otherwise put a
          short noun phrase summarising what the concept refers to in
          this domain.

          Include a concept ONLY if the source document EXPLICITLY
          references it as a relevant entity of one of the allowed types.
          Output the list as a YAML list (each item on its own line
          prefixed by "- ") OR as a JSON array.
        multivalued: true

      relationships:
        description: |-
          A list of subject-predicate-object triples. Each item must be
          a single line:

             subject -> predicate -> object

          The subject and object should match concept names above. The
          predicate MUST be one of the allowed predicate names listed in
          the top-level description. If a relationship cannot be expressed
          using one of those predicates, omit it entirely. Output as a
          YAML list or JSON array.
        multivalued: true
"""

        temp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8",
            prefix=f"ontozense_profile_{profile.profile_name}_",
        )
        temp.write(template_yaml)
        temp.close()
        return Path(temp.name)

    def extract_from_file(self, file_path: str | Path) -> DomainDocumentExtractionResult:
        """Extract concepts and relationships from a single document.

        Args:
            file_path: Path to a plain-text document (.md, .txt). Confidence
                scoring and provenance lookup require a readable source text
                file. PDF/DOCX support is not yet implemented — those formats
                must be converted to text upstream.
        """
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"Document not found: {file_path}")

        try:
            source_text = file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            source_text = file_path.read_text(encoding="utf-8", errors="ignore")

        raw_output = self._ontogpt._run_ontogpt(file_path, self.template_path)
        result = self._parse_ontogpt_output(raw_output, file_path, source_text)

        # Profile-aware post-processing: applied only when a profile is set.
        # In unconstrained mode this branch is skipped and the result is
        # byte-identical to commit 46e2e8d.
        if self.profile is not None:
            self._apply_profile(result)

        return result

    # ─── Profile-aware post-processing ───────────────────────────────────

    def _apply_profile(self, result: DomainDocumentExtractionResult) -> None:
        """Apply alias resolution, ID generation, and verb canonicalisation.

        Mutates ``result`` in place. Records profile metadata on the
        result. Quarantines (does not drop) entities whose declared type
        isn't in the profile schema — Phase 4's validation stage decides
        what to do with them.
        """
        from ..core.identity import compute_id

        result.extraction_mode = "constrained"
        result.profile_name = self.profile.profile_name
        result.profile_version = self.profile.profile_version

        # Concepts: resolve aliases, compute deterministic IDs
        for c in result.concepts:
            # Resolve alias before computing ID so synonyms collapse to
            # the canonical name in IDs.
            canonical_name = self.profile.resolve_alias(c.name)
            c.name = canonical_name

            # Only compute an ID if the LLM gave us a type. If the type
            # is missing or empty, leave id="" — Phase 4 will flag it.
            if c.entity_type and canonical_name.strip():
                try:
                    c.id = compute_id(c.entity_type, canonical_name)
                except ValueError:
                    # Label normalises to empty (e.g. all-punctuation):
                    # leave id="" so validation catches it.
                    c.id = ""

        # Relationships: canonicalise predicate verbs
        for rel in result.relationships:
            rel.predicate = self.profile.canonicalise_verb(rel.predicate)
            # Resolve aliases on subject + object too, so cross-source
            # matching works downstream (Phase 5).
            rel.subject = self.profile.resolve_alias(rel.subject)
            rel.object = self.profile.resolve_alias(rel.object)

    # ─── Output parsing ───────────────────────────────────────────────────

    def _parse_ontogpt_output(
        self,
        raw_output: str,
        source_path: Path,
        source_text: str,
    ) -> DomainDocumentExtractionResult:
        """Parse OntoGPT JSON output, prioritizing ``raw_completion_output``."""
        result = DomainDocumentExtractionResult(
            source_documents=[str(source_path)],
            raw_outputs=[raw_output],
            extraction_timestamp=datetime.utcnow().isoformat(),
        )

        try:
            data = json.loads(raw_output)
        except (json.JSONDecodeError, ValueError):
            return result

        if not isinstance(data, dict):
            return result

        # Get domain_name from extracted_object — SPIRES handles this top-level
        # string field correctly
        eo = data.get("extracted_object", {})
        if isinstance(eo, dict):
            result.domain_name = str(eo.get("domain_name", "") or "")

        # PRIMARY: parse raw_completion_output for the full lists
        raw_completion = data.get("raw_completion_output", "")
        if raw_completion:
            concepts_text = self._extract_section(raw_completion, "concepts")
            relationships_text = self._extract_section(raw_completion, "relationships")

            for raw_concept in self._parse_list(concepts_text):
                concept = self._build_concept(raw_concept, source_path, source_text)
                if concept.name:
                    result.concepts.append(concept)

            for raw_rel in self._parse_list(relationships_text):
                relationship = self._build_relationship(raw_rel, source_path, source_text)
                if relationship.subject and relationship.object:
                    result.relationships.append(relationship)

        # FALLBACK: if raw parsing produced nothing, try SPIRES's extracted_object
        if not result.concepts and isinstance(eo, dict):
            for c in eo.get("concepts", []) or []:
                if isinstance(c, str):
                    concept = self._build_concept(c, source_path, source_text)
                    if concept.name:
                        result.concepts.append(concept)
                elif isinstance(c, dict):
                    name = c.get("name") or c.get("element_name") or ""
                    if name:
                        concept = self._build_concept(name, source_path, source_text)
                        if c.get("definition"):
                            concept.definition = c["definition"]
                            concept.confidence.append(
                                self._score_text_field(c["definition"], source_text, "definition")
                            )
                        result.concepts.append(concept)

        if not result.relationships and isinstance(eo, dict):
            for r in eo.get("relationships", []) or []:
                if isinstance(r, str):
                    rel = self._build_relationship(r, source_path, source_text)
                    if rel.subject and rel.object:
                        result.relationships.append(rel)
                elif isinstance(r, dict):
                    subj = r.get("subject", "")
                    pred = r.get("predicate", "")
                    obj = r.get("object", "")
                    if subj and obj:
                        rel = self._make_relationship(
                            subj, pred or "related_to", obj, source_path, source_text
                        )
                        result.relationships.append(rel)

        return result

    @staticmethod
    def _extract_section(text: str, section_name: str) -> str:
        """Find a section like 'concepts:' in the raw completion text.

        Returns the body of the section up to the next top-level section or
        the end of the text. Handles indented continuation lines.
        """
        lines = text.split("\n")
        in_section = False
        body_lines: list[str] = []
        section_pattern = re.compile(rf"^{re.escape(section_name)}\s*:\s*(.*)$", re.IGNORECASE)
        # Other top-level keys mark the end of our section
        other_key_pattern = re.compile(r"^[a-zA-Z_][\w-]*\s*:")

        for line in lines:
            if in_section:
                # End on next top-level key (must be at column 0)
                if other_key_pattern.match(line):
                    break
                body_lines.append(line)
            else:
                m = section_pattern.match(line.strip())
                if m:
                    in_section = True
                    # The first line might have inline content
                    inline = m.group(1).strip()
                    if inline:
                        body_lines.append(inline)

        return "\n".join(body_lines).strip()

    @staticmethod
    def _parse_list(section_text: str) -> list[str]:
        """Parse a list from a section body. Handles three formats:

        1. JSON array: ``["item1","item2","item3"]``
        2. YAML list: ``- item1\\n- item2\\n- item3``
        3. Semicolon-separated: ``item1; item2; item3``
        """
        if not section_text:
            return []

        text = section_text.strip()

        # Try JSON array format first (gpt-5.2 sometimes uses this)
        if text.startswith("["):
            try:
                arr = json.loads(text)
                if isinstance(arr, list):
                    return [str(x).strip() for x in arr if str(x).strip()]
            except (json.JSONDecodeError, ValueError):
                pass

        # Try YAML list format
        if "\n-" in text or text.startswith("-"):
            items = []
            for raw_line in text.split("\n"):
                line = raw_line.strip()
                if line.startswith("- "):
                    items.append(line[2:].strip())
                elif line.startswith("-") and len(line) > 1:
                    items.append(line[1:].strip())
            if items:
                return [i for i in items if i]

        # Fall back to semicolon-separated
        return [item.strip() for item in text.split(";") if item.strip()]

    def _build_concept(
        self,
        raw: str,
        source_path: Path,
        source_text: str,
    ) -> Concept:
        """Build a ``Concept`` from a raw text item.

        Profile-aware parser:
          * In **constrained mode** (``self.profile is not None``), accepts
            the 3-part format ``name :: TYPE :: definition``. The middle
            field is captured as ``entity_type``. If the LLM emits only
            two parts in constrained mode, we still accept it and leave
            ``entity_type=""`` — Phase 4 validation will flag it.
          * In **unconstrained mode** (default), accepts the 2-part
            ``name :: definition`` format unchanged from earlier
            commits — splits parenthetical inline definitions, etc.

        The unconstrained path is byte-identical to commit 46e2e8d.
        """
        raw = raw.strip().strip('"').strip("'")
        entity_type = ""

        if "::" in raw:
            parts = [p.strip() for p in raw.split("::")]
            # Profile mode prefers 3 parts; unconstrained always treats
            # everything after the first :: as the definition.
            if self.profile is not None and len(parts) >= 3:
                # name :: TYPE :: definition (rejoin extras into definition
                # in case it itself contains "::")
                name = parts[0]
                entity_type = parts[1]
                definition = "::".join(parts[2:]).strip()
            else:
                # Unconstrained, or profile-mode but the LLM only gave us
                # 2 parts — fall through to the legacy 2-part split which
                # the test suite locks down byte-identical.
                name, _, definition = raw.partition("::")
                name = name.strip()
                definition = definition.strip()
        elif raw.endswith(")") and "(" in raw:
            paren_start = raw.rfind("(")
            name = raw[:paren_start].strip()
            definition = raw[paren_start + 1 : -1].strip()
            # If the parenthetical looks like an acronym (≤5 chars, all caps),
            # it's not a definition — keep it as part of the name.
            if len(definition) <= 5 and definition.isupper():
                name = raw.strip()
                definition = ""
        else:
            name = raw
            definition = ""

        concept = Concept(name=name, definition=definition, entity_type=entity_type)

        concept.confidence.append(self._score_text_field(name, source_text, "name"))
        if definition:
            concept.confidence.append(
                self._score_text_field(definition, source_text, "definition")
            )
        else:
            # No definition is a real gap, not a non-event. Score it as
            # missing so the overall confidence reflects that half of the
            # expected information is absent. Without this, a concept with
            # only a name (verbatim, 0.95) would score 0.95 overall — which
            # is dishonest because the human reviewer still needs to find
            # or write the definition. With this penalty: name 0.95 + def
            # 0.0 → overall 0.475 → flagged needs_review.
            concept.confidence.append(
                FieldConfidence("definition", 0.0, "missing")
            )

        snippet = self._find_snippet(name, source_text) or self._find_snippet(definition, source_text)
        concept.provenance = Provenance(
            source_document=str(source_path),
            source_section=self._find_section(snippet, source_text),
            source_text_snippet=snippet[:200] if snippet else "",
            extraction_timestamp=datetime.utcnow().isoformat(),
        )

        return concept

    def _build_relationship(
        self,
        raw: str,
        source_path: Path,
        source_text: str,
    ) -> Relationship:
        """Build a ``Relationship`` from a raw text item.

        Expected format: ``subject -> predicate -> object``
        Also accepts ``--``, ``=>``, and pipe-separated forms.
        """
        raw = raw.strip().strip('"').strip("'")

        for sep in (" -> ", " --> ", " => ", " -- ", " | "):
            if sep in raw:
                parts = [p.strip() for p in raw.split(sep)]
                if len(parts) >= 3:
                    subject = parts[0]
                    predicate = parts[1]
                    obj = sep.join(parts[2:])
                    return self._make_relationship(
                        subject, predicate, obj, source_path, source_text
                    )
                if len(parts) == 2:
                    return self._make_relationship(
                        parts[0], "related_to", parts[1], source_path, source_text
                    )

        # Couldn't parse — return empty (caller will skip)
        return Relationship(subject="", predicate="", object="")

    def _make_relationship(
        self,
        subject: str,
        predicate: str,
        obj: str,
        source_path: Path,
        source_text: str,
    ) -> Relationship:
        rel = Relationship(subject=subject.strip(), predicate=predicate.strip(), object=obj.strip())

        # Score each endpoint by source presence:
        #   verbatim → 0.95
        #   absent   → 0.30  (was 0.5; lowered so a both-missing triple
        #                     scores 0.30, clearly below the 0.7 review
        #                     threshold instead of sitting on the fence)
        # The predicate is not scored — predicates are usually paraphrased
        # verb phrases that don't match the source verbatim.
        score_s = 0.95 if self._appears_in(subject, source_text) else 0.30
        score_o = 0.95 if self._appears_in(obj, source_text) else 0.30
        avg = (score_s + score_o) / 2
        # avg cases:
        #   both verbatim          → 0.95   (both endpoints grounded)
        #   one verbatim, one not  → 0.625  (mixed grounding)
        #   neither verbatim       → 0.30   (no source grounding — flagged)
        rel.confidence.append(FieldConfidence("triple", avg, "source_overlap"))

        # Provenance snippet: prefer subject anchor, fall back to object.
        # Without the fallback, relationships where the subject is absent
        # but the object is present would have empty provenance even
        # though the evidence exists.
        snippet = (
            self._find_snippet(subject, source_text)
            or self._find_snippet(obj, source_text)
        )
        rel.provenance = Provenance(
            source_document=str(source_path),
            source_section=self._find_section(snippet, source_text),
            source_text_snippet=snippet[:200] if snippet else "",
            extraction_timestamp=datetime.utcnow().isoformat(),
        )
        return rel

    # ─── Helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _appears_in(needle: str, source_text: str) -> bool:
        if not needle:
            return False
        # Use first 30 chars to allow partial matches on long phrases
        return needle[:30].lower() in source_text.lower()

    @staticmethod
    def _score_text_field(value: str, source_text: str, field_name: str) -> FieldConfidence:
        if not value:
            return FieldConfidence(field_name, 0.0, "empty")
        normalized_value = " ".join(value.lower().split())
        normalized_source = " ".join(source_text.lower().split())
        if normalized_value in normalized_source:
            return FieldConfidence(field_name, 0.95, "verbatim")
        # Token overlap on significant words (length > 3)
        value_words = [w for w in normalized_value.split() if len(w) > 3]
        if value_words:
            hits = sum(1 for w in value_words if w in normalized_source)
            overlap = hits / len(value_words)
            if overlap >= 0.7:
                return FieldConfidence(field_name, 0.75, "high_overlap")
            if overlap >= 0.4:
                return FieldConfidence(field_name, 0.55, "partial_overlap")
        return FieldConfidence(field_name, 0.35, "low_evidence")

    @staticmethod
    def _find_snippet(needle: str, source_text: str, min_length: int = 4) -> str:
        if not needle or len(needle.strip()) < min_length or not source_text:
            return ""
        idx = source_text.lower().find(needle.lower())
        if idx < 0:
            return ""
        start = max(0, idx - 50)
        end = min(len(source_text), idx + len(needle) + 150)
        return source_text[start:end].strip()

    @staticmethod
    def _find_section(snippet: str, source_text: str) -> str:
        if not snippet or not source_text:
            return ""
        idx = source_text.find(snippet)
        if idx < 0:
            return ""
        before = source_text[:idx]
        for line in reversed(before.split("\n")):
            stripped = line.strip()
            if stripped.startswith("#"):
                return stripped.lstrip("#").strip()
        return ""
