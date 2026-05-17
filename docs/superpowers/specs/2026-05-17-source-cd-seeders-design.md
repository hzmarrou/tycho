# Source C and Source D as First-Class Candidate Seeders — Design

**Status:** Draft. Brainstormed 2026-05-17. Awaiting external review (Codex: The Architect).
**Branch:** `feat/source-cd-seeders` (worktree).
**Predecessor:** `docs/superpowers/specs/2026-05-16-tycho-semantic-layer-redesign-design.md` (semantic-layer redesign that just shipped as v1.0.0).

---

## 1. Goal

Promote Source C (schemas) and Source D (code) from accepted-but-discarded CLI flags into **first-class candidate seeders**, ingested through source-specific adapters that classify, filter, and weight evidence before contributing to the common candidate graph.

In one line: **make `survey` work for data-led and code-led domains, not only documentation-led ones, without losing the deterministic property of today's non-A pipeline.**

---

## 2. Why

Today's `build_candidate_graph` consumes only Sources A (docs, LLM-extracted) and B (governance JSON). Sources C and D are accepted in the CLI signature for forward-compat but their payloads are discarded. Fusion consumes C and D downstream, but only as **confirmation** of A/B candidates — concepts that exist only in the schema or only in code never enter the candidate graph and therefore never reach the curator.

This works for documentation-heavy domains where the regulator's prose is authoritative. It breaks for **data-led domains** (banking, insurance, healthcare) where the database schema is the canonical inventory of what the business actually models, and for **code-led domains** where running code is the most authoritative description of behaviour.

The user-articulated principle:

> Source A and B seed *semantic* concepts from language.
> Source C seeds *structural* concepts from schema.
> Source D seeds *executable* concepts/rules/signals from code.
> Each source needs its own ingestion policy before entering the common candidate graph.

---

## 3. Architecture

### 3.1 Three-axis framing

Every candidate is attested on one or more of three axes:

| Axis | Source | Attestation means |
|---|---|---|
| **Semantic** | A, B | A human (writer / glossary author) named this concept in natural language |
| **Structural** | C | The data model enforces this concept structurally (table, column, FK, constraint) |
| **Executable** | D | Running code declares or operates on this concept (class, method, validation rule) |

A concept attested on all three axes is highest-confidence. A concept attested on only one axis still contributes — but its strength tier reflects the lack of cross-axis corroboration, and the curator sees explicitly that *"data has this but nobody documented it"* or *"docs mention this but the data doesn't"*.

### 3.2 Per-source ingestion pipeline

Every source's ingestion follows the same four-stage pipeline, implemented by a source-specific adapter:

```
raw artifact ──▶ extract ──▶ classify (artifact kind) ──▶ filter (noise heuristics)
                                                           │
                                                           ▼
                                                  promote with strength tier
                                                  + promotion_reason / suppression_reason
                                                  + provenance
                                                           │
                                                           ▼
                                              common candidate graph
```

Stage definitions:

- **Extract** — enumerate raw artifacts from the source's native shape (parse DDL, walk JSON, AST-traverse code).
- **Classify** — assign each artifact an `artifact_kind` from a closed vocabulary (`entity`, `attribute`, `relationship`, `vocabulary`, `behavior`, `rule`). Source-specific rules; deterministic.
- **Filter** — apply noise heuristics (audit columns, test files, generated code). Default rules baked in, glob-pattern overrides via per-domain config.
- **Promote** — assign a `strength` tier (`strong | medium | weak`) and record a human-readable `promotion_reason`. If filtered out, record a `suppression_reason` instead and mark `suppressed=true` (still emitted, but excluded from downstream consumption by default).

### 3.3 Three-axis property: no new LLM dependencies

The structural and executable axes are **deterministic by design**. Stage-by-stage:

| Stage | Source A | Source B | Source C | Source D |
|---|---|---|---|---|
| Extract | LLM (unchanged) | JSON walk | DDL parse | AST walk |
| Classify | rule-based | rule-based | rule-based | rule-based |
| Filter | rule-based | rule-based | rule-based | rule-based |
| Promote | rule-based | rule-based | rule-based | rule-based + existing LLM labelling step (unchanged) |

LLMs appear only in the two places they appear today: Source A prose extraction, and the existing `code_extractor.py` LLM-labelling step for Source D. The new C and D classification, filtering, and promotion logic introduces **zero new LLM calls**. Properties this gives us:

- Reproducible — same schema → byte-identical candidates
- Cheap — zero new LLM cost
- Explainable — every candidate carries a rule-traceable reason
- CI-friendly — schema/code ingestion runs without API keys
- Testable — deterministic logic is unit-testable

---

## 4. Candidate schema

The common candidate dict gains four fields beyond today's shape (`label`, `definition`, `source_type`, `source_artifact`, `raw_type`, `eid`):

```jsonc
{
  "label":               "Customer",
  "definition":          "...",                  // best available across sources
  "source_type":         "C",                    // A | B | C | D
  "source_artifact":     "schemas/core.sql:42",  // file + locator
  "raw_type":            "table",                // source-native type hint
  "eid":                 "...",

  "artifact_kind":       "entity",               // NEW — closed vocab (see §5)
  "strength":            "strong",               // NEW — strong | medium | weak
  "promotion_reason":    "Table 'customers' corroborated by Source A 'customer' + Source B 'Customer'",  // NEW
  "suppression_reason":  null                    // NEW — non-null only when suppressed
}
```

Merging across sources preserves union of `source_presence: {A, B, C, D}` (existing behaviour) and adds:

- `strength` becomes the **max** across attesting sources, boosted one tier when ≥2 axes corroborate
- `promotion_reason` becomes a concatenation listing each contributing reason
- `definition` selection prefers explicit text (existing rule)

Suppressed candidates are emitted to the graph too (with `suppressed: true`) so downstream consumers and tests can see exactly what got filtered and why. The default `build_candidate_graph` consumer skips them; the audit consumer reads them.

---

## 5. Artifact-kind closed vocabulary

A single closed enum used across all sources. Each source maps its native shapes into this vocabulary:

| `artifact_kind` | OWL mapping at emit time | Source A | Source B | Source C | Source D |
|---|---|---|---|---|---|
| `entity` | `owl:Class` | concept (LLM-extracted noun) | record with `entity_type=entity` | table / model | class / dataclass / Pydantic model |
| `attribute` | `owl:DatatypeProperty` | LLM-extracted property phrase | record with `entity_type=attribute` | non-FK column | dataclass field / class field |
| `relationship` | `owl:ObjectProperty` | LLM-extracted predicate | record with `entity_type=relationship` | foreign key | method between two classes |
| `vocabulary` | `skos:ConceptScheme` + `skos:Concept` | (rare) | enum-typed record | code/lookup table | Python `Enum` subclass |
| `behavior` | (annotation-only; not in OWL by default) | (rare) | (rare) | (n/a) | non-CRUD method |
| `rule` | (annotation-only; not in OWL by default) | (rare) | (rare) | `CHECK` constraint | validation function / SQL predicate |

Existing `core/owl_export.py` already handles `entity`, `attribute`, `relationship`. The new contribution is `vocabulary` (SKOS emission, already partially supported via the `use_skos` flag) and the two annotation-only kinds (`behavior`, `rule`) which exist for downstream consumers but don't add OWL classes.

---

## 6. Source C ingestion (specifics)

### 6.1 Input format (v1)

**SQL DDL files (`.sql`)** only in v1. Parsed via `sqlglot` (new dependency). Rationale: universal, no DB credentials, version-controllable, deterministic.

JSON dumps (SQLAlchemy reflection, dbt manifest) and direct DB connections are out of scope for v1 (see §13).

### 6.2 Artifact taxonomy and default strength

| Source C artifact | Emitted as | Default strength | Notes |
|---|---|---|---|
| Table with ≥3 columns, ≥1 non-key column, doesn't match code-table detector | `entity` | `strong` | The standard case |
| Table flagged as code/lookup (see §6.4) | `vocabulary` | `medium` | SKOS, not class |
| Non-FK, non-PK column | `attribute` of parent table | tier of parent | Datatype-hint in `raw_type` |
| Single-column FK | `relationship` from parent to referenced table | inherits stronger of parent / referent | Domain/range pre-pinned |
| Composite FK | `relationship` with composite key annotation | as above | |
| PK column | NOT emitted as standalone — flagged on parent as identifier | — | Demoted from "concept" to "identifier of parent" |
| `CHECK` constraint with named predicate | `rule` | `weak` | Annotation only; not in OWL |
| Bridge table (≥2 FKs, no other domain columns) | `relationship` between the two referents | `medium` | The table itself does not become a class |

### 6.3 Default noise filters

Suppress (with explicit `suppression_reason`):

- **Tables** matching `*_audit`, `*_history`, `*_log`, `*_journal`, `tmp_*`, `bkp_*`, `bak_*`; views with `vw_*_audit` patterns
- **Columns** matching:
  - Timestamps: `created_at`, `updated_at`, ending in `_at` / `_ts` / `_timestamp` — **unless** prefixed by a domain-bearing token (`birth_date`, `expiry_date`, `valuation_date`)
  - System metadata: `etag`, `row_version`, `version`, `_partition_*`, all-caps `SYS_*`
  - Tenant / soft-delete: `tenant_id`, `is_deleted`, `deleted_at`
  - User attribution: `created_by`, `updated_by`, `modified_by`
- **Columns with `COMMENT`** containing `DEPRECATED` or `DO NOT USE`

Demote (not suppress):

- PK columns named `id`, `*_id` — demoted from standalone candidate to identifier-of-parent

### 6.4 Code-table detection

A table is classified as `vocabulary` (not `entity`) when **at least two** of these triggers fire:

1. Naming matches `*_codes`, `*_lookup`, `ref_*`, `*_code_master`, `cd_*`
2. Schema shape: 2–3 columns where one matches `code` / `code_value` / `id` and another matches `description` / `name` / `label`
3. Inbound FK count ≥ 2 (other tables reference it) and outbound FK count = 0

### 6.5 Per-domain config override

`<domain-dir>/source-c.yaml`:

```yaml
source_c:
  exclude_tables:
    - legacy_*
    - regional_*_archive
  include_tables:           # bring something back the defaults dropped
    - audit_loan_status
  exclude_columns:
    - "*.hash_value"
    - "*.legacy_*"
  force_vocabulary:         # explicit code-table assignment
    - country_lookup
  force_entity:             # explicit entity assignment despite default
    - status_codes          # we want this curated as a class
```

Globbing applied case-insensitively. Override semantics: `exclude_*` and `force_*` win over default heuristics; `include_*` brings back items the default would have dropped.

---

## 7. Source D ingestion (specifics)

### 7.1 Input scope (v1)

Python files (`.py`) only in v1. The existing `code_extractor.py` already supports SQL, JS, TS — these are accepted by the CLI but the v1 ingestion policy only documents Python. SQL/JS/TS support is the existing behaviour preserved as-is.

### 7.2 Artifact taxonomy and default strength

| Source D artifact | Emitted as | Default strength |
|---|---|---|
| `class` with at least one non-method attribute | `entity` | `strong` |
| `@dataclass` / Pydantic `BaseModel` / SQLAlchemy model | `entity` | `strong` (cross-attested with C if same table) |
| `class FooEnum(Enum):` | `vocabulary` | `medium` |
| Class field with type annotation | `attribute` of parent class | tier of parent |
| Method involving two domain classes | `relationship` | `medium` |
| Function with name matching `validate_*`, `check_*`, `assert_*` plus regex `^validate|^check|^assert` body | `rule` | `weak` |
| Other methods | `behavior` | `weak` |

### 7.3 Default noise filters

Suppress:

- **Path-based:** files under `tests/`, `test/`, `mocks/`, `fixtures/`, `migrations/`, `vendor/`, `__pycache__/`, `examples/`; files matching `test_*.py`, `*_test.py`, `conftest.py`
- **Generated code:** files where the first 5 lines contain `# DO NOT EDIT`, `# Generated by`, `# AUTOGENERATED`, or `# This file was automatically generated`
- **Private:** classes starting with `_` (Python convention)
- **Framework boilerplate:** `class Meta:`, `class Config:`, anything inheriting from `unittest.TestCase`

Flag (not suppress):

- DTOs ambiguous: classes ending in `DTO`, `Request`, `Response`, `Schema`, `Model` — emit with `raw_type="dto_candidate"` so the curator (or per-domain config) can decide. They are valid domain entities in many shops (Pydantic models often are); they are pure transport objects in others.

### 7.4 Per-domain config override

`<domain-dir>/source-d.yaml`:

```yaml
source_d:
  exclude_paths:
    - apps/legacy_engine/**
    - "src/**/internal/**"
  exclude_classes:
    - "*Mixin"
    - "*Factory"
    - "Base*"
  include_classes:          # explicitly promote DTOs we know are canonical
    - LoanRequest
    - PaymentInstruction
  force_vocabulary:
    - StatusEnum
```

Same override semantics as Source C.

---

## 8. Cross-source corroboration

After every source has run its own ingestion pipeline, the common merge step (`_upsert` in today's code, extended) does three things:

1. **Normalise the label** — case-fold, singularize (English plurals via `inflect`), strip table-name prefixes (`tbl_`, `dim_`, `fact_`), apply optional `alias_map` from profile. Label normalisation is identical across sources.
2. **Match by normalised label** — candidates from different sources with the same normalised label merge into one node. Existing behaviour, but now driven by classification:
   - Two `entity` candidates with the same normalised label → merge
   - An `entity` (Source C table) and an `attribute` (Source A "customer attribute") with the same label → conflict logged, both survive with distinct artifact_kinds, the conflict is surfaced in the audit
3. **Tier boost on corroboration** — a candidate attested on ≥2 axes is **boosted one strength tier**:
   - Was `medium`, now attested across semantic + structural → becomes `strong`
   - Was `weak` and attested only on one axis → stays `weak`
   - Already `strong` → stays `strong` (no super-strong tier)

The result: a Customer table corroborated by docs and governance → strong. A lone `updated_by_user_id` column → suppressed at filter stage and never reaches merge. A `risk_grade` lookup table corroborated by a governance term → strong vocabulary.

---

## 9. Code shape

### 9.1 New package: `core/ingest/`

```
src/ontozense/core/ingest/
  __init__.py
  base.py            # IngestionPolicy ABC, Candidate dataclass, strength enum
  ingest_a.py        # extracted from current build_candidate_graph
  ingest_b.py        # extracted from current build_candidate_graph
  ingest_c.py        # NEW — DDL parse + classify + filter + promote
  ingest_d.py        # NEW — wires the existing code_extractor + new classify/filter/promote
  filters.py         # shared default heuristic lists; per-domain YAML loader
```

`base.py` exports:

```python
@dataclass(frozen=True)
class Candidate:
    label: str
    definition: str
    source_type: str            # "A" | "B" | "C" | "D"
    source_artifact: str
    raw_type: str
    eid: str
    artifact_kind: ArtifactKind
    strength: Strength
    promotion_reason: str
    suppression_reason: str | None = None

class IngestionPolicy(ABC):
    def extract(self, raw_input: Any) -> Iterable[RawArtifact]: ...
    def classify(self, artifact: RawArtifact) -> ArtifactKind: ...
    def filter(self, artifact: RawArtifact, config: SourceConfig) -> tuple[bool, str | None]: ...
    def promote(self, artifact: RawArtifact, kind: ArtifactKind, kept: bool) -> Candidate: ...
```

### 9.2 `build_candidate_graph` becomes an orchestrator

`core/candidate_graph.py` is reshaped to call each ingester and merge their outputs. The four ingester instances are constructed once and dispatched per-source. The inline ingestion logic that exists today for A and B moves into `ingest_a.py` / `ingest_b.py` with **byte-identical behaviour** (regression-tested against the existing fixture suite).

### 9.3 Downstream consumers see new fields

- `profile.induce` — reads `artifact_kind` and `strength` to weight type proposals. Schema-only entities (no A/B attestation) are surfaced for curator review with a distinct status flag.
- `fusion.engine.fuse` — confidence scoring incorporates `strength` and multi-axis attestation. Today's flat source-presence count is replaced by an axis-weighted score.
- `core/owl_export.fused_to_owl` — emits `skos:ConceptScheme` + `skos:Concept` for `artifact_kind=vocabulary` candidates (extending the existing `use_skos` path). `behavior` and `rule` kinds emit as annotation properties, not OWL classes.

### 9.4 CLI surface — no change

`ontozense survey` keeps its existing flags (`--source-a`, `--source-b`, `--source-c`, `--source-d`). What changes is that `--source-c` and `--source-d` now do real work. A user who never passed them gets the exact same survey output as today (regression-tested).

---

## 10. Provenance and explainability

Every candidate carries the trail that produced it. Concretely:

- `source_artifact` — file path + locator (`schemas/core.sql:42`, `src/loans/models.py:Customer:line 15`)
- `promotion_reason` — human-readable rule-trace (`"Table 'customers' classified as entity (≥3 cols, ≥1 non-key, no code-table triggers). Corroborated by Source A 'customer' (LLM-extracted). Strength: strong (tier boost from medium due to multi-axis attestation)."`)
- `suppression_reason` — populated only when suppressed; concrete (`"Column 'created_at' matches default noise filter rule 'timestamp without domain prefix'."`)

A new `candidate-graph.json` field, `audit`, lists every suppressed candidate alongside its reason. Default-filtered consumers ignore it; an explicit `ontozense audit` consumer (deferred to v1.2, see §13) surfaces it for the curator.

This provides the foundation for **explainable induction**: every concept that survives to `draft.owl` has a rule-traceable justification, and every concept that did not survive has a rule-traceable rejection.

---

## 11. Testing strategy

### 11.1 Regression — no behaviour change without C/D

The existing test suite for `build_candidate_graph` must pass without modification. The A and B ingesters extracted into `ingest_a.py` and `ingest_b.py` are pinned to be byte-identical against the existing fixtures. This is the highest-priority test: nothing breaks for documentation-led domains.

### 11.2 Per-ingester unit tests

- `tests/core/ingest/test_ingest_c.py` — DDL parsing (sqlglot integration), artifact taxonomy classification (table → entity, code table → vocabulary, FK → relationship, audit column suppressed), heuristic filters, per-domain config overrides. ~25 tests.
- `tests/core/ingest/test_ingest_d.py` — AST extraction (classes, dataclasses, enums, validation functions), DTO ambiguity flag, path-based suppression, generated-code detection. ~20 tests.

### 11.3 Cross-source merge tests

`tests/core/test_candidate_graph_cross_source.py` — corroboration logic. Cases:

- Single-axis attested → expected strength tier
- Two-axis attested → tier boost applied
- Three-axis attested → strongest tier, boost capped
- Classification conflict (`entity` from C + `attribute` from A, same label) → both survive with audit entry
- Suppressed in one source → not boosted by attestation in another

### 11.4 End-to-end fixtures

Two new domain fixtures under `tests/fixtures/`:

- `banking_minimal/` — small Basel-like governance + tiny DDL + tiny Python models. End-to-end: survey runs, candidate graph has expected concepts at expected strengths.
- `data_only_minimal/` — DDL only, no docs, no governance. Validates that survey produces useful output for data-led domains (the v1 motivating case).

### 11.5 OWL output regression

Existing `tests/test_owl_export.py` must pass without modification (since semantic-axis-only flows produce byte-identical OWL). New cases added for `vocabulary` → SKOS emission and `behavior` / `rule` annotation properties.

---

## 12. Migration and backward compatibility

### 12.1 Same `survey` invocation → same output

A user who runs `ontozense survey --source-a docs.md --source-b governance.json --domain-dir d/` (no `--source-c`, no `--source-d`) gets a `candidate-graph.json` byte-identical to today's. This is regression-pinned.

### 12.2 New `--source-c .sql` / `--source-d code/` flags now do real work

The CLI signature is already in place (forward-compat hook from the previous redesign). Users who start passing them get the new behaviour. No deprecation needed; the flags were no-ops, now they aren't.

### 12.3 New consumed field: `audit` in `candidate-graph.json`

Consumers that read `candidate-graph.json` without reading the new `audit` field continue to work. Consumers that want to see suppressed candidates with reasons start reading it.

### 12.4 New `strength` / `artifact_kind` / `promotion_reason` fields on each candidate

Same as above — additive, non-breaking.

### 12.5 Profile induction and fusion behaviour change

Today they consume flat source-presence. Tomorrow they consume axis-weighted attestation. **This changes default `draft.owl` output** for domains where Source C is passed (which today is no-op, tomorrow is meaningful). For domains running only A+B, output is unchanged.

### 12.6 New dependencies

- `sqlglot` — pure-Python SQL parser. Permissive license. Adds ~3 MB to the install footprint. Adds no runtime cost when Source C is not used (lazy-imported inside `ingest_c.py`).
- `inflect` (optional, ~50 KB) — English pluralization for label normalisation. Standard library `re` could substitute with a small chop-trailing-s heuristic; `inflect` is preferred but not load-bearing.

---

## 13. Out of scope (deferred)

Explicit non-goals for v1.1, to keep this design tight:

1. **Source C input formats other than `.sql`** — JSON (SQLAlchemy reflection / dbt manifest) and direct DB connections are deferred to v1.2.
2. **Source D languages other than Python** — SQL/JS/TS code extraction is preserved as-is (existing behaviour) but the new ingestion-policy formalisation only documents Python in v1.1.
3. **`ontozense audit` CLI** — a consumer that displays suppressed candidates with reasons for curator review. Useful, deferred.
4. **Smart "domain-ness scoring"** — ML/LLM-assisted scoring of columns/classes for ambiguous cases. The deterministic heuristics + per-domain overrides cover the realistic 80%+; smart scoring is a v1.2+ refinement.
5. **Schema-aware promotion** — promoting `customer.status` to its own sub-entity because it has a backing code table and is FK'd from many places. Requires graph-analysis over the schema; deferred.
6. **Cross-table relationship inference** — deriving relationships from JOIN patterns in query logs. Out of scope.
7. **LLM-generated promotion-reason prose** — the rule-generated reason is fine for v1.1. Optional LLM polish later.

---

## 14. Risks

| Risk | Mitigation |
|---|---|
| Default heuristics overfit to one schema style and miss real concepts in others | Validate against two real schemas (one banking, one ESG-ish) before merging. Per-domain config override gives users a fast escape hatch. |
| `sqlglot` doesn't parse a real-world DDL we hit | Fall back to a clear error pointing the user at the `--source-c` JSON form (deferred to v1.2). For v1.1, document supported SQL dialects explicitly. |
| Multi-axis tier boost over-promotes weak corroborations | Tier boost is capped at one tier and never produces a tier higher than `strong`. Boost happens only with explicit multi-axis evidence (no transitive boosts). |
| The CLI behaviour silently changes for users who currently pass `--source-c` "to see what happens" | The flag is currently a no-op — no user could be depending on its no-op behaviour for correctness. Document the change clearly in release notes. |
| Adding new dataclass fields to `Candidate` breaks downstream JSON consumers | Fields are additive; serialised JSON gains keys but never loses them. Existing consumers ignoring unknown keys are unaffected. |

---

## 15. Vocabulary

| Term | Meaning |
|---|---|
| **Seeder** | A source that contributes candidate concepts to the candidate graph at survey time (not just at fusion time). |
| **Ingester** | The source-specific adapter that turns raw artifacts into uniform `Candidate` records via the extract → classify → filter → promote pipeline. |
| **Artifact kind** | The closed-vocabulary classification of a candidate's nature: `entity`, `attribute`, `relationship`, `vocabulary`, `behavior`, `rule`. |
| **Strength tier** | The candidate's confidence band: `strong`, `medium`, `weak`. Independent of `artifact_kind`. |
| **Axis** | One of the three evidence dimensions: semantic (A/B), structural (C), executable (D). |
| **Corroboration** | Multi-axis attestation of the same normalised label. Drives tier boosts. |
| **Promotion reason** | Rule-trace text justifying why a candidate survived to the candidate graph at its assigned strength. |
| **Suppression reason** | Rule-trace text justifying why a candidate was filtered out. |
| **Audit log** | The `audit` block of `candidate-graph.json` listing suppressed candidates + their reasons, available to opt-in consumers. |

---

## 16. Scope summary

**In scope for v1.1:**

- `core/ingest/` package with four source-specific ingesters
- `Candidate` dataclass with new `artifact_kind`, `strength`, `promotion_reason`, `suppression_reason` fields
- Source C ingestion from `.sql` files via `sqlglot`
- Source D ingestion from `.py` files (Python only) via existing `code_extractor.py` + new classify/filter/promote
- Default noise heuristics + per-domain `source-c.yaml` / `source-d.yaml` overrides
- Cross-source label normalisation + corroboration-based tier boost
- Profile induction + fusion confidence scoring uses new fields
- OWL export emits `skos:ConceptScheme` for `artifact_kind=vocabulary`
- Comprehensive tests including two new end-to-end domain fixtures
- README + tutorial updates documenting the new C/D behaviour

**Out of scope (see §13):**

- Source C from `.json` / direct DB connection
- Source D from non-Python languages (preserved as-is, not refactored)
- `ontozense audit` consumer CLI
- Smart / LLM-assisted classification
- Schema-aware sub-entity promotion
- Cross-table relationship inference from query logs

---

## 17. Acceptance criteria

The implementation is complete when:

- **AC1 — backward compat:** A run with only `--source-a` and `--source-b` produces a `candidate-graph.json` byte-identical to today's (regression-pinned).
- **AC2 — Source C seeds:** A run with `--source-c schema.sql` adds new candidates to the graph with `source_type="C"`, `artifact_kind` set per §5, default strength per §6.2, suppression of audit-table noise per §6.3, code-table detection per §6.4.
- **AC3 — Source D seeds:** A run with `--source-d code/` adds new candidates with `source_type="D"`, classification per §7.2, default suppression per §7.3, DTO ambiguity flag per §7.3.
- **AC4 — corroboration:** A concept attested across two axes is at least one tier higher than the same concept attested on only one. A concept attested across all three is at `strong`.
- **AC5 — explainability:** Every non-suppressed candidate has a non-empty `promotion_reason`. Every suppressed candidate has a non-empty `suppression_reason`. Both are deterministic given the input.
- **AC6 — config override:** A per-domain `source-c.yaml` `exclude_tables` rule actually excludes the matching table from the graph. Same for `source-d.yaml`.
- **AC7 — OWL emission:** A `vocabulary` candidate produces `skos:ConceptScheme` + `skos:Concept`s in `draft.owl`, not `owl:Class`.
- **AC8 — fixture validation:** Both end-to-end fixtures (`banking_minimal/`, `data_only_minimal/`) produce expected `candidate-graph.json` and `draft.owl` outputs.
- **AC9 — no new LLM dependency:** Source C and D ingestion paths run end-to-end with `LITELLM_KEY` unset and produce candidates (provided neither A nor D LLM-labelling is invoked).
- **AC10 — full suite green:** all existing tests pass without modification, plus the new tests pass.
