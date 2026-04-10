"""OntoGPT extraction wrapper.

Wraps OntoGPT's SPIRES extraction to extract ontology concepts and relationships
from domain documents. Outputs an OntologyManager instance ready for refinement.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ..core.manager import OntologyManager

# ─── Default LinkML template for domain ontology extraction ───────────────────

DOMAIN_ONTOLOGY_TEMPLATE = """\
id: http://w3id.org/ontogpt/domain_ontology
name: domain_ontology
title: Domain Ontology Extraction Template
description: >-
  Extract domain concepts, their definitions, and relationships from authoritative domain
  or policy documents to build a domain ontology.
license: https://creativecommons.org/publicdomain/zero/1.0/
prefixes:
  rdf: http://www.w3.org/1999/02/22-rdf-syntax-ns#
  domain: http://w3id.org/ontogpt/domain_ontology/
  linkml: https://w3id.org/linkml/

default_prefix: domain
default_range: string

imports:
  - linkml:types

classes:
  DomainOntologyExtraction:
    tree_root: true
    description: >-
      A collection of domain concepts and their relationships extracted from text.
    attributes:
      concepts:
        description: >-
          Domain concepts (entities/classes) found in the text with their definitions.
        range: DomainConcept
        multivalued: true
        inlined: true
        inlined_as_list: true
      relationships:
        description: >-
          Relationships between domain concepts.
        range: ConceptRelationship
        multivalued: true
        inlined: true
        inlined_as_list: true

  DomainConcept:
    description: >-
      A domain concept representing an entity or class in the ontology.
    attributes:
      name:
        description: The canonical name of the concept.
        identifier: true
      definition:
        description: The definition of the concept as stated or implied in the text.
      category:
        description: >-
          The broad category this concept belongs to
          (e.g. entity, process, status, classification, metric, role).

  ConceptRelationship:
    description: >-
      A directed relationship between two domain concepts.
    attributes:
      subject:
        description: The source concept name.
        range: DomainConcept
      predicate:
        description: >-
          The relationship type (e.g. has_part, is_a, regulates, measured_by,
          applies_to, classified_as, triggers, requires).
      object:
        description: The target concept name.
        range: DomainConcept
"""


@dataclass
class ExtractionResult:
    """Result of an OntoGPT extraction."""
    concepts: list[dict] = field(default_factory=list)
    relationships: list[dict] = field(default_factory=list)
    raw_output: Optional[str] = None
    source_document: Optional[str] = None


class OntoGPTExtractor:
    """Wraps OntoGPT to extract ontology from documents."""

    def __init__(
        self,
        model: str = "azure/gpt-5.2",
        template: Optional[str] = None,
        template_path: Optional[str] = None,
    ):
        """Initialize the extractor.

        Args:
            model: LiteLLM model identifier (e.g. "azure/gpt-5.2", "openai/gpt-4o")
            template: Name of a built-in or custom OntoGPT template
            template_path: Path to a custom LinkML YAML template file
        """
        self.model = model
        self.template = template
        self.template_path = template_path

    def extract_from_file(self, file_path: str | Path) -> ExtractionResult:
        """Extract ontology concepts from a document file.

        Args:
            file_path: Path to the document (markdown, text, etc.)

        Returns:
            ExtractionResult with concepts and relationships
        """
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"Document not found: {file_path}")

        # Determine template to use
        template_path = self._resolve_template()

        # Run OntoGPT extraction
        raw_output = self._run_ontogpt(file_path, template_path)

        # Parse the output
        result = self._parse_output(raw_output)
        result.source_document = str(file_path)
        result.raw_output = raw_output
        return result

    def extract_from_text(self, text: str) -> ExtractionResult:
        """Extract ontology concepts from a text string."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as f:
            f.write(text)
            temp_path = f.name
        try:
            return self.extract_from_file(temp_path)
        finally:
            os.unlink(temp_path)

    def to_manager(self, result: ExtractionResult, base_uri: str | None = None) -> OntologyManager:
        """Convert extraction result to an OntologyManager instance.

        This is the key bridge: OntoGPT output → rdflib OWL graph.
        """
        from rdflib import Literal, URIRef
        from rdflib.namespace import OWL, RDF, RDFS, XSD

        if base_uri is None:
            base_uri = "http://example.org/extracted-ontology#"

        mgr = OntologyManager(base_uri=base_uri)

        # Add classes from concepts
        for concept in result.concepts:
            name = self._to_class_name(concept["name"])
            cls_uri = mgr._uri(name)
            mgr.graph.add((cls_uri, RDF.type, OWL.Class))
            # Label = original name
            mgr.graph.add((cls_uri, RDFS.label, Literal(concept["name"])))
            # Definition as comment
            if concept.get("definition"):
                mgr.graph.add((cls_uri, RDFS.comment, Literal(concept["definition"])))
            # Category as custom annotation
            if concept.get("category"):
                category_pred = mgr.namespace["category"]
                mgr.graph.add((cls_uri, category_pred, Literal(concept["category"])))

        # Add relationships as object properties
        seen_predicates: set[str] = set()
        for rel in result.relationships:
            subj_name = self._to_class_name(rel["subject"])
            obj_name = self._to_class_name(rel["object"])
            pred_name = self._to_property_name(rel["predicate"])

            subj_uri = mgr._uri(subj_name)
            obj_uri = mgr._uri(obj_name)
            prop_uri = mgr._uri(pred_name)

            # Ensure subject and object classes exist
            if (subj_uri, RDF.type, OWL.Class) not in mgr.graph:
                mgr.graph.add((subj_uri, RDF.type, OWL.Class))
                mgr.graph.add((subj_uri, RDFS.label, Literal(rel["subject"])))
            if (obj_uri, RDF.type, OWL.Class) not in mgr.graph:
                mgr.graph.add((obj_uri, RDF.type, OWL.Class))
                mgr.graph.add((obj_uri, RDFS.label, Literal(rel["object"])))

            # Declare the object property (once per unique predicate)
            if pred_name not in seen_predicates:
                mgr.graph.add((prop_uri, RDF.type, OWL.ObjectProperty))
                mgr.graph.add((prop_uri, RDFS.label, Literal(rel["predicate"])))
                seen_predicates.add(pred_name)

            # Add domain and range
            mgr.graph.add((prop_uri, RDFS.domain, subj_uri))
            mgr.graph.add((prop_uri, RDFS.range, obj_uri))

        return mgr

    # ─── Internal methods ─────────────────────────────────────────────────

    def _resolve_template(self) -> Path:
        """Resolve which template to use, creating a temp file if needed."""
        if self.template_path:
            path = Path(self.template_path)
            if not path.exists():
                raise FileNotFoundError(f"Template not found: {path}")
            return path

        # Write built-in template to temp file
        temp = tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False, encoding="utf-8")
        temp.write(DOMAIN_ONTOLOGY_TEMPLATE)
        temp.close()
        return Path(temp.name)

    def _run_ontogpt(self, input_path: Path, template_path: Path) -> str:
        """Run OntoGPT CLI extraction.

        Azure OpenAI auth is passed via explicit --api-base / --api-version
        CLI flags plus the AZURE_API_KEY env var. This avoids the unreliable
        runoak/oaklib keyring path and works with both the legacy
        '<resource>.openai.azure.com' and the new Foundry-style
        '<resource>.cognitiveservices.azure.com' endpoints.
        """
        ontogpt_exe = self._resolve_ontogpt_executable()
        cmd = [
            ontogpt_exe, "extract",
            "-i", str(input_path),
            "-t", str(template_path),
            "-m", self.model,
            "-O", "json",
        ]

        env = os.environ.copy()
        # If the user provided AZURE_OPENAI_* env vars (the newer naming),
        # alias them to the legacy AZURE_API_* names that litellm reads,
        # and pass --api-base / --api-version explicitly to OntoGPT.
        api_key = (
            os.environ.get("AZURE_API_KEY")
            or os.environ.get("AZURE_OPENAI_API_KEY")
        )
        api_base = (
            os.environ.get("AZURE_API_BASE")
            or os.environ.get("AZURE_OPENAI_ENDPOINT", "").rstrip("/") or None
        )
        api_version = (
            os.environ.get("AZURE_API_VERSION")
            or os.environ.get("AZURE_OPENAI_API_VERSION")
        )

        if api_key:
            env["AZURE_API_KEY"] = api_key
            # litellm fallback — some code paths read OPENAI_API_KEY when
            # routing through Azure with explicit api_base
            env["OPENAI_API_KEY"] = api_key
        if api_base:
            env["AZURE_API_BASE"] = api_base
            cmd.extend(["--api-base", api_base])
        if api_version:
            env["AZURE_API_VERSION"] = api_version
            cmd.extend(["--api-version", api_version])

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=600,  # 10 min timeout for long documents
                env=env,
            )
            if result.returncode != 0:
                raise RuntimeError(f"OntoGPT failed:\n{result.stderr}")
            return result.stdout
        except FileNotFoundError:
            raise RuntimeError(
                f"OntoGPT executable not found at: {ontogpt_exe}\n"
                f"Install it with: {sys.executable} -m pip install ontogpt"
            )

    @staticmethod
    def _resolve_ontogpt_executable() -> str:
        """Find the ontogpt executable in the same venv as the running Python.

        On Windows, scripts live in <venv>/Scripts/; on Unix in <venv>/bin/.
        Falls back to bare 'ontogpt' if not found in the venv (PATH lookup).
        """
        import shutil
        # Same directory as the running Python interpreter
        python_dir = Path(sys.executable).parent
        for candidate_name in ("ontogpt.exe", "ontogpt"):
            candidate = python_dir / candidate_name
            if candidate.exists():
                return str(candidate)
        # Fall back to PATH lookup
        on_path = shutil.which("ontogpt")
        if on_path:
            return on_path
        # Last resort: bare name (will fail with a clear error)
        return "ontogpt"

    def _parse_output(self, raw_output: str) -> ExtractionResult:
        """Parse OntoGPT JSON output into ExtractionResult."""
        result = ExtractionResult()

        try:
            data = json.loads(raw_output)
        except json.JSONDecodeError:
            # OntoGPT sometimes outputs YAML — try that
            try:
                import yaml
                data = yaml.safe_load(raw_output)
            except Exception:
                result.raw_output = raw_output
                return result

        if data is None:
            return result

        # Handle OntoGPT's nested output structure
        extracted = data
        if "results" in data:
            extracted = data["results"]
        if "extracted_object" in extracted:
            extracted = extracted["extracted_object"]

        # Extract concepts
        concepts_raw = extracted.get("concepts", extracted.get("definitions", []))
        for c in concepts_raw:
            if isinstance(c, dict):
                concept = {
                    "name": c.get("name", c.get("term", "")),
                    "definition": c.get("definition", ""),
                    "category": c.get("category", ""),
                }
                if concept["name"]:
                    result.concepts.append(concept)
            elif isinstance(c, str):
                result.concepts.append({"name": c, "definition": "", "category": ""})

        # Extract relationships
        rels_raw = extracted.get("relationships", [])
        for r in rels_raw:
            if isinstance(r, dict):
                rel = {
                    "subject": r.get("subject", ""),
                    "predicate": r.get("predicate", ""),
                    "object": r.get("object", ""),
                }
                if rel["subject"] and rel["object"]:
                    result.relationships.append(rel)

        return result

    @staticmethod
    def _to_class_name(name: str) -> str:
        """Convert a concept name to a valid OWL class name (PascalCase)."""
        import re
        # Remove parenthetical content like "(NPE)"
        name = re.sub(r"\s*\([^)]*\)", "", name).strip()
        # Remove URI-unsafe characters
        name = re.sub(r"[<>{}|\\^`\"/]", "", name)
        # PascalCase
        words = re.split(r"[\s_\-–—,;:]+", name)
        result = "".join(w.capitalize() for w in words if w.isalnum() or w.replace("'", "").isalnum())
        # Truncate extremely long names (max 80 chars)
        return result[:80] if result else "Unknown"

    @staticmethod
    def _to_property_name(predicate: str) -> str:
        """Convert a predicate to a valid OWL property name (camelCase)."""
        import re
        words = re.split(r"[\s_-]+", predicate.strip())
        if not words:
            return "relatedTo"
        return words[0].lower() + "".join(w.capitalize() for w in words[1:])


def load_existing_extraction(json_path: str | Path) -> ExtractionResult:
    """Load a previously saved OntoGPT extraction (like d403-combined-extraction.json)."""
    path = Path(json_path)
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    result = ExtractionResult(source_document=data.get("source_document"))

    for c in data.get("concepts", []):
        result.concepts.append({
            "name": c.get("term", c.get("name", "")),
            "definition": c.get("definition", ""),
            "category": c.get("category", ""),
        })

    for r in data.get("relationships", []):
        result.relationships.append({
            "subject": r.get("subject", ""),
            "predicate": r.get("predicate", ""),
            "object": r.get("object", ""),
        })

    return result
