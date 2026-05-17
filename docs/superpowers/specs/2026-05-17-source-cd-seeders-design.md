# Source C and Source D as First-Class Candidate Seeders — Design

**Status:** Draft, revision 2 (Codex review round 1 findings addressed). Brainstormed 2026-05-17.
**Branch:** `feat/source-cd-seeders` (worktree).
**Target release:** v1.1 (this design). v1.2 work explicitly marked as out-of-scope (§13).
**Predecessor:** `docs/superpowers/specs/2026-05-16-tycho-semantic-layer-redesign-design.md` (semantic-layer redesign shipped as v1.0.0).

---

## 1. Goal

Promote Source C (schemas) and Source D (code) from accepted-but-discarded CLI flags into **first-class candidate seeders** of the candidate graph at `survey` time, ingested through source-specific adapters that classify, filter, and weight evidence before contributing.

In one line: **make `survey` work for data-led and code-led domains, not only documentation-led ones — at the candidate-graph layer only.** Downstream consumption changes (profile induction reweighting, fusion confidence scoring, new OWL constructs) are explicitly deferred to v1.2.

---

## 2. Why

Today's `build_candidate_graph` consumes only Sources A (docs, LLM-extracted) and B (governance JSON). Sources C and D are accepted in the CLI signature for forward-compat but their payloads are discarded. Fusion does consume C and D downstream, but only as **confirmation** of A/B candidates — concepts that exist only in the schema or only in code never enter the *candidate graph* and therefore never reach the curator's pre-fusion inspection step.

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

A concept attested on all three axes is highest-confidence. A concept attested on only one axis still contributes — its strength tier reflects the lack of cross-axis corroboration, and the curator sees explicitly that *"data has this but nobody documented it"* or *"docs mention this but the data doesn't"*.

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
- **Promote** — assign a `strength` tier (`strong | medium | weak`) and record a human-readable `promotion_reason`. If filtered out, record a `suppression_reason` instead and emit with `suppressed=true` for the audit consumer.

### 3.3 Determinism property

The structural and executable axes are **deterministic by design** for v1.1. Stage-by-stage:

| Stage | Source A | Source B | Source C | Source D |
|---|---|---|---|---|
| Extract | LLM (unchanged) | JSON walk | DDL parse | AST walk |
| Classify | rule-based | rule-based | rule-based | rule-based |
| Filter | rule-based | rule-based | rule-based | rule-based |
| Promote | rule-based | rule-based | rule-based | rule-based |

Today's codebase: the only LLM call in the four-source pipeline is Source A's prose extraction. `code_extractor.py` (Source D) ships only the **deterministic AST/sqlglot parsing pass**; its module docstring explicitly marks LLM labelling and symbol-table validation as **future work** (lines 20–25 of `code_extractor.py`: *"This module ships with the deterministic parsing complete. The LLM labeling and symbol-table validator land in a follow-up iteration"*).

**v1.1 adds zero new LLM calls.** Source D classification uses only the AST output that exists today. The (future) LLM-labelling step that the existing extractor reserves space for is **out of scope** for this design — it remains future work, to be designed and shipped separately.

Properties this gives us in v1.1:

- Reproducible — same schema → byte-identical candidate-graph for C/D portions
- Cheap — zero new LLM cost
- Explainable — every candidate carries a rule-traceable reason
- CI-friendly — schema/code ingestion runs without API keys
- Testable — deterministic logic is unit-testable

---

## 4. Candidate schema (backward-compatible additive)

The common candidate dict in `candidate-graph.json` gains four fields beyond today's shape:

```jsonc
{
  // EXISTING fields — values unchanged from today
  "label":              "Customer",
  "definition":         "...",
  "source_type":        "C",
  "source_artifact":    "schemas/core.sql:42",
  "raw_type":           "table",
  "eid":                "...",

  // NEW additive fields (default values when not derivable)
  "artifact_kind":      "entity",           // closed vocab (see §5)
  "strength":           "strong",           // strong | medium | weak
  "promotion_reason":   "Table 'customers' classified as entity (≥3 cols, ≥1 non-key, no code-table triggers).",
  "suppression_reason": null                // non-null only when suppressed=true
}
```

**Serialisation contract:** `candidate-graph.json` becomes **additive backward-compatible** — every existing field and existing value is preserved exactly. The four new keys are added to every candidate.

This is **not** byte-identical serialisation (snapshot tests that diff the whole JSON will need a one-time snapshot update). It **is** value-stable for every key that consumers of today's `candidate-graph.json` read.

Merging across sources:

- `source_presence: {A, B, C, D}` continues to be a union (existing behaviour)
- `strength` becomes the **max** across attesting sources, with an optional one-tier boost when ≥2 axes corroborate (boost is internal to v1.1 record-keeping; downstream consumers don't act on `strength` until v1.2 — see §13)
- `promotion_reason` becomes a concatenation listing each contributing reason
- `definition` selection prefers explicit text (existing rule)

Suppressed candidates are emitted to the graph too (with `suppressed: true`) so downstream consumers and tests can see exactly what got filtered and why. The default `build_candidate_graph` consumer skips them; an opt-in audit consumer reads them.

`candidate-graph.json` also gains an `audit` top-level block listing suppressed candidates with their reasons. Consumers ignoring unknown top-level keys are unaffected.

---

## 5. Artifact-kind closed vocabulary

A single closed enum used across all sources. Each source maps its native shapes into this vocabulary:

| `artifact_kind` | Source A | Source B | Source C | Source D |
|---|---|---|---|---|
| `entity` | concept (LLM-extracted noun) | record with `entity_type=entity` | table / model | class / dataclass / Pydantic model |
| `attribute` | LLM-extracted property phrase | record with `entity_type=attribute` | non-FK column | dataclass field / class field |
| `relationship` | LLM-extracted predicate | record with `entity_type=relationship` | foreign key | method between two classes |
| `vocabulary` | (rare) | enum-typed record | code/lookup table | Python `Enum` subclass |
| `behavior` | (rare) | (rare) | (n/a) | non-CRUD method |
| `rule` | (rare) | (rare) | `CHECK` constraint | validation function / SQL predicate |

**OWL emission in `draft.owl` is unchanged in v1.1.** Today's `owl_export.py` emits `owl:Class` for every fused element and `owl:ObjectProperty` for every distinct predicate. v1.1 does not extend this; OWL changes (DatatypeProperty for `attribute`, SKOS for `vocabulary`, annotation properties for `behavior`/`rule`) are explicitly deferred to v1.2 — see §13.

This means: in v1.1, a `vocabulary`-tagged candidate from a code/lookup table **shows up in `candidate-graph.json` with its kind correctly tagged**, but if fusion picks it through to `fused.json`, it still emits as `owl:Class` in `draft.owl`. That's an acceptable transitional state — the curator sees the kind tag in the candidate graph and in the audit log, and v1.2 will improve the OWL emission.

---

## 6. Source C ingestion

### 6.1 Input format (v1.1)

**SQL DDL files (`.sql`) only.** Parsed via `sqlglot` (new dependency). Rationale: universal, no DB credentials, version-controllable, deterministic.

JSON dumps (SQLAlchemy reflection, dbt manifest) and direct DB connections are out of scope — see §13.

### 6.2 Artifact taxonomy and default strength

| Source C artifact | Emitted as | Default strength | Notes |
|---|---|---|---|
| Table with ≥3 columns, ≥1 non-key column, doesn't match code-table detector | `entity` | `strong` | The standard case |
| Table flagged as code/lookup (see §6.4) | `vocabulary` | `medium` | Kind tag only; OWL emission unchanged in v1.1 |
| Non-FK, non-PK column | `attribute` of parent table | same tier as parent | Datatype-hint in `raw_type` |
| Single-column FK | `relationship` from parent to referenced table | tier of stronger endpoint | Domain/range pre-pinned |
| Composite FK | `relationship` with composite-key annotation | as above | |
| PK column | NOT emitted as standalone — flagged on parent as identifier | — | Demoted from "concept" to "identifier of parent" |
| Named `CHECK` constraint | `rule` | `weak` | Kind tag only; not emitted to OWL in v1.1 |
| Bridge table (≥2 FKs, no other domain columns) | `relationship` between the two referents | `medium` | The table itself does not become a class |

### 6.3 Default noise filters

Suppress (with explicit `suppression_reason`):

- **Tables** matching `*_audit`, `*_history`, `*_log`, `*_journal`, `tmp_*`, `bkp_*`, `bak_*`; views with `vw_*_audit` patterns
- **Columns** matching:
  - Timestamps: `created_at`, `updated_at`, ending in `_at` / `_ts` / `_timestamp` — **unless** prefixed by a domain-bearing token (`birth_date`, `expiry_date`, `valuation_date`, etc.)
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

**Note on SKOS members:** DDL alone yields the *scheme* (the existence of the code table) but not its *members* (the row values). v1.1 emits only the scheme marker via `artifact_kind="vocabulary"` on the candidate. Actual `skos:Concept` member emission is deferred to v1.2 when value-bearing inputs are also designed in (Source B enum lists, Source D `Enum` literals, future Source C value-bearing inputs) — see §13.

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
    - status_codes
```

Globbing applied case-insensitively. Override semantics: `exclude_*` and `force_*` win over default heuristics; `include_*` brings back items the default would have dropped.

---

## 7. Source D ingestion

### 7.1 Input scope (v1.1)

Python files (`.py`) only. The existing `code_extractor.py` supports SQL and sqlglot today; the v1.1 ingestion policy formally documents Python. SQL/JS/TS support is preserved as the existing behaviour but not refactored.

### 7.2 Artifact taxonomy and default strength

| Source D artifact | Emitted as | Default strength |
|---|---|---|
| `class` with at least one non-method attribute | `entity` | `strong` |
| `@dataclass` / Pydantic `BaseModel` / SQLAlchemy model | `entity` | `strong` |
| `class FooEnum(Enum):` | `vocabulary` | `medium` |
| Class field with type annotation | `attribute` of parent class | same tier as parent |
| Method involving two domain classes | `relationship` | `medium` |
| Function with name matching `validate_*`, `check_*`, `assert_*` plus regex-matching body | `rule` | `weak` |
| Other methods | `behavior` | `weak` |

**Determinism in v1.1:** classification is purely AST-based. The `code_extractor.py` module's docstring lists LLM labelling as future work (not shipped). v1.1 does not add LLM labelling; the deterministic AST output drives all of Source D's classification.

### 7.3 Default noise filters

Suppress:

- **Path-based:** files under `tests/`, `test/`, `mocks/`, `fixtures/`, `migrations/`, `vendor/`, `__pycache__/`, `examples/`; files matching `test_*.py`, `*_test.py`, `conftest.py`
- **Generated code:** files where the first 5 lines contain `# DO NOT EDIT`, `# Generated by`, `# AUTOGENERATED`, or `# This file was automatically generated`
- **Private:** classes starting with `_` (Python convention)
- **Framework boilerplate:** `class Meta:`, `class Config:`, anything inheriting from `unittest.TestCase`

Flag (not suppress):

- DTOs are ambiguous: classes ending in `DTO`, `Request`, `Response`, `Schema`, `Model` emit with `raw_type="dto_candidate"` so the curator (or per-domain config) can decide. They are valid domain entities in many shops (Pydantic models often are); they are pure transport objects in others.

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
2. **Match by normalised label** — candidates from different sources with the same normalised label merge into one node. Existing `_upsert` behaviour, now driven by classification:
   - Two `entity` candidates with the same normalised label → merge
   - An `entity` (Source C table) and an `attribute` (Source A "customer attribute") with the same label → conflict logged, both survive with distinct `artifact_kind`s, the conflict is surfaced in the audit
3. **Tier boost on corroboration (record-only in v1.1)** — a candidate attested on ≥2 axes is **boosted one strength tier**:
   - Was `medium`, now attested across semantic + structural → becomes `strong`
   - Was `weak` and attested only on one axis → stays `weak`
   - Already `strong` → stays `strong` (no super-strong tier)
   - **Boost is recorded on the candidate but does not yet drive downstream behaviour in v1.1.** Profile induction and fusion confidence scoring continue to use today's flat source-presence model. v1.2 starts consuming `strength` as a real signal (see §13).

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
    suppressed: bool = False

class IngestionPolicy(ABC):
    def extract(self, raw_input: Any) -> Iterable[RawArtifact]: ...
    def classify(self, artifact: RawArtifact) -> ArtifactKind: ...
    def filter(self, artifact: RawArtifact, config: SourceConfig) -> tuple[bool, str | None]: ...
    def promote(self, artifact: RawArtifact, kind: ArtifactKind, kept: bool) -> Candidate: ...
```

### 9.2 `build_candidate_graph` becomes an orchestrator

`core/candidate_graph.py` is reshaped to call each ingester and merge their outputs. The four ingester instances are constructed once and dispatched per-source. The inline ingestion logic that exists today for A and B moves into `ingest_a.py` / `ingest_b.py` with **byte-identical behaviour for inputs that produce no new fields** (regression-tested against the existing fixture suite; the new `artifact_kind`, `strength`, `promotion_reason` fields are populated from rule defaults — see §11.1 for the regression contract).

### 9.3 What does NOT change in v1.1 (intentional narrow scope)

The following stay exactly as they are today, **deferred to v1.2**:

- **`profile.induce`** — reads candidates the same way; does not consume `artifact_kind` / `strength`.
- **`fusion.engine.fuse`** — confidence scoring continues to use today's flat source-presence model; does not yet consume `strength` or axis-attestation.
- **`core/owl_export.fused_to_owl`** — continues to emit `owl:Class` per element and `owl:ObjectProperty` per distinct predicate (current shipped behaviour). No new constructs (no `owl:DatatypeProperty`, no `skos:ConceptScheme`, no annotation properties for `behavior`/`rule`).

This intentional narrowness keeps v1.1 contained: the candidate graph becomes richer and more honest, but downstream consumers continue to behave as they do today. v1.2 takes up the downstream work once the seeded graph quality is validated against real domains.

### 9.4 CLI surface — no change

`ontozense survey` keeps its existing flags (`--source-a`, `--source-b`, `--source-c`, `--source-d`). What changes is that `--source-c` and `--source-d` now do real work. A user who never passed them gets the same candidate-graph values as today (with the new additive keys present — see §11.1 for the precise regression contract).

### 9.5 `CandidateConcept` loader / serialiser contract

`core/discovery_contracts.py::CandidateConcept` is a strict frozen dataclass; its `from_dict()` does `cls(**data)`, which raises on unknown keys. To match the new on-disk serialisation in §4, **the dataclass itself grows**:

```python
@dataclass(frozen=True)
class CandidateConcept:
    # ... all existing fields unchanged ...

    # NEW additive fields (v1.1) — all optional with defaults so old
    # candidate-graph.json snapshots from v1.0 deserialise correctly.
    artifact_kind:       str        = "entity"   # closed vocab (§5)
    strength:            str        = "medium"   # strong | medium | weak
    promotion_reason:    str        = ""
    suppression_reason:  str | None = None
    suppressed:          bool       = False
```

**Why grow the dataclass instead of tolerating unknown keys:** loading what we wrote is the natural behaviour; a write-then-discard asymmetry is harder to reason about; v1.2 consumers (profile induction, fusion) will need the fields on the loaded object anyway, so growing now is honest and avoids touching the dataclass twice.

**Compatibility properties:**

- **Old v1.0 `candidate-graph.json` snapshots** (without the new keys) deserialise correctly: `from_dict()` constructs the object, dataclass defaults fill the missing fields.
- **New v1.1 `candidate-graph.json` snapshots** (with the new keys) deserialise correctly: `from_dict()` reads them into the matching dataclass fields.
- **`to_dict()` always writes the new keys** (drawing from current field values or defaults), so the on-disk shape is stable across writers.
- **Existing consumers** (`induce-profile`, `report`, etc.) that read only the pre-v1.1 attributes continue to work without modification — the new attributes are accessible to them but ignored.

This is the precise mechanism behind the "additive backward-compatible" claim in §4. AC1 (§17) pins the contract end-to-end.

---

## 10. Provenance and explainability

Every candidate carries the trail that produced it. Concretely:

- `source_artifact` — file path + locator (`schemas/core.sql:42`, `src/loans/models.py:Customer:line 15`)
- `promotion_reason` — human-readable rule-trace (`"Table 'customers' classified as entity (≥3 cols, ≥1 non-key, no code-table triggers). Corroborated by Source A 'customer' (LLM-extracted). Strength: strong (tier boost from medium due to multi-axis attestation)."`)
- `suppression_reason` — populated only when `suppressed=true`; concrete (`"Column 'created_at' matches default noise filter rule 'timestamp without domain prefix'."`)

A new `audit` top-level block in `candidate-graph.json` lists every suppressed candidate alongside its reason. Default-filtered consumers ignore it; an explicit `ontozense audit` consumer (deferred to v1.2 — see §13) surfaces it for the curator.

This provides the foundation for **explainable induction**: every concept that survives to the candidate graph has a rule-traceable justification, and every concept that did not survive has a rule-traceable rejection.

---

## 11. Testing strategy

### 11.1 Regression — backward-compat-additive

The existing test suite for `build_candidate_graph` must continue to pass. The contract:

- **Existing fields and existing values are byte-identical to today** when only A and B are passed.
- **New keys** (`artifact_kind`, `strength`, `promotion_reason`, `suppression_reason`, top-level `audit`) **are added**, populated from rule defaults.
- Snapshot tests that compare the entire JSON dict will fail until snapshots are updated (one-time refresh). Field-targeted assertions on existing keys remain green without change.
- The A and B ingesters extracted into `ingest_a.py` and `ingest_b.py` are pinned to produce byte-identical values for all existing fields against today's fixtures.

This is **higher priority** than any new C/D test — nothing existing breaks for documentation-led domains.

### 11.2 Per-ingester unit tests

- `tests/core/ingest/test_ingest_c.py` — DDL parsing (sqlglot integration), artifact taxonomy classification (table → entity, code table → vocabulary, FK → relationship, audit column suppressed), heuristic filters, per-domain config overrides. ~25 tests.
- `tests/core/ingest/test_ingest_d.py` — AST extraction (classes, dataclasses, enums, validation functions), DTO ambiguity flag, path-based suppression, generated-code detection. ~20 tests.

### 11.3 Cross-source merge tests

`tests/core/test_candidate_graph_cross_source.py` — corroboration logic. Cases:

- Single-axis attested → expected strength tier (no boost)
- Two-axis attested → tier boost applied (recorded on candidate)
- Three-axis attested → strongest tier, boost capped at `strong`
- Classification conflict (`entity` from C + `attribute` from A, same label) → both survive with audit entry
- Suppressed in one source → not boosted by attestation in another

### 11.4 End-to-end fixtures

Two new domain fixtures under `tests/fixtures/`:

- `banking_minimal/` — small Basel-like governance + tiny DDL + tiny Python models. End-to-end: survey runs, candidate graph has expected concepts at expected strengths, draft.owl emission is unchanged from today's behaviour (since v1.1 doesn't change OWL semantics).
- `data_only_minimal/` — DDL only, no docs, no governance. Validates that survey produces useful candidate-graph output for data-led domains (the v1.1 motivating case). Draft.owl emission still produces `owl:Class` for tables-as-entities (existing behaviour).

### 11.5 OWL output regression

Existing `tests/test_owl_export.py` must pass without modification. v1.1 does not change OWL emission. New OWL constructs (DatatypeProperty for attributes, SKOS for vocabularies, annotation properties for behavior/rule) are v1.2 work — see §13.

---

## 12. Migration and backward compatibility

### 12.1 A+B-only `survey` invocation — additive backward-compatible

A user who runs `ontozense survey --source-a docs.md --source-b governance.json --domain-dir d/` (no `--source-c`, no `--source-d`) gets a `candidate-graph.json` where:

- Every existing key carries the same value as today
- Four new keys (`artifact_kind`, `strength`, `promotion_reason`, `suppression_reason`) are added per candidate, populated from rule defaults
- A new top-level `audit` key is added (empty list when nothing is suppressed)

Consumers reading only the existing keys see no behaviour change. Consumers comparing full JSON snapshots will need a one-time snapshot update.

### 12.2 New `--source-c .sql` / `--source-d code/` flags now do real work

The CLI signature is already in place (forward-compat hook from the previous redesign). Users who start passing them get the new behaviour. No deprecation needed; the flags were no-ops, now they aren't.

### 12.3 New consumed field: `audit` in `candidate-graph.json`

Consumers that read `candidate-graph.json` without reading the `audit` block continue to work. The `ontozense audit` consumer that displays this block is itself v1.2 work.

### 12.4 Profile induction, fusion confidence, OWL emission — unchanged

The new fields on candidates are present in v1.1 but not consumed by downstream stages. Profile induction reads candidates the same way it does today. Fusion's confidence scoring is unchanged. OWL emission is unchanged. **draft.owl byte-equivalence with today's output is preserved for A+B-only runs.** This is the intentional narrowing per Codex Finding #3.

### 12.5 New dependencies

- `sqlglot` — pure-Python SQL parser. Permissive MIT licence. Adds ~3 MB to the install footprint. Adds no runtime cost when Source C is not used (lazy-imported inside `ingest_c.py`).
- `inflect` (optional, ~50 KB) — English pluralization for label normalisation. A small chop-trailing-s heuristic could substitute; `inflect` is preferred but not load-bearing.

---

## 13. Out of scope (deferred to v1.2 and beyond)

Explicit non-goals for v1.1, to keep this design tight:

### 13.1 Deferred to v1.2 (downstream consumption of the new fields)

1. **Profile induction reweighting.** `profile.induce` consumes `artifact_kind` and `strength` to weight type proposals. Schema-only entities (no A/B attestation) become a distinct curator-visible status.
2. **Fusion confidence reweighting.** `fusion.engine.fuse` switches from flat source-presence counting to axis-weighted attestation scoring.
3. **OWL emission semantics for new artifact kinds.** `owl_export.fused_to_owl` learns to emit:
   - `owl:DatatypeProperty` for `attribute`-kind candidates with detected datatypes
   - `skos:ConceptScheme` + `skos:Concept`s for `vocabulary`-kind candidates (with members from value-bearing inputs)
   - Annotation properties for `behavior` and `rule` kinds
4. **`skos:Concept` member emission** — requires concrete vocabulary values from Source B enums, Source D `Enum` literals, or value-bearing Source C inputs. v1.1 emits only the `vocabulary` kind marker.
5. **`ontozense audit` consumer CLI** — a consumer that displays suppressed candidates with reasons for curator review.

### 13.2 Deferred to v1.2+ (input expansion)

6. **Source C input formats other than `.sql`** — JSON (SQLAlchemy reflection / dbt manifest) and direct DB connections.
7. **Source D languages other than Python** — SQL/JS/TS code extraction is preserved as-is (existing behaviour) but the new ingestion-policy formalisation only documents Python in v1.1.
8. **LLM labelling pass for Source D** — `code_extractor.py` reserves space for an LLM semantic-labelling pass per the AI-BRX pattern (today's docstring marks this as future work). Designing and shipping that labelling pass is its own work item, separate from this design.

### 13.3 Deferred indefinitely (likely never v1.x)

9. **Smart "domain-ness scoring"** — ML/LLM-assisted scoring of columns/classes for ambiguous cases. The deterministic heuristics + per-domain overrides cover the realistic 80%+; smart scoring is a v1.x+ refinement.
10. **Schema-aware sub-entity promotion** — promoting `customer.status` to its own sub-entity because it has a backing code table and is FK'd from many places. Requires graph-analysis over the schema.
11. **Cross-table relationship inference from query logs** — deriving relationships from JOIN patterns observed at runtime.
12. **LLM-generated promotion-reason prose** — the rule-generated reason is fine. Optional LLM polish later.

---

## 14. Risks

| Risk | Mitigation |
|---|---|
| Default heuristics overfit to one schema style and miss real concepts in others | Validate against two real schemas (one banking, one ESG-ish) before merging. Per-domain config override gives users a fast escape hatch. |
| `sqlglot` doesn't parse a real-world DDL we hit | Document supported SQL dialects explicitly; fail with a clear error pointing the user at the per-domain config override. Alternative input formats are explicitly v1.2 work. |
| Multi-axis tier boost over-promotes weak corroborations | Tier boost is capped at one tier and never produces a tier higher than `strong`. Boost happens only with explicit multi-axis evidence (no transitive boosts). In v1.1 it is recorded but does not yet drive downstream consumption, so over-promotion has no observable effect on `draft.owl` until v1.2 — giving us a release of real-world data to calibrate before the boost becomes load-bearing. |
| Snapshot tests break for A+B-only runs due to new additive keys | One-time snapshot refresh as part of the v1.1 PR. Documented in release notes. |
| Per-domain YAML config files drift from the spec | Schema-validate them at load time and emit clear errors. |
| Adding new dataclass fields to `Candidate` breaks downstream JSON consumers | Fields are additive; existing keys preserved; consumers ignoring unknown keys are unaffected. |

---

## 15. Vocabulary

| Term | Meaning |
|---|---|
| **Seeder** | A source that contributes candidate concepts to the candidate graph at survey time (not just at fusion time). |
| **Ingester** | The source-specific adapter that turns raw artifacts into uniform `Candidate` records via the extract → classify → filter → promote pipeline. |
| **Artifact kind** | The closed-vocabulary classification of a candidate's nature: `entity`, `attribute`, `relationship`, `vocabulary`, `behavior`, `rule`. |
| **Strength tier** | The candidate's confidence band: `strong`, `medium`, `weak`. Independent of `artifact_kind`. Recorded in v1.1, not yet load-bearing on downstream consumption. |
| **Axis** | One of the three evidence dimensions: semantic (A/B), structural (C), executable (D). |
| **Corroboration** | Multi-axis attestation of the same normalised label. Drives the (record-only in v1.1) tier boost. |
| **Promotion reason** | Rule-trace text justifying why a candidate survived to the candidate graph at its assigned strength. |
| **Suppression reason** | Rule-trace text justifying why a candidate was filtered out. |
| **Audit block** | The `audit` top-level key of `candidate-graph.json` listing suppressed candidates + their reasons. |

---

## 16. Scope summary (v1.1)

**In scope for v1.1:**

- `core/ingest/` package with four source-specific ingesters
- `Candidate` dataclass with new `artifact_kind`, `strength`, `promotion_reason`, `suppression_reason`, `suppressed` fields
- Source C ingestion from `.sql` files via `sqlglot`
- Source D ingestion from `.py` files via existing AST-based `code_extractor.py`
- Default noise heuristics + per-domain `source-c.yaml` / `source-d.yaml` overrides
- Cross-source label normalisation + corroboration-based tier boost (record-only, not yet consumed downstream)
- `audit` block in `candidate-graph.json` listing suppressed candidates
- `build_candidate_graph` refactored to orchestrate the four ingesters
- A and B ingesters extracted to their own modules with byte-identical existing-field behaviour
- Comprehensive tests including two new end-to-end domain fixtures
- README + tutorial updates documenting the new C/D behaviour

**Out of scope (see §13):**

- Profile induction reweighting using new fields
- Fusion confidence reweighting using new fields
- OWL emission of new constructs (DatatypeProperty, SKOS, annotation properties)
- `skos:Concept` member emission from value-bearing sources
- `ontozense audit` consumer CLI
- Source C input formats other than `.sql`
- Source D languages other than Python (preserved as-is, not refactored)
- LLM labelling pass for Source D
- Smart / LLM-assisted classification
- Schema-aware sub-entity promotion
- Cross-table relationship inference

---

## 17. Acceptance criteria

The implementation is complete when:

- **AC1 — additive backward-compat for A+B-only runs:** A run with only `--source-a` and `--source-b` produces a `candidate-graph.json` where every existing key carries the same value as today's pipeline. The new candidate fields (`artifact_kind`, `strength`, `promotion_reason`, `suppression_reason`, `suppressed`) and the new top-level `audit` key are present. Snapshot tests get a one-time refresh; value-targeted assertions on existing keys pass without change. The `CandidateConcept` dataclass (§9.5) gains matching optional fields with defaults; **a v1.0 candidate-graph.json snapshot (no new keys) deserialises cleanly via `from_dict()`** and **a v1.1 candidate-graph.json snapshot round-trips through `to_dict()` / `from_dict()` without data loss**. Existing consumers (`induce-profile`, `report`, etc.) run unmodified.
- **AC2 — Source C seeds:** A run with `--source-c schema.sql` adds new candidates to the graph with `source_type="C"`, `artifact_kind` set per §5, default strength per §6.2, suppression of audit-table noise per §6.3, code-table detection per §6.4.
- **AC3 — Source D seeds:** A run with `--source-d code/` adds new candidates with `source_type="D"`, classification per §7.2 (deterministic AST-driven, no LLM), default suppression per §7.3, DTO ambiguity flag per §7.3.
- **AC4 — corroboration recorded:** A concept attested across two axes records at least one tier higher than the same concept attested on only one. A concept attested across all three records at `strong`. The boosted strength is present in `candidate-graph.json` but does not change `draft.owl` output in v1.1.
- **AC5 — explainability:** Every non-suppressed candidate has a non-empty `promotion_reason`. Every suppressed candidate has a non-empty `suppression_reason`. Both are deterministic given the input.
- **AC6 — config override:** A per-domain `source-c.yaml` `exclude_tables` rule actually excludes the matching table from the graph (or records it as suppressed with the rule cited). Same for `source-d.yaml`.
- **AC7 — vocabulary kind tagged, OWL unchanged:** A code/lookup table detected per §6.4 produces a candidate with `artifact_kind="vocabulary"` in `candidate-graph.json`. The `draft.owl` emitted from a fusion run including this candidate continues to use today's emission rules (`owl:Class` for the element). SKOS emission is v1.2 work.
- **AC8 — fixture validation:** Both end-to-end fixtures (`banking_minimal/`, `data_only_minimal/`) produce expected `candidate-graph.json` outputs. Their `draft.owl` outputs match today's emission rules (no new constructs).
- **AC9 — no new LLM dependency:** Source C and D ingestion paths run end-to-end with no LLM API key configured and produce candidates correctly. Source A continues to require its LLM key when invoked (unchanged).
- **AC10 — full suite green:** all existing tests pass (snapshot refreshes excepted), plus the new tests pass. `draft.owl` snapshot tests on A+B-only fixtures remain byte-identical to today.

---

## 18. Open questions for review

### Resolved (Codex review round 2 — 2026-05-17)

1. ✅ **Record-only tier boost** — kept. Codex: *"useful instrumentation: you get real-domain data about whether the corroboration heuristic is sensible before making it load-bearing. Deferring it entirely just postpones the same calibration problem."*
2. ✅ **Single `candidate-graph.json` with `audit` block** — kept (no split into `candidate-graph-audit.json`). Codex: *"simpler contract, less orchestration, easier debugging. If size becomes a problem later, split it in v1.2."*

### Resolved (Codex review round 3 — 2026-05-17)

3. ✅ **Two config files (`source-c.yaml`, `source-d.yaml`), not merged.** Codex: *"source-specific heuristics will diverge quickly; separate schemas are simpler to validate; avoids one large nested `sources.yaml` accumulating unrelated knobs; easier for users to reason about ownership and review diffs."* If a real need for cross-source coordination emerges later, a unified `sources.yaml` can be revisited.
4. ✅ **DTOs flagged, not suppressed by default.** Codex: *"in many modern Python stacks, DTOs / Pydantic models are real domain surface, not transport noise. Default suppression would create false negatives in code-led domains. The current `raw_type="dto_candidate"` approach preserves evidence while staying honest about ambiguity. Per-domain config already gives the opt-out path where DTOs are known to be noise."*

All open questions resolved. The spec is ready for implementation planning.
