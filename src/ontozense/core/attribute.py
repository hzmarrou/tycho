"""Per-element typed attribute for property-extraction Phase A.

The ``Attribute`` dataclass is the fused, ontology-ready representation of
a per-entity property: name, XSD-typed range, multiplicity, identifier flag,
nullability, optional enum value set, and provenance.

Provenance follows the established Tycho pattern: every contributing source
records a ``FieldProvenance`` so the curator can see which adapter (Source
C SQL DDL, Source D Python AST, Source B governance JSON) attested each
fact.

Phase A is **deterministic-only**: Attribute records are built from Source
C / D / B raw extractor output, with no LLM involvement. Phase B will later
populate Attribute records from a SPIRES Pass-2 fallback when a concept
has no deterministic backing.

OWL emission (Phase A PR3) projects each Attribute into one
``owl:DatatypeProperty`` whose ``rdfs:range`` is the ``xsd_type`` field
and whose ``rdfs:domain`` is the URI of the parent class.

XSD type mapping is encoded in ``xsd_type_for_sql()`` and
``xsd_type_for_python()`` so the table in
``docs/PROPERTY_EXTRACTION_DESIGN.md §5`` has a single executable home.
Unknown / vendor-specific types collapse to ``xsd:string`` with the
original string preserved in ``raw_type`` and surfaced as a comment in
the OWL projection.

Phase A scope (this module):
  - Attribute dataclass + JSON serialise/deserialise helpers.
  - Pure type-mapping functions for SQL → XSD and Python → XSD.
  - No fusion logic, no OWL emission, no extraction (those live in PR2
    and PR3 respectively).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


# ─── XSD type mapping tables ─────────────────────────────────────────────────
#
# Source-of-truth for the design doc XSD table (revised r1).
# Keep these dicts in sync with docs/PROPERTY_EXTRACTION_DESIGN.md §5.
#
# Keys are stored uppercase. Look-ups normalise the caller's input to
# uppercase and strip vendor parameters (``VARCHAR(255)`` → ``VARCHAR``)
# before consulting the table.

_SQL_BASE_TO_XSD: dict[str, str] = {
    # Strings
    "VARCHAR": "xsd:string",
    "CHAR": "xsd:string",
    "TEXT": "xsd:string",
    "CITEXT": "xsd:string",
    "UUID": "xsd:string",             # r1: was xsd:anyURI; corrected per Codex
    "JSON": "xsd:string",
    "JSONB": "xsd:string",
    "GEOMETRY": "xsd:string",
    "GEOGRAPHY": "xsd:string",
    "STRING": "xsd:string",
    # Integers (all widths collapse)
    "SMALLINT": "xsd:integer",
    "INT": "xsd:integer",
    "INTEGER": "xsd:integer",
    "BIGINT": "xsd:integer",
    "TINYINT": "xsd:integer",
    "SERIAL": "xsd:integer",
    "BIGSERIAL": "xsd:integer",
    "SMALLSERIAL": "xsd:integer",
    # Decimal / fixed point / money
    "DECIMAL": "xsd:decimal",
    "NUMERIC": "xsd:decimal",
    "MONEY": "xsd:decimal",
    # Floating point
    "FLOAT": "xsd:double",
    "REAL": "xsd:double",
    "DOUBLE": "xsd:double",
    "DOUBLE PRECISION": "xsd:double",
    # Date / time
    "DATE": "xsd:date",
    "TIME": "xsd:time",
    "TIMESTAMP": "xsd:dateTime",
    "DATETIME": "xsd:dateTime",
    "TIMESTAMPTZ": "xsd:dateTimeStamp",
    "TIMESTAMP WITH TIME ZONE": "xsd:dateTimeStamp",
    "INTERVAL": "xsd:duration",
    # Boolean
    "BOOLEAN": "xsd:boolean",
    "BOOL": "xsd:boolean",
    # Binary
    "BLOB": "xsd:base64Binary",
    "BYTEA": "xsd:base64Binary",
}


_PY_BASE_TO_XSD: dict[str, str] = {
    "str": "xsd:string",
    "bytes": "xsd:base64Binary",
    "bytearray": "xsd:base64Binary",
    "int": "xsd:integer",
    "float": "xsd:double",
    "decimal": "xsd:decimal",
    "Decimal": "xsd:decimal",
    "bool": "xsd:boolean",
    "date": "xsd:date",
    "time": "xsd:time",
    "datetime": "xsd:dateTime",
    "UUID": "xsd:string",
    "uuid": "xsd:string",
}


_DEFAULT_XSD = "xsd:string"


# Recognised wrapper types whose first parameter carries the real type
# (e.g. ``DECIMAL(10,2)``, ``VARCHAR(255)``, ``NUMERIC(18,4)``). We strip
# the parameter list before look-up.
_PARAM_STRIP_RE = re.compile(r"^\s*([A-Za-z_][\w\s]*)\s*(?:\(.*\))?\s*$")


def xsd_type_for_sql(sql_type: str) -> str:
    """Map an SQL type string to an XSD URI.

    ``sql_type`` may include precision/scale parameters
    (``DECIMAL(10,2)``) — the parameter list is stripped before look-up.
    Multi-word types like ``DOUBLE PRECISION`` and ``TIMESTAMP WITH TIME
    ZONE`` are recognised verbatim.

    Unknown / vendor-specific types default to ``xsd:string``; callers
    are expected to retain the original string in
    ``Attribute.raw_type``.

    Element-type extraction for arrays (``INT[]``, ``ARRAY``) lives in
    Source C/D adapter code that sets ``is_multivalued = True`` on the
    Attribute and passes the element type to this function.
    """
    if not sql_type:
        return _DEFAULT_XSD
    s = sql_type.strip()

    # ARRAY notation: ``INT[]`` → look up ``INT`` (caller is responsible
    # for flipping is_multivalued).
    if s.endswith("[]"):
        return xsd_type_for_sql(s[:-2])

    # Try multi-word forms first, before stripping parameters.
    upper_full = s.upper()
    if upper_full in _SQL_BASE_TO_XSD:
        return _SQL_BASE_TO_XSD[upper_full]

    # Strip ``(...)`` parameters and try again.
    match = _PARAM_STRIP_RE.match(s)
    if match:
        base = match.group(1).strip().upper()
        if base in _SQL_BASE_TO_XSD:
            return _SQL_BASE_TO_XSD[base]

    return _DEFAULT_XSD


def xsd_type_for_python(py_type: str) -> str:
    """Map a Python type annotation string to an XSD URI.

    Accepts the verbatim ``ast.unparse(annotation)`` output. Wrappers
    (``Optional[T]``, ``list[T]``, ``Mapped[T]``, ``T | None``) are
    stripped by the caller via the AttributeFact metadata extracted in
    PR1a; this function takes the inner type name.

    Unknown / complex annotations default to ``xsd:string``. PEP 604
    union types beyond ``T | None`` collapse to the leftmost non-None
    arm per design §5 decision 5.
    """
    if not py_type:
        return _DEFAULT_XSD
    s = py_type.strip()
    if s in _PY_BASE_TO_XSD:
        return _PY_BASE_TO_XSD[s]
    # Best-effort: split on ``.`` for ``decimal.Decimal``, ``datetime.date``
    # style fully-qualified names; try the tail first.
    tail = s.rsplit(".", 1)[-1]
    if tail in _PY_BASE_TO_XSD:
        return _PY_BASE_TO_XSD[tail]
    return _DEFAULT_XSD


# ─── Attribute dataclass + provenance ───────────────────────────────────────


@dataclass
class FieldProvenance:
    """One source's attestation of a single attribute fact.

    Mirrors the shape used by element-level fusion
    (``ontozense.core.fusion.FieldProvenance``) so curators see one
    consistent provenance structure across the whole fused.json.
    """

    source: str                         # "A" | "B" | "C" | "D"
    artifact: str = ""                  # file path or extractor identifier
    line: int = 0
    confidence: float = 1.0             # 1.0 for deterministic
    extractor: str = ""                 # "ddl" | "ast" | "governance" | ...

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "artifact": self.artifact,
            "line": self.line,
            "confidence": self.confidence,
            "extractor": self.extractor,
        }

    @classmethod
    def from_json_dict(cls, raw: dict[str, Any]) -> FieldProvenance:
        return cls(
            source=raw.get("source", ""),
            artifact=raw.get("artifact", ""),
            line=raw.get("line", 0),
            confidence=raw.get("confidence", 1.0),
            extractor=raw.get("extractor", ""),
        )


@dataclass
class Attribute:
    """Per-entity typed property — Phase A deterministic shape.

    One ``Attribute`` projects into one ``owl:DatatypeProperty`` at OWL
    emission time (PR3). ``description`` populates ``rdfs:comment``,
    ``enum_values`` projects into an ``ontozense:enumValues`` annotation
    (annotation-only in Phase A; class-restriction encoding is deferred
    to Phase C per design §5 / Open Question #1).
    """

    name: str
    xsd_type: str                                       # "xsd:string", "xsd:decimal", ...
    description: str = ""
    is_id: bool = False                                 # PK or @id
    is_multivalued: bool = False
    is_nullable: bool = True
    enum_values: list[str] = field(default_factory=list)
    raw_type: str = ""                                  # original SQL/Python type verbatim
    field_provenance: list[FieldProvenance] = field(default_factory=list)
    confidence: float = 1.0

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "xsd_type": self.xsd_type,
            "description": self.description,
            "is_id": self.is_id,
            "is_multivalued": self.is_multivalued,
            "is_nullable": self.is_nullable,
            "enum_values": list(self.enum_values),
            "raw_type": self.raw_type,
            "field_provenance": [
                fp.to_json_dict() for fp in self.field_provenance
            ],
            "confidence": self.confidence,
        }

    @classmethod
    def from_json_dict(cls, raw: dict[str, Any]) -> Attribute:
        return cls(
            name=raw.get("name", ""),
            xsd_type=raw.get("xsd_type", _DEFAULT_XSD),
            description=raw.get("description", ""),
            is_id=raw.get("is_id", False),
            is_multivalued=raw.get("is_multivalued", False),
            is_nullable=raw.get("is_nullable", True),
            enum_values=list(raw.get("enum_values") or []),
            raw_type=raw.get("raw_type", ""),
            field_provenance=[
                FieldProvenance.from_json_dict(fp)
                for fp in raw.get("field_provenance") or []
            ],
            confidence=raw.get("confidence", 1.0),
        )
