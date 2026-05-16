# Tycho Semantic-Layer Redesign — Design Spec

**Date:** 2026-05-16
**Status:** Approved (brainstorm)
**Type:** Documentation rewrite + 2 new CLI commands + 1 new internal module

---

## 1. Problem statement

A third-party user walked through Tycho's NPL validation tutorial and surfaced four compounding sources of confusion:

1. **Goal-first framing is missing.** The README opens with "auto-generate rich data dictionaries from four sources" — a mechanism, not an outcome. A new reader cannot picture what they will end up with.
2. **Two workflows + same vocabulary = ambiguity.** "Profile" means an input in Path 2 and an output in Path 1. "Validate" is rules-check; "lint" is consistency-check; "discover" sounds like exploration but is actually merging.
3. **No "you finished, here's what you have" anchor.** After running the chain the user has `fused.json` + an induced profile + a report, but the docs do not name the output as a *semantic layer* the user is supposed to do something with.
4. **The output is not crisply actionable.** `fused.json` is a Tycho-internal artifact; nothing in the current pipeline produces a file the user can directly open in a downstream ontology-curation tool such as Ontology Playground or Protégé.

These problems compound because each amplifies the others: an unclear goal makes the workflow fork harder to choose between, which makes the output harder to interpret, which makes the vocabulary feel arbitrary.

## 2. Audience and outcome

**Audience:** anyone building a semantic layer for a domain — data engineers, analysts, data stewards, domain SMEs. Roles differ in which sources they bring (engineer: code + schemas; steward: governance JSON; SME: regulations) but the *outcome* is the same.

**Outcome they want:** *"Get a 60–70% draft semantic layer from my existing sources, then hand it to a curator (or a curation tool) to finish."*

**Tycho's job ends when the draft is handed off.** The expert curator does the remaining 30–40% in Ontology Playground, Protégé, or another OWL editor.

## 3. The canonical output

A **draft OWL ontology** in standard W3C OWL/RDF format. Default serialisation: Turtle (`.ttl` syntax, `.owl` extension by convention) — most human-readable for hand editing.

The OWL file is the **handoff artifact**: the thing the expert opens. It is a *projection* of Tycho's internal `fused.json` working file into the standard format curation tools understand.

Mapping `fused.json` → OWL:

| `fused.json` field | OWL representation |
|---|---|
| Each element (entity) | OWL `Class` (or `Individual` if the profile marks it as instance-level) |
| Each relationship | OWL `ObjectProperty` with `rdfs:domain` and `rdfs:range` from the profile's entity types |
| `definition` field | `rdfs:comment` (or `skos:definition` via opt-in flag) |
| `citation` field | `dc:source` annotation |
| Per-field provenance (which source contributed) | `prov:wasDerivedFrom` annotation |
| ID format | URIs generated from the profile's `id_format` rule (`https://tycho.local/<domain>/<entity_type>_<normalized_label>_<hash6>`) |

**Not in the OWL** (intentionally — stays in `fused.json` for power-user inspection): confidence scores, multi-source conflict logs, regex-vs-LLM extraction flags. These do not have a natural OWL representation and would clutter the curator's view.

## 4. The user journey

```text
  ┌─────────────┐         ┌──────────────┐         ┌──────────────┐
  │   SOURCES   │   →     │   SURVEY     │   →     │    DRAFT     │   →    draft.owl
  │             │         │   (Tycho)    │         │   (Tycho)    │              │
  │ docs/*.md   │         │              │         │              │              ↓
  │ governance  │         │ extract +    │         │ induce +     │   ┌────────────────┐
  │   .json     │         │ merge into   │         │ fuse + check │   │  Ontology       │
  │ schemas/    │         │ candidate    │         │ + emit OWL   │   │  Playground     │
  │ code/       │         │ graph        │         │              │   │  (expert        │
  └─────────────┘         └──────────────┘         └──────────────┘   │   curation)     │
                                                                       └────────────────┘
                                                                              ↓
                                                                       Final ontology
```

The journey has **two Tycho commands** and one external handoff:

| Stage | Command | Output |
|---|---|---|
| **Survey** | `ontozense survey` | `candidate-graph.json` + provenance under `<domain-dir>/discovery/` |
| **Draft** | `ontozense draft` | `draft.owl` + `draft-summary.md` |
| **Hand off** | (no Tycho command) | The expert opens `draft.owl` in a curation tool |

The Path 1 vs Path 2 distinction disappears: both paths are now `ontozense draft`, with or without `--profile`.

## 5. CLI surface

### 5.1 `ontozense survey` (Stage 1 — new)

```
ontozense survey
  --source-a PATH        repeatable; file, glob, or directory (see input rules below)
  --source-b PATH        governance JSON (file, glob, or directory)
  --source-c PATH        schema dir (forward-compat hook; see legacy note)
  --source-d PATH        code dir (forward-compat hook)
  --profile PATH         optional; only the profile's alias_map is used (light normalisation, no filtering)
  --domain-dir PATH      required; workspace
  --model TEXT           LLM model for extract-a step (default: azure/gpt-5.4)
```

**Behavior:**

1. Expand each `--source-a` argument (file / glob / directory) into a flat list of files.
2. Partition by extension: `.md`/`.txt`/`.markdown` → run `extract-a` (LLM call); `.json` → treat as already-extracted Source A output (skip LLM).
3. Concatenate extracted-and-existing Source A outputs.
4. Same expand-and-load logic for Source B (`.json` files).
5. Run the existing `discover` logic with the merged sources.
6. Write artifacts under `<domain-dir>/discovery/`: `source-a.json`, `candidate-graph.json`, `candidate-provenance.json`.
7. Print a one-line summary to stdout.

**Exit codes:** 0 success, 2 malformed/missing input, 1 internal error.

### 5.2 `ontozense draft` (Stage 2 — new)

```
ontozense draft
  --domain-dir PATH      required; reads <domain-dir>/discovery/ + workspace sources
  --profile PATH         optional; if given, use this hand-authored profile and skip induction
  --output PATH          required; path for draft.owl
  --thresholds PATH      optional; only used when inducing
  --weights PATH         optional; only used when inducing
  --mode TEXT            validation mode: "flag" (default) | "filter"
  --format TEXT          OWL serialisation: "turtle" (default) | "json-ld" | "owl-xml"
  --plan                 print what would run; don't execute
```

**Behavior:**

1. Resolve profile: load `--profile` if given; else run `induce-profile` on the candidate graph and use the result.
2. Run `fuse` with the resolved profile + all source inputs → `<domain-dir>/fused.json`.
3. Run `validate` against the profile in the requested mode.
4. Run `lint` on the fused output.
5. Convert `fused.json` → OWL (new internal step, §5.3) → write to `--output`.
6. Write `<domain-dir>/draft-summary.md` with counts, top concepts, validation findings, lint findings, a curator-review checklist.
7. Print a console summary ending with `"Draft written to <path>. Open in Ontology Playground or Protégé."`

**Exit codes:** 0 on success.

### 5.3 New internal module: `core/owl_export.py`

Not a user-facing command (folded into `draft`). Converts `fused.json` to an OWL graph using `rdflib` (already in the dependency tree).

API:

```python
def fused_to_owl(
    fused: FusionResult,
    profile: Profile | None = None,
    domain_namespace: str = "https://tycho.local",
    format: str = "turtle",
    use_skos: bool = False,
) -> str:
    """Return the OWL serialisation as a string."""
```

Mapping rules per §3. Handles missing profile gracefully (falls back to a generic `:Concept` type for every entity).

### 5.4 Input shape rules (uniform across all sources)

Each `--source-*` flag accepts one of three shapes:

| Shape | Example | Meaning |
|---|---|---|
| Single file | `--source-a docs/regulation.md` | Process exactly that file |
| Glob pattern | `--source-a "docs/*.md"` | Process every match |
| Directory | `--source-a docs/` | Walk recursively; pick up every file with a recognised extension |

Recognised extensions per source:

| Source | Extensions |
|---|---|
| `--source-a` | `.md`, `.txt`, `.markdown` (run LLM extractor); `.json` (treated as already-extracted Source A output) |
| `--source-b` | `.json` |
| `--source-c` | follows existing Source C contract |
| `--source-d` | `.py`, `.sql`, `.js`, `.ts` (whatever the code extractor already supports) |

Repeatable flags are concatenated. Empty directories warn but do not error. Mixed extensions inside a Source A directory are handled correctly (LLM-extract `.md` files; reuse `.json` files).

### 5.5 Legacy command treatment

Every existing command keeps its current signature and behaviour. The README and `--help` text group them as **Advanced / power-user commands**.

| Existing command | Role going forward |
|---|---|
| `extract-a` | Stage 1 power-user (single document) |
| `discover` | Stage 1 power-user (merge step only) |
| `induce-profile` | Stage 2 power-user (just induction) |
| `fuse` | Stage 2 power-user (just consolidation) |
| `validate` | Stage 2 power-user (just conformance check) |
| `lint` | Stage 2 power-user (just consistency check) |
| `report` | Stage 2 power-user (just benchmark) |
| `rebuild` | Deprecated; prints a deprecation note suggesting `draft --plan`. Behaviour unchanged. Removed in v2.0. |
| `extract`, `refine`, `convert`, `export`, `diff`, `info` | Legacy OWL pipeline — unchanged, marked legacy in README |

No removals in this release.

## 6. Vocabulary anchor

A short glossary at the top of the README, used consistently everywhere afterwards:

| Term | Definition |
|---|---|
| **Semantic layer** *(canonical noun)* | Structured map of a domain's entities, definitions, relationships, properties, and rules. Tycho produces a draft. |
| **Draft ontology** / `draft.owl` | The handoff file. Standard OWL/Turtle. Open in Protégé, Ontology Playground, or any OWL editor. |
| **Domain** | The area being modeled (NPL, ESG, customer data). Each domain has its own `domains/<name>/` workspace. |
| **Profile** | A schema declaring allowed entity types, predicates, ID format. Either hand-authored or auto-**induced** by Tycho during Draft. |
| **Survey** | Stage 1 — extract from sources, merge into a candidate graph. |
| **Draft** | Stage 2 — turn the candidate graph into a constrained semantic layer; emit OWL. |
| `fused.json` | Tycho's internal working file. `draft.owl` is the human-facing output; `fused.json` carries provenance and confidence details that don't fit cleanly in OWL. |
| **Source A / B / C / D** | The four input kinds: A = authoritative documents, B = governance JSON, C = database schemas, D = production code. |

## 7. Documentation rewrite

### 7.1 README

Replaced sections:

- **Front matter (first ~30 lines):** new outcome-first intro (full text in design Section 3), the journey diagram, the two-command happy path, the vocabulary glossary.
- **`## Three operating modes`** → renamed to `## How Tycho works` and reworded around the survey-draft-handoff journey.
- **`## Quick start`** → reduced to the survey-and-draft pair (one block) plus the handoff sentence; the full seven-command chain moved to a new `## Advanced — running the pipeline by hand` section.
- **`## Discovery workflow`** → merged into the new front matter (no longer a separate section).

Unchanged sections:

- `## What's in a rich data dictionary?`
- `## Design principles`
- `## Legacy commands`

### 7.2 Tutorial

`docs/ontozense-npl-validation.md` rewritten around survey + draft:

| Part | What | Approximate command count |
|---|---|---|
| **A. Setup** | Prerequisites, `uv sync`, `pytest -q` | 3 |
| **B. Workspace** | Create `domains/npl/sources/`, copy fixtures | 4 |
| **C. Survey** | `ontozense survey …` + inspect | 1 + verification snippet |
| **D. Draft** | `ontozense draft …` + inspect | 1 + verification snippet |
| **E. Hand off** | Open `draft.owl` in Protégé / Playground; review checklist | 0 commands |

Existing seven-command walkthrough renamed to `docs/ontozense-npl-advanced.md` and re-framed as a power-user reference.

### 7.3 CLI `--help` text

`survey` and `draft` get rich help text covering all flags and the input shape rules. Every other command's help text adds a one-liner: *"Most users will call `survey` or `draft` instead; this is the underlying step."*

## 8. Scope summary

**New code:**

- `cli.py` — two new commands (`survey`, `draft`); deprecation note added to `rebuild`. Estimated +300 LOC.
- `core/owl_export.py` — new module. Estimated +300 LOC.

**Modified code:**

- `cli.py` existing commands — help-text additions only; no behaviour changes. Estimated +100 LOC across edits.

**Rewritten docs:**

- `README.md` — substantial front-matter rewrite. ~150 LOC net change.
- `docs/ontozense-npl-validation.md` — rewritten around survey + draft. ~400 LOC net (mostly removed; new tutorial is shorter).
- `docs/ontozense-npl-advanced.md` — new file containing the old seven-command walkthrough, re-framed.

**Tests:**

- `tests/test_cli_survey.py` — happy path, multi-file, directory walk, glob expansion, mixed-shape `--source-a`, error surfaces.
- `tests/test_cli_draft.py` — happy path with induced profile, with hand-authored profile, `--plan` flag, `--format` options.
- `tests/test_owl_export.py` — `fused.json` → OWL round-trip, profile-aware URI generation, provenance annotation, missing-profile fallback.

The existing 834-test suite stays intact; no regressions.

**Backward compatibility:**

- Every existing CLI command keeps its signature and exit behaviour.
- `rebuild` adds a deprecation warning but still functions.
- `fused.json` shape unchanged.
- Existing profiles in `docs/profile-examples/` work unchanged.

## 9. Non-goals

- No CLI command renames (covered by the original "B" constraint).
- No removal of legacy commands in this release.
- No Knowledge-graph database export (Neo4j, Memgraph) — explicit handoff target is OWL only.
- No LLM-grounding service (MCP / FastAPI) — out of scope; future work.
- No visual stakeholder review UI — out of scope; the OWL handoff to Playground covers that need.
- No additional ontology adapter (LinkML, dbt semantic_models.yml, Cypher) — OWL is the single canonical handoff format for v1 of this redesign.

## 10. Open questions

None blocking. Two minor decisions to confirm during implementation, both with safe defaults:

1. **Default OWL serialisation: Turtle.** Open to switch to RDF/XML if Ontology Playground prefers that; verify with Playground's loader before locking it in.
2. **Whether `--use-skos` flag should be opt-in or default.** Recommended: opt-in (default to plain `rdfs:comment`). SKOS adds dependencies on the curator's tool understanding `skos:definition`; not universal.

## 11. Estimated effort

- **Implementation:** 1,000–1,500 LOC new code + 100 LOC existing-code edits.
- **Tests:** 3 new test files, ~600 LOC.
- **Docs rewrite:** ~500 LOC net (mostly mass-replacement, not new prose).
- **Total:** 1 implementation plan, executable in one focused work session by a single contributor with the help of the test suite as a safety net.

---

## Approval log

- Brainstorm conducted 2026-05-16 with the project owner.
- Sections 1–5 of the design (problem framing, output, journey, README/tutorial, CLI surface) approved section-by-section during brainstorm.
- Input-shape rules (§5.4) added as a follow-up at owner request after Section 5 was first presented.
- Spec ready for self-review and owner review.
