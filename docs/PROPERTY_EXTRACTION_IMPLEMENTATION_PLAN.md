# Property Extraction — Implementation Plan (Phase A)

**Status:** Draft, revised 2026-05-25 per Codex review
**Scope:** Phase A only (deterministic Source C/D/B path).
Phases B and C get their own plans once Phase A is merged and validated
end-to-end.
**Target reviewer:** Codex (round 3 after revision)
**Branch:** `feat/property-extraction`

**Revisions:**
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
    `extra_fields["data_type"]`, B with `extra_fields["enum_values"]`,
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

## 6. Rollback plan (revised r2)

Three revert units, each fully independent:

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
