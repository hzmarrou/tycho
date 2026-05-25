# Property Extraction — Implementation Plan (Phase A)

**Status:** Draft, depends on reviewer sign-off of
[PROPERTY_EXTRACTION_DESIGN.md](./PROPERTY_EXTRACTION_DESIGN.md)
**Scope:** Phase A only (deterministic Source C/D/B path).
Phases B and C get their own plans once Phase A is merged and validated
end-to-end.
**Target reviewer:** Tycho maintainer / senior dev
**Branch:** `feat/property-extraction`

---

## 0. Pre-conditions

Before any code is written, reviewers must answer the six decisions
listed in [PROPERTY_EXTRACTION_DESIGN.md §8](./PROPERTY_EXTRACTION_DESIGN.md#8-decision-needed-from-reviewers).
This plan **assumes** the following answers; flag in review if any
differ:

| § | Decision | Assumed answer |
|---|---|---|
| 1 | Approve Phase A scope                    | Yes |
| 2 | Phase B opt-in via flag                  | Yes, but deferred to later plan |
| 3 | XSD type mapping table                   | Approved as written |
| 4 | URI naming `{base}/{class}/{attr}`       | Approved |
| 5 | Type-mapping ambiguity (Pydantic unions) | Pick leftmost non-`None`; full union in `rdfs:comment` |
| 6 | Source precedence (C vs D)               | C wins type, D wins description |

If any answer changes, the corresponding §§ below need revision before
implementation.

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

- `discovery/source-c.json` and `discovery/source-d.json` with
  full field metadata (new files).
- `fused.json` with each element carrying an `attributes[]` array.
- `draft.owl` with `owl:DatatypeProperty` declarations per attribute,
  matching the cosmic-coffee pattern.
- All existing tests green; new tests in `tests/test_property_extraction.py`.

No CLI surface change required for Phase A — `--source-c` is already a
recognised flag on both `survey` and `draft`.

---

## 2. File-level change list

Files marked **NEW** are created in this phase. All others are edits.

```
src/ontozense/
├── core/
│   ├── attribute.py                      NEW   Attribute dataclass + XSD type map
│   ├── fusion.py                         EDIT  populate FusedElement.attributes
│   ├── owl_export.py                     EDIT  emit owl:DatatypeProperty
│   ├── ingest/
│   │   ├── source_c/
│   │   │   ├── pipeline.py               EDIT  persist column metadata
│   │   │   └── persistence.py            NEW   write discovery/source-c.json
│   │   └── source_d/
│   │       └── persistence.py            NEW   write discovery/source-d.json
│   └── manager.py                        EDIT  load source-c.json / source-d.json
└── cli.py                                EDIT  survey writes the new discovery files

tests/
├── test_attribute.py                     NEW   XSD type map + dataclass behaviour
├── test_fusion_attributes.py             NEW   attribute-level fusion + provenance
├── test_owl_export_datatype.py           NEW   DatatypeProperty emission
├── test_source_c_persistence.py          NEW   discovery/source-c.json shape
├── test_source_d_persistence.py          NEW   discovery/source-d.json shape
└── fixtures/
    ├── synthetic_props.sql               NEW   minimal SQL fixture with PK/FK/types
    └── synthetic_props.py                NEW   minimal Pydantic+dataclass fixture

docs/
└── PROPERTY_EXTRACTION_IMPLEMENTATION_PLAN.md   this file
```

Estimated diff size: ~600 LOC added (≈ 250 prod, ≈ 350 tests +
fixtures).

---

## 3. Step-by-step PR breakdown

Phase A lands as **three sequential PRs**, each independently reviewable
and revertable. PR 1 establishes the data model; PR 2 wires fusion;
PR 3 emits OWL.

### PR 1 — `feat: Attribute dataclass + Source C/D persistence`

**Adds:**
- `src/ontozense/core/attribute.py` — `Attribute` dataclass per
  [PROPERTY_EXTRACTION_DESIGN.md §5](./PROPERTY_EXTRACTION_DESIGN.md#5-design-contracts).
  Includes `xsd_type_for(sql_type)` and `xsd_type_for_python(py_type)`
  pure functions using the mapping table.
- `src/ontozense/core/ingest/source_c/persistence.py` —
  `write_source_c_json(path, tables)` and `read_source_c_json(path)`.
- `src/ontozense/core/ingest/source_d/persistence.py` — analogous
  pair for the Python AST extractor output.
- `cli.py` survey orchestrator: when Source C inputs are present,
  write `discovery/source-c.json`. Same for D.
- Tests: `test_attribute.py`, `test_source_c_persistence.py`,
  `test_source_d_persistence.py`, plus fixtures.

**Does not touch:** fusion, owl_export, draft pipeline. Behaviour
unchanged in `draft.owl` after PR 1.

**Review focus:**
- `Attribute` field set is sufficient for Phase A and forward-compatible
  with Phase B / C (no breaking changes expected later).
- XSD type table edge cases (vendor SQL types: `CITEXT`, `JSONB`,
  `MONEY`, `GEOMETRY`).
- Pydantic union handling matches design §5 / open question #1.

**Acceptance:**
- Running `survey` on the NPL fixture writes `discovery/source-c.json`
  and `discovery/source-d.json`.
- JSON shape is documented inline at the top of each `persistence.py`.
- Backwards-compat: existing `survey` runs without `--source-c` /
  `--source-d` skip the new file writes silently.

---

### PR 2 — `feat: attribute-level fusion`

**Adds:**
- `FusedElement.attributes: list[Attribute]` field (new, default
  `[]`).
- Fusion logic in `core/fusion.py`:
  - For each fused element, look up matching table/class in the loaded
    `source-c.json` and `source-d.json` by normalised name (reuse
    existing `normalise_name`).
  - Merge attributes from C + D + B following the precedence rules in
    design §5 and open question #4.
  - Per-attribute provenance (`field_provenance: list[FieldProvenance]`)
    populated from the contributing sources.
- Tests: `test_fusion_attributes.py` covering:
  - C-only attributes (XSD type from SQL).
  - D-only attributes (XSD type from Python).
  - C+D agreement (one merged Attribute, two provenance entries).
  - C+D conflict on type (C wins, D logged in `conflicts[]`).
  - B-only attributes (when `data_type` is populated).
  - Enum extraction from Python `Literal[...]` and SQL `CHECK IN (...)`.

**Does not touch:** owl_export. `fused.json` gains the new field;
`draft.owl` is unchanged.

**Review focus:**
- Element-to-table/class matching algorithm — what counts as a match
  (exact name, normalised name, fuzzy match)? Recommend exact +
  normalised only in Phase A; defer fuzzy to a later phase.
- Conflict logging hooks into the existing `conflicts[]` array on
  `FusedElement`.
- No regression on element-level fusion tests.

**Acceptance:**
- Running `draft` on the NPL fixture produces `fused.json` where the
  `Loan` element carries attributes derived from `loan` table columns
  and the `Loan` Pydantic class fields.
- Existing fusion tests pass without modification.

---

### PR 3 — `feat: emit owl:DatatypeProperty in draft.owl`

**Adds:**
- `core/owl_export.py` extension:
  - For each `Attribute` on each element, emit `owl:DatatypeProperty`
    per design §5 emission rules.
  - `owl:FunctionalProperty` for `is_id` attributes.
  - `owl:minCardinality 1` for non-nullable.
  - `owl:oneOf` block for enum attributes.
  - Bind `xsd` and `xml` namespaces in the graph.
- Tests: `test_owl_export_datatype.py` verifying:
  - One `owl:DatatypeProperty` per `Attribute`.
  - Correct `rdfs:domain` linkage to parent class URI.
  - Correct `rdfs:range` XSD type.
  - ID attributes carry `owl:FunctionalProperty`.
  - Enum attributes emit `owl:oneOf` with the right literal list.

**Touches:** `core/owl_export.py` only (export-time concern).

**Review focus:**
- URI fragment generation handles names with spaces, slashes, leading
  digits (`_id_fragment` already does this for class names — reuse for
  attribute names).
- The new `owl:DatatypeProperty` declarations don't collide with
  existing `owl:ObjectProperty` URIs (potential clash: a class has
  attribute `borrower` and a predicate also called `borrower` — pick
  precedence and document).
- Emitted file still passes `rdflib.Graph().parse()` round-trip and
  imports cleanly into Protégé.

**Acceptance:**
- NPL `draft.owl` (regenerated with PRs 1+2+3 merged) contains
  `owl:DatatypeProperty` entries for table-backed classes.
- Manual smoke test: import the file in Protégé, confirm entity cards
  show properties matching the cosmic-coffee pattern.
- All tests pass.

---

## 4. Test strategy

### New fixtures

- `tests/fixtures/synthetic_props.sql` — three tables:
  `customer(id PK, email VARCHAR NOT NULL, created_at TIMESTAMP)`,
  `order(id PK, customer_id FK, amount DECIMAL(10,2), status VARCHAR
  CHECK IN ('open','closed'))`, `order_item(order_id FK PK,
  product_id FK PK, qty INTEGER)`. Covers PK, FK, NOT NULL, enum,
  composite PK, many-to-many junction.
- `tests/fixtures/synthetic_props.py` — `Customer(BaseModel)` with
  `id: UUID`, `email: str`, `tags: list[str]`, plus a
  `@dataclass Order` with `Decimal` amount and `Literal["open",
  "closed"]` status.

### Existing test coverage to preserve

- `tests/test_owl_export.py` — 15 tests, must remain green.
- `tests/test_cli_draft.py` — 2 tests including `test_owl_xml_format`.
- `tests/test_fusion*.py` — element-level fusion suite.
- `tests/test_npl_pipeline.py` — end-to-end (currently `xfail`/skip on
  Windows for LLM calls; structure-only assertions still run).

### Coverage targets

- New code: 90% line coverage (matches project default).
- XSD type mapping branches: 100% — every entry in the design §5
  table exercised by a unit test.

---

## 5. Backwards compatibility and migration

- `discovery/source-c.json` and `discovery/source-d.json` are **new**
  files. Old `discovery/` directories remain valid; `draft` treats
  missing files as "no field-level data available" and falls back to
  the current behaviour (no `owl:DatatypeProperty` emission).
- `FusedElement.attributes` defaults to `[]`. Existing `fused.json`
  files written before this change deserialise cleanly via dataclass
  defaults (they need a `from_dict`-style loader patched at the same
  time — see `core/fusion.py` deserialisation path; currently lossy on
  reload — flagged in design doc).
- No CLI flag changes. No profile schema changes (Phase C handles
  profile schema).
- Existing tutorial commands continue to work; tutorial gets a
  follow-up patch in a separate PR to document the new `--source-c`
  passthrough on `draft`.

---

## 6. Rollback plan

Each PR is independently revertable:

- Revert PR 3 → `draft.owl` reverts to no `DatatypeProperty`, fused.json
  still carries attributes (harmless extra data).
- Revert PR 2 → `fused.json.attributes` empties out, OWL emission
  produces no DatatypeProperty regardless of PR 3 state.
- Revert PR 1 → discovery files no longer written; no downstream
  changes break because PR 2 reads them defensively (missing file →
  empty list).

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
- **Tutorial update** to document `--source-c` on `draft` — single-doc
  patch in its own PR after Phase A merges.

---

## 8. Effort estimate

| PR | Person-days (focused) | Test writing included |
|----|-----------------------|----------------------|
| 1  | 1.5                   | Yes |
| 2  | 2.5                   | Yes |
| 3  | 1.0                   | Yes |
| **Total Phase A** | **~5 person-days** | |

Estimate assumes the reviewer is also the implementer (no async-review
hand-off). Add ~1 day if Phase A is split across two people.

---

## 9. Sign-off checklist

Before merging each PR:

- [ ] All tests green (`pytest -q`).
- [ ] No new warnings in `ruff check`.
- [ ] Diff reviewed against design doc §5 contracts.
- [ ] Manual smoke test: NPL fixture run, import draft.owl in Protégé,
      verify entity cards.
- [ ] Reviewer ack on `feat/property-extraction` PR.

Final Phase A acceptance (after PR 3):

- [ ] `draft.owl` for NPL contains ≥ 1 DatatypeProperty per
      table-backed class (`Loan`, `Borrower`, `Collateral`, ...).
- [ ] Doc-only domains see no regression — same output as today.
- [ ] CI passes on all 3 PRs.
- [ ] Updated tutorial PR queued.
