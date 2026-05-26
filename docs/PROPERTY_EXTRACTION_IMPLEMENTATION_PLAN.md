# Property Extraction — Implementation Plan (Phase A)

**Status:** Draft, revised 2026-05-25 per Codex review
**Scope:** Phase A only (deterministic Source C/D/B path).
Phases B and C get their own plans once Phase A is merged and validated
end-to-end.
**Reviewer status:** Codex APPROVE on r3 (2026-05-25). r3 patches address final nit + impl caution.
**Branch:** `feat/property-extraction`

**Revisions:**
- 2026-05-25 r3: Codex round-3 review (APPROVE). Minor changes:
  - §6 wording tightened — removed self-contradictory "fully
    independent" claim. Revert units are internally atomic; ordering
    across units is reverse-merge.
  - §3 PR2 gains an "enum_values input normalisation" subsection
    covering list / comma-string / semicolon-string / malformed
    shapes (Codex implementation caution). `data_type` shape guard
    added too. Test list extended to cover each variant.
- 2026-05-25 r2: Codex round-2 review (REJECT → addressed). Changes:
  - PR1a's `AttributeFact` extension now includes
    `description: str = ""`, so the "D wins description" rule in PR2
    is wired end-to-end (Codex finding #1).
  - §3 sequencing and §6 rollback rewritten: PR1a + PR1b form a
    single revert unit. The earlier "all four independently
    revertable" claim was self-contradictory (Codex finding #2).
  - §3 PR2 now specifies the Source B contract seam: reads
    `rec.extra_fields["data_type"]` and
    `rec.extra_fields["enum_values"]` on `GovernanceRecord`; no
    contract change in Phase A (Codex finding #3).
  - Doc nits: `serialise(...)` → `dump_source_c_json(...)`; added
    `core/source_d.py` (typed `SourceDResult` contract) to replace
    the r1 "ad hoc JSON" approach Codex called out as debt risk.
- 2026-05-25 r1: Codex round-1 review. Major changes:
  - PR1 split into PR1a (Source D IR contract extension) +
    PR1b (persistence) because the current IR
    (`src/ontozense/core/ingest/source_d/ir.py::AttributeFact`) is
    too lossy to carry `multivalued`, `default_factory`, `enum`, or
    PK metadata.
  - File list corrected: `core/ingest/source_c/` does not exist —
    actual files are `core/ingest/ingest_c.py` and
    `core/source_c.py` (the existing typed contract).
    `core/manager.py` removed from the edit list.
  - PR2 scope expanded to include the serializer + reconstructor
    fixes in `cli.py` (`_serialize_element` whitelists fields;
    `_reconstruct_fusion_result` ignores unknown keys; both must
    handle the new `attributes` field in the same PR as fusion).
  - Draft load path patch added: current `draft` command ignores
    `--source-c` discovery data; the wiring is now an explicit
    deliverable.
  - Effort revised from ~5 PD to 6-8 PD.

---

## 0. Pre-conditions

Reviewer decisions are recorded in
[PROPERTY_EXTRACTION_DESIGN.md §8](./PROPERTY_EXTRACTION_DESIGN.md#8-decisions-round-1--codex-review-2026-05-25).
Round 1 status: all six decisions resolved (some "Approved", some
"Revised"). Round 2 will re-review this plan after revisions.

Locked-in answers used by this plan:

| § | Decision | Locked answer |
|---|---|---|
| 1 | Phase A scope                                | Deterministic only |
| 2 | Phase B opt-in via flag                      | Yes, separate plan |
| 3 | XSD type mapping table                       | Revised (UUID → xsd:string, +11 vendor types) |
| 4 | URI naming                                   | `/rel/` branch for object props |
| 5 | Pydantic union resolution                    | Leftmost non-None + raw_type |
| 6 | Source C / D precedence                      | C wins storage, D wins description |
| Open Q1 (OWL required/enum encoding) | Annotation-only in Phase A | |
| Open Q2 (FK direction)               | Property on FK-owning class; no auto-inverse | |
| Open Q3 (M2M detection)              | SQL junction tables only; defer SQLA `secondary` | |

---

## 1. Phase A deliverable summary

A user running:

```bash
ontozense survey \
  --source-a domains/npl/sources/npl-basel-guidelines.md \
  --source-b domains/npl/sources/governance.json \
  --source-c domains/npl/sources/npl-schema.sql \
  --source-d domains/npl/sources/npl-code \
  --domain-dir domains/npl

ontozense draft \
  --domain-dir domains/npl \
  --source-b domains/npl/sources/governance.json \
  --source-c domains/npl/sources/npl-schema.sql \
  --source-d domains/npl/sources/npl-code \
  --format owl-xml \
  --output domains/npl/draft.owl
```

gets:

- `discovery/source-c.json` — reuses the existing typed
  `SchemaResult` contract from `core/source_c.py`, written by the
  `survey` orchestrator.
- `discovery/source-d.json` — new per-Phase-A artefact serialised from
  the (newly-extended) Source D IR.
- `fused.json` with each element carrying a non-empty `attributes[]`
  array when matched against a Source C table or Source D class.
- `draft.owl` with `owl:DatatypeProperty` declarations per attribute
  (matching the cosmic-coffee pattern; see design doc §1 for the
  reference card).
- All existing tests green; new tests under
  `tests/test_property_extraction*.py`.

**Required CLI change (r1):** `--source-c` was already accepted by
the `draft` command but its discovery output was never re-loaded for
property fusion. Phase A wires the seam. No new flags.

---

## 2. File-level change list (revised r1)

```
src/ontozense/
├── core/
│   ├── attribute.py                              NEW   Attribute dataclass + XSD type map
│   ├── source_c.py                               EDIT  if SchemaField needs new fields (likely no-op)
│   ├── source_d.py                               NEW   typed contract for discovery/source-d.json (r2)
│   ├── fusion.py                                 EDIT  FusedElement.attributes + attr-level fusion
│   ├── owl_export.py                             EDIT  emit owl:DatatypeProperty + /rel/ branch
│   ├── ingest/
│   │   ├── ingest_c.py                           EDIT  surface SchemaResult to survey orchestrator
│   │   ├── ingest_d.py                           EDIT  hook persistence before emit flattens
│   │   └── source_d/
│   │       ├── ir.py                             EDIT  AttributeFact: description, multivalued, default_factory, enum, is_pk, is_nullable, raw_type
│   │       ├── model_extractor.py                EDIT  populate new IR fields from Pydantic/SQLA/dataclass
│   │       └── emit.py                           READ-ONLY  unchanged; persistence hooks BEFORE this
└── cli.py                                        EDIT  multiple sites — see breakdown below

cli.py edit sites:
  - survey orchestrator: write discovery/source-c.json + source-d.json
  - draft orchestrator:  load both files and pass into fusion
  - _serialize_element:  include attributes[]
  - _reconstruct_fusion_result: defensively parse attributes[] (default []) for legacy JSON
  - standalone fuse command (line ~1290 area): same serialization path

tests/
├── test_attribute.py                             NEW   XSD type map + dataclass round-trip
├── test_fusion_attributes.py                     NEW   attribute-level fusion + provenance + conflicts
├── test_owl_export_datatype.py                   NEW   DatatypeProperty emission + /rel/ branch
├── test_source_c_persistence.py                  NEW   discovery/source-c.json shape via SchemaResult
├── test_source_d_persistence.py                  NEW   discovery/source-d.json shape
├── test_source_d_ir_extension.py                 NEW   AttributeFact new field population
├── test_fusion_serialization.py                  NEW   serialize/reconstruct round-trip with attrs
├── test_legacy_fused_json_reload.py              NEW   reload pre-Phase-A fused.json (no attrs key)
├── test_draft_discovery_load.py                  NEW   draft reads discovery/source-c.json + d.json
└── fixtures/
    ├── synthetic_props.sql                       NEW   PK / FK / NOT NULL / enum / junction table
    ├── synthetic_props.py                        NEW   Pydantic + dataclass + SQLAlchemy minimal
    └── legacy_fused_no_attrs.json                NEW   pre-Phase-A fused.json for reload test

docs/
└── PROPERTY_EXTRACTION_IMPLEMENTATION_PLAN.md    this file
```

Estimated diff size: ~900 LOC added (≈ 400 prod, ≈ 500 tests +
fixtures). Up from ~600 in the r0 estimate because the IR extension,
serializer fixes, and additional tests were not previously counted.

---

## 3. Step-by-step PR breakdown (revised r1)

Phase A lands as **four sequential PRs**, grouped into **three revert
units**: PR1a+PR1b together (Source D IR extension is meaningless
without the persistence that exercises it; PR1b's persistence writer
expects PR1a's fields), then PR2 alone, then PR3 alone. Within a
revert unit the PRs still merge sequentially for review ergonomics, but
a rollback reverts the whole unit. See §6 for the revert matrix.

### PR1a — `feat(source-d): extend AttributeFact IR for property metadata`

**Why this PR exists separately (r1):** `AttributeFact` in
`src/ontozense/core/ingest/source_d/ir.py` currently carries only
`name, evidence_span, extractor_family, subject_entity, annotation,
has_default`. The Phase A payload requires `is_multivalued`,
`default_factory`, `enum_values`, and `is_pk`. Promising persistence
on top of the current IR would deliver an empty payload.

**Adds:**
- `AttributeFact` new fields with backwards-compatible defaults:
  ```python
  description: str = ""        # r2: was missing; needed for D-wins-description rule
  is_multivalued: bool = False
  default_factory: str | None = None
  enum_values: list[str] = field(default_factory=list)
  is_pk: bool = False
  is_nullable: bool = True
  raw_type: str = ""           # e.g. "list[Decimal]" or "Literal['open','closed']"
  ```
- `model_extractor.py` populates the new fields from Pydantic, dataclass,
  and SQLAlchemy column metadata (uses the existing AST visit; no new
  walks). Specifically:
  - `description`: populated from, in order of priority:
    1. Pydantic `Field(description="...")` literal argument.
    2. dataclass `field(metadata={"description": "..."})` literal.
    3. SQLAlchemy `Column(..., comment="...")` literal.
    4. The inline `# comment` on the field line (last fallback).
    Empty string when none of those are present. AST extraction only —
    no source-text round-trip beyond the line comment.
  - `is_multivalued`: detected from `list[...]`, `Sequence[...]`,
    `set[...]`, or `default_factory=list`.
  - `enum_values`: detected from `Literal["a", "b"]` and Enum subclasses.
  - `is_pk`: detected from SQLAlchemy `primary_key=True`.
  - `is_nullable`: detected from `Optional[T]`, `T | None`, or
    SQLAlchemy `nullable=False`.
- Tests: `test_source_d_ir_extension.py` covering each populated field
  (including a dedicated description-from-each-source case).

**Does not touch:** persistence layer, fusion, owl_export. Behaviour
observable to users unchanged.

**Acceptance:**
- All existing Source D tests pass.
- New tests assert that running `extract` on the synthetic Pydantic +
  dataclass + SQLAlchemy fixture surfaces the populated fields on
  `AttributeFact`.

---

### PR1b — `feat: Attribute dataclass + discovery/source-c.json + source-d.json`

**Adds:**
- `src/ontozense/core/attribute.py` — `Attribute` dataclass per
  [PROPERTY_EXTRACTION_DESIGN.md §5](./PROPERTY_EXTRACTION_DESIGN.md#5-design-contracts).
  Pure functions `xsd_type_for_sql(sql_type, vendor_hint)` and
  `xsd_type_for_python(py_type)` using the revised mapping table.
- `cli.py` survey orchestrator: when `--source-c` is passed, write
  `discovery/source-c.json` via the existing helper
  `core/source_c.py::dump_source_c_json(result, path)`
  (`src/ontozense/core/source_c.py:223`). Reuses the existing
  `SchemaResult` contract instead of inventing a parallel schema
  (Codex's call-out).
- `src/ontozense/core/source_d.py` (NEW, r2 fix per Codex doc nit):
  typed contract for the persisted Source D artefact, mirroring
  `core/source_c.py`. Declares `SourceDAttribute`, `SourceDEntity`,
  `SourceDResult` dataclasses with a `schema_version` field and
  `dump_source_d_json(result, path)` / `load_source_d_json(path)`
  helpers. Replaces the r1 "ad hoc JSON documented inline at writer"
  approach, which Codex flagged as debt risk and divergence from the
  repo pattern set by `source_c.py`.
- `cli.py` survey orchestrator: when `--source-d` is passed, populate
  a `SourceDResult` from the (PR1a-extended) IR and write
  `discovery/source-d.json` via `dump_source_d_json(...)`.
- Tests: `test_attribute.py`, `test_source_c_persistence.py`,
  `test_source_d_persistence.py`, plus fixtures.

**Does not touch:** fusion, owl_export. `draft` behaviour unchanged
until PR2.

**Review focus:**
- `Attribute` field set forward-compatible with Phase B / C.
- XSD type mapping branches each hit by a test (per design §5 table).
- Reuse of `core/source_c.py::SchemaResult` rather than introducing a
  parallel schema (Codex flagged this in r0 file list).
- Persistence hooks fire BEFORE `core/ingest/source_d/emit.py` flattens
  the IR to `IntermediateCandidate` (Codex flagged this risk).

**Acceptance:**
- `survey` writes `discovery/source-c.json` and
  `discovery/source-d.json` when the matching inputs are provided.
- The JSON files validate against their respective schemas.
- Skipping `--source-c` / `--source-d` writes neither file (silent
  fallback).

---

### PR2 — `feat: attribute-level fusion + serializer/reconstructor round-trip`

**Adds:**
- `FusedElement.attributes: list[Attribute]` field (new, default `[]`).
- Fusion logic in `core/fusion.py`:
  - For each fused element, look up matching table/class in the loaded
    `source-c.json` and `source-d.json` by exact + normalised name
    only (no fuzzy match in Phase A — Codex constraint).
  - Merge attributes from C + D + B following design §5 precedence
    rules:
    - **Storage facts from C** (type, nullable, PK, FK target,
      DB-derived enum_values).
    - **Description from D** (carried on `AttributeFact.description`
      after PR1a — from Pydantic `Field(description=...)`, dataclass
      `field(metadata={"description": ...})`, or SQLAlchemy
      `Column(comment=...)`).
    - **B as silent fallback** when both C and D are absent.

  **Source B contract seam (r2 — Codex finding #3):** PR2 reads
  `rec.extra_fields["data_type"]` and `rec.extra_fields["enum_values"]`
  on `GovernanceRecord`. No change to the `GovernanceRecord` dataclass
  in Phase A. Rationale: the existing contract in
  `src/ontozense/extractors/governance_extractor.py:57-64` deliberately
  shoves unknown keys into `extra_fields`; reading them there preserves
  backwards compatibility for governance.json files that already use
  `data_type` ad hoc. Promotion of `data_type` / `enum_values` to
  first-class fields on `GovernanceRecord` is deferred to Phase C
  alongside the profile schema work. PR2 includes a helper
  `_attribute_from_governance(rec)` that returns `None` when neither
  key is present, so B-only attributes only materialise when the
  governance JSON actually carries the data.

  **enum_values input normalisation (r3 — Codex impl caution):** the
  `extra_fields["enum_values"]` value may arrive from governance.json
  as either a `list[str]` (canonical) or as a delimiter-separated
  `str` ("open,closed" / "open;closed"). PR2's
  `_attribute_from_governance(rec)` normalises deterministically:
    - `list` → use as-is, stringify each element.
    - `str` → split on `;` first, then `,`, strip whitespace, drop
      empties.
    - any other type (dict, number, None) → skip the field, log via
      the existing conflicts channel ("source B enum_values: unsupported
      shape, ignored"). No attribute materialises from B for this
      record. The same coercion rule applies to `extra_fields["data_type"]`
      (must be str; non-str → skip + log).
  Test list extended with a dedicated normalisation case (string,
  list, malformed).
  - Per-attribute provenance (`field_provenance: list[FieldProvenance]`)
    populated from contributing sources.
  - Conflicts logged into the existing `FusedElement.conflicts` list.
- `cli.py` draft orchestrator: load `discovery/source-c.json` and
  `discovery/source-d.json` and pass to fusion. New Codex-flagged seam.
- `cli.py::_serialize_element`: add `attributes` to the whitelist.
- `cli.py::_reconstruct_fusion_result`: defensively read
  `re_.get("attributes", [])` and reconstruct via a new
  `_attribute_from(item)` helper. Legacy fused.json (no attributes
  key) deserialises to `attributes=[]` — no breaking change.
- `cli.py` standalone `fuse` command: same serializer change so the
  output of `fuse` round-trips through `validate` / `lint` / `query`.
- Tests:
  - `test_fusion_attributes.py` covering C-only, D-only, C+D
    agreement, C+D type conflict (C wins), B-only via
    `extra_fields["data_type"]`, B with `extra_fields["enum_values"]`
    as `list[str]`, B with `enum_values` as comma-separated `str`,
    B with `enum_values` as semicolon-separated `str`,
    B with malformed `enum_values` (dict / number → skip + log),
    governance record with neither key (no attribute materialises),
    enum extraction from Source D.
  - `test_fusion_serialization.py` — round-trip fused.json with
    attributes.
  - `test_legacy_fused_json_reload.py` — reload a pre-Phase-A fixture
    without attrs key; assert `attributes == []` and no exception.
  - `test_draft_discovery_load.py` — draft picks up
    `discovery/source-c.json` and emits attribute-bearing
    `FusedElement`s.

**Does not touch:** owl_export. `fused.json` gains the new field
and round-trips; `draft.owl` is unchanged.

**Review focus:**
- Element-to-table/class matching uses **exact + normalised name
  only** (Codex hard constraint for Phase A).
- Serializer and reconstructor patches land in the same PR — without
  both, fused.json round-trips lose attributes silently.
- Standalone `fuse` (line ~1290 area in cli.py) gets the same serializer.
- No regression on existing fusion tests.

**Acceptance:**
- `draft` on the NPL fixture produces `fused.json` where the `loan`
  element carries attributes derived from `loan` table columns and
  the `Loan` Pydantic class fields.
- Round-trip test: load → save → load yields byte-identical or
  semantically-equal JSON for both new and legacy fixtures.
- Existing fusion tests pass without modification.

---

### PR3 — `feat: emit owl:DatatypeProperty in draft.owl (with /rel/ URI branch)`

**Adds:**
- `core/owl_export.py` extension:
  - For each `Attribute` on each element, emit `owl:DatatypeProperty`
    per design §5 emission rules.
  - **Annotations only** for cardinality and enum encoding
    (`ontozense:required`, `ontozense:enumValues`,
    `ontozense:rawType`). No on-property `owl:minCardinality` or
    `owl:oneOf` — Codex's Open Q1 resolution.
  - `owl:FunctionalProperty` for `is_id` attributes (this *is*
    idiomatic and harmless).
  - Datatype property URIs at `{base}/{class}/{attr}`.
  - Object property URIs migrated to `{base}/rel/{predicate}` per
    revised URI scheme (design §5).
  - New `ontozense:` namespace bound in the graph header.
- Tests in `test_owl_export_datatype.py`:
  - One `owl:DatatypeProperty` per `Attribute`.
  - Correct `rdfs:domain` URI scheme.
  - Correct `rdfs:range` XSD type per the revised table.
  - ID attributes carry `owl:FunctionalProperty`.
  - Non-nullable carry `ontozense:required` annotation.
  - Enum carry `ontozense:enumValues` annotation (semicolon-joined).
  - Object property URIs land under `/rel/`.
  - Attribute named after a predicate (e.g. attribute `borrower` on
    `Loan` and predicate `borrower`) yields two non-colliding URIs.
  - Round-trip parse via `rdflib.Graph().parse()` succeeds.

**Touches:** `core/owl_export.py` only.

**Review focus:**
- URI fragment generation handles names with spaces, slashes,
  leading digits (extend the existing `_id_fragment` for attribute names).
- The new datatype property URIs don't collide with object property
  URIs (verified by the dedicated collision test).
- Emitted file imports cleanly into Protégé — manual smoke test (not
  CI) recorded in the PR description.
- `--format owl-xml` (rdflib `pretty-xml`) still emits typed nodes
  for the new datatype properties.

**Acceptance:**
- NPL `draft.owl` (regenerated after PR1a + 1b + 2 + 3) contains
  `owl:DatatypeProperty` entries for every table-backed class.
- Object property URIs landed under `/rel/`.
- Manual smoke: Protégé entity cards show properties matching the
  cosmic-coffee pattern.
- All tests pass.

---

## 4. Test strategy (revised r1)

### New fixtures

- `tests/fixtures/synthetic_props.sql` — three tables:
  `customer(id PK, email VARCHAR NOT NULL, created_at TIMESTAMP)`,
  `order(id PK, customer_id FK, amount DECIMAL(10,2), status VARCHAR
  CHECK IN ('open','closed'))`, `order_item(order_id FK PK,
  product_id FK PK, qty INTEGER)`. Covers PK, FK, NOT NULL, enum,
  composite PK, many-to-many junction.
- `tests/fixtures/synthetic_props.py` — `Customer(BaseModel)` with
  `id: UUID`, `email: str`, `tags: list[str]`, `description:
  Optional[str]`, plus a `@dataclass Order` with `Decimal` amount and
  `Literal["open", "closed"]` status, plus a SQLAlchemy `Shipment`
  with `primary_key=True` and `nullable=False`.
- `tests/fixtures/legacy_fused_no_attrs.json` — a minimal fused.json
  shaped as written by the current code (no `attributes` key on
  elements), used to verify reconstructor backwards compatibility.

### New tests (Codex-driven additions in **bold**)

- XSD type mapping per row in the design table.
- Attribute dataclass round-trip.
- Source C persistence shape (reuses `SchemaResult` serialiser).
- Source D IR extension — each new field populated correctly.
- Source D persistence shape.
- Fusion: C-only / D-only / C+D agreement / C+D type conflict /
  B-only / enum extraction / multivalued from `list[T]`.
- **Fusion serializer + reconstructor round-trip with attrs.**
- **Legacy fused.json (no attrs key) reload — assert empty
  attributes list, no exception.**
- **Survey writes new discovery artefacts when sources provided;
  silent skip when absent.**
- **Draft auto-loads `discovery/source-c.json` and
  `discovery/source-d.json` and emits attribute-bearing elements.**
- **Standalone `fuse` parity — same output as
  survey → draft fusion path for the same inputs.**
- **Missing discovery file fallback — no exception; behaviour matches
  pre-Phase-A.**
- **Exact + normalised matching only — fuzzy-matching disabled
  guarded by a test.**
- OWL: DatatypeProperty per attribute, FunctionalProperty on ID,
  required/enum annotations, /rel/ branch for object properties,
  **attr-URI vs predicate-URI collision** (e.g. attribute `borrower`
  on `Loan` and predicate `borrower`),
  **OWL round-trip parse via rdflib**.

### Existing test coverage to preserve

- `tests/test_owl_export.py` — 15 tests, must remain green.
- `tests/test_cli_draft.py` — 2 tests including `test_owl_xml_format`.
- `tests/test_fusion*.py` — element-level fusion suite.
- `tests/test_npl_pipeline.py` — end-to-end (`xfail`/skip on Windows
  for LLM calls; structure-only assertions still run).

### Coverage targets

- New code: 90% line coverage (matches project default).
- XSD type mapping branches: 100% — every row in design §5 hit by a
  unit test.

---

## 5. Backwards compatibility and migration

- `discovery/source-c.json` and `discovery/source-d.json` are **new**
  files. Old `discovery/` directories remain valid; `draft` treats
  missing files as "no field-level data available" and emits no
  attributes (no `owl:DatatypeProperty`). Verified by
  `test_draft_discovery_load.py` (missing-file branch).
- `FusedElement.attributes` defaults to `[]`. Legacy fused.json files
  (no `attributes` key) deserialise via `re_.get("attributes", [])`.
  Verified by `test_legacy_fused_json_reload.py`.
- `_serialize_element` whitelists fields; PR2 adds `attributes` to
  the whitelist. Old fused.json files written without the field
  still load — covered above.
- **One-way URI break for object properties**: old draft.owl files have
  object properties at `{base}/{predicate}`; new files put them at
  `{base}/rel/{predicate}`. Tycho's OWL output is a handoff artefact,
  not a stored identifier source, so no automated migration is
  required. The tutorial gets a callout.
- No CLI flag changes. No profile schema changes (Phase C handles
  profile schema).

---

## 6. Rollback plan (revised r2, tightened r3)

Three revert units. Each unit is internally atomic (revert the unit as
a whole, never a single PR within it). Units must be reverted in
reverse merge order — see "Rollback ordering across units" below.

| Unit | What it covers | What reverting it leaves behind |
|---|---|---|
| **Unit 1: PR1a + PR1b** (reverted together) | Source D IR extension + Attribute dataclass + survey writes `discovery/source-c.json` / `source-d.json` | discovery dir no longer carries the new files; PR2 reads them defensively (missing file → empty attributes) so the fused.json shape stays valid but empty |
| **Unit 2: PR2** | Attribute-level fusion + serializer/reconstructor + draft load wiring | `fused.json.attributes` empties out; OWL emission still emits no DatatypeProperty regardless of PR3 state (PR3 reads `element.attributes` which is now `[]`) |
| **Unit 3: PR3** | OWL DatatypeProperty emission + `/rel/` URI branch | `draft.owl` reverts to the cosmic-pattern OWL fixes baseline; `fused.json` still carries attributes (harmless extra data downstream consumers ignore) |

**Why PR1a and PR1b are one revert unit (r2 fix):** PR1b's
persistence writer in `model_extractor.py` populates fields that only
exist on `AttributeFact` after PR1a. Reverting PR1a while PR1b is
still in place would leave the writer referencing non-existent fields
(`AttributeError`). Treat them as a single revert unit; for review
ergonomics they still merge as two separate PRs.

**Rollback ordering across units:** revert in reverse merge order
(Unit 3 → Unit 2 → Unit 1). Skipping a middle unit is unsupported
(e.g. reverting Unit 1 while Unit 2 is still in place would leave
the fusion path trying to load discovery files that are no longer
written — empty attributes result, no exception, but the test for
"draft auto-loads discovery files" would fail in CI).

No data migration. No external API impact (Tycho has no external API).

---

## 7. Out of scope for this implementation plan

Same as design doc §7, plus:

- **Phase B** (LLM-based property induction) — separate plan once
  Phase A merges.
- **Phase C** (profile attribute schemas + VR007) — separate plan.
- **Bug-fix bundle** for the cosmic-pattern OWL fixes (already on
  `main` via a separate stashed change set) — landed via its own PR,
  not part of this work.
- **Tutorial update** to document `--source-c` on `draft` and the
  `/rel/` URI scheme change — single-doc patch in its own PR after
  Phase A merges.
- **OWL2-DL idiomatic encoding** of cardinality and enum (currently
  annotations only) — deferred to Phase C alongside profile-driven
  class restrictions.

---

## 8. Effort estimate (revised r1)

| PR | Person-days (focused) | Why r1 changed |
|----|-----------------------|----------------|
| 1a | 1.0                   | Was bundled into r0 PR1; now isolated for the IR contract work. |
| 1b | 1.5                   | Was r0 PR1 minus the IR work — roughly unchanged. |
| 2  | 3.0                   | r0 estimated 2.5; r1 adds serializer + reconstructor + draft load wiring + 4 new tests. |
| 3  | 1.0                   | Unchanged from r0. |
| **Total Phase A** | **~6.5 PD** | r0 estimate was ~5 PD. r1 estimate range: 6 - 8 PD depending on Source D IR familiarity. |

Estimate assumes the implementer also reviews. Async hand-off adds 1 PD
of context-loading.

---

## 9. Sign-off checklist

Before merging each PR:

- [ ] All tests green (`pytest -q`).
- [ ] No new warnings in `ruff check`.
- [ ] Diff reviewed against design doc §5 contracts.
- [ ] Manual smoke test: NPL fixture run, import draft.owl in Protégé,
      verify entity cards.
- [ ] Reviewer ack on `feat/property-extraction` PR.
- [ ] PR descriptions reference §6 revert unit they belong to (Unit 1
      = PR1a+PR1b paired, Unit 2 = PR2, Unit 3 = PR3).

Final Phase A acceptance (after PR3):

- [ ] `draft.owl` for NPL contains ≥ 1 DatatypeProperty per
      table-backed class (`Loan`, `Borrower`, `Collateral`, ...).
- [ ] Doc-only domains see no regression — same output as today
      (verified by missing-file fallback test and an end-to-end
      Basel-only fixture run).
- [ ] CI passes on all four PRs.
- [ ] Updated tutorial PR queued.

**Phase A status (2026-05-25):** all four PRs merged (PRs #14-#18),
umbrella PR #13 merged to main at `5b19925`, cosmic-pattern OWL fixes
PR #19 merged to main at `b621069`, tutorial update PR #20 merged at
`25a9494`. `public` branch synced at `2257ad5`. Final integrated
suite green: 1419 passed, 4 skipped, 0 failed.

---

## 10. Phase D implementation plan (revised r1 — Codex round-1)

**Status:** Draft 2026-05-26. r0 proposed a four-PR delivery with
L1 annotations + L2 OWL restrictions + L3 SWRL emission. Codex
round-1 review (REJECT) flagged a contract-level blocker:
`BusinessRule` (per `src/ontozense/core/fusion.py:148`) lacks the
`subject_attribute` / `predicate` / `object_value` / `condition`
fields that L2 / L3 mechanical projection requires. The richer
`RuleFact` shape exists in `src/ontozense/core/ingest/source_d/ir.py:74`
but does not reach `FusedElement.business_rules` today.

**r1 scope:** Phase D ships **L1 annotations only** (single PR D1).
L2 / L3 reasoner-form emission moves to a separate Phase E with its
own design doc + plan, blocked on a future contract upgrade that
routes the richer rule payload into fusion.

Depends on
[PROPERTY_EXTRACTION_DESIGN.md §4 Phase D](./PROPERTY_EXTRACTION_DESIGN.md#phase-d--source-d-business-rule-projection-to-owl-annotation-layer)
+ §5 Phase D contracts + §9 decisions (round 1 closed).

### 10.1 Phase D deliverable summary

A user running:

```bash
ontozense draft \
  --domain-dir domains/npl \
  --source-b domains/npl/sources/governance.json \
  --source-d domains/npl/sources/npl-code \
  --format owl-xml \
  --output domains/npl/draft.owl
```

gets a `draft.owl` where every `BusinessRule` on every fused element
projects to one `ontozense:businessRule` annotation on the parent
class, plus structured siblings (`ontozense:ruleType`,
`ontozense:ruleAnchor`, `ontozense:ruleConfidence`,
`ontozense:ruleValue` when the rule is a constant,
`ontozense:ruleReferencedSymbols` when non-empty, and one
`dc:source` per citation).

`--emit-rules annotations` is the **default** (r1 — revised from
r0's `all`) so existing draft invocations get the new annotations
transparently. `--emit-rules none` matches pre-Phase-D behaviour
exactly. The other r0 modes (`restrictions`, `swrl`, `all`) are
accepted by the CLI parser but rejected at runtime with a
"not yet implemented (queued for Phase E)" error. No doc link is
promised in the error message because the Phase E design doc does
not exist yet — Phase E will be scoped separately after Phase D
ships.

### 10.2 File-level change list

```
src/ontozense/
├── core/
│   ├── rule_projection.py                NEW   RuleAnnotation dataclass +
│   │                                            per-rule_type L1 projectors +
│   │                                            project_annotations() entry point
│   ├── owl_export.py                     EDIT  call project_annotations + emit
│   │                                            triples + bind ontozense:
│   │                                            properties added by Phase D
│   └── fusion.py                         READ-ONLY  BusinessRule shape unchanged
│                                                    (contract upgrade is Phase E)
└── cli.py                                EDIT  --emit-rules flag on draft command

tests/
├── test_rule_projection.py               NEW   per-rule_type L1 projection
│                                                unit tests
├── test_owl_export_rules.py              NEW   end-to-end: BusinessRule on
│                                                FusedElement -> ontozense:
│                                                triples on parent class
└── fixtures/
    └── synthetic_business_rules.py       NEW   one BusinessRule per
                                                 CodeExtractor rule_type
```

Estimated diff: ~450 LOC (≈ 200 prod, ≈ 250 tests + fixtures).

### 10.3 PR breakdown — single PR D1

**PR D1 — `feat(rule-projection): Phase D — L1 annotation emission for BusinessRule`**

- `core/rule_projection.py`:
  - `RuleAnnotation` dataclass (rule + parent_class_uri + triples).
  - `project_annotations(fused, ontozense_ns) → list[RuleAnnotation]`
    entry point. Walks every `FusedElement.business_rules` and emits
    one `RuleAnnotation` per rule per parent class.
  - Per-rule_type triple builders for `constant`, `conditional`,
    `function`, `sql_check`, `sql_where`, `sql_view`,
    `comment_citation` (the seven types CodeExtractor actually emits
    per `extractors/code_extractor.py:77`). Each builder returns the
    list of `(s, p, o)` tuples for that rule's annotation cluster.
  - Truncation guard: `ontozense:businessRule` literal capped at
    2000 chars; longer expressions truncate with trailing `"..."`
    and the full text remains addressable via the
    `ontozense:ruleAnchor` (file:line click-through). Open Q7 in
    design §6.
  - `BusinessRule.value` coerced to str via `repr()` for
    `ontozense:ruleValue` on constants. Open Q8 in design §6.
- `core/owl_export.py`:
  - Bind new annotation properties in the graph header:
    `ontozense:businessRule`, `ontozense:ruleType`,
    `ontozense:ruleAnchor`, `ontozense:ruleConfidence`,
    `ontozense:ruleValue`, `ontozense:ruleReferencedSymbols`.
  - After the existing per-element class emission loop (which Phase A
    already populates), call `project_annotations` when
    `emit_rules == "annotations"` and add the returned triples to
    the graph.
  - `dc:source` emitted per entry in `rule.citations`. Matches
    existing class-level emission at `core/owl_export.py:114` per
    design §9 D5 (closed r2).
- `cli.py`:
  - `--emit-rules <mode>` flag on `draft` with choices
    `annotations|restrictions|swrl|all|none`. Default `annotations`.
    `restrictions|swrl|all` raise `typer.BadParameter` with
    "not yet implemented (queued for Phase E)". No doc link in the
    error message — Phase E design doc does not exist yet.
    `annotations` and `none` are honoured.
- Tests:
  - `test_rule_projection.py`: per-rule_type L1 triple shape for
    each of the seven CodeExtractor rule_types; truncation guard
    fires at the 2000-char boundary; `BusinessRule` with empty
    `citations` emits zero `dc:source` triples; `BusinessRule`
    with multiple citations emits one triple each; constant
    `value=None` does not emit `ontozense:ruleValue`.
  - `test_owl_export_rules.py`: end-to-end with a fixture
    FusionResult carrying mixed rule types; assert per-class
    annotation cluster shape; assert `--emit-rules none` regenerates
    a `draft.owl` byte-identical (modulo rdflib serialisation
    quirks — compare graph isomorphism via `rdflib.compare.isomorphic`)
    to a pre-Phase-D run; assert `--emit-rules annotations` adds
    only the expected triples and breaks nothing else.
  - `test_owl_export_datatype.py` (existing): must remain green —
    Phase D does not touch the Phase A DatatypeProperty path.
  - Coverage targets: 90% line on new code; 100% per-rule_type
    branch in `project_annotations`.

**Acceptance (Phase D / PR D1):**

- Every `BusinessRule` in NPL's `fused.json` (~50 today) carries
  exactly one `ontozense:businessRule` annotation in the regenerated
  `draft.owl`.
- `--emit-rules none` regenerates `draft.owl` graph-isomorphic to
  pre-Phase-D for the same inputs.
- `--emit-rules restrictions|swrl|all` rejected at the CLI with a
  clear "queued for Phase E" error.
- Curator opens NPL `draft.owl` in Protégé and sees per-class
  `ontozense:businessRule` annotations in the class info pane.

### 10.4 Backwards compatibility and migration

- `--emit-rules annotations` is the **default**. Existing draft
  invocations get the new annotations transparently — pure additions,
  no triple deletion, no URI break.
- Strict pre-Phase-D byte-identity (graph isomorphism) available via
  `--emit-rules none`.
- No `fused.json` shape change — `business_rules` already there
  (Phase A r0). `BusinessRule` contract unchanged.
- No URI break for existing classes / datatype / object properties.
  L1 emission attaches new triples to existing class URIs only — no
  new URIs introduced in Phase D (rule URIs are a Phase E concern
  for reasoner-form emission).
- Existing test fixtures with empty `business_rules` produce zero
  new triples.

### 10.5 Rollback plan

Single revert unit, independent of Phase A:

| Unit | What it covers | Revert effect |
|---|---|---|
| **PR D1** | `RuleAnnotation` scaffold + L1 annotation projectors + `--emit-rules` CLI flag | `draft.owl` loses all `ontozense:businessRule` annotations and the structured siblings. `fused.json` unchanged (rules still attached to FusedElements). CLI loses the `--emit-rules` flag entirely. |

Reverting PR D1 has zero side effects on Phase A behaviour. No
ordering constraint with future Phase E PRs.

### 10.6 Effort estimate

| PR | Person-days (focused) |
|----|-----------------------|
| D1 | **~1.5 PD** (revised from r0's ~4 PD across two PRs) |

Phase E (L2 + L3) is a separate effort, will get its own estimate
when scoped.

### 10.7 Sign-off checklist

Before merging PR D1:

- [ ] All tests green (`pytest -q`).
- [ ] No new warnings in `ruff check` on touched files.
- [ ] `tests/test_domain_neutrality.py` passes — docstring /
      comment examples use neutral terms (no banking jargon in `src/`).
- [ ] Diff reviewed against design doc §5 Phase D contracts (L1 only).
- [ ] Manual smoke: regenerate NPL `draft.owl`, import in Protégé,
      verify `ontozense:businessRule` annotations show on entity-card
      info pane.
- [ ] PR description references PR D1 as a single revert unit and
      explicitly notes Phase E (L2 + L3) is deferred.

Final Phase D acceptance:

- [ ] NPL `draft.owl` contains ≥ 1 `ontozense:businessRule`
      annotation per `BusinessRule` in `fused.json`.
- [ ] `--emit-rules none` produces `draft.owl` graph-isomorphic to
      pre-Phase-D for the same inputs (regression guard via
      `rdflib.compare.isomorphic`).
- [ ] `--emit-rules restrictions|swrl|all` rejected at CLI parse
      time with a clear "queued for Phase E" error message. No doc
      link required (Phase E design doc does not exist yet).
- [ ] CI passes on PR D1.
- [ ] Tutorial follow-up PR queued (Step 3 "What you'll see"
      section gets an L1 rules paragraph).

### 10.8 Phase E placeholder

Phase E (L2 OWL restrictions + L3 SWRL Horn-clause rules) is out of
scope for this plan. Pre-conditions for Phase E spec work:

- A `BusinessRule` contract upgrade or a parallel typed channel that
  surfaces `RuleFact` fields (`subject_attribute`, `predicate`,
  `object_value`, `condition`) on `FusedElement`.
- Real-domain feedback on which `rule_type` shapes most need
  reasoner-form coverage (constants? sql_checks? conditionals?).
  Phase D shipping first gives us this signal.
- A decision on SWRL raw-triple emission (rdflib has no native SWRL
  serialiser — Phase E will need ~150 LOC of triple-builder code per
  the W3C SWRL submission shape).

Phase E will get its own design doc section and its own plan section.
Not in scope here.

---

## 11. Phase B implementation plan (pending Codex review)

**Status:** Draft 2026-05-26. Phase B (LLM SPIRES Pass-2 for
doc-only domains) per
[PROPERTY_EXTRACTION_DESIGN.md §4 Phase B](./PROPERTY_EXTRACTION_DESIGN.md#phase-b--llm-property-extraction-spires-pass-2)
with the 5-gate pre-spec scope lock baked in.

**Reviewer answers needed** — see
[PROPERTY_EXTRACTION_DESIGN.md §10 B1-B13](./PROPERTY_EXTRACTION_DESIGN.md#10-decisions-for-phase-b-round-1--pending-codex-review).

### 11.1 Phase B deliverable summary

A user running:

```bash
ontozense draft \
  --domain-dir domains/<doc-only-domain> \
  --source-b ... \
  --source-d ... \
  --format owl-xml \
  --property-induction llm \
  --property-induction-max-concepts 50 \
  --output domains/<doc-only-domain>/draft.owl
```

on a domain that has Source A docs but no Source C SQL and no
Source D code gets a `draft.owl` where every doc-discovered concept
with at least one Source A `field_provenance` entry carries
LLM-induced `owl:DatatypeProperty` declarations on the parent class
(when the LLM extracted something).

The same command WITHOUT the `--property-induction llm` flag
produces a `draft.owl` byte-identical (graph-isomorphic) to
pre-Phase-B for any input — Phase A regression guarantee preserved.

A run with the flag on a deterministic-rich domain (Phase A
already populated every `attributes[]`) produces output byte-
identical to the no-flag run — gate 1 (eligibility) means Phase B
is a no-op when nothing's empty.

### 11.2 File-level change list

```
src/ontozense/
├── core/
│   ├── property_induction.py             NEW   Phase B orchestrator —
│   │                                            template generator + SPIRES
│   │                                            invocation + parser + cache
│   ├── attribute.py                      READ-ONLY  reuses Phase A Attribute shape
│   ├── fusion.py                         READ-ONLY  attribute slot already in place
│   └── owl_export.py                     READ-ONLY  emission already in place
└── cli.py                                EDIT  --property-induction* flags on draft

tests/
├── test_property_induction.py            NEW   per-component unit tests
├── test_property_induction_budget.py     NEW   budget enforcement
├── test_cli_draft_property_induction.py  NEW   CLI flag contract
└── fixtures/
    ├── synthetic_doc_only/               NEW   Source A only (no C/D)
    └── synthetic_deterministic_rich.py   NEW   already-attributed fixture
```

Estimated diff: ~700 LOC (≈ 350 prod, ≈ 350 tests + fixtures).

### 11.3 PR breakdown

**Two PRs** in two independent revert units.

**PR B1 — `feat(property-induction): scaffold + CLI flags + eligibility + budget (no cache, no LLM)`**

PR B1 deliberately omits the cache file to avoid the conflict
Codex r1 blocker 2 identified: a B1 "dry-run cache" written to the
same path B11 says "cache hit always wins" on would cause B2's
real LLM calls to silently skip every previously dry-run-visited
class. PR B1 prints what would be called and writes nothing to
disk. The cache is exclusively a PR B2 deliverable.

- `core/property_induction.py`:
  - `EligibleConcept` dataclass: `(fused_element, snippet, confidence)`.
  - `find_eligible_concepts(fused) -> list[EligibleConcept]`:
    implements gate 1 (attributes empty + Source A presence).
    Returns sorted by Source A confidence descending so budget
    skipping is deterministic.
  - `Budget` dataclass + `BudgetEnforcer` helper enforcing
    `max_concepts`, `max_calls`, `token_budget` per the design.
  - `MAX_SPIRES_INPUT_CHARS = 8000` constant + `select_input_text`
    helper that concatenates + truncates snippets.
  - `induce_attributes(fused, model, budget, dry_run=True)`:
    entry point. PR B1 only supports `dry_run=True`. Logs the
    eligible-concept list + budget plan to the console and
    returns; **does not write any file**. `dry_run=False` raises
    `NotImplementedError("queued for PR B2")`.
- `cli.py`: `--property-induction <mode>` flag with choices
  `off|llm`. Default `off`. In PR B1 `llm` triggers the dry-run
  path (console-only output). Plus the three budget flags +
  `--property-induction-model` (default `azure/gpt-5.4`) +
  `--property-induction-refresh` (accepted but a no-op in PR B1
  because no cache to refresh). When the user passes
  `--property-induction-refresh` to a PR-B1 build, the CLI prints
  an explicit console note ("`--property-induction-refresh` ignored:
  cache lands in PR B2") so the user doesn't assume cache behaviour
  exists yet.
- Tests: eligibility filter (`attributes==[]` + Source A
  required); budget enforcement (max_concepts trims to N; max_calls
  hard cap; token_budget cumulative); console output asserts what
  would be called; CLI flag parsing + defaults; `--property-induction
  llm` produces zero disk writes outside the existing draft
  artefacts.

**Acceptance (PR B1):**

- `--property-induction llm` on the doc-only fixture identifies the
  right eligible concepts and prints them with the budget summary.
  **Zero actual LLM calls. Zero new files written.**
- `--property-induction off` (default) is a complete no-op — no
  eligibility scan, no draft.owl diff.
- All Phase A + Phase D tests stay green.

**PR B2 — `feat(property-induction): real SPIRES Pass-2 LLM call + attribute merge + cache`**

PR B2 introduces the cache file. PR B1 did not write any cache to
avoid the dry-run-vs-real-call collision Codex r1 flagged. Cache is
**only consulted and only written when `--property-induction llm`
is explicitly set on the rerun** (per design §4 / §10 B11). Default
draft invocations (no flag) never touch the cache file, so the
"default-flag run = byte-identical to pre-Phase-B" regression
guarantee holds.

- `core/property_induction.py`:
  - `PropertyInductionCache` reader/writer for
    `discovery/source-a-properties.json` per the §5 contract shape.
  - `_generate_linkml_template(concept) -> str`: builds the SPIRES
    template per §4 Mechanism step 1.
  - `_call_spires(model, template, input_text) -> list[Attribute]`:
    invokes the existing `extract-a`-style LiteLLM wrapper (reuses
    the Source A SPIRES infra). Parses the YAML output into typed
    `Attribute` records with `source="B-LLM"` and `confidence=0.5`.
  - `_merge_into_fused(fused, induced_attributes)`: attaches the
    parsed attributes to the matching FusedElement's
    `attributes[]`. Per gate 1, the slot is guaranteed empty before
    merge.
  - `induce_attributes(...)` now supports `dry_run=False` (the
    default for the `llm` CLI mode in B2): reads cache → calls LLM
    for cache misses → writes updated cache → merges results.
- `cli.py`: no flag changes (flags already shipped in PR B1).
  `--property-induction-refresh` becomes meaningful in B2 — forces
  cache miss for every eligible class.
- Tests:
  - LLM call is mocked at the LiteLLM seam; assertions cover
    template shape, parsed `Attribute` records, B-LLM source code
    on `field_provenance`, confidence=0.5.
  - End-to-end on the doc-only fixture (with mocked LLM): every
    eligible concept gains attributes; OWL emission picks them up
    via the existing Phase A `owl:DatatypeProperty` path.
  - Deterministic-rich fixture: graph-isomorphic to no-flag run
    (Phase A guarantee).
  - Default run (no flag) byte-identical to pre-Phase-B for the
    same input. Cache file is not even read.
  - Cache hit/miss matrix: first run populates cache; second run
    with the flag re-uses cache (zero new LLM calls);
    `--property-induction-refresh` forces cache miss.
  - Default-flag run after a cache file is on disk does NOT emit
    the cached attributes (regression guard for design §4 r1
    cache opt-in clause).
  - Budget overage: `--property-induction-max-concepts 3` results
    in exactly 3 LLM calls; remaining concepts logged as
    `skipped:budget:max_concepts` in the cache.

**Acceptance (PR B2):**

- Doc-only fixture run with `--property-induction llm` produces
  `draft.owl` containing `owl:DatatypeProperty` declarations on the
  top-5 eligible classes by Source A confidence.
- B-LLM provenance visible in `fused.json` per-attribute
  `field_provenance` array.
- Deterministic-rich fixture run produces graph-isomorphic output
  to no-flag run.
- Default-flag run preserves byte-identity.

### 11.4 Test strategy

- **Fixture 1** `tests/fixtures/synthetic_doc_only/`: Source A
  markdown declaring 5+ concepts with prose attribute descriptions
  ("A Customer has an email, a name, and a join date"). No Source
  C, no Source D. The end-to-end gold output proves Phase B fills
  attributes.
- **Fixture 2** `tests/fixtures/synthetic_deterministic_rich.py`:
  reuses the existing Phase A SQL + Python fixture. Phase B is
  guaranteed to be a no-op on it (gate 1).
- LLM mocking via the existing `monkeypatch` pattern on the
  LiteLLM seam (same pattern Source A SPIRES tests already use).
  No live API calls in CI.
- rdflib `compare.isomorphic` for the byte-identity regression
  checks (graph comparison robust to literal order shifts across
  rdflib versions).

### 11.5 Backwards compatibility and migration

- New CLI flags default off / unbounded. Old `draft` invocations
  unchanged.
- `Attribute` shape unchanged — Phase B reuses the Phase A
  dataclass.
- New discovery file `source-a-properties.json` written ONLY when
  `--property-induction llm` runs. No file = pre-Phase-B behaviour.
- Cache file shape versioned (`schema_version`) so future Phase B
  upgrades don't silently break older caches.

### 11.6 Rollback plan

| Unit | What it covers | Revert effect |
|---|---|---|
| **PR B1** | Eligibility filter + budget + CLI flags (dry-run console output only — no cache file, no disk writes) | CLI loses `--property-induction*` flags; nothing else changes. |
| **PR B2** | Cache reader/writer + real LLM call + attribute merge | Cache file (if present from earlier runs) is left on disk as harmless data — pre-PR-B2 readers don't consult it. No LLM-induced attributes reach `fused.json` / `draft.owl`. `--property-induction llm` falls back to PR B1's dry-run console output. |

Reverting in reverse-merge order is the recommended path. PR B2
revert leaves the CLI flag scaffold intact (`llm` mode becomes
dry-run-console-only again). PR B1 revert removes the flag
entirely.

### 11.7 Effort estimate

| PR | Person-days (focused) |
|----|-----------------------|
| B1 | 2.0 (scaffold + budget + cache + tests) |
| B2 | 1.5 (LLM call wiring + parser + mocked end-to-end tests) |
| **Total Phase B** | **~3.5 PD** |

### 11.8 Sign-off checklist

Before merging each Phase B PR:

- [ ] All tests green (`pytest -q`).
- [ ] No new warnings in `ruff check` on touched files.
- [ ] `tests/test_domain_neutrality.py` passes — no banking jargon
      in `src/`.
- [ ] `tests/test_source_d_acceptance.py::test_ac11_no_shacl_or_swrl_emitter_added`
      passes — Phase B does NOT introduce SHACL / SWRL tokens to
      core/ (Phase B only emits annotations via Phase A's existing
      DatatypeProperty path).
- [ ] Diff reviewed against design doc §4 5-gate scope lock — no
      gate violations.
- [ ] No live LLM calls in CI (all mocked at the LiteLLM seam).
- [ ] PR description references the revert unit it belongs to.

Final Phase B acceptance (after PR B2):

- [ ] Doc-only fixture run with `--property-induction llm` produces
      `draft.owl` with ≥ 1 `owl:DatatypeProperty` per eligible
      class.
- [ ] Deterministic-rich fixture run with flag = graph-isomorphic
      to no-flag run (gate 1 enforcement).
- [ ] Default run (no flag) = byte-identical to pre-Phase-B for
      same inputs (regression guard).
- [ ] CI passes on both PRs.
