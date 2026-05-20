"""Core ontology manager — rdflib-based OWL manipulation engine.

Loads OWL ontologies (from OntoGPT or any source), validates, normalizes,
merges, and exports them. Inspired by OrionBelt's OntologyManager patterns
but scoped to the Ontozense pipeline.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from rdflib import BNode, Graph, Literal, Namespace, URIRef
from rdflib.namespace import OWL, RDF, RDFS, XSD


# ─── Standard namespaces ─────────────────────────────────────────────────────

DCTERMS = Namespace("http://purl.org/dc/terms/")
DC = Namespace("http://purl.org/dc/elements/1.1/")
SKOS = Namespace("http://www.w3.org/2004/02/skos/core#")

# XSD type mapping: friendly name → XSD URI
XSD_TYPES = {
    "string": XSD.string,
    "integer": XSD.integer,
    "int": XSD.integer,
    "decimal": XSD.decimal,
    "float": XSD.float,
    "double": XSD.double,
    "boolean": XSD.boolean,
    "date": XSD.date,
    "datetime": XSD.dateTime,
    "dateTime": XSD.dateTime,
    "anyURI": XSD.anyURI,
    "nonNegativeInteger": XSD.nonNegativeInteger,
}


# ─── Data classes ─────────────────────────────────────────────────────────────

@dataclass
class ValidationIssue:
    severity: str  # "error", "warning", "info"
    message: str
    subject: Optional[str] = None
    category: str = "general"


@dataclass
class DiffResult:
    added_classes: list[str] = field(default_factory=list)
    removed_classes: list[str] = field(default_factory=list)
    added_properties: list[str] = field(default_factory=list)
    removed_properties: list[str] = field(default_factory=list)
    added_triples: int = 0
    removed_triples: int = 0
    summary: str = ""


@dataclass
class MergeResult:
    triples_before: int = 0
    triples_after: int = 0
    triples_added: int = 0
    conflicts: list[dict] = field(default_factory=list)


# ─── Naming policies ─────────────────────────────────────────────────────────
#
# A naming policy enforces a target system's identifier rules. The engine
# itself is target-agnostic; pass a NamingPolicy if you need to validate or
# normalize names for a specific consumer (e.g. Microsoft Fabric IQ, Snowflake,
# BigQuery, etc.).

@dataclass
class NamingPolicy:
    """A naming convention enforced by some target system."""
    name: str                       # human-readable identifier (e.g. "fabric_iq")
    pattern: re.Pattern             # regex the name must match
    single_char_pattern: re.Pattern # regex for single-char edge case
    max_length: int                 # truncation length

    def is_compliant(self, name: str) -> bool:
        if not name:
            return False
        if len(name) == 1:
            return bool(self.single_char_pattern.match(name))
        return bool(self.pattern.match(name))

    def normalize(self, name: str) -> str:
        """Normalize a name to comply with this policy."""
        normalized = re.sub(r"[^a-zA-Z0-9_-]", "-", name)
        normalized = re.sub(r"-+", "-", normalized)
        normalized = normalized.strip("-_")
        normalized = normalized[: self.max_length].rstrip("-_")
        return normalized or "unnamed"


# Fabric IQ is provided as a built-in policy *example*. Users targeting other
# systems can construct their own NamingPolicy instances. Nothing in the
# extraction or fusion pipeline depends on Fabric IQ specifically.
FABRIC_IQ_POLICY = NamingPolicy(
    name="fabric_iq",
    pattern=re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,24}[a-zA-Z0-9]$"),
    single_char_pattern=re.compile(r"^[a-zA-Z0-9]$"),
    max_length=26,
)


# Backwards-compat shims for code that imported the old function names
def is_fabric_iq_compliant(name: str) -> bool:
    return FABRIC_IQ_POLICY.is_compliant(name)


def normalize_to_fabric_iq(name: str) -> str:
    return FABRIC_IQ_POLICY.normalize(name)


# ─── OntologyManager ─────────────────────────────────────────────────────────

class OntologyManager:
    """Manages an OWL ontology graph with validation, normalization, and export capabilities."""

    def __init__(self, base_uri: str = "http://example.org/ontology#"):
        if not base_uri.endswith(("#", "/")):
            base_uri += "#"
        self.base_uri = base_uri
        self.namespace = Namespace(base_uri)
        self.graph = Graph()
        self._bind_standard_prefixes()
        # Declare the ontology
        ont_uri = URIRef(base_uri.rstrip("#/"))
        self.graph.add((ont_uri, RDF.type, OWL.Ontology))
        # Undo/redo
        self._undo_stack: list[bytes] = []
        self._redo_stack: list[bytes] = []
        self._max_history = 50

    def _bind_standard_prefixes(self) -> None:
        self.graph.bind("owl", OWL)
        self.graph.bind("rdf", RDF)
        self.graph.bind("rdfs", RDFS)
        self.graph.bind("xsd", XSD)
        self.graph.bind("dc", DC)
        self.graph.bind("dcterms", DCTERMS)
        self.graph.bind("skos", SKOS)
        self.graph.bind("", self.namespace)

    # ─── URI helpers ──────────────────────────────────────────────────────

    def _uri(self, name: str) -> URIRef:
        """Convert a local name or full URI to a URIRef."""
        if name.startswith(("http://", "https://")):
            return URIRef(name)
        return self.namespace[name]

    def _local_name(self, uri: URIRef | str) -> str:
        """Extract the local/fragment name from a URI."""
        uri_str = str(uri)
        for sep in ("#", "/"):
            if sep in uri_str:
                return uri_str.rsplit(sep, 1)[-1]
        return uri_str

    # ─── Load / Save ─────────────────────────────────────────────────────

    def load(self, source: str, format: str | None = None) -> None:
        """Load an ontology from a file path or URL."""
        self.graph = Graph()
        self.graph.parse(source, format=format)
        self._bind_standard_prefixes()
        self._detect_namespace()

    def load_from_string(self, data: str, format: str = "xml") -> None:
        """Load an ontology from a string."""
        self.graph = Graph()
        self.graph.parse(data=data, format=format)
        self._bind_standard_prefixes()
        self._detect_namespace()

    def _detect_namespace(self) -> None:
        """Detect the base namespace from the loaded ontology."""
        for s in self.graph.subjects(RDF.type, OWL.Ontology):
            uri_str = str(s)
            if uri_str.endswith("#"):
                self.base_uri = uri_str
            elif uri_str.endswith("/"):
                self.base_uri = uri_str
            else:
                self.base_uri = uri_str + "#"
            self.namespace = Namespace(self.base_uri)
            self.graph.bind("", self.namespace)
            return
        # Fallback: infer from most common namespace among classes
        ns_count: dict[str, int] = {}
        for s in self.graph.subjects(RDF.type, OWL.Class):
            if isinstance(s, BNode):
                continue
            uri_str = str(s)
            for sep in ("#", "/"):
                if sep in uri_str:
                    ns = uri_str.rsplit(sep, 1)[0] + sep
                    ns_count[ns] = ns_count.get(ns, 0) + 1
                    break
        if ns_count:
            self.base_uri = max(ns_count, key=ns_count.get)  # type: ignore[arg-type]
            self.namespace = Namespace(self.base_uri)
            self.graph.bind("", self.namespace)

    def serialize(self, format: str = "xml") -> str:
        """Serialize the ontology to a string."""
        return self.graph.serialize(format=format)

    def save(self, path: str, format: str = "xml") -> None:
        """Save the ontology to a file."""
        self.graph.serialize(destination=path, format=format)

    # ─── Query: Classes ──────────────────────────────────────────────────

    def get_classes(self) -> list[dict]:
        """Return all named OWL classes with their metadata."""
        classes = []
        for cls_uri in self.graph.subjects(RDF.type, OWL.Class):
            if isinstance(cls_uri, BNode):
                continue
            name = self._local_name(cls_uri)
            label = self._get_label(cls_uri)
            comment = self._get_comment(cls_uri)
            parents = [
                self._local_name(p)
                for p in self.graph.objects(cls_uri, RDFS.subClassOf)
                if isinstance(p, URIRef)
            ]
            children = [
                self._local_name(c)
                for c in self.graph.subjects(RDFS.subClassOf, cls_uri)
                if isinstance(c, URIRef)
            ]
            classes.append({
                "uri": str(cls_uri),
                "name": name,
                "label": label or name,
                "comment": comment or "",
                "parents": parents,
                "children": children,
            })
        return classes

    def get_class_hierarchy(self) -> dict[str, list[str]]:
        """Return class hierarchy as adjacency list: parent → [children]."""
        hierarchy: dict[str, list[str]] = {}
        for cls_uri in self.graph.subjects(RDF.type, OWL.Class):
            if isinstance(cls_uri, BNode):
                continue
            name = self._local_name(cls_uri)
            if name not in hierarchy:
                hierarchy[name] = []
            for parent_uri in self.graph.objects(cls_uri, RDFS.subClassOf):
                if isinstance(parent_uri, URIRef):
                    parent = self._local_name(parent_uri)
                    if parent not in hierarchy:
                        hierarchy[parent] = []
                    hierarchy[parent].append(name)
        return hierarchy

    # ─── Query: Properties ───────────────────────────────────────────────

    def get_object_properties(self) -> list[dict]:
        """Return all OWL object properties."""
        props = []
        for prop_uri in self.graph.subjects(RDF.type, OWL.ObjectProperty):
            if isinstance(prop_uri, BNode):
                continue
            name = self._local_name(prop_uri)
            label = self._get_label(prop_uri)
            comment = self._get_comment(prop_uri)
            domain = [self._local_name(d) for d in self.graph.objects(prop_uri, RDFS.domain) if isinstance(d, URIRef)]
            range_ = [self._local_name(r) for r in self.graph.objects(prop_uri, RDFS.range) if isinstance(r, URIRef)]
            characteristics = self._get_property_characteristics(prop_uri)
            props.append({
                "uri": str(prop_uri),
                "name": name,
                "label": label or name,
                "comment": comment or "",
                "domain": domain,
                "range": range_,
                "characteristics": characteristics,
            })
        return props

    def get_data_properties(self) -> list[dict]:
        """Return all OWL datatype properties."""
        props = []
        for prop_uri in self.graph.subjects(RDF.type, OWL.DatatypeProperty):
            if isinstance(prop_uri, BNode):
                continue
            name = self._local_name(prop_uri)
            label = self._get_label(prop_uri)
            comment = self._get_comment(prop_uri)
            domain = [self._local_name(d) for d in self.graph.objects(prop_uri, RDFS.domain) if isinstance(d, URIRef)]
            range_ = []
            for r in self.graph.objects(prop_uri, RDFS.range):
                if isinstance(r, URIRef):
                    local = self._local_name(r)
                    range_.append(local)
            props.append({
                "uri": str(prop_uri),
                "name": name,
                "label": label or name,
                "comment": comment or "",
                "domain": domain,
                "range": range_,
            })
        return props

    def _get_property_characteristics(self, prop_uri: URIRef) -> list[str]:
        """Get OWL property characteristics (functional, transitive, etc.)."""
        chars = []
        type_map = {
            OWL.FunctionalProperty: "functional",
            OWL.InverseFunctionalProperty: "inverse_functional",
            OWL.TransitiveProperty: "transitive",
            OWL.SymmetricProperty: "symmetric",
            OWL.AsymmetricProperty: "asymmetric",
            OWL.ReflexiveProperty: "reflexive",
            OWL.IrreflexiveProperty: "irreflexive",
        }
        for owl_type, name in type_map.items():
            if (prop_uri, RDF.type, owl_type) in self.graph:
                chars.append(name)
        return chars

    # ─── Annotation helpers ──────────────────────────────────────────────

    def _get_label(self, uri: URIRef) -> str | None:
        for label in self.graph.objects(uri, RDFS.label):
            return str(label)
        for label in self.graph.objects(uri, SKOS.prefLabel):
            return str(label)
        return None

    def _get_comment(self, uri: URIRef) -> str | None:
        for comment in self.graph.objects(uri, RDFS.comment):
            return str(comment)
        return None

    # ─── Validation ──────────────────────────────────────────────────────

    def validate(
        self,
        naming_policy: NamingPolicy | None = None,
    ) -> list[ValidationIssue]:
        """Validate the ontology and return issues.

        Args:
            naming_policy: Optional naming policy to enforce
                (e.g. FABRIC_IQ_POLICY). If None, no naming compliance checks.
        """
        issues: list[ValidationIssue] = []
        classes = self.get_classes()
        obj_props = self.get_object_properties()
        data_props = self.get_data_properties()

        # Check: at least one class
        if not classes:
            issues.append(ValidationIssue("error", "Ontology has no classes defined", category="completeness"))

        # Check: classes without labels
        for cls in classes:
            if cls["label"] == cls["name"]:
                # No explicit label — name is being used as fallback
                issues.append(ValidationIssue(
                    "warning",
                    f"Class '{cls['name']}' has no rdfs:label",
                    subject=cls["name"],
                    category="labeling",
                ))

        # Check: orphan classes (no parents, no children, not referenced in any property)
        referenced_classes = set()
        for prop in obj_props:
            referenced_classes.update(prop["domain"])
            referenced_classes.update(prop["range"])
        for prop in data_props:
            referenced_classes.update(prop["domain"])
        for cls in classes:
            if not cls["parents"] and not cls["children"] and cls["name"] not in referenced_classes:
                issues.append(ValidationIssue(
                    "info",
                    f"Class '{cls['name']}' is an orphan — no hierarchy or property references",
                    subject=cls["name"],
                    category="structure",
                ))

        # Check: properties without domain or range
        for prop in obj_props:
            if not prop["domain"]:
                issues.append(ValidationIssue(
                    "warning",
                    f"Object property '{prop['name']}' has no rdfs:domain",
                    subject=prop["name"],
                    category="completeness",
                ))
            if not prop["range"]:
                issues.append(ValidationIssue(
                    "warning",
                    f"Object property '{prop['name']}' has no rdfs:range",
                    subject=prop["name"],
                    category="completeness",
                ))
        for prop in data_props:
            if not prop["domain"]:
                issues.append(ValidationIssue(
                    "warning",
                    f"Data property '{prop['name']}' has no rdfs:domain",
                    subject=prop["name"],
                    category="completeness",
                ))

        # Check: duplicate labels
        label_map: dict[str, list[str]] = {}
        for cls in classes:
            label = cls["label"].lower()
            label_map.setdefault(label, []).append(cls["name"])
        for label, names in label_map.items():
            if len(names) > 1:
                issues.append(ValidationIssue(
                    "warning",
                    f"Duplicate label '{label}' on classes: {', '.join(names)}",
                    category="naming",
                ))

        # Check: naming policy compliance (if a policy was provided)
        if naming_policy is not None:
            for cls in classes:
                if not naming_policy.is_compliant(cls["name"]):
                    issues.append(ValidationIssue(
                        "info",
                        f"Class '{cls['name']}' is not compliant with naming policy '{naming_policy.name}'",
                        subject=cls["name"],
                        category=f"naming_policy_{naming_policy.name}",
                    ))

        return issues

    # ─── Normalization ───────────────────────────────────────────────────

    def normalize_names(
        self,
        naming_policy: NamingPolicy | None = None,
    ) -> dict[str, str]:
        """Normalize class and property names per a naming policy.

        Args:
            naming_policy: Policy to enforce. If None, no normalization.

        Returns:
            Mapping of old → new names for renamed classes.
        """
        renames: dict[str, str] = {}
        if naming_policy is None:
            return renames

        for cls in self.get_classes():
            if not naming_policy.is_compliant(cls["name"]):
                new_name = naming_policy.normalize(cls["name"])
                if new_name != cls["name"]:
                    renames[cls["name"]] = new_name

        # Apply renames
        for old_name, new_name in renames.items():
            self._rename_resource(self._uri(old_name), self._uri(new_name))

        return renames

    def _rename_resource(self, old_uri: URIRef, new_uri: URIRef) -> None:
        """Rename a resource everywhere it appears in the graph."""
        # Replace as subject
        for p, o in list(self.graph.predicate_objects(old_uri)):
            self.graph.remove((old_uri, p, o))
            self.graph.add((new_uri, p, o))
        # Replace as object
        for s, p in list(self.graph.subject_predicates(old_uri)):
            self.graph.remove((s, p, old_uri))
            self.graph.add((s, p, new_uri))

    # ─── Deduplication ───────────────────────────────────────────────────

    def find_duplicates(self, threshold: float = 0.8) -> list[tuple[str, str, float]]:
        """Find potentially duplicate classes by name similarity."""
        classes = [cls["name"] for cls in self.get_classes()]
        duplicates = []
        for i, name_a in enumerate(classes):
            for name_b in classes[i + 1:]:
                score = self._name_similarity(name_a, name_b)
                if score >= threshold:
                    duplicates.append((name_a, name_b, score))
        return sorted(duplicates, key=lambda x: -x[2])

    @staticmethod
    def _name_similarity(a: str, b: str) -> float:
        """Simple normalized similarity between two names."""
        a_lower = a.lower().replace("_", "").replace("-", "")
        b_lower = b.lower().replace("_", "").replace("-", "")
        # Exact match after normalization
        if a_lower == b_lower:
            return 1.0
        # One is plural of the other
        if a_lower + "s" == b_lower or b_lower + "s" == a_lower:
            return 0.95
        if a_lower + "es" == b_lower or b_lower + "es" == a_lower:
            return 0.95
        # Substring containment
        if a_lower in b_lower or b_lower in a_lower:
            shorter = min(len(a_lower), len(b_lower))
            longer = max(len(a_lower), len(b_lower))
            return shorter / longer if longer > 0 else 0.0
        return 0.0

    # ─── Merge ───────────────────────────────────────────────────────────

    def merge(self, other: OntologyManager, strategy: str = "additive") -> MergeResult:
        """Merge another ontology into this one.

        Strategies:
            - "additive": union of all triples (other wins on conflicts)
            - "conservative": only add triples that don't conflict
        """
        result = MergeResult(triples_before=len(self.graph))

        if strategy == "additive":
            for s, p, o in other.graph:
                self.graph.add((s, p, o))
        elif strategy == "conservative":
            conflict_preds = {RDFS.label, RDFS.comment, RDFS.domain, RDFS.range}
            for s, p, o in other.graph:
                if p in conflict_preds and (s, p, None) in self.graph:
                    result.conflicts.append({
                        "subject": str(s),
                        "predicate": str(p),
                        "existing": str(list(self.graph.objects(s, p))[0]),
                        "incoming": str(o),
                    })
                else:
                    self.graph.add((s, p, o))

        result.triples_after = len(self.graph)
        result.triples_added = result.triples_after - result.triples_before
        return result

    # ─── Diff ────────────────────────────────────────────────────────────

    def diff(self, other: OntologyManager) -> DiffResult:
        """Compare this ontology with another, focusing on classes and properties."""
        my_classes = {cls["name"] for cls in self.get_classes()}
        other_classes = {cls["name"] for cls in other.get_classes()}

        my_props = {p["name"] for p in self.get_object_properties() + self.get_data_properties()}
        other_props = {p["name"] for p in other.get_object_properties() + other.get_data_properties()}

        my_triples = set(self.graph)
        other_triples = set(other.graph)

        result = DiffResult(
            added_classes=sorted(other_classes - my_classes),
            removed_classes=sorted(my_classes - other_classes),
            added_properties=sorted(other_props - my_props),
            removed_properties=sorted(my_props - other_props),
            added_triples=len(other_triples - my_triples),
            removed_triples=len(my_triples - other_triples),
        )
        parts = []
        if result.added_classes:
            parts.append(f"+{len(result.added_classes)} classes")
        if result.removed_classes:
            parts.append(f"-{len(result.removed_classes)} classes")
        if result.added_properties:
            parts.append(f"+{len(result.added_properties)} properties")
        if result.removed_properties:
            parts.append(f"-{len(result.removed_properties)} properties")
        result.summary = ", ".join(parts) or "No changes"
        return result

    # ─── Reasoning ───────────────────────────────────────────────────────

    def apply_reasoning(self, profile: str = "rdfs") -> int:
        """Apply RDFS or OWL-RL reasoning. Returns number of new triples inferred."""
        import owlrl

        before = len(self.graph)
        if profile == "rdfs":
            owlrl.DeductiveClosure(owlrl.RDFS_Semantics).expand(self.graph)
        elif profile == "owl-rl":
            owlrl.DeductiveClosure(owlrl.OWLRL_Semantics).expand(self.graph)
        elif profile == "owl-rl-ext":
            owlrl.DeductiveClosure(owlrl.OWLRL_Extension).expand(self.graph)
        return len(self.graph) - before

    # ─── Undo / Redo ─────────────────────────────────────────────────────

    def checkpoint(self, label: str = "edit") -> None:
        """Save current state for undo."""
        snapshot = self.graph.serialize(format="ntriples").encode("utf-8")
        self._undo_stack.append(snapshot)
        self._redo_stack.clear()
        if len(self._undo_stack) > self._max_history:
            self._undo_stack.pop(0)

    def undo(self) -> bool:
        """Restore the previous state. Returns True if successful."""
        if not self._undo_stack:
            return False
        current = self.graph.serialize(format="ntriples").encode("utf-8")
        self._redo_stack.append(current)
        snapshot = self._undo_stack.pop()
        self.graph = Graph()
        self.graph.parse(data=snapshot.decode("utf-8"), format="ntriples")
        self._bind_standard_prefixes()
        return True

    def redo(self) -> bool:
        """Redo the last undone operation. Returns True if successful."""
        if not self._redo_stack:
            return False
        current = self.graph.serialize(format="ntriples").encode("utf-8")
        self._undo_stack.append(current)
        snapshot = self._redo_stack.pop()
        self.graph = Graph()
        self.graph.parse(data=snapshot.decode("utf-8"), format="ntriples")
        self._bind_standard_prefixes()
        return True

    # ─── Statistics ──────────────────────────────────────────────────────

    def get_statistics(self) -> dict[str, int]:
        """Return counts of ontology elements."""
        return {
            "classes": sum(1 for s in self.graph.subjects(RDF.type, OWL.Class) if not isinstance(s, BNode)),
            "object_properties": sum(1 for _ in self.graph.subjects(RDF.type, OWL.ObjectProperty)),
            "data_properties": sum(1 for _ in self.graph.subjects(RDF.type, OWL.DatatypeProperty)),
            "total_triples": len(self.graph),
        }

    def __repr__(self) -> str:
        stats = self.get_statistics()
        return (
            f"OntologyManager(classes={stats['classes']}, "
            f"obj_props={stats['object_properties']}, "
            f"data_props={stats['data_properties']}, "
            f"triples={stats['total_triples']})"
        )
