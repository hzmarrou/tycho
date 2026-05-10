# Tycho

Auto-generate rich data dictionaries and domain ontologies from four
complementary sources: authoritative documents, governance references,
database schemas, and production code.

Tycho does the mechanical 60–70% of the work, so domain experts
review a draft with provenance, confidence scores, conflict detection,
typed per-field anchors back to the source, and structural validation
against a domain profile — instead of starting from a blank
spreadsheet.

## The four-source pipeline

```
  Source A: documents (LLM)  ──┐
  Source B: governance (JSON)  ├─→  FUSION  ─→  VALIDATE  ─→  LINT  ─→  REPORT
  Source C: schemas (DB/AST)   │       │            │           │         │
  Source D: code (AST)         ─┘      │            │           │         │
                                       │            │           │         ↓
                                       │            │           │   Benchmark
                                       │            │           │   snapshot
                                       │            │           │   (JSON+MD)
                                       ↓            ↓           ↓
                                   QUERY  ←→  FILE-BACK  ←→  rich data dictionary
                                                              (Karpathy feedback loop)
```

Each source contributes only the fields it can defensibly produce.
Fusion combines them with per-field provenance, conflict resolution,
and (in profile mode) cross-source ID alignment so the same canonical
entity from N sources / M documents collapses to one element. Validate
checks the fused output against six structural rules borrowed from the
[OntoMetric](https://github.com/Inspiring-Ming/OntoMetric) methodology.
Lint catches contradictions, orphans, coverage gaps, and structural
holes via graph analysis. Report produces a benchmark snapshot for
run-vs-run comparison. Query + file-back lets experts review the
draft and commit corrections back into the knowledge base.

## Two operating modes

**Unconstrained mode** (no profile). Source A's LLM extracts whatever
concepts it finds; fusion merges by normalised name. Use this when
you don't yet know the target ontology shape.

**Profile mode** (with `--profile <dir>`). You hand Tycho a small
profile package (`schema.json` + optional sidecars) declaring the
allowed entity types, predicates, alias map, ID format, and canonical
verbs. The LLM is constrained to that vocabulary; concepts get
deterministic IDs derived from `(entity_type, normalised_label)`; all
four sources align on those IDs so consolidation is a `dict[id]`
group-by; Validate's six rules check the result against the profile.
See `docs/PROFILE_SPEC.md` for the format and
`docs/profile-examples/esg/` for a worked reference.

## What's in a rich data dictionary?

The fused output is a JSON file containing a list of **elements** (one
per data element) — a structured governed dictionary with two
dimensions that can vary:

- **Number of elements**: highly variable. A tiny domain might have 5
  elements, a large regulatory specification 500. Depends on what the
  sources contributed.
- **Number of fields per element**: up to **17 canonical fields**
  defined in [PLAYBOOK §2](docs/PLAYBOOK.md) — `element_name`,
  `definition`, `is_critical`, `citation`, `data_type`, `enum_values`,
  `business_rules`, the six DQ dimensions, and so on. Each has a
  primary source and fallbacks; fusion knows how to merge and
  conflict-resolve them. **Plus** an `extra_fields` dict that carries
  anything a source contributed beyond the canonical 17 — including
  profile-mode `id` and `entity_type`, multi-doc
  `corroborating_doc_count` and `source_documents`, and any custom
  column from the upstream source (e.g., a `data_steward` field in
  your governance JSON).

Each `field_provenance` entry can also carry a typed `FieldAnchor`
locating where in the source artifact the value came from — page,
char offset, line, segment heading, snippet — so a reviewer can
click through from a fused field to the exact span in the source.

A typical element might have 5–10 fields populated. A fully-enriched
one could have 20+. Fields stay empty when no source provides them —
the lint and validate layers surface those gaps so the expert knows
where to fill in.

## Quick start

```bash
pip install -e ".[dev]"

# 1. Extract from one or more domain documents (needs Azure OpenAI key).
#    Add --profile <dir> for ontology-constrained extraction with
#    deterministic IDs and a fixed vocabulary.
ontozense extract-a path/to/reg-part1.md path/to/reg-part2.md \
  --profile docs/profile-examples/esg \
  --json source-a.json --domain-dir domains/mydomain

# 2. (Optional) Route a whole folder by content type
ontozense ingest domains/mydomain/sources/ --dry-run

# 3. Fuse everything into a rich data dictionary. --source-a is
#    repeatable: each document gets consolidated by deterministic
#    id (profile mode) or normalised name (unconstrained), with
#    multi-doc corroboration tracked.
ontozense fuse \
  --source-a source-a.json \
  --source-b governance.json \
  --source-c path/to/django/models/ \
  --source-d path/to/code/ \
  --output fused.json

# 4. Validate against the profile (profile mode only).
#    --mode flag (default) annotates findings; --mode filter drops
#    invalid entities and cascade-drops dangling relationships.
ontozense validate fused.json \
  --profile docs/profile-examples/esg \
  --output validated.json

# 5. Find contradictions, orphans, coverage gaps, structural holes
ontozense lint fused.json

# 6. Ask an LLM to suggest bridging concepts for structural gaps
ontozense suggest-bridges fused.json -o bridges.md

# 7. Generate a benchmark snapshot — element counts, confidence
#    distribution, conflict stats, anchor coverage, multi-doc
#    corroboration, profile-coverage of declared types/predicates.
#    JSON is machine-diffable for run-vs-run comparison.
ontozense report fused.json \
  --profile docs/profile-examples/esg \
  --output report.json --markdown report.md

# 8. Look up any element across all sources
ontozense query "Default" --fused fused.json

# 9. File expert reviews back into the knowledge base
ontozense file-back my-review.md --domain-dir domains/mydomain
```

For the full walkthrough with an NPL (Non-Performing Loans) example,
see [docs/ontozense-npl-tutorial.md](docs/ontozense-npl-tutorial.md).

## Design principles

- **Domain-agnostic core, profile-driven specialisation.** The core
  has zero hardcoded domain vocabulary (enforced by a regression
  test). Domain knowledge lives in user-supplied profiles
  (`schema.json` + sidecars), not in the package.
- **Provenance is non-negotiable.** Every claim traces to a source:
  which document, which section, which extractor, what confidence —
  and (in Phase 6+) the exact span in the source via typed
  `FieldAnchor` per field.
- **Cross-source ID alignment.** When a profile is loaded, all four
  sources produce the same deterministic ID for the same canonical
  `(entity_type, label)` tuple. Fusion consolidation becomes a
  `dict[id]` group-by — no fuzzy matching.
- **Field-aware confidence.** The scoring rubric (PLAYBOOK §3) uses
  different rules for different field types (NARRATIVE, CITATION,
  ENUM, STRUCTURED, etc.).
- **Honest failure modes.** Exit code 2 for zero output, exit code 3
  for all-low-confidence output and validation errors, exit code 1
  for usage errors. Scripts can rely on these.
- **Human is the final authority.** Tycho produces a 60–70%
  draft. Experts review, edit, and accept corrections via file-back.
- **Backward-compatible by default.** Every phase of the pipeline
  upgrade was gated on byte-identical output for the unconstrained
  (no-profile) path. Adding a profile opts you into more strict
  behaviour; everything you ran before still works.

See [docs/PLAYBOOK.md](docs/PLAYBOOK.md) for the convention layer
that governs all of this. For the history of how the upgraded
pipeline was built — the spec, the per-phase reviews, the design
trade-offs — see `docs/PRD.txt` and the `docs/REVIEW_*.md` files.

## Legacy commands

The following commands are retained from the earlier OWL-centric
pipeline and still work, but the main flow above uses the newer
four-source architecture:

- `ontozense extract` — generic OntoGPT extraction
- `ontozense refine` — validate/normalise/deduplicate an OWL graph
- `ontozense export` — OWL → Playground JSON
- `ontozense convert` — existing extraction JSON → Playground JSON
- `ontozense diff` — compare two OWL ontologies
- `ontozense info` — stats for an OWL graph
