# Ontozense Tutorial — NPL Domain (Non-Performing Loans)

This tutorial walks you through building a domain ontology for the
**Non-Performing Loans (NPL)** domain using Ontozense.

The tutorial is split into two parts:

- **Part 1 — Fast track (`survey` → `draft`).** Two commands take you
  from raw sources to a draft OWL ontology. This is the recommended
  starting point: it runs end-to-end in a few minutes and produces a
  reviewable artifact you can open in Protégé or Ontology Playground.
- **Part 2 — Manual pipeline (power-user).** The same flow broken into
  its underlying primitives (`ingest`, `extract-a`, `fuse`, `lint`,
  `suggest-bridges`, `query`, `file-back`) for when you need fine
  control, want to inspect intermediate artifacts, or are iterating
  on a single stage.

The tutorial uses real fixtures shipped with Ontozense, so everything
runs without external API calls except the Source A extraction and the
LLM bridge suggestions (which need an Azure OpenAI key).

> **Note on counts:** Expected output numbers (concept counts, gap
> counts, etc.) are **approximate**. The LLM step in Source A is
> non-deterministic — your actual numbers will vary by ±20% depending
> on the model version and random sampling. The tutorial's numbers are
> from one representative run, not a ground-truth contract.

---

## Prerequisites

### 1. Install Ontozense

From the Tycho repo root (where this `docs/` folder lives):

```powershell
cd C:\Users\hzmarrou\OneDrive\python\evolve\tycho
```

**With `uv` (recommended — isolated, reproducible):**

```powershell
uv venv
.\.venv\Scripts\Activate.ps1
uv pip install -e ".[dev]"
```

Re-activate `.venv` whenever you open a new shell. Re-run
`uv pip install -e ".[dev]"` only when dependencies in
`pyproject.toml` change.

To skip activation each time, prefix commands with `uv run` from the
repo root, e.g. `uv run ontozense survey ...`.

**Alternative — plain `pip` global install (faster, but pollutes
system site-packages and can clash with other editable installs):**

```powershell
pip install -e ".[dev]"
```

Confirm install:

```powershell
ontozense --help
```

You should see the command list (`survey`, `draft`, `ingest`,
`extract-a`, `fuse`, `lint`, ...). If you get
`ModuleNotFoundError: No module named 'ontozense.cli'`, another
editable install is pointing at a stale path — re-run
`uv pip install -e ".[dev]"` (or `pip install -e ".[dev]"`) from this
directory to override it.

### 2. Set up Azure OpenAI credentials

Create a `.env` file in your working directory. Either naming
convention works — the CLI aliases Azure SDK names → LiteLLM names
at load time (`_load_env` in `cli.py`).

**Azure SDK convention (recommended — matches what the Azure portal
gives you):**

```env
AZURE_OPENAI_API_KEY=your-azure-openai-key
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_API_VERSION=2024-10-01-preview
AZURE_OPENAI_CHAT_DEPLOYMENT=gpt-5.4
```

**LiteLLM convention (also accepted):**

```env
AZURE_API_KEY=your-azure-openai-key
AZURE_API_BASE=https://your-resource.openai.azure.com
AZURE_API_VERSION=2024-10-01-preview
OPENAI_API_KEY=your-azure-openai-key
```

Source A (the LLM-based document extractor) and `suggest-bridges`
(LLM-suggested bridging concepts) need these. Sources B, C, and D
and the other commands are fully deterministic and don't require
any API key.

The deployment name in `AZURE_OPENAI_CHAT_DEPLOYMENT` must match the
suffix of the `--model` value (default `azure/gpt-5.4`).

### 3. Create a domain workspace

```bash
mkdir -p domains/npl/sources
```

This is where all inputs and outputs for the NPL domain will live.
`survey` and `draft` create the `discovery/`, `induced-profile/`, and
derived subdirectories for you on first run.

### 4. Stage the NPL sources

> **If you're using a packaged Tycho distribution** (e.g.
> `dist/tycho-public/` produced by
> `python scripts/export_tycho_public.py`), the four NPL sources are
> already staged at `domains/npl/sources/`:
>
> - `npl-basel-guidelines.md` (Source A — Basel D403 document)
> - `governance.json` (Source B — governance reference)
> - `npl-schema.sql` (Source C — OpenNPL database schema)
> - `npl-code/` (Source D — production Python + SQL)
>
> Skip ahead to **Part 1**. If you're working from a dev checkout,
> run the three `cp` commands below first.

```bash
cp tests/fixtures/npl-basel-guidelines.md domains/npl/sources/
cp docs/governance_example.json domains/npl/sources/governance.json
cp -r tests/fixtures/synthetic_npl_code domains/npl/sources/npl-code
```

What each source is:

- **Source A** — Basel D403 regulatory document
  (*"Prudential treatment of problem assets — definitions of
  non-performing exposures and forbearance"*).
- **Source B** — 18-entry governance reference derived from the
  OpenNPL ontology (Borrower, Collateral, Counterparty, Forbearance,
  Loan, ...), each with definition, criticality flag, and citation.
- **Source D** — synthetic NPL codebase: `npe_classifier.py`
  (`NPE_DPD_THRESHOLD = 90`, IFRS stage assignments),
  `upgrade_rules.py`, `forbearance_validator.py`,
  `finrep_npl_query.sql`, `loan_constraints.sql`.

---

# Part 1 — Fast track (`survey` → `draft`)

Two commands. Start to finish. Use this path first.

```
sources/  ──survey──>  discovery/  ──draft──>  draft.owl + summary
```

## Step 1 — `survey` (Stage 1)

`survey` is the **Stage 1 orchestrator**. It runs `extract-a` on every
document you point at, merges in governance / schema / code, and
writes a unified candidate graph under `discovery/`.

```bash
ontozense survey \
  --source-a domains/npl/sources/npl-basel-guidelines.md \
  --source-b domains/npl/sources/governance.json \
  --source-d domains/npl/sources/npl-code \
  --domain-dir domains/npl
```

Expected output (approximate — LLM step is non-deterministic, expect
±20% on candidate/relationship counts):

```
Survey: ~50 candidates, ~27 relationships, ~3 cross-source matches.
See domains\npl\discovery.
Rules: 9 (eligibility: 9)
```

**Artifacts produced under `domains/npl/discovery/`:**

- `source-a.json` — concatenated `extract-a` output across all
  `--source-a` documents.
- `candidate-graph.json` — unified graph of concepts and relationships
  with per-source presence flags.
- `candidate-provenance.json` — per-candidate provenance trail
  (which file, which line, which extractor).

**What happened:**

1. Each `--source-a` document was passed through `extract-a` (LLM
   extraction with the SPIRES methodology).
2. JSON `--source-a` inputs (pre-extracted) are reused as-is.
3. Source B governance records were merged in by name.
4. Source D Python files were parsed by the deterministic AST
   extractor (classes, dataclasses, Pydantic/SQLAlchemy models,
   Enums, validation functions).
5. Cross-source matches (concepts present in ≥2 sources) were
   counted as a quality signal.

`--source-c <file.sql>` adds a schema (parsed via `sqlglot`). Repeat
flags to add multiple inputs; pass a directory to walk it recursively.

## Step 2 — `draft` (Stage 2)

`draft` is the **Stage 2 orchestrator**. It scores the candidate
graph, induces a profile (or uses one you supply), fuses the sources,
runs validation + lint, and emits a draft OWL ontology — the handoff
artifact for an expert curator.

```bash
ontozense draft \
  --domain-dir domains/npl \
  --source-b domains/npl/sources/governance.json \
  --source-d domains/npl/sources/npl-code \
  --output domains/npl/draft.owl
```

> **Why re-pass `--source-b` / `--source-d`?** `survey` writes only
> Source A into `discovery/source-a.json`. Source B/D are NOT
> persisted into `discovery/` yet. For the fusion step inside `draft`
> to enrich the OWL with governance flags (`is_critical`,
> `citation`) and code rules (`BusinessRule` objects with line
> anchors), B and D must be re-loaded directly. `--source-c` on
> `draft` is deprecated — Source C flows through
> `discovery/candidate-graph.json` only.

Expected output (approximate):

```
Source A: ~27 concepts, ~37 relationships from source-a.json
Source B: 18 governance records from governance.json
Source D: 50 code rules from domains\npl\sources\npl-code
Draft written to domains\npl\draft.owl
  Summary: domains\npl\draft-summary.md
Open in Ontology Playground or Protégé.
```

**Artifacts produced:**

- `domains/npl/draft.owl` — the draft ontology (Turtle by default;
  use `--format json-ld` or `--format owl-xml` to switch).
- `domains/npl/draft-summary.md` — human-readable summary: profile
  used, element/relationship counts, validation errors, lint
  warnings, suggested review priorities.
- `domains/npl/fused.json` — the fused rich data dictionary that fed
  the OWL export.
- `domains/npl/induced-profile/` — induced profile (skipped if you
  passed `--profile`).

**What happened:**

1. Loaded `discovery/candidate-graph.json` from Step 1.
2. Scored candidates with default weights + thresholds (override
   with `--weights` / `--thresholds`).
3. Wrote an induced profile under `induced-profile/`. To skip
   induction, pass a hand-authored profile: `--profile <dir>`.
4. Fused Source A + (optional Source B / D) into `fused.json`.
5. Validated against the profile (`--mode flag` annotates findings;
   `--mode filter` drops them).
6. Linted for contradictions, orphans, coverage gaps, structural
   gaps.
7. Serialised to OWL via `rdflib` and wrote `draft-summary.md`.

**Plan without running:**

```bash
ontozense draft --domain-dir domains/npl --output domains/npl/draft.owl --plan
```

## Step 3 — Open the draft

`draft.owl` is a standard OWL file. Open it in any OWL editor:

- **Ontology Playground** — drag-and-drop the file.
- **Protégé** — `File → Open` and point at `draft.owl`.

Read `draft-summary.md` first to know where to start the review.

---

## What's next?

You now have a working draft. For a deeper, step-by-step pass —
inspecting intermediate artifacts, tuning a single stage, or wiring
in `file-back` and `suggest-bridges` — continue with Part 2.

---

# Part 2 — Manual pipeline (power-user)

`survey` and `draft` are convenience orchestrators built on top of a
set of lower-level primitives. Reach for these when you want to
inspect or replay a single stage in isolation.

```
ingest  ──>  extract-a  ──>  fuse  ──>  lint  ──>  suggest-bridges
                                 │
                                 └──>  query / file-back
```

## Step M1 — Route your files (`ingest`)

Preview how the router classifies your files before extracting:

```bash
ontozense ingest domains/npl/sources/ --dry-run --domain-dir domains/npl
```

Expected output:

```
Routed 8 file(s):
  A - 1 file(s) - Source A - Authoritative domain documents
  B - 1 file(s) - Source B - Governance / data dictionaries
  C - 2 file(s) - Source C - Database schemas
  D - 4 file(s) - Source D - Production code

  ->      A (95%, extension) npl-basel-guidelines.md
          Markdown file with no significant code blocks; Source A
  ->      B (95%, content_sniff) governance.json
          JSON contains 'element_name' field — governance reference
  ->      C (90%, content_sniff) npl-schema.sql
          SQL file with 5 DDL statements (CREATE TABLE/VIEW/...)
  ->      C (90%, content_sniff) finrep_npl_query.sql
          SQL file with 1 DDL statements (CREATE TABLE/VIEW/...)
  ->      D (95%, extension) npe_classifier.py
  ->      D (95%, extension) forbearance_validator.py
  ->      D (95%, extension) upgrade_rules.py
  ->      D (60%, content_sniff) loan_constraints.sql
          SQL file with no clear DDL or procedural pattern

Dry run — no extractors invoked.
```

**What the router did:**

- `.md` → Source A by extension rule.
- `governance.json` → Source B by content sniff (`element_name`
  field).
- `.py` → Source D by extension.
- `npl-schema.sql` (5 DDL statements) and `finrep_npl_query.sql`
  (`CREATE VIEW`) → Source C by content sniff.
- `loan_constraints.sql` has `ALTER TABLE ... CHECK` without strong
  DDL signal → Source D at lower confidence (0.60). Worth a manual
  review before dispatch.

SQL that declares structure → Source C; SQL that expresses rules
(`WHERE`, `CHECK`, procedural code) → Source D.

Drop `--dry-run` and add `--auto` to actually dispatch to extractors
for files routed above the 0.9 confidence threshold:

```bash
ontozense ingest domains/npl/sources/ --auto --domain-dir domains/npl
```

## Step M2 — Extract from the domain document (`extract-a`)

The LLM-powered step. Uses OntoGPT with the SPIRES methodology to
extract concepts and relationships from the Basel D403 document:

```bash
mkdir -p domains/npl/derived/source-a
ontozense extract-a \
  domains/npl/sources/npl-basel-guidelines.md \
  --json domains/npl/derived/source-a/basel-d403.json \
  --output domains/npl/derived/source-a/basel-d403.xlsx \
  --domain-dir domains/npl
```

This takes 30-60 seconds depending on your Azure OpenAI endpoint.

Expected output (approximate — LLM output varies by run):

```
Extracting from: domains/npl/sources/npl-basel-guidelines.md
  Domain: NPL   Concepts: ~30 (mostly LLM + a few regex)
  Relationships: ~20-25
  Definitions enriched: 8-12

Excel saved: domains/npl/derived/source-a/basel-d403.xlsx
JSON saved:  domains/npl/derived/source-a/basel-d403.json

Concepts:
  high (>=80%): ~25   mid (50-79%): ~3   low (<50%): ~2
Relationships:
  high (>=80%): ~20   mid (50-79%): ~2   low (<50%): ~2
```

Expect ±20% variation across runs.

**What happened:**

1. OntoGPT sent the document to the LLM with a LinkML template.
2. The extractor parsed `raw_completion_output` directly (bypassing
   SPIRES's lossy recursion) to recover all identified concepts.
3. A regex-based second pass found definitions in bold-colon,
   "means", "is defined as" patterns.
4. Concepts from both passes were merged. Regex-only finds get
   confidence 0.40 so the reviewer knows to check them.
5. Every concept carries a confidence score and provenance.

**If `extract-a` fails:** the CLI surfaces a clean error with a hint
about the likely cause (auth, OntoGPT install, template). You should
not see a raw Python traceback.

**Inspect the output:**

Open `basel-d403.xlsx` in Excel:

- **Concepts** — name, definition, citation, confidence, source,
  "Needs Review" flag.
- **Relationships** — subject/predicate/object triples with
  confidence.

If you don't have an Azure OpenAI key, drop in a pre-generated
`basel-d403.json` and continue.

## Step M3 — Fuse all sources (`fuse`)

Combine Source A, Source B, Source D into one rich data dictionary:

```bash
mkdir -p domains/npl/derived/fused
ontozense fuse \
  --source-a domains/npl/derived/source-a/basel-d403.json \
  --source-b domains/npl/sources/governance.json \
  --source-d domains/npl/sources/npl-code \
  --output domains/npl/derived/fused/v1.json \
  --domain-dir domains/npl
```

Expected output (approximate):

```
Source A: ~30 concepts, ~24 relationships from basel-d403.json
Source B: 18 governance records from governance.json
Source D: ~50 code rules from npl-code

Fused ~42 elements from sources A+B+D
  Governance-validated: ~8   Conflicts: ~3   Relationships: ~24
  Governance-only (not in Source A): ~6
  Unmatched code rules: ~35

Fused dictionary saved: domains/npl/derived/fused/v1.json
```

**What happened:**

1. Source A concepts seeded the element list.
2. Source B records matched against Source A by name (case-insensitive,
   underscore/hyphen normalised). Matches got marked as
   "governance-validated" and enriched with `is_critical` + citation.
3. Source D rules attached as `business_rules` on matching elements.
   Unmatched rules (code that doesn't reference any extracted
   concept) tracked separately.
4. Conflicts (two sources, same field, different values) resolved by
   priority A > B > C > D. Rejected values preserved for audit.

### Structure of a fused element

Per [PLAYBOOK §2](PLAYBOOK.md), 17 canonical fields with defined
semantics (`element_name`, `definition`, `is_critical`, `citation`,
`data_type`, `enum_values`, `business_rules`, six DQ dimensions,
etc.). Each has a primary source and a fallback. Extra columns from
your sources (e.g., a custom `data_steward` in your governance JSON)
are carried through in `extra_fields`.

Two dimensions vary:

- **Total element count**: ~42 here. A larger regulation or more
  governance terms could push this to 200–500.
- **Fields per element**: depends on which sources contributed.
  Governance-validated concept with a schema match and a code rule
  → 10+ populated fields. Name-only concept from a regulation
  → maybe 3.

Example element:

```json
{
  "element_name": "Borrower",
  "definition": "A sub-class of Counterparty...",
  "is_critical": true,
  "citation": "data marketplace",
  "business_rules": [],
  "governance_validated": true,
  "confidence": 0.85,
  "sources": ["A", "B"],
  "needs_review": false,
  "conflicts": [],
  "extra_fields": {}
}
```

## Step M4 — Lint the fused output (`lint`)

Run consistency checks:

```bash
ontozense lint domains/npl/derived/fused/v1.json --domain-dir domains/npl
```

Expected output (approximate):

```
Lint report for v1.json
  Elements: ~42   Relationships: ~24   Sources: A+B+D

Contradictions (~3):
  [warning] ! Field 'definition': A ('Inability to pay...') vs B
    ('Status assigned when...'). Resolved by priority.
  ...

Orphan terms (~6):
  [info] - 'Value Adjustments' is not referenced by any relationship.
  [info] - 'Gross Carrying Amount' is not referenced by any relationship.
  ...

Coverage gaps (~8):
  [warning] ! 'Probation Period' is missing: definition, citation. Sources: A.
  [info] - 'IFRS Stage 1' is missing: citation. Sources: A.
  ...

Structural gaps (up to 10 warnings + bridge concepts):
  [warning] ! Communities {Default, Forbearance, Non-Performing Exposure}
    and {Collateral, Property Collateral, Enforcement} have no
    cross-connections (density 0.00). Consider adding bridging
    relationships.
  [info] - 'Loan' is a bridge concept (betweenness centrality 0.35).
    It connects otherwise separate concept clusters.
  [info] - N additional structural gap(s) not shown (showing worst 10).
          Re-run with --max-gaps N to see more.

Summary: 0 errors, ~15-20 warnings, ~10-15 info
```

**What each check means:**

- **Contradictions** — two sources, different values for the same
  field. Fusion resolved them (A wins by priority), but the expert
  should verify the rejected value isn't better.
- **Orphan terms** — concepts not referenced by any relationship.
  May indicate missing relationships.
- **Coverage gaps** — elements where important fields (definition,
  citation) are empty. Fill during review.
- **Structural gaps** — concept clusters with no/weak connections,
  detected by graph community analysis (`networkx`). Capped at 10
  worst gaps (by density); use `--max-gaps N` to see more or
  `--max-gaps 0` to disable. Bridge concepts (high betweenness
  centrality) reported as info — controlled independently by
  `--max-bridges N`.

## Step M5 — Suggest bridging concepts (`suggest-bridges`)

When lint finds structural gaps, ask an LLM to suggest bridges:

```bash
ontozense suggest-bridges \
  domains/npl/derived/fused/v1.json \
  --output domains/npl/bridge-suggestions.md \
  --domain-dir domains/npl
```

Expected output:

```
Found ~15 structural gap(s). Asking LLM about the worst 5
(5 LLM call(s))...
~10 additional gap(s) not sent to the LLM. Raise --max-gaps to
include more.

# Bridge Suggestions

## Gap 1: {Default, Forbearance, Non-Performing Exposure} <->
          {Collateral, Property Collateral, Enforcement}

**Suggested concept:** Collateral Liquidation

**Suggested relationships:**
- Default --[triggers]--> Collateral Liquidation
- Collateral Liquidation --[applies_to]--> Collateral
- Enforcement --[includes]--> Collateral Liquidation

**Rationale:** When a borrower defaults, the lender may initiate
enforcement proceedings that include liquidating collateral to recover
losses. ...

Saved: domains/npl/bridge-suggestions.md
Filed back: derived/analyses/bridge-suggestions.md
```

**Cost control:** one LLM call per gap. Default cap of 5 keeps cost
bounded; raise `--max-gaps` to explore more.

The expert reviews, approves or rejects, and files corrections back.
This is the **Karpathy feedback loop**: Lint → LLM suggests bridges
→ Expert reviews → File-back → Re-fuse.

> Requires an Azure OpenAI key (or another LLM provider via
> litellm). Skip if you don't have one.

## Step M6 — Query a specific element (`query`)

Look up everything Ontozense knows about a concept. **Borrower** is in
both Source A and Source B, so the query shows cross-source output:

```bash
ontozense query "Borrower" --fused domains/npl/derived/fused/v1.json
```

Output (approximate):

```markdown
### Borrower

| Field | Value | Source |
|---|---|---|
| domain_name | Risk Management |  |
| definition | A sub-class of Counterparty that applies to lending relations. The party that receives funds under a credit agreement and is obligated to repay. |  |
| is_critical | True |  |
| citation | data marketplace |  |

**Governance validated**

*Confidence: 0.95 | Sources: B | Needs review: no*
```

The exact `Sources` set, confidence, and presence of a `Relationships`
block depend on whether the LLM extracted `Borrower` from the Basel
document (Source A) on your run. When `Borrower` is governance-only
(Source B alone), you'll see `Sources: B` and no relationships.
When the LLM also picked it up, expect `Sources: A+B` plus
relationships like `Borrower --[owes_to]--> Lender`.

Substring search returns all matching elements:

```bash
ontozense query "exposure" --fused domains/npl/derived/fused/v1.json
```

Save the result and file it back in one shot:

```bash
ontozense query "Borrower" \
  --fused domains/npl/derived/fused/v1.json \
  --output domains/npl/borrower-review.md \
  --domain-dir domains/npl
```

This writes the markdown **and** files it back into
`domains/npl/derived/analyses/borrower-review.md`. The expert edits
this file (corrections, approvals, missing context) and it joins the
audit trail.

## Step M7 — File back an expert review (`file-back`)

After review, the expert writes a markdown file with corrections:

```markdown
# NPL Domain Review — Expert Notes

## Borrower
The fused definition from Source B is accurate but could be enriched
with the Basel D403 wording about credit agreements. The complete
definition should be:

> A sub-class of Counterparty that applies to lending relations.
> The party that receives funds under a credit agreement (Basel D403
> §4) and is obligated to repay according to the agreed terms.

Status: CORRECTED

## Probation Period
Coverage gap: definition is missing. Adding from Basel D403 Section 22:

> The minimum probation period before a non-performing exposure can be
> reclassified as performing is one year of continuous repayment.

Status: FILLED
```

Save as `domains/npl/expert-review-v1.md` and file it back:

```bash
ontozense file-back \
  domains/npl/expert-review-v1.md \
  --domain-dir domains/npl
```

Output:

```
Filed back: derived/analyses/expert-review-v1.md
Log entry appended to domains/npl/log.md
```

The expert review is part of the knowledge base. The audit log at
`domains/npl/log.md` records every operation:

```
## [2026-04-22] survey | sources=A+B+D | candidates=~42 | ...
## [2026-04-22] extract-a | source=npl-basel-guidelines.md | concepts=~30 | ...
## [2026-04-22] fuse | sources=A+B+D | elements=~42 | conflicts=~3 | ...
## [2026-04-22] lint | contradiction=~3 | orphan=~6 | coverage_gap=~8 | ...
## [2026-04-22] file-back | source=expert-review-v1.md | destination=derived/analyses/expert-review-v1.md
```

## Step M8 — Iterate (the feedback loop)

When a new document arrives (regulation update, internal policy
change, new codebase module), the cycle repeats. The fast track makes
re-runs cheap:

```bash
# 1. Drop the new file into sources
cp eba-guidelines.pdf domains/npl/sources/

# 2. Re-survey (extracts new doc, refreshes candidate graph)
ontozense survey \
  --source-a domains/npl/sources/npl-basel-guidelines.md \
  --source-a domains/npl/sources/eba-guidelines.pdf \
  --source-b domains/npl/sources/governance.json \
  --source-d domains/npl/sources/npl-code \
  --domain-dir domains/npl

# 3. Re-draft (induces a fresh profile, emits v2 ontology)
ontozense draft \
  --domain-dir domains/npl \
  --output domains/npl/draft-v2.owl

# 4. Spot-check a concept
ontozense query "Forbearance" \
  --fused domains/npl/fused.json \
  --output domains/npl/forbearance-review.md \
  --domain-dir domains/npl
```

Each iteration enriches the knowledge base. Expert corrections
accumulate as filed-back analyses. The audit log tracks every
operation. The ontology grows by accretion, not replacement.

---

## Directory structure after the full tutorial

```
domains/npl/
├── sources/
│   ├── npl-basel-guidelines.md          (Source A input)
│   ├── governance.json                  (Source B input)
│   └── npl-code/                        (Source D input)
│       ├── classification/npe_classifier.py
│       ├── transitions/upgrade_rules.py
│       ├── forbearance/forbearance_validator.py
│       └── reporting/
│           ├── finrep_npl_query.sql
│           └── loan_constraints.sql
├── discovery/                           (written by `survey`)
│   ├── source-a.json
│   ├── candidate-graph.json
│   └── candidate-provenance.json
├── induced-profile/                     (written by `draft`)
├── fused.json                           (written by `draft`)
├── draft.owl                            (written by `draft`)
├── draft-summary.md                     (written by `draft`)
├── derived/                             (written by manual pipeline)
│   ├── source-a/
│   │   └── basel-d403.json
│   ├── fused/
│   │   └── v1.json
│   └── analyses/
│       ├── borrower-review.md
│       ├── bridge-suggestions.md
│       └── expert-review-v1.md
└── log.md                               (append-only audit trail)
```

---

## CLI Reference (quick)

### Stage orchestrators (recommended)

| Command | What it does |
|---|---|
| `ontozense survey --source-a … --source-b … --domain-dir D` | **Stage 1.** Run `extract-a` on documents, merge Sources B/C/D, write `discovery/{source-a,candidate-graph,candidate-provenance}.json`. |
| `ontozense draft --domain-dir D --output draft.owl` | **Stage 2.** Score the candidate graph, induce a profile, fuse + validate + lint, emit OWL + `draft-summary.md`. Use `--plan` to preview. |

### Lower-level primitives

| Command | What it does |
|---|---|
| `ontozense ingest <path> --dry-run` | Preview how the router classifies files. |
| `ontozense ingest <path> --auto` | Route and auto-dispatch to extractors (confidence > 0.9). |
| `ontozense extract-a <doc> --json out.json` | Extract concepts + relationships from a domain document (Source A). |
| `ontozense fuse --source-a a.json --source-b b.json -o fused.json` | Fuse sources into a rich data dictionary. |
| `ontozense lint fused.json [--max-gaps N]` | Consistency checks (contradictions, orphans, structural gaps). |
| `ontozense suggest-bridges fused.json -o bridges.md [--max-gaps N]` | Ask LLM to suggest bridging concepts for structural gaps. |
| `ontozense query "term" --fused fused.json` | Look up an element or search by substring. |
| `ontozense file-back review.md --domain-dir D` | Save an expert review into the knowledge base. |

---

## Troubleshooting

- **`survey` / `extract-a` fails with auth error** → check
  `AZURE_API_KEY`, `AZURE_API_BASE`, `AZURE_API_VERSION` in `.env`.
  CLI prints a hint when it detects an auth-related error.
- **`draft` exits with "No candidate-graph.json under …/discovery"**
  → run `ontozense survey` first.
- **`--source-c` on `draft` is ignored** → deprecated. Source C
  reaches `draft` via `discovery/candidate-graph.json`. Pass schema
  files to `survey --source-c <file>.sql` instead.
- **Lint reports too many structural gaps** → capped at 10 by
  default. Raise with `--max-gaps N`; set `--max-gaps 0` to disable
  gap reporting. Bridges controlled separately via `--max-bridges N`.
- **`query "Default"` returns no match** → try a concept in the
  governance file (`Borrower`, `Collateral`, `Counterparty`,
  `Forbearance`, `Loan`). Not every regulation term lands in
  governance — only curated ones.
- **Windows terminal shows garbled characters** → all CLI output is
  ASCII-only. Check your terminal encoding settings.

---

## What Ontozense does NOT do

- **Not a replacement for the expert.** Produces 60-70% of the data
  dictionary; the expert reviews and fills the rest.
- **Does not invent definitions.** Every field carries a confidence
  score and provenance. Weak evidence → low confidence → flagged.
- **Does not silently succeed with bad output.** Exit code 2 means
  zero elements extracted; exit code 3 means all elements are
  low-confidence. Scripts can rely on these codes.
- **Not locked to one domain.** Core engine is domain-neutral
  (enforced by a regression test). NPL, healthcare, manufacturing,
  telecom — same pipeline, different inputs.
