# Property Extraction — Design Proposal

**Status:** Draft for review, revised 2026-05-25 per Codex review rounds 1 and 2
**Author:** Generated via Claude Code session, 2026-05-25
**Reviewers:** Codex (r1 APPROVE-WITH-CHANGES, r2 REJECT — addressed in implementation plan r2; design doc unchanged at r2)
**Related docs:** [PROFILE_INDUCTION_ARCHITECTURE.md](./PROFILE_INDUCTION_ARCHITECTURE.md),
[PROFILE_SPEC.md](./PROFILE_SPEC.md), [SPIRES.md](./SPIRES.md),
[PROPERTY_EXTRACTION_IMPLEMENTATION_PLAN.md](./PROPERTY_EXTRACTION_IMPLEMENTATION_PLAN.md)

**Revisions:**
- 2026-05-25 r1: incorporated Codex review — XSD table expanded, UUID
  corrected to `xsd:string`, `Attribute` dataclass gains `description`,
  Source C/D precedence rewritten around storage-vs-semantic split, OWL
  emission moved off on-property restrictions, URI scheme adds `/rel/`
  branch for object properties to avoid attribute/predicate collision.

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
    description: str = ""                      # human-readable, from D docstrings / SQL COMMENT
    is_id: bool = False                        # PK or @id
    is_multivalued: bool = False               # collection / list / ARRAY
    is_nullable: bool = True                   # NOT NULL → False
    enum_values: list[str] = field(default_factory=list)
    raw_type: str = ""                         # original SQL/Python type verbatim (for curator)
    field_provenance: list[FieldProvenance] = field(default_factory=list)
    confidence: float = 1.0                    # 1.0 for deterministic
```

Revision note (r1): `description` and `raw_type` added per Codex review.
Without `description` the Source C/D precedence rule (§6 / Open Question #4)
was not implementable. `raw_type` lets the curator see the original
SQL/Python type when the XSD mapping was lossy (e.g. `DECIMAL(10,2)` →
`xsd:decimal`).

### XSD type mapping

Revised table (r1) — adds 11 types Codex flagged as missing; corrects
UUID from `xsd:anyURI` to `xsd:string`.

| Source type                                    | XSD output         | Notes                              |
|------------------------------------------------|--------------------|------------------------------------|
| VARCHAR / TEXT / CHAR / str / CITEXT           | `xsd:string`       |                                    |
| SMALLINT / INT / BIGINT / SERIAL / BIGSERIAL / int | `xsd:integer`  | All integer widths collapse        |
| DECIMAL / NUMERIC / MONEY / Decimal            | `xsd:decimal`      | Precision recorded in `raw_type`   |
| FLOAT / REAL / DOUBLE PRECISION / float        | `xsd:double`       |                                    |
| DATE                                           | `xsd:date`         |                                    |
| TIME                                           | `xsd:time`         |                                    |
| TIMESTAMP / datetime                           | `xsd:dateTime`     |                                    |
| TIMESTAMPTZ / `timestamp with time zone`       | `xsd:dateTimeStamp`| Carries timezone                   |
| INTERVAL                                       | `xsd:duration`     |                                    |
| BOOLEAN / bool                                 | `xsd:boolean`      |                                    |
| BLOB / BYTEA / bytes                           | `xsd:base64Binary` |                                    |
| UUID                                           | `xsd:string`       | r1: was `xsd:anyURI`               |
| JSON / JSONB                                   | `xsd:string`       | Annotated `rdfs:comment "json"`    |
| GEOMETRY / GEOGRAPHY                           | `xsd:string`       | WKT serialisation assumed; flagged |
| ARRAY / list[T] / `T[]`                        | XSD of element T   | `is_multivalued = True`            |
| Enum / Literal[...]                            | XSD of member type | `enum_values` populated            |
| Anything else                                  | `xsd:string`       | `rdfs:comment` records original    |

Unknown / vendor-specific types default to `xsd:string`. The original
type string is preserved in both `raw_type` (machine-readable) and an
`rdfs:comment` on the property (curator-visible).

### OWL emission rules (Phase A)

Revision note (r1): Codex flagged on-property `owl:minCardinality` and
`owl:oneOf` as not idiomatic OWL2-DL. Phase A uses **annotations only**
for cardinality and enum (curator-visible, no reasoner impact); proper
class-restriction encoding moves to Phase C alongside the profile
schema work that already lives in `core/validation.py`.

For each `Attribute a` on `FusedElement e`:

```turtle
<{base}/{e.id}/{a.name}> a owl:DatatypeProperty ;
    rdfs:label "{a.name}" ;
    rdfs:domain <{base}/{e.id}> ;
    rdfs:range {a.xsd_type} ;
    {if a.description}    rdfs:comment "{a.description}" ; {endif}
    {if a.is_id}          a owl:FunctionalProperty ; {endif}
    {if not a.is_nullable} ontozense:required "true"^^xsd:boolean ; {endif}
    {if a.enum_values}    ontozense:enumValues "{v1};{v2};..." ; {endif}
    {if a.raw_type}       ontozense:rawType "{a.raw_type}" ; {endif}
    .
```

`ontozense:` is a custom annotation namespace bound in the graph
header. Curators see the cardinality/enum information; reasoners
ignore unknown annotation properties, so no DL inconsistency is
introduced.

### URI naming (revised r1)

Revised per Codex review to give object properties a separate URI
branch so attributes named after predicates don't collide.

| Element kind         | URI pattern                          | Example                                           |
|----------------------|--------------------------------------|---------------------------------------------------|
| `owl:Class`          | `{base}/{class_fragment}`            | `https://tycho.local/npl/borrower`               |
| `owl:DatatypeProperty` | `{base}/{class}/{attr}`            | `https://tycho.local/npl/borrower/email`         |
| `owl:ObjectProperty` | `{base}/rel/{predicate_fragment}`    | `https://tycho.local/npl/rel/has_collateral`     |

Matches the cosmic-coffee pattern for classes and datatype properties,
adds the `/rel/` branch as a Codex-recommended improvement. Migration
note: existing draft.owl files (pre-r1) have object properties at
`{base}/{predicate}`. The new scheme is a one-way URI break; consumers
generating reports off old URIs need to update. No data migration
needed because Tycho's OWL output is a handoff artefact, not a stored
identifier source.

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
4. **Source C precedence over Source D.** Resolved r1 (Codex review).
   Rule: **Source C wins all storage facts** — `xsd_type`,
   `is_nullable`, `is_id` (PK), foreign-key targets, `enum_values`
   when derived from `CHECK IN (...)`. **Source D wins for
   `description`** (closer to business semantics — read from Python
   docstrings, field-level comments, Pydantic `Field(description=...)`)
   and contributes `is_multivalued` evidence when Python uses
   `list[T]` / `default_factory=list` and Source C is silent. Source B
   `data_type` is consulted only when both C and D are silent; B-only
   attributes get `confidence = 0.7` instead of `1.0`.
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

## 8. Decisions (round 1 — Codex review 2026-05-25)

| § | Question | Decision |
|---|---|---|
| 1 | Phase A scope (deterministic only) | **Approved.** |
| 2 | Phase B opt-in via `--property-induction llm` | **Approved.** Concrete plan deferred to a separate Phase B doc. |
| 3 | XSD type mapping table | **Revised** (see §5). UUID corrected to `xsd:string`; 11 types added. |
| 4 | URI naming | **Revised** (see §5). Object properties move to `/rel/` branch to avoid collision with datatype properties named after predicates. |
| 5 | Pydantic union types | **Leftmost non-`None`**; full union preserved in `raw_type` and `rdfs:comment`. `owl:unionOf` deferred — too heavy for Phase A. |
| 6 | Source C / D precedence | **Revised** (see §5 / §6.4). Storage facts from C; description from D; B is silent-fallback only. |

Round-2 decisions (if any) will be appended below.

The implementation plan in
[PROPERTY_EXTRACTION_IMPLEMENTATION_PLAN.md](./PROPERTY_EXTRACTION_IMPLEMENTATION_PLAN.md)
has been revised against these decisions and Codex's plan audit.
