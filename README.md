# Ontozense

Auto-generate rich data dictionaries and domain ontologies from four
complementary sources: authoritative documents, governance references,
database schemas, and production code.

Ontozense does the mechanical 60-70% of the work, so domain experts
review a draft with provenance, confidence scores, and conflict
detection — instead of starting from a blank spreadsheet.

## The four-source pipeline

```
  Source A: documents (LLM)  ──┐
  Source B: governance (JSON)  ├─→  FUSION  ─→  Rich data dictionary
  Source C: schemas (DB/AST)   │                (JSON + Excel)
  Source D: code (AST)         ─┘                  │
                                                   ↓
                            LINT  ←→  QUERY  ←→  FILE-BACK
                                    (Karpathy feedback loop)
```

Each source contributes only the fields it can defensibly produce.
The fusion layer combines them with per-field provenance and conflict
resolution. Lint runs consistency checks including structural gap
analysis on the concept graph. Query + file-back lets experts review
the draft and commit their corrections back into the knowledge base,
so the ontology improves with every cycle.

## Quick start

```bash
pip install -e ".[dev]"

# 1. Extract from a domain document (needs Azure OpenAI key)
ontozense extract-a path/to/regulation.md \
  --json source-a.json --domain-dir domains/mydomain

# 2. Route a whole folder (auto-dispatch by content type)
ontozense ingest domains/mydomain/sources/ --dry-run

# 3. Fuse everything into a rich data dictionary
ontozense fuse \
  --source-a source-a.json \
  --source-b governance.json \
  --source-d path/to/code/ \
  --output fused.json

# 4. Find contradictions, orphans, coverage gaps, structural holes
ontozense lint fused.json

# 5. Ask an LLM to suggest bridging concepts for structural gaps
ontozense suggest-bridges fused.json -o bridges.md

# 6. Look up any element across all sources
ontozense query "Default" --fused fused.json

# 7. File expert reviews back into the knowledge base
ontozense file-back my-review.md --domain-dir domains/mydomain
```

For the full walkthrough with an NPL (Non-Performing Loans) example,
see [docs/ontozense-npl-tutorial.md](docs/ontozense-npl-tutorial.md).

## Design principles

- **Domain-agnostic.** The core has zero hardcoded domain vocabulary
  (enforced by a regression test). NPL is the test case, not the product.
- **Provenance is non-negotiable.** Every claim traces to a source:
  which document, which section, which extractor, what confidence.
- **Field-aware confidence.** The scoring rubric (PLAYBOOK §3) uses
  different rules for different field types (NARRATIVE, CITATION,
  ENUM, STRUCTURED, etc.).
- **Honest failure modes.** Exit code 2 for zero output, exit code 3
  for all-low-confidence output. Scripts can rely on these.
- **Human is the final authority.** Ontozense produces a 60-70% draft.
  Experts review, edit, and accept corrections via file-back.

See [docs/PLAYBOOK.md](docs/PLAYBOOK.md) for the convention layer that
governs all of this.

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
