"""Playground exporter — maps OWL ontology to Ontology Playground's JSON format.

Target format matches the TypeScript interfaces in
Ontology-Playground/src/data/ontology.ts:
  - Ontology { name, description, entityTypes[], relationships[] }
  - EntityType { id, name, description, properties[], icon, color }
  - Property { name, type, isIdentifier?, unit?, values?, description? }
  - Relationship { id, name, from, to, cardinality, description?, attributes? }
"""

from __future__ import annotations

import json
import re
from typing import Any

from rdflib import BNode, URIRef
from rdflib.namespace import OWL, RDF, RDFS, XSD

from ..core.manager import OntologyManager

# ─── Default colors and icons for generated entities ─────────────────────────

DEFAULT_COLORS = [
    "#0078D4",  # Microsoft Blue
    "#107C10",  # Microsoft Green
    "#5C2D91",  # Microsoft Purple
    "#FFB900",  # Microsoft Gold
    "#D83B01",  # Microsoft Orange
    "#00A9E0",  # Light Blue
    "#8764B8",  # Lavender
    "#00B294",  # Teal
    "#E74856",  # Red
    "#744DA9",  # Violet
]

DEFAULT_ICONS = ["📦", "🏷️", "📋", "🔗", "📊", "🏢", "👤", "💰", "📄", "⚙️", "🔒", "📈"]

# XSD → Playground type mapping
XSD_TO_PLAYGROUND = {
    str(XSD.string): "string",
    str(XSD.integer): "integer",
    str(XSD.int): "integer",
    str(XSD.long): "integer",
    str(XSD.nonNegativeInteger): "integer",
    str(XSD.positiveInteger): "integer",
    str(XSD.decimal): "decimal",
    str(XSD.float): "double",
    str(XSD.double): "double",
    str(XSD.boolean): "boolean",
    str(XSD.date): "date",
    str(XSD.dateTime): "datetime",
}


class PlaygroundExporter:
    """Exports an OntologyManager graph to Ontology Playground JSON format."""

    def __init__(self, manager: OntologyManager):
        self.mgr = manager

    def export(self, name: str | None = None, description: str | None = None) -> dict[str, Any]:
        """Export the ontology to Playground's JSON format.

        Returns a dict with `ontology` key matching what ImportExportModal expects:
        { ontology: { name, description, entityTypes[], relationships[] } }
        """
        ont_name = name or self._detect_ontology_name()
        ont_desc = description or self._detect_ontology_description()

        entity_types = self._build_entity_types()
        relationships = self._build_relationships(entity_types)

        return {
            "ontology": {
                "name": ont_name,
                "description": ont_desc,
                "entityTypes": entity_types,
                "relationships": relationships,
            }
        }

    def export_json(self, name: str | None = None, description: str | None = None, indent: int = 2) -> str:
        """Export as a JSON string."""
        return json.dumps(self.export(name, description), indent=indent, ensure_ascii=False)

    def save(self, path: str, name: str | None = None, description: str | None = None) -> None:
        """Save Playground JSON to a file."""
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.export_json(name, description))

    # ─── Entity types ─────────────────────────────────────────────────────

    def _build_entity_types(self) -> list[dict[str, Any]]:
        """Build EntityType[] from OWL classes and their data properties."""
        classes = self.mgr.get_classes()
        data_props = self.mgr.get_data_properties()

        # Map domain → properties
        domain_props: dict[str, list[dict]] = {}
        for prop in data_props:
            for domain_class in prop["domain"]:
                domain_props.setdefault(domain_class, []).append(prop)

        entity_types = []
        for i, cls in enumerate(classes):
            entity_id = self._to_entity_id(cls["name"])
            props = self._build_properties(domain_props.get(cls["name"], []))

            # Add a default identifier if none exists
            has_identifier = any(p.get("isIdentifier") for p in props)
            if not has_identifier:
                props.insert(0, {
                    "name": f"{entity_id}Id",
                    "type": "string",
                    "isIdentifier": True,
                    "description": f"Unique identifier for {cls['label']}",
                })

            entity_types.append({
                "id": entity_id,
                "name": cls["label"],
                "description": cls["comment"] or f"{cls['label']} entity",
                "properties": props,
                "icon": DEFAULT_ICONS[i % len(DEFAULT_ICONS)],
                "color": DEFAULT_COLORS[i % len(DEFAULT_COLORS)],
            })

        return entity_types

    def _build_properties(self, data_props: list[dict]) -> list[dict[str, Any]]:
        """Build Property[] from OWL data properties."""
        props = []
        for dp in data_props:
            pg_type = "string"
            for r in dp.get("range", []):
                # Check XSD type mapping
                for xsd_uri, playground_type in XSD_TO_PLAYGROUND.items():
                    if r in xsd_uri or r == self._local_name_from_uri(xsd_uri):
                        pg_type = playground_type
                        break

            prop: dict[str, Any] = {
                "name": self._to_property_name(dp["name"]),
                "type": pg_type,
            }
            if dp.get("comment"):
                prop["description"] = dp["comment"]

            props.append(prop)

        return props

    # ─── Relationships ────────────────────────────────────────────────────

    def _build_relationships(self, entity_types: list[dict]) -> list[dict[str, Any]]:
        """Build Relationship[] from OWL object properties."""
        obj_props = self.mgr.get_object_properties()
        entity_ids = {et["name"].lower(): et["id"] for et in entity_types}
        # Also map by class name
        for cls in self.mgr.get_classes():
            entity_ids[cls["name"].lower()] = self._to_entity_id(cls["name"])

        relationships = []
        seen = set()

        for prop in obj_props:
            for domain_cls in prop["domain"]:
                for range_cls in prop["range"]:
                    from_id = entity_ids.get(domain_cls.lower(), self._to_entity_id(domain_cls))
                    to_id = entity_ids.get(range_cls.lower(), self._to_entity_id(range_cls))

                    # Deduplicate
                    key = (from_id, prop["name"], to_id)
                    if key in seen:
                        continue
                    seen.add(key)

                    # Infer cardinality from property characteristics
                    cardinality = self._infer_cardinality(prop)

                    rel_id = f"{from_id}-{self._to_property_name(prop['name'])}-{to_id}"
                    relationships.append({
                        "id": rel_id,
                        "name": prop["label"] or prop["name"],
                        "from": from_id,
                        "to": to_id,
                        "cardinality": cardinality,
                    })
                    if prop.get("comment"):
                        relationships[-1]["description"] = prop["comment"]

        return relationships

    def _infer_cardinality(self, prop: dict) -> str:
        """Infer cardinality from OWL property characteristics."""
        chars = prop.get("characteristics", [])
        if "functional" in chars:
            # Functional = at most one value → many-to-one or one-to-one
            if "inverse_functional" in chars:
                return "one-to-one"
            return "many-to-one"
        if "inverse_functional" in chars:
            return "one-to-many"
        return "one-to-many"  # Default assumption

    # ─── Ontology metadata ────────────────────────────────────────────────

    def _detect_ontology_name(self) -> str:
        """Try to extract ontology name from the graph."""
        for s in self.mgr.graph.subjects(RDF.type, OWL.Ontology):
            label = self.mgr._get_label(s)
            if label:
                return label
            # Try dc:title
            from ..core.manager import DC, DCTERMS
            for title in self.mgr.graph.objects(s, DC.title):
                return str(title)
            for title in self.mgr.graph.objects(s, DCTERMS.title):
                return str(title)
        return "Extracted Ontology"

    def _detect_ontology_description(self) -> str:
        """Try to extract ontology description from the graph."""
        for s in self.mgr.graph.subjects(RDF.type, OWL.Ontology):
            comment = self.mgr._get_comment(s)
            if comment:
                return comment
            from ..core.manager import DC
            for desc in self.mgr.graph.objects(s, DC.description):
                return str(desc)
        return ""

    # ─── Name conversion helpers ──────────────────────────────────────────

    @staticmethod
    def _to_entity_id(name: str) -> str:
        """Convert a class name to a Playground entity ID (camelCase)."""
        # Remove non-alphanumeric (keep spaces for splitting)
        clean = re.sub(r"[^a-zA-Z0-9\s]", "", name)
        words = clean.split()
        if not words:
            return "unknown"
        return words[0].lower() + "".join(w.capitalize() for w in words[1:])

    @staticmethod
    def _to_property_name(name: str) -> str:
        """Convert an OWL property name to a Playground property name (camelCase)."""
        # Split on underscores, hyphens, or camelCase boundaries
        parts = re.split(r"[_\-\s]+", name)
        if not parts:
            return "unknown"
        return parts[0].lower() + "".join(p.capitalize() for p in parts[1:])

    @staticmethod
    def _local_name_from_uri(uri: str) -> str:
        """Extract local name from a URI."""
        for sep in ("#", "/"):
            if sep in uri:
                return uri.rsplit(sep, 1)[-1]
        return uri
