"""Schema-based ontology refiner.

Merges a top-down extracted ontology (from documents via OntoGPT) with
a bottom-up database schema (from Django models) to produce a refined,
data-grounded ontology.

The schema acts as:
  - A FILTER: only concepts that map to tables become entities
  - A PROPERTY SOURCE: columns become entity properties with real types
  - A RELATIONSHIP VALIDATOR: foreign keys confirm relationships
  - An ENUM POPULATOR: choice fields become enum property values
  - A DEFINITION ENRICHER: extracted definitions annotate schema entities
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from ..extractors.django_schema import SchemaModel, SchemaResult
from ..extractors.ontogpt_extractor import ExtractionResult


@dataclass
class RefinementReport:
    """Report of what the refinement did."""
    matched_entities: list[tuple[str, str]] = field(default_factory=list)  # (concept, model)
    unmatched_concepts: list[str] = field(default_factory=list)
    unmatched_models: list[str] = field(default_factory=list)
    properties_added: int = 0
    relationships_confirmed: int = 0
    definitions_applied: int = 0
    enums_populated: int = 0


class SchemaRefiner:
    """Refines an extracted ontology using a database schema.

    Domain-agnostic. To improve matching for a specific domain, pass a
    `synonym_map` that maps concept names (extracted from documents) to
    schema model names (from the database). The synonym map is the only
    domain-specific input — the matcher itself is generic.

    Example synonym_map (terms shaped like {extracted_name: schema_table_name}):
        {"client": "customer", "purchase": "order", ...}
    """

    def __init__(
        self,
        schema: SchemaResult,
        extraction: ExtractionResult,
        synonym_map: dict[str, str] | None = None,
    ):
        self.schema = schema
        self.extraction = extraction
        self.synonym_map = synonym_map or {}
        # Build lookup maps
        self._concept_map: dict[str, dict] = {}
        for c in extraction.concepts:
            key = self._normalize(c["name"])
            self._concept_map[key] = c
        self._model_map: dict[str, SchemaModel] = {}
        for m in schema.models:
            self._model_map[self._normalize(m.name)] = m

    def refine(self) -> tuple[dict[str, Any], RefinementReport]:
        """Produce a refined Playground ontology and a refinement report.

        Returns:
            (playground_ontology_dict, report)
        """
        report = RefinementReport()

        # Step 1: Match schema models to extracted concepts
        matches = self._match_models_to_concepts()
        report.matched_entities = [(concept, model) for model, concept in matches.items()]

        matched_model_names = set(matches.keys())
        matched_concept_keys = {self._normalize(c) for c in matches.values()}

        report.unmatched_concepts = [
            c["name"] for c in self.extraction.concepts
            if self._normalize(c["name"]) not in matched_concept_keys
        ]
        report.unmatched_models = [
            m.name for m in self.schema.models
            if self._normalize(m.name) not in matched_model_names
        ]

        # Step 2: Build entity types from matched schema models + extracted definitions
        entity_types = []
        entity_id_map: dict[str, str] = {}  # model_name → entity_id

        colors = ["#0078D4", "#107C10", "#5C2D91", "#FFB900", "#D83B01",
                  "#00A9E0", "#8764B8", "#00B294", "#E74856", "#744DA9"]
        icons = ["📦", "👤", "💰", "🏠", "🔗", "📋", "⚖️", "🏢", "📊", "🔒"]

        for i, (model_name_norm, model) in enumerate(self._model_map.items()):
            concept_name = matches.get(model_name_norm)
            concept = self._concept_map.get(self._normalize(concept_name)) if concept_name else None

            entity_id = self._to_camel_case(model.name)
            entity_id_map[model.name] = entity_id

            # Build properties from schema fields
            properties = []
            for f in model.fields:
                prop: dict[str, Any] = {
                    "name": self._to_camel_case(f.name),
                    "type": f.playground_type,
                }
                # Mark identifier fields
                if f.is_primary_key or f.name.endswith("_identifier") and not properties:
                    prop["isIdentifier"] = True

                if f.help_text:
                    prop["description"] = f.help_text

                if f.playground_type == "enum" and f.choices_values:
                    prop["values"] = f.choices_values
                    report.enums_populated += 1

                properties.append(prop)
                report.properties_added += 1

            # Ensure at least one identifier
            has_id = any(p.get("isIdentifier") for p in properties)
            if not has_id and properties:
                # Look for *_identifier field
                for p in properties:
                    if "identifier" in p["name"].lower():
                        p["isIdentifier"] = True
                        has_id = True
                        break
                if not has_id:
                    properties.insert(0, {
                        "name": f"{entity_id}Id",
                        "type": "string",
                        "isIdentifier": True,
                        "description": f"Unique identifier for {model.name}",
                    })

            # Description: prefer extracted definition, fall back to model docstring
            description = ""
            if concept and concept.get("definition"):
                description = concept["definition"]
                report.definitions_applied += 1
            elif model.doc:
                # Clean up docstring
                description = re.sub(r"`[^`]+`", "", model.doc).strip()
                description = re.sub(r"\.\. note::.*", "", description, flags=re.DOTALL).strip()
                description = description.split("\n")[0].strip()

            entity_types.append({
                "id": entity_id,
                "name": self._to_display_name(model.name),
                "description": description or f"{model.name} entity",
                "properties": properties,
                "icon": icons[i % len(icons)],
                "color": colors[i % len(colors)],
            })

        # Step 3: Build relationships from schema foreign keys
        relationships = []
        for model in self.schema.models:
            from_id = entity_id_map.get(model.name)
            if not from_id:
                continue
            for rel in model.relationships:
                to_id = entity_id_map.get(rel.to_model)
                if not to_id:
                    continue
                rel_name = self._to_display_name(
                    rel.field_name.replace("_identifier", "").replace("_id", "")
                )
                rel_id = f"{from_id}-{self._to_camel_case(rel.field_name)}-{to_id}"
                cardinality = "many-to-one"  # FK default

                # Check if the extracted relationships have something to say
                for ext_rel in self.extraction.relationships:
                    from_match = self._concepts_match(ext_rel["subject"], model.name)
                    to_match = self._concepts_match(ext_rel["object"], rel.to_model)
                    if from_match and to_match:
                        rel_name = ext_rel["predicate"]
                        report.relationships_confirmed += 1
                        break

                relationships.append({
                    "id": rel_id,
                    "name": rel_name,
                    "from": from_id,
                    "to": to_id,
                    "cardinality": cardinality,
                })

        ontology = {
            "ontology": {
                "name": "Refined Ontology",
                "description": "Ontology refined by merging document extraction with database schema",
                "entityTypes": entity_types,
                "relationships": relationships,
            }
        }

        return ontology, report

    # ─── Matching logic ──────────────────────────────────────────────────

    def _match_models_to_concepts(self) -> dict[str, str]:
        """Match schema models to extracted concepts by name similarity.

        Uses synonym mapping, substring matching, and word overlap.
        Returns: dict of normalized_model_name → concept_name
        """
        matches: dict[str, str] = {}

        for model in self.schema.models:
            model_norm = self._normalize(model.name)
            best_match: str | None = None
            best_score = 0.0

            for concept in self.extraction.concepts:
                concept_norm = self._normalize(concept["name"])
                score = self._match_score(model_norm, concept_norm)

                # Also check user-supplied synonym map
                synonym_target = self.synonym_map.get(concept_norm)
                if synonym_target and self._normalize(synonym_target) == model_norm.replace(" ", ""):
                    score = max(score, 0.9)

                if score > best_score and score >= 0.4:
                    best_score = score
                    best_match = concept["name"]

            if best_match:
                matches[model_norm] = best_match

        return matches

    def _match_score(self, a: str, b: str) -> float:
        """Score how well two normalized names match."""
        if a == b:
            return 1.0
        # Remove spaces for compound name comparison (e.g. "linecount" vs "line count")
        a_compact = a.replace(" ", "")
        b_compact = b.replace(" ", "")
        if a_compact == b_compact:
            return 1.0
        if a_compact in b_compact or b_compact in a_compact:
            shorter = min(len(a_compact), len(b_compact))
            longer = max(len(a_compact), len(b_compact))
            return shorter / longer if longer > 0 else 0.0
        # Substring match on words
        if a in b or b in a:
            shorter = min(len(a), len(b))
            longer = max(len(a), len(b))
            return shorter / longer if longer > 0 else 0.0
        # Check word overlap
        a_words = set(a.split())
        b_words = set(b.split())
        if a_words and b_words:
            overlap = len(a_words & b_words)
            total = len(a_words | b_words)
            return overlap / total
        return 0.0

    def _concepts_match(self, concept_name: str, model_name: str) -> bool:
        """Check if a concept name and model name refer to the same thing."""
        cn = self._normalize(concept_name)
        mn = self._normalize(model_name)
        if self._match_score(cn, mn) >= 0.4:
            return True
        synonym_target = self.synonym_map.get(cn)
        if synonym_target and self._normalize(synonym_target) == mn.replace(" ", ""):
            return True
        return False

    # ─── Name helpers ────────────────────────────────────────────────────

    @staticmethod
    def _normalize(name: str) -> str:
        """Normalize a name for comparison."""
        name = re.sub(r"\s*\([^)]*\)", "", name)  # Remove parenthetical
        name = re.sub(r"[^a-zA-Z0-9\s]", " ", name)  # Keep alphanumeric + spaces
        return " ".join(name.lower().split())

    @staticmethod
    def _to_camel_case(name: str) -> str:
        """Convert to camelCase."""
        words = re.split(r"[_\s-]+", name)
        if not words:
            return "unknown"
        return words[0].lower() + "".join(w.capitalize() for w in words[1:])

    @staticmethod
    def _to_display_name(name: str) -> str:
        """Convert CamelCase or snake_case to display name."""
        # Split CamelCase
        name = re.sub(r"([a-z])([A-Z])", r"\1 \2", name)
        # Split snake_case
        name = name.replace("_", " ")
        return " ".join(w.capitalize() for w in name.split())
