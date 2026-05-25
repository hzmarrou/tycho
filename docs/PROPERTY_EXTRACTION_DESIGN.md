# Property Extraction — Design Proposal

**Status:** Draft for review
**Author:** Generated via Claude Code session, 2026-05-25
**Reviewers:** [assign]
**Related docs:** [PROFILE_INDUCTION_ARCHITECTURE.md](./PROFILE_INDUCTION_ARCHITECTURE.md),
[PROFILE_SPEC.md](./PROFILE_SPEC.md), [SPIRES.md](./SPIRES.md)

---

## 1. Problem Statement

Tycho's current pipeline produces draft ontologies that are **conceptually
correct but property-blind**.

A run on the NPL domain (Basel D403 + governance.json + npl-code AST +
npl-schema.sql) emits an OWL file containing:

- ~30 `owl:Class` entries
- ~12 `owl:ObjectProperty` entries with `rdfs:domain` / `rdfs:range`
- **0 `owl:DatatypeProperty` entries**
- **0 cardinality assertions on object properties**

When loaded into a standard ontology editor (Protégé, IRIS, the
`cosmic-coffee-company-ontology.rdf` reference editor), each entity card
shows a name and label, but no fields. The reference pattern looks like:

```
ENTITY TYPE: Shipment
  Properties (5):
    shipmentId      string  (ID)
    dispatchDate    date
    arrivalDate     date
    status          enum
    weight (kg)     decimal
  Relationships (3):
    sentBy       → Supplier    many-to-one
    deliveredTo  → Store       many-to-one
    carries      → Product     many-to-many
```

Tycho today produces only the bottom (relationships) half, never the top
(properties) half.

### Why this matters

1. **Curator friction.** The OWL file is Tycho's handoff artefact to a
   human curator. A class with no properties forces the curator to
   reconstruct every field by hand from the source files — exactly the
   work Tycho is supposed to bootstrap.
2. **Validation rules underused.** The profile schema already supports
   `required_fields` per entity type (used by VR003 in
   `core/validation.py`), but without per-entity attribute extraction we
   have nothing to validate against.
3. **Code-anchored domains pay double.** For domains that already supply
   structured field information (SQL DDL, Pydantic models, dataclasses),
   the data is parsed by Tycho's extractors but discarded before fusion.

### Root cause

Two independent gaps, both intentional in earlier phases:

1. **The SPIRES LinkML template used by `domain_doc_extractor.py` is
   flat.** It declares two slots — `concepts` and `relationships` — and
   no per-class attribute schema. SPIRES (per
   [SPIRES.md](./SPIRES.md) §2-3) is *capable* of nested per-class
   attribute extraction; Tycho's template doesn't ask for it.
   See `src/ontozense/extractors/domain_doc_extractor.py:282-326`.
2. **`candidate-graph.json` is lossy for field metadata.** Source C
   columns (parsed by `sqlglot`) and Source D class fields (parsed by
   AST) carry column name, SQL type, primary-key flag, foreign-key
   target, and nullability. The candidate graph keeps the *table name*
   as a concept but drops everything below it. Fusion therefore never
   sees field data, and the OWL exporter at `core/owl_export.py:72-106`
   correspondingly never emits any `owl:DatatypeProperty`.

### Constraint: domain agnosticism

Tycho is designed to bootstrap ontologies across **arbitrary domains**,
not just NPL. The property-extraction design must work across all of:

| Domain shape           | Source A docs | Source C SQL | Source D code | Comment                |
|------------------------|---------------|--------------|---------------|------------------------|
| NPL (current)          | ✓ Basel       | ✓ schema     | ✓ Python      | Strong code anchor     |
| Pure regulatory        | ✓             | ✗            | ✗             | Doc-only               |
| SaaS data model        | ✗             | ✓            | ✓             | No prose docs          |
| Wet-lab biology        | ✓ papers      | ✗            | ✗             | Doc-only               |
| Manufacturing / ERP    | ✓ specs       | ✓ DDL        | partial       | Mixed                  |

A solution that only works when Source C or D are present (deterministic
extraction) is insufficient. A solution that only works via LLM
(expensive, less reliable) is insufficient. We need both, layered.

---

## 2. Goals

1. **Per-class `owl:DatatypeProperty` emission** with `rdfs:domain`
   pointing at the parent class and `rdfs:range` set to an `xsd:*` type.
2. **Per-class `owl:ObjectProperty` cardinality** annotations
   (`owl:FunctionalProperty`, `owl:maxCardinality`, etc.) where source
   data supports them.
3. **Provenance per attribute**, mirroring the existing
   `field_provenance` infrastructure used for element-level fusion.
4. **Domain-agnostic fallback chain** — deterministic sources preferred,
   LLM extraction triggered only when no deterministic data exists.
5. **Profile-aware** — the induced profile and any human-edited profile
   can declare expected attributes per entity type, used both as priors
   for extraction and as inputs to validation.
6. **No regression** on the existing concept/relationship pipeline. The
   current profile-driven workflow stays default and unchanged.

## 3. Non-Goals

- **Not** instance-level data extraction. We extract the schema
  (`Customer has field customerId of type string`), never instances
  (`Customer #123, name "Alice"`).
- **Not** full SHACL or OWL2-DL inference. The exporter stays at the
  level of axiom emission; consistency checking is left to downstream
  tools (Protégé reasoner, ROBOT).
- **Not** automatic foreign-key inference across unrelated sources. FK
  detection is limited to what the SQL parser and AST extractor already
  surface.
- **Not** a redesign of `candidate-graph.json` semantics — we add a
  parallel attribute channel rather than re-shape the existing fields.

---

## 4. Proposed Solution

Three phases, sequential. Each phase delivers independent user-visible
value. Phase A unblocks code-anchored domains; Phase B adds doc-only
domains; Phase C closes the loop with profile-driven validation.

### Phase A — Deterministic property extraction (Source C + D + B)

**What:** persist field-level data from existing extractors into
`discovery/`, carry it through fusion, emit `owl:DatatypeProperty` in
the OWL output.

**Source signals:**

- **Source C (SQL DDL via `sqlglot`)** — columns become datatype
  properties. SQL type → XSD type mapping (e.g. `VARCHAR` → `xsd:string`,
  `DECIMAL` → `xsd:decimal`, `DATE` → `xsd:date`). Primary key → ID
  annotation. Foreign key → object property domain/range + functional
  annotation (many-to-one).
- **Source D (Python AST)** — Pydantic/dataclass/SQLAlchemy fields
  become datatype properties. Python type → XSD type mapping. Field
  with `default_factory=list` → multivalued. Field with `unique=True`
  on a SQLAlchemy column → ID candidate.
- **Source B (governance.json)** — `data_type` field, when populated,
  becomes the XSD type. `enum_values` when populated becomes an
  `owl:oneOf` enumeration.

**Pipeline changes:**

1. New file `discovery/source-c.json` written by `survey` containing
   the full table → columns map (name, sql_type, nullable, pk, fk_target).
2. New file `discovery/source-d.json` written by `survey` containing the
   full class → fields map (name, py_type, default, multivalued).
3. `core/fusion.py` extended: each `FusedElement` gains an `attributes:
   list[Attribute]` field. Attribute carries `name`, `xsd_type`,
   `is_id`, `is_multivalued`, `enum_values`, and `field_provenance` (one
   entry per source that contributed).
4. `core/fusion.py` adds attribute-level fusion: when Source C says
   `customer.email VARCHAR(255)` and Source D says `Customer.email: str`,
   merge into a single `Attribute(name="email", xsd_type="xsd:string")`
   with provenance from both sources.
5. `core/owl_export.py` emits `owl:DatatypeProperty` per attribute,
   `owl:FunctionalProperty` for ID and many-to-one FK attributes.

**What ships in Phase A:**

- For NPL, the draft.owl will contain typed properties for every
  table/class present in `npl-schema.sql` and `npl-code/`.
- For SaaS / pure-data-model domains, full entity cards land
  immediately.
- For doc-only domains, no change — Phase B fills that gap.

**Acceptance:**

- `draft.owl` for NPL contains ≥ 1 `owl:DatatypeProperty` per class
  that has a backing table in `npl-schema.sql` or a backing class in
  `npl-code/`.
- All existing tests pass.
- A new test fixture covers an end-to-end run with synthetic SQL +
  Pydantic input, asserting per-attribute XSD types and ID flags.

### Phase B — LLM property extraction (SPIRES Pass-2)

**What:** for domains where Phase A produces no attributes on a given
concept *and* Source A documents exist, run a second SPIRES extraction
pass with a per-class LinkML template asking the LLM to enumerate
attributes from the source text.

**Trigger condition:**

- `FusedElement.attributes` is empty after Phase A fusion, AND
- the element has at least one `field_provenance` entry from Source A.

**Mechanism:**

1. `core/property_induction.py` (new) generates a LinkML template per
   eligible class with the SPIRES patterns from
   [SPIRES.md](./SPIRES.md) §3.1:
   ```yaml
   classes:
     Customer:
       attributes:
         attributes:
           description: |-
             A list of attributes of Customer. Each item must be a single
             line in the format:  attribute_name :: XSD_TYPE :: description
             where XSD_TYPE is one of: xsd:string, xsd:integer,
             xsd:decimal, xsd:date, xsd:dateTime, xsd:boolean, xsd:anyURI,
             or an enum value set.
           multivalued: true
   ```
2. Source text passed to SPIRES = the segments where the class was
   originally discovered (use `field_provenance[*].anchor.snippet`).
3. SPIRES output parsed into `Attribute` records and merged via the
   same fusion path as Phase A, with `source: "A"` and a confidence
   score derived from SPIRES grounding.
4. Phase B is opt-in via `--property-induction llm` on `draft`. Default
   off to control LLM cost.

**Cost control:**

- Triggered only for concepts with zero deterministic attributes.
- Per-concept LLM call (not per-document) — bounded by concept count.
- Result cached under `discovery/source-a-properties.json` so reruns
  don't re-query.

**Acceptance:**

- For a doc-only fixture (Basel D403 only, no SQL or code), `draft.owl`
  with `--property-induction llm` contains attributes on at least the
  top 5 concepts by Source A confidence.
- Without `--property-induction llm`, behaviour is identical to Phase
  A.

### Phase C — Profile-declared attribute schemas

**What:** extend the profile schema (`PROFILE_SPEC.md`) to allow
declaring expected attributes per entity type, drive both extraction
priors and validation.

**Profile additions:**

```yaml
entity_types:
  Customer:
    description: A person who purchases products.
    attributes:
      - name: customerId
        xsd_type: xsd:string
        is_id: true
        required: true
      - name: name
        xsd_type: xsd:string
        required: true
      - name: createdAt
        xsd_type: xsd:dateTime
        required: false
```

**Effects:**

- Phase B's SPIRES template uses the declared attributes as priors —
  prompts the LLM "the following attributes are expected; extract
  values for them or mark missing", improving recall.
- A new validation rule **VR007 (Required attributes present)** flags
  fused elements missing any `required: true` attribute.
- Profile induction (existing pipeline) extended to *suggest* attribute
  declarations based on Phase A output, so the draft profile already
  carries attribute schemas the user can edit.

**Acceptance:**

- Profiles with attribute declarations parse without error.
- VR007 fires on a fixture where required attributes are missing.
- Profile induction emits attribute suggestions in the draft profile
  when Phase A or B produced attributes.

---

## 5. Design Contracts

### Attribute dataclass (new)

```python
@dataclass
class Attribute:
    name: str                                  # "customerId"
    xsd_type: str                              # "xsd:string"
    is_id: bool = False                        # PK or @id
    is_multivalued: bool = False               # collection / list
    is_nullable: bool = True                   # NOT NULL → False
    enum_values: list[str] = field(default_factory=list)
    field_provenance: list[FieldProvenance] = field(default_factory=list)
    confidence: float = 1.0                    # 1.0 for deterministic
```

### XSD type mapping

| Source type              | XSD output       |
|--------------------------|------------------|
| VARCHAR / TEXT / str     | `xsd:string`     |
| INT / BIGINT / int       | `xsd:integer`    |
| DECIMAL / NUMERIC / Decimal | `xsd:decimal` |
| FLOAT / REAL / float     | `xsd:double`     |
| DATE                     | `xsd:date`       |
| TIMESTAMP / datetime     | `xsd:dateTime`   |
| BOOLEAN / bool           | `xsd:boolean`    |
| BLOB / bytes             | `xsd:base64Binary` |
| UUID                     | `xsd:anyURI`     |
| Enum / Literal[...]      | `owl:oneOf` set  |

Unknown / complex types default to `xsd:string` with a
`rdfs:comment` recording the original type for the curator.

### OWL emission rules (Phase A)

For each `Attribute a` on `FusedElement e`:

```turtle
<{base}/{e.id}/{a.name}> a owl:DatatypeProperty ;
    rdfs:label "{a.name}" ;
    rdfs:domain <{base}/{e.id}> ;
    rdfs:range {a.xsd_type} ;
    {if a.is_id} a owl:FunctionalProperty ; {endif}
    {if not a.is_nullable} owl:minCardinality "1"^^xsd:nonNegativeInteger ; {endif}
    {if a.enum_values} owl:oneOf ( {literals} ) ; {endif}
    .
```

URI naming: `{ontology_base}/{class_fragment}/{attr_fragment}`
matches the cosmic-coffee pattern
(`http://example.org/ontology/cosmic-coffee-company/customer_customerId`).

---

## 6. Risks and Open Questions

1. **Type-mapping ambiguity for Python.** Pydantic union types
   (`str | int | None`) collapse poorly to a single XSD type. Proposal:
   pick the leftmost non-`None` type; record the full union in
   `rdfs:comment`. Open: is that acceptable, or should we emit
   `owl:unionOf`?
2. **FK direction.** SQL FKs are directional; OWL ObjectProperty
   cardinality requires choosing which side carries the property. We
   propose: FK column on `Order(customer_id)` → emits `customer` object
   property on `Order` with `owl:FunctionalProperty`. Inverse direction
   not auto-emitted.
3. **Many-to-many via junction tables.** Detected when a table has
   exactly 2 FKs and no other non-PK columns. Open: should we also
   detect SQLAlchemy `secondary=` and Pydantic `list[ForeignRef]`
   patterns, or defer to a later phase?
4. **Source C precedence over Source D.** When both define the same
   attribute, which wins? Current proposal: Source C wins for the
   XSD type (closer to storage), Source D wins for `description`
   (closer to business semantics). Open for review.
5. **Profile induction churn.** If Phase A emits attributes and Phase
   C induces a profile that declares them as `required: true`, a
   subsequent rerun without those source files would flag everything.
   Need a `required` heuristic — propose: `required: NOT NULL in SQL`
   + `description: from comment` only.
6. **LLM cost cap for Phase B.** Per-concept fallback could explode on
   a 200-concept domain. Propose a `--property-induction-budget N` flag
   and skip concepts beyond the budget, sorted by Source A confidence
   descending.

---

## 7. Out of Scope (this design)

- Instance data extraction.
- Reasoner integration (Protégé / ROBOT) for inferred class hierarchy.
- SHACL shape generation.
- SKOS taxonomy emission.
- Cross-domain attribute reuse (e.g. shared `customerId` URI across
  multiple ontologies).
- UI changes — output is OWL only.

---

## 8. Decision needed from reviewers

1. **Approve Phase A scope** as the first deliverable (deterministic
   path only)?
2. **Approve Phase B as opt-in** behind `--property-induction llm`?
3. **Approve the XSD type mapping table** in §5, or propose changes?
4. **Approve the URI naming pattern** `{base}/{class}/{attr}`?
5. **Type-mapping ambiguity (open question #1)** — pick leftmost
   non-`None` or emit `owl:unionOf`?
6. **Source precedence (open question #4)** — Source C wins for type,
   Source D for description?

Once the above are decided, a separate
`PROPERTY_EXTRACTION_IMPLEMENTATION_PLAN.md` will follow with concrete
file-level edits, test fixtures, and a phase-A PR breakdown.
