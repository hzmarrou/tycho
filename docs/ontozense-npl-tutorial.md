# Ontozense Tutorial — NPL Domain (Non-Performing Loans)

This tutorial walks you through building a domain ontology for the
**Non-Performing Loans (NPL)** domain using Ontozense. By the end
you will have:

- Extracted concepts and relationships from a Basel regulatory document
- Validated those concepts against a governance reference file
- Extracted business rules from production code
- Fused all sources into a rich data dictionary
- Run lint checks on the fused output, including structural gap analysis
- Used an LLM to suggest bridging concepts for disconnected clusters
- Queried the dictionary and filed back an expert review

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

```bash
cd C:\Users\hzmarrou\OneDrive\python\projects\ontozense
pip install -e ".[dev]"
```

### 2. Set up Azure OpenAI credentials

Create a `.env` file in the ontozense root directory:

```env
AZURE_API_KEY=your-azure-openai-key
AZURE_API_BASE=https://your-resource.openai.azure.com
AZURE_API_VERSION=2024-12-01-preview
OPENAI_API_KEY=your-azure-openai-key
```

Source A (the LLM-based document extractor) and `suggest-bridges`
(LLM-suggested bridging concepts) need these. Sources B, C, and D
and the other commands are fully deterministic and don't require
any API key.

### 3. Create a domain workspace

```bash
mkdir -p domains/npl/sources
mkdir -p domains/npl/derived/source-a
mkdir -p domains/npl/derived/fused
```

This is where all inputs and outputs for the NPL domain will live.

---

## Step 1 — Prepare your sources

### Source A: Authoritative domain document

Ontozense ships with a Basel D403 regulatory guidelines document. Copy
it into your domain workspace:

```bash
cp tests/fixtures/npl-basel-guidelines.md domains/npl/sources/
```

This is a real regulatory document: *"Prudential treatment of problem
assets — definitions of non-performing exposures and forbearance"* from
the Basel Committee on Banking Supervision.

### Source B: Governance reference (optional)

Ontozense ships with an 18-entry governance reference file derived from
the OpenNPL ontology. It contains canonical terms like Borrower,
Collateral, Counterparty, Forbearance, Loan, etc. — each with a
definition, criticality flag, and a citation to "data marketplace".

Copy it into your workspace:

```bash
cp docs/governance_example.json domains/npl/sources/governance.json
```

The governance file is a simple JSON array. Each entry has
`element_name` (required) plus optional `domain_name`, `definition`,
`is_critical`, and `citation`:

```json
[
  {
    "domain_name": "Risk Management",
    "element_name": "Borrower",
    "definition": "A sub-class of Counterparty that applies to lending relations...",
    "is_critical": true,
    "citation": "data marketplace"
  },
  {
    "element_name": "Collateral",
    "definition": "An asset or property pledged by a borrower to secure a loan...",
    "is_critical": true,
    "citation": "data marketplace"
  }
]
```

The shipped file has 18 entries (12 critical, 6 non-critical) covering
the core NPL domain concepts. Source B's role is **validation**: the
fusion layer uses it to confirm that concepts extracted by Source A
actually exist in the governance system.

### Source D: Production code (optional)

Ontozense ships with a synthetic NPL codebase containing Python and SQL
files that implement Basel D403 rules. Copy them into your workspace:

```bash
cp -r tests/fixtures/synthetic_npl_code domains/npl/sources/npl-code
```

This synthetic codebase contains:
- `classification/npe_classifier.py` — thresholds (`NPE_DPD_THRESHOLD = 90`),
  classification logic, IFRS stage assignments
- `transitions/upgrade_rules.py` — probation periods, upgrade conditions
- `forbearance/forbearance_validator.py` — forbearance detection rules
- `reporting/finrep_npl_query.sql` — regulatory reporting SQL view
- `reporting/loan_constraints.sql` — database CHECK constraints

---

## Step 2 — Route your files (optional preview)

Before extracting, you can preview how the router classifies your files:

```bash
ontozense ingest domains/npl/sources/ --dry-run --domain-dir domains/npl
```

Expected output:

```
Routed 7 file(s):
  A - 1 file(s) - Source A - Authoritative domain documents
  B - 1 file(s) - Source B - Governance / data dictionaries
  C - 1 file(s) - Source C - Database schemas
  D - 4 file(s) - Source D - Production code

  ->      A (95%, extension) npl-basel-guidelines.md
          Markdown file with no significant code blocks; Source A
  ->      B (95%, content_sniff) governance.json
          JSON contains 'element_name' field - governance reference
  ->      D (95%, extension) npe_classifier.py
          File extension '.py' maps to Source D
  ->      D (95%, extension) forbearance_validator.py
  ->      D (95%, extension) upgrade_rules.py
  ->      C (90%, content_sniff) finrep_npl_query.sql
          SQL file with 1 DDL statements (CREATE TABLE/VIEW/...)
  ->      D (60%, content_sniff) loan_constraints.sql
          SQL file with no clear DDL or procedural pattern

Dry run - no extractors invoked.
```

**What the router did:**
- `.md` file → Source A by extension rule.
- `governance.json` → Source B by **content sniff** (recognises the
  `element_name` field in the JSON).
- `.py` files → Source D by extension.
- `finrep_npl_query.sql` contains a `CREATE VIEW`, so the SQL content
  sniffer classifies it as **Source C** (schema DDL) — not Source D.
- `loan_constraints.sql` has `ALTER TABLE ... CHECK` without a strong
  DDL signal, so it falls back to Source D at lower confidence (0.60).
  Worth reviewing manually before dispatch.

This is correct behaviour: SQL files that declare structure (CREATE
TABLE/VIEW) go to Source C; SQL files that express rules (WHERE
filters, CHECK constraints, procedural code) go to Source D. No
extractors ran in this dry run — it was just a preview.

---

## Step 3 — Extract from the domain document (Source A)

This is the LLM-powered step. It uses OntoGPT with the SPIRES
methodology to extract concepts and relationships from the Basel D403
document:

```bash
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

Expect ±20% variation on these counts across runs.

**What happened:**
1. OntoGPT sent the document to the LLM with a LinkML template
2. The extractor parsed the LLM's `raw_completion_output` (bypassing
   SPIRES's lossy recursion) to recover all identified concepts
3. A regex-based second pass found definitions in bold-colon, "means",
   "is defined as" patterns
4. Concepts from both passes were merged, with regex-only finds scored
   at lower confidence (0.40) so the human knows to review them
5. Every concept carries a confidence score and provenance (source
   document, section, text snippet)

**If Source A fails:** the CLI now surfaces a clean error message with
a hint about the likely cause (auth, OntoGPT install, template).
You should never see a raw Python traceback.

**Inspect the output:**

Open `domains/npl/derived/source-a/basel-d403.xlsx` in Excel. You'll
see two sheets:
- **Concepts** — one row per extracted concept, with columns for name,
  definition, citation, confidence, source document, and a "Needs Review"
  flag
- **Relationships** — subject/predicate/object triples with confidence

### If you don't have an Azure OpenAI key

You can skip this step and use a pre-generated JSON file for the
remaining steps. If you have a previous extraction JSON, copy it to
`domains/npl/derived/source-a/basel-d403.json` and continue from Step 4.

---

## Step 4 — Fuse all sources

Now combine Source A (domain document), Source B (governance), and
Source D (code) into a single rich data dictionary:

```bash
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
1. Source A concepts seeded the element list
2. Source B governance records matched against Source A concepts by
   name (case-insensitive, underscore/hyphen normalised). Matching
   concepts got marked as "governance-validated" and enriched with
   `is_critical` flags and governance citations
3. Source D code rules were attached as `business_rules` to matching
   elements (by name or referenced symbol). Unmatched rules (code
   that doesn't reference any extracted concept) were tracked separately
4. Conflicts (two sources providing different values for the same field)
   were resolved by priority order (A > B > C > D by default), with
   rejected values preserved for audit

**Inspect the fused output:**

The JSON at `domains/npl/derived/fused/v1.json` contains:
- `elements[]` — one entry per data element, with all fields populated
  from whichever source could defensibly provide them
- `relationships[]` — from Source A and Source C (if schema was provided)
- `summary` — counts of elements, governance-validated, conflicts, etc.

Each element has:
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
  "conflicts": []
}
```

---

## Step 5 — Lint the fused output

Run consistency checks to find issues the expert should review:

```bash
ontozense lint domains/npl/derived/fused/v1.json --domain-dir domains/npl
```

Expected output (approximate — your numbers will vary):

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
- **Contradictions** — two sources provided different values for the
  same field. The fusion layer resolved them (A wins by priority), but
  the expert should verify the rejected value isn't better.
- **Orphan terms** — concepts that exist but aren't connected to
  anything via relationships. May indicate missing relationships.
- **Coverage gaps** — elements where important fields (definition,
  citation) are empty. These are the rows the expert should fill during
  review.
- **Structural gaps** — concept clusters with no or weak connections
  between them, detected by graph community analysis (networkx). These
  indicate areas where the ontology has topological holes — the concepts
  exist but the relationships between groups are missing. Bridge
  concepts (high betweenness centrality) are also reported as info —
  these are the nodes that hold different clusters together. The output
  is **capped at the 10 worst gaps** (by density) plus an overflow
  summary — use `--max-gaps N` to see more, or `--max-gaps 0` to
  disable the gap reporting entirely (no warnings, no overflow
  summary). Bridge concepts are controlled independently by
  `--max-bridges N` (default 10; `--max-bridges 0` disables that scan).

---

## Step 5b — Suggest bridging concepts for structural gaps

When lint finds structural gaps, you can ask an LLM to suggest
bridging relationships that would connect the disconnected clusters:

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
losses. This concept naturally bridges the default/NPE cluster with
the collateral/enforcement cluster.

Saved: domains/npl/bridge-suggestions.md
Filed back: derived/analyses/bridge-suggestions.md
```

**What happened:**
1. The command ran the same structural gap analysis as lint (networkx
   community detection)
2. For the worst 5 gaps (by density), it constructed a targeted prompt
   with both clusters' concepts and definitions — one LLM call per gap
3. The LLM suggested bridging concepts with specific relationships
   (Subject --[predicate]--> Object format)
4. The output was saved as markdown and automatically filed back into
   the knowledge base

**Cost control:** Each gap is one LLM call. The default cap of 5 keeps
cost bounded; raise `--max-gaps` if you want to explore more gaps.

The expert reviews the suggestions, approves or rejects each one, and
files the corrections back. On the next fusion run, these filed-back
artifacts are part of the audit trail.

This is the **Karpathy feedback loop** in action: Lint finds gaps ->
LLM suggests bridges -> Expert reviews -> File-back -> Re-fuse.

> **Note:** This step requires an Azure OpenAI key (or another LLM
> provider configured via litellm). If you don't have one, skip this
> step — the rest of the tutorial works without it.

---

## Step 6 — Query a specific element

Look up everything Ontozense knows about a specific concept. We'll use
**Borrower** here — it's in both the Basel document (Source A) and the
governance file (Source B), so the query shows rich cross-source
output:

```bash
ontozense query "Borrower" --fused domains/npl/derived/fused/v1.json
```

Output (approximate):

```markdown
### Borrower

| Field | Value | Source |
|---|---|---|
| domain_name | Risk Management | B |
| definition | A sub-class of Counterparty that applies to lending relations... | B |
| is_critical | True | B |
| citation | data marketplace | B |

**Governance validated**

**Relationships:**
- Borrower --[owes_to]--> Lender (source: A)
- Borrower --[secures_with]--> Collateral (source: A)

*Confidence: 0.88 | Sources: A+B | Needs review: no*
```

Your specific output depends on what concepts and relationships the LLM
extracted. Any term that appears in both Sources A and B — like
Borrower, Collateral, Counterparty, Forbearance, Loan — should produce
a similar cross-source result.

### Save the query result and file it back

```bash
ontozense query "Borrower" \
  --fused domains/npl/derived/fused/v1.json \
  --output domains/npl/borrower-review.md \
  --domain-dir domains/npl
```

This saves the markdown result **and** automatically files it back
into `domains/npl/derived/analyses/borrower-review.md`. The expert can
now edit this file (add their corrections, approve/reject the
definition, note missing context) and it becomes part of the knowledge
base's audit trail.

### Search for related concepts

```bash
ontozense query "exposure" --fused domains/npl/derived/fused/v1.json
```

This finds all elements whose name contains "exposure":
- Non-Performing Exposure
- Exposure Classification
- Past-Due Exposure
- ...

---

## Step 7 — File back an expert review

After reviewing the fused output, the expert writes a markdown file
with their corrections and observations:

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

Save this as `domains/npl/expert-review-v1.md` and file it back:

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

The expert review is now part of the knowledge base. The audit log at
`domains/npl/log.md` records every operation:

```
## [2026-04-22] extract-a | source=npl-basel-guidelines.md | concepts=~30 | ...
## [2026-04-22] fuse | sources=A+B+D | elements=~42 | conflicts=~3 | ...
## [2026-04-22] lint | contradiction=~3 | orphan=~6 | coverage_gap=~8 | ...
## [2026-04-22] file-back | source=expert-review-v1.md | destination=derived/analyses/expert-review-v1.md
```

---

## Step 8 — Iterate (the feedback loop)

When a new document arrives (a regulation update, an internal policy
change, a new codebase module), the cycle repeats:

```bash
# 1. Ingest the new file
ontozense ingest domains/npl/sources/new-eba-guidelines.pdf \
  --auto --domain-dir domains/npl

# 2. Re-fuse with all available sources
ontozense fuse \
  --source-a domains/npl/derived/source-a/basel-d403.json \
  --source-a domains/npl/derived/source-a/eba-guidelines.json \
  --source-b domains/npl/sources/governance.json \
  --source-d domains/npl/sources/npl-code \
  --output domains/npl/derived/fused/v2.json \
  --domain-dir domains/npl

# 3. Lint the new version
ontozense lint domains/npl/derived/fused/v2.json --domain-dir domains/npl

# 4. Query, review, file back
ontozense query "Forbearance" \
  --fused domains/npl/derived/fused/v2.json \
  --output domains/npl/forbearance-review.md \
  --domain-dir domains/npl
```

Each iteration enriches the knowledge base. The domain expert's
corrections accumulate as filed-back analyses. The audit log tracks
every operation. The ontology grows by accretion, not replacement.

---

## Directory structure after the tutorial

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
├── derived/
│   ├── source-a/
│   │   └── basel-d403.json              (Source A extraction)
│   ├── fused/
│   │   └── v1.json                      (fused rich data dictionary)
│   └── analyses/
│       ├── borrower-review.md           (filed-back query result)
│       ├── bridge-suggestions.md        (LLM-suggested bridges)
│       └── expert-review-v1.md          (filed-back expert review)
└── log.md                               (append-only audit trail)
```

---

## CLI Reference (quick)

| Command | What it does |
|---|---|
| `ontozense extract-a <doc> --json out.json` | Extract concepts + relationships from a domain document (Source A) |
| `ontozense ingest <path> --dry-run` | Preview how the router classifies files |
| `ontozense ingest <path> --auto` | Route and auto-dispatch to extractors (confidence > 0.9) |
| `ontozense fuse --source-a a.json --source-b b.json -o fused.json` | Fuse sources into a rich data dictionary |
| `ontozense lint fused.json [--max-gaps N]` | Run consistency checks (contradictions, orphans, structural gaps) |
| `ontozense suggest-bridges fused.json -o bridges.md [--max-gaps N]` | Ask LLM to suggest bridging concepts for structural gaps |
| `ontozense query "term" --fused fused.json` | Look up an element or search by substring |
| `ontozense file-back review.md --domain-dir domain/` | Save an expert review into the knowledge base |

---

## Troubleshooting

- **`extract-a` fails with auth error** → check `AZURE_API_KEY`,
  `AZURE_API_BASE`, `AZURE_API_VERSION` in `.env`. The CLI prints
  a hint when it detects an auth-related error message.
- **Lint reports too many structural gaps** → this is capped at 10
  by default. Raise with `--max-gaps N` to see more, or set
  `--max-gaps 0` to disable gap reporting entirely (no warnings, no
  overflow summary). Bridges are controlled separately via
  `--max-bridges N`.
- **`query "Default"` returns no match** → try a concept that's in the
  governance file: `Borrower`, `Collateral`, `Counterparty`,
  `Forbearance`, `Loan`, etc. Not every regulation term lands in
  governance; only curated ones.
- **Windows terminal shows garbled characters** → all CLI output is
  ASCII-only. If you see garbled output, check your terminal encoding
  settings — Ontozense's output itself should never produce cp1252
  encoding errors.

---

## What Ontozense does NOT do

- **It does not replace the expert.** It produces 60-70% of the data
  dictionary; the expert reviews and fills the rest.
- **It does not invent definitions.** Every field carries a confidence
  score and provenance. If the evidence is weak, the confidence is low
  and the element is flagged for review.
- **It does not silently succeed with bad output.** Exit code 2 means
  zero elements were extracted; exit code 3 means all elements are
  low-confidence. Scripts can rely on these codes.
- **It does not lock you into one domain.** The core engine is
  domain-neutral (enforced by a regression test). NPL, healthcare,
  manufacturing, telecom — the same pipeline works. Only the input
  documents change.
