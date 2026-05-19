# Ontozense — NPL Validation Tutorial (for new users)

This tutorial takes you from a blank machine to a fully-validated
Ontozense install on real NPL (Non-Performing Loans) data, using
the recommended two-command flow: **`survey`** then **`draft`**.

By the end you'll have:

1. Cloned the repository and installed the CLI with `uv`.
2. Run the test suite to confirm the install is healthy.
3. Surveyed the NPL sources (Basel guidance + governance JSON +
   sample code) into a candidate graph for inspection.
4. Drafted a semantic layer (`draft.owl`) you can hand to an
   expert in Ontology Playground / Protégé.

Each step has a `✓ Expected:` checkpoint so you can verify the
run is healthy before moving on.

> **Shell:** Commands below are PowerShell 7+ on Windows; bash
> equivalents are nearly identical (swap `` ` `` line
> continuations for `\` and adjust `Get-ChildItem` /
> `Select-String` to `ls` / `grep`).

> **Power-user path:** If you'd rather run each underlying
> pipeline command yourself (extract-a, discover, induce-profile,
> fuse, validate, lint, report) instead of using the orchestrators,
> see [`docs/ontozense-npl-advanced.md`](./ontozense-npl-advanced.md).

## What you'll validate

| Stage | What it proves |
|---|---|
| Environment | Package installed, deps present, `pytest -q` green |
| Survey | `survey` produces a candidate graph from the NPL inputs |
| Draft | `draft` produces a loader-valid `draft.owl` from the candidate graph |
| Hand-off | The OWL file opens in any standard editor (Protégé, Ontology Playground) |

---

## Part A — Setup

### A.1 Prerequisites

- **Python 3.11 / 3.12 / 3.13** (`python --version`)
- **Git** (`git --version`)
- **PowerShell 7+** (`$PSVersionTable.PSVersion`)
- **[uv](https://github.com/astral-sh/uv)** (`uv --version`)
- *(Optional)* Azure OpenAI access in a `.env` — only needed if
  you re-run `extract-a` from raw `.md` instead of reusing the
  Source A JSON in this tutorial.

### A.2 Clone the repository

```powershell
cd C:\Users\$env:USERNAME\projects   # or anywhere
git clone https://github.com/hzmarrou/tycho.git
cd tycho
```

✓ **Expected:** clone completes, working directory is the
repo's root.

### A.3 Install Ontozense with uv

```powershell
uv sync
```

✓ **Expected:** `uv` reports "Installed N packages"; a `.venv\`
directory now exists.

### A.4 Activate the venv

```powershell
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks the script:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope Process
```

Then re-activate.

✓ **Expected:** prompt prefix changes to `(ontozense)` or `(.venv)`.

### A.5 Confirm the CLI is reachable

```powershell
ontozense --help
```

✓ **Expected:** the command list includes **`survey`** and
**`draft`** (alongside `extract-a`, `discover`, `induce-profile`,
`fuse`, `validate`, `lint`, `report`).

### A.6 Run the test suite

```powershell
pytest -q
```

✓ **Expected:** `992 passed, 14 skipped` (or higher if commits
have landed since this tutorial was written — the count grew from
873 → 992 with the v1.1 Source C/D-as-seeders work). Zero failures.

If you see failures, **stop**. Don't continue with NPL validation
until the regression suite is clean.

---

## Part B — Set up the NPL workspace

A fresh clone has no `domains/` workspace (`.gitignore` excludes
it). You'll create one and copy the NPL fixtures into it.

### B.1 Create the workspace directory

```powershell
New-Item -ItemType Directory -Path domains/npl/sources -Force | Out-Null
```

### B.2 Copy the NPL fixtures into the workspace

```powershell
# Idempotent: re-creates the workspace directory if B.1 was skipped.
New-Item -ItemType Directory -Path domains/npl/sources -Force | Out-Null

Copy-Item tests/fixtures/npl-basel-guidelines.md `
  -Destination domains/npl/sources/npl-basel-guidelines.md
Copy-Item docs/governance_example.json `
  -Destination domains/npl/sources/governance.json
Copy-Item tests/fixtures/synthetic_npl_code `
  -Destination domains/npl/sources/npl-code -Recurse
```

✓ **Verify:**

```powershell
Get-ChildItem domains/npl/sources
```

Expected output includes:
- `npl-basel-guidelines.md` (~1700 lines of Basel D403 NPL guidance)
- `governance.json` (18 NPL governance terms)
- `npl-code/` (Source D code fixtures organised by topic)

### B.3 *(v1.1)* Drop a small NPL DDL fixture for Source C

> **⚠ This is a synthetic smoke-test schema, not a real reference
> model.** The DDL below was written for this tutorial. The
> terminology is NPL-flavoured (Basel D403 / EBA NPE concepts —
> `default_date`, `forbearance_event`, `days_past_due`,
> `industry_segment_code`), but it is **not lifted** from any real
> bank, **not** from FIBO / BIAN / ACORD / FINREP, and **not** from
> an anonymised production schema. Its purpose is to **exercise
> each v1.1 Source C classification path** (entity, attribute, FK
> relationship, vocabulary auto-detection, audit-table suppression,
> domain-bearing date column preservation) so you can confirm the
> pipeline works as designed.
>
> **For higher-signal validation**, substitute your own banking
> schema in place of this file — even a 5-10 table slice from a
> real (anonymised) production DDL will surface heuristic gaps and
> real-world dialect issues that a synthetic schema never will.
> Codex's whole-branch v1.1 review explicitly flagged real-schema
> validation as the highest-value mitigation against heuristic
> overfit: *"Default heuristics overfit to one schema style and
> miss real concepts in others — validate against two real schemas
> (one banking, one ESG-ish) before merging."*

The bundled NPL data doesn't ship a `CREATE TABLE` schema (only
`ALTER TABLE` constraint files and a `CREATE VIEW` regulatory
query, which v1.1's sqlglot-based Source C ingester doesn't yet
handle). Drop the minimal smoke-test DDL into the workspace so
Source C has input for this walkthrough:

```powershell
@'
CREATE TABLE loan (
    loan_id INT PRIMARY KEY,
    borrower_id INT,
    principal_balance DECIMAL(18,2),
    days_past_due INT,
    is_non_performing BOOLEAN,
    default_date DATE,
    origination_date DATE,
    created_at TIMESTAMP,
    FOREIGN KEY (borrower_id) REFERENCES borrower(borrower_id)
);

CREATE TABLE borrower (
    borrower_id INT PRIMARY KEY,
    name VARCHAR(200),
    industry_segment_code VARCHAR(20)
);

CREATE TABLE forbearance_event (
    forbearance_event_id INT PRIMARY KEY,
    loan_id INT,
    start_date DATE,
    end_date DATE,
    FOREIGN KEY (loan_id) REFERENCES loan(loan_id)
);

CREATE TABLE loan_status_lookup (
    code VARCHAR(10) PRIMARY KEY,
    description VARCHAR(200)
);

CREATE TABLE loan_audit (
    audit_id INT PRIMARY KEY,
    loan_id INT,
    event VARCHAR(50),
    occurred_at TIMESTAMP
);
'@ | Out-File -Encoding utf8 domains/npl/sources/npl-schema.sql
```

**What this synthetic fixture demonstrates** (each table maps to
a v1.1 classification path you'll see fire in Part C):

| Table | v1.1 classification path it exercises |
|---|---|
| `loan`, `borrower`, `forbearance_event` | Standard tables → entity candidates with FK relationships |
| `loan_status_lookup` | 2-col `code + description` + `_lookup` naming → vocabulary auto-detection |
| `loan_audit` | `*_audit` naming pattern → default suppression / audit-block entry |
| `created_at` column | Timestamp without domain-bearing prefix → column-level suppression |
| `default_date`, `origination_date` | Domain-bearing date prefixes → **kept** (not suppressed) |
| FK to `borrower` / `loan` | Foreign-key constraints → relationship candidates |

If you replace `npl-schema.sql` with a real schema, the expected
counts and labels in Parts C.3 and C.4 below will differ — but the
**shape** of what's exercised (per-source attestation, multi-axis
corroboration, audit block, suppression reasons) stays the same.

### B.4 *(Skip-the-LLM shortcut)* — provide a pre-extracted Source A

If you don't have Azure OpenAI configured yet, you can hand the
tutorial a pre-extracted `source-a.json` so the survey step
doesn't need to call an LLM:

```powershell
@'
{
  "concepts": [
    {"name": "Borrower", "definition": "A party that owes an obligation under a credit arrangement."},
    {"name": "Loan", "definition": "A credit facility extended by a lender."},
    {"name": "Collateral", "definition": "An asset pledged to secure a loan."},
    {"name": "Forbearance", "definition": "A concession granted to a counterparty in financial difficulty."},
    {"name": "Default", "definition": "Failure to meet contractual obligations."}
  ],
  "relationships": [
    {"subject": "Borrower", "predicate": "Holds", "object": "Loan"},
    {"subject": "Loan", "predicate": "SecuredBy", "object": "Collateral"}
  ]
}
'@ | Out-File -Encoding utf8 domains/npl/sources/source-a.json
```

If you have Azure OpenAI keys in `.env`, skip B.4 and let
`survey` extract from the markdown directly.

---

## Part C — Survey the NPL sources

A single command extracts (or reuses) Source A, merges in Source
B governance, **(new in v1.1) parses Source C SQL DDL into
entity / attribute / relationship / vocabulary candidates, AND
parses Source D Python code into first-class candidates** — all
into one candidate graph for inspection.

### C.1 Run survey (A + B + C + D)

```powershell
ontozense survey `
  --source-a domains/npl/sources/source-a.json `
  --source-b domains/npl/sources/governance.json `
  --source-c domains/npl/sources/npl-schema.sql `
  --source-d domains/npl/sources/npl-code `
  --domain-dir domains/npl
```

(If you skipped B.4 and have Azure OpenAI configured, replace
`--source-a domains/npl/sources/source-a.json` with
`--source-a domains/npl/sources/npl-basel-guidelines.md` to run
fresh LLM extraction. That gives 20-50 concepts from the real
Basel document instead of the 5 stubs in `source-a.json`.)

#### Choosing the extraction model (optional)

When Source A is a `.md` / `.txt` / `.pdf` document, `survey`
invokes `extract-a` under the hood and the `--model` flag picks
which LLM does the extraction. Default is `azure/gpt-5.4`.

| Model identifier | Credentials needed (in `.env`) | Cost (approx) | Notes |
|---|---|---|---|
| `azure/gpt-5.4` *(default)* | `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_VERSION` | $$$ | Highest quality on regulatory text (PLAYBOOK §12); the recommended default. |
| `azure/gpt-5.2` | same Azure keys | $$ | Cheaper, faster; ~2.4× fewer validated concepts on regulatory text per PLAYBOOK §12. |
| `openrouter/deepseek/deepseek-v4-pro` | `OPENROUTER_API_KEY` | $ (10-20× cheaper than gpt-5.4) | Comparable extraction quality on regulatory text per the session-internal comparison; widest reasoning budget. |
| `openrouter/deepseek/deepseek-r1` | `OPENROUTER_API_KEY` | $ | DeepSeek's reasoning model; slower per call but very strong on inference-heavy prose. |
| `openrouter/anthropic/claude-sonnet-4-5` | `OPENROUTER_API_KEY` | $$ | Strong general extraction; useful when you want a third opinion vs gpt / deepseek. |

To override the default:

```powershell
ontozense survey `
  --source-a domains/npl/sources/npl-basel-guidelines.md `
  --source-b domains/npl/sources/governance.json `
  --source-c domains/npl/sources/npl-schema.sql `
  --source-d domains/npl/sources/npl-code `
  --domain-dir domains/npl `
  --model openrouter/deepseek/deepseek-v4-pro
```

LiteLLM (the routing layer under `extract-a`) supports any of
its ~100 provider model identifiers. The `--model` flag accepts
whatever string LiteLLM accepts — see
[litellm.ai/docs/providers](https://docs.litellm.ai/docs/providers).
Source B/C/D never call an LLM; they're deterministic, so
`--model` only affects Source A's extraction quality.

> **Source C in v1.1 (new):** `--source-c .sql` is parsed via
> sqlglot. Each `CREATE TABLE` becomes an entity candidate; columns
> become attributes (PK columns demoted, FK columns route through
> the FK relationship instead); foreign keys emit relationship
> candidates with synthetic labels of the form
> `<src>__<col>__<ref>`; tables matching the code-table heuristic
> (e.g. `loan_status_lookup`) classify as vocabulary candidates
> instead of entities. Tables matching audit / timestamp / system
> patterns are routed to the new `audit` block. Mixed `.sql` +
> `.json` in one `--source-c` invocation is rejected.
>
> **Source D in v1.1 (changed behaviour):** `--source-d` is now an
> active participant in the candidate graph at the **survey** stage,
> not just at `draft`. The deterministic AST extractor walks the
> directory and emits entity candidates for classes / dataclasses /
> Pydantic models, attribute candidates for typed fields, vocabulary
> candidates for `Enum` subclasses, rule candidates for validation
> functions (`validate_*` / `check_*` / `assert_*`), and behaviour
> candidates for other methods — all at *survey* time. No LLM call
> involved.

✓ **Expected output:**

```text
Survey: N candidates, M relationships, X cross-source matches.
See domains/npl/discovery.
```

Concrete numbers vary with input. The shape of the output is
what matters here.

### C.2 Confirm the three discovery artifacts exist

```powershell
Get-ChildItem domains/npl/discovery
```

✓ **Expected:** `candidate-graph.json`, `candidate-provenance.json`,
`source-a.json`.

### C.3 Inspect the candidate graph

```powershell
@'
import json
from collections import Counter

g = json.load(open("domains/npl/discovery/candidate-graph.json"))
print(f"concepts:      {len(g['concepts'])}")
print(f"relationships: {len(g['relationships'])}")
print(f"audit:         {len(g.get('audit', []))}  (v1.1 — suppressed candidates)")
print()

# Per-source attestation counts (one concept can attest in multiple sources).
by_source = Counter()
for c in g["concepts"]:
    for src, present in c["source_presence"].items():
        if present:
            by_source[src] += 1
for src in "ABCD":
    print(f"Source {src}: {by_source[src]:>3} candidates attested")
print()

# Multi-axis attestation: A=docs, B=governance, C=schema, D=code.
two_axis = [c for c in g["concepts"]
            if sum(c["source_presence"].values()) >= 2]
strong = [c for c in g["concepts"] if c.get("strength") == "strong"]
print(f"multi-axis attested (>= 2 sources):    {len(two_axis)}")
print(f"strength=strong (boosted or default):  {len(strong)}")
print()
print("sample multi-axis-attested labels:",
      sorted({c["label"] for c in two_axis})[:10])
'@ | python
```

✓ **Expected (v1.1):**
- `concepts` is at least the union of A + B + C + D, with cross-source
  merges deduplicated by canonical (singularised) label.
- All four `Source A/B/C/D` lines show non-zero counts.
- `audit` is a non-zero number — Source C's `loan_audit` table
  (from the B.3 fixture) appears here along with any private
  classes / test files from Source D.
- `multi-axis attested` includes the concepts attested in at least
  2 of (semantic A/B, structural C, executable D). These are the
  highest-confidence concepts — the corroboration tier boost
  promotes them to `strong`. Expect `loan` and `borrower` here
  (attested in A + C + D from the fixtures).
- Sample labels are NPL business words (`Borrower`, `Loan`,
  `Forbearance`, `Collateral`, …), not `tmp_*` / `*_id`
  code-shaped names. Suppressed shapes appear in the `audit` block,
  not the main `concepts` list.

### C.4 (Optional) Inspect what got suppressed

```powershell
@'
import json
g = json.load(open("domains/npl/discovery/candidate-graph.json"))
for entry in g.get("audit", [])[:10]:
    print(f"- {entry['label']:<40} ({entry['source_type']})")
    print(f"    {entry['suppression_reason']}")
'@ | python
```

✓ **Expected:** each entry has a `label`, a `source_type`, and a
human-readable `suppression_reason` that names the rule which
filtered it. From the B.3 fixture you should see at minimum:

- `loan_audit  (C)` — *Default Source C suppression: table name
  matches pattern '\*_audit'.*
- `created_at  (C)` — *Default Source C suppression: column
  'created_at' matches a noise filter pattern.*

Plus any Source D suppressions (private classes, test files, etc.).
This is what the curator inspects to decide whether to bring
something back via a per-domain YAML override (see Part D.5 below).

---

## Part D — Draft the semantic layer

A single command scores the candidates, induces a profile (or
uses one you provide), fuses + validates + lints, and emits the
draft OWL ontology.

### D.1 Run draft

```powershell
ontozense draft `
  --domain-dir domains/npl `
  --source-b domains/npl/sources/governance.json `
  --source-c domains/npl/sources/npl-schema.sql `
  --source-d domains/npl/sources/npl-code `
  --output domains/npl/draft.owl
```

> The `--source-b` flag passes the same governance JSON to the
> fusion engine that survey used for the candidate-graph merge.
> The `--source-d` flag re-supplies the code directory to fusion;
> survey already extracted candidates from it at the candidate-graph
> stage (v1.1 change — see Part C.1), so fusion receives both the
> survey-derived candidates AND the raw code path for any
> deeper extraction the fusion engine performs.
> Source A is read automatically from
> `domains/npl/discovery/source-a.json`.

✓ **Expected console output:**

```text
Draft written to domains/npl/draft.owl
  Summary: domains/npl/draft-summary.md
Open in Ontology Playground or Protégé.
```

### D.2 Confirm the draft + summary exist

```powershell
Get-Item domains/npl/draft.owl
Get-Item domains/npl/draft-summary.md
Get-Item domains/npl/fused.json
```

✓ **Expected:** all three exist; `draft.owl` is non-empty.

### D.3 Confirm the draft loads as valid OWL

```powershell
@'
from rdflib import Graph, RDF, OWL
g = Graph()
g.parse("domains/npl/draft.owl", format="turtle")
classes = list(g.subjects(RDF.type, OWL.Class))
properties = list(g.subjects(RDF.type, OWL.ObjectProperty))
print(f"OWL classes:      {len(classes)}")
print(f"object properties: {len(properties)}")
print(f"total triples:    {len(g)}")
'@ | python
```

✓ **Expected:** at least a handful of classes, possibly some
object properties (depending on the Source A relationships).

### D.4 Read the draft summary

```powershell
Get-Content domains/npl/draft-summary.md
```

✓ **Expected:** a short markdown file with element counts,
validation findings, lint findings, and a "what the curator
should review first" list.

### D.5 (Optional, v1.1) Tune Source D classification with `source-d.yaml`

If the audit block in C.4 surfaced a class you actually *want* in
the candidate graph — or a Source D class you want to **demote** to
a vocabulary candidate — drop a `source-d.yaml` next to your
domain workspace:

```powershell
@'
source_d:
  # Bring tests back into the candidate graph (overrides default tests/** suppression)
  exclude_paths: []
  # Reclassify all *Status classes as vocabulary candidates (not entities)
  force_vocabulary:
    - "*Status"
  # Suppress factory classes (these are usually transport helpers, not domain entities)
  exclude_classes:
    - "*Factory"
'@ | Out-File -Encoding utf8 domains/npl/source-d.yaml
```

The same idea works for Source C via `source-c.yaml`
(`exclude_tables`, `include_tables`, `force_vocabulary`,
`force_entity`, `exclude_columns`). Both files live in the
domain workspace and are loaded automatically by `survey`.

Re-run survey and inspect the diff — the candidate graph should
reflect the overrides:

```powershell
ontozense survey `
  --source-a domains/npl/sources/source-a.json `
  --source-b domains/npl/sources/governance.json `
  --source-d domains/npl/sources/npl-code `
  --domain-dir domains/npl
```

✓ **Expected:** the new `candidate-graph.json` has the
overridden classifications; any forced-vocabulary classes now
have `"artifact_kind": "vocabulary"`; force-suppressed classes
move from `concepts` to `audit`.

For a deeper Source C example (with `.sql` DDL) and the full
default-suppression reference, see
[`docs/ontozense-npl-advanced.md`](./ontozense-npl-advanced.md)
Part E.

---

## Part E — Hand off to the curator

`draft.owl` is a standard OWL ontology. Open it in any OWL editor:

| Tool | Why use it |
|---|---|
| **[Ontology Playground](https://github.com/hzmarrou/ontology-playground)** | Browser-based, designed for review-and-edit workflows; reads OWL directly |
| **[Protégé](https://protege.stanford.edu)** *(desktop)* | The classic OWL editor; reasoning + plugins |
| **[WebProtégé](https://webprotege.stanford.edu)** | Browser-based collaborative editing for teams |

What the expert reviews:

- **Entities** — right concepts present? definitions accurate?
- **Relationships** — typed relations match domain logic?
- **Coverage** — what's missing? (Tycho catches ~60-70%;
  you fill the rest.)

The OWL preserves several layers of context for the curator:

- **Definitions** live in `rdfs:comment` on each class — the concept's
  human-readable description, drawn from whichever source contributed
  it during fusion.
- **Source citations** live in `dc:source` annotations — references
  back to where the concept came from (e.g. a Basel doc section,
  a governance record).
- **Full per-field provenance** (which source contributed which
  field, confidence scores, multi-source conflicts) stays in
  `domains/<name>/fused.json` rather than the OWL. Power users
  inspect that file; curators usually don't need to.

Tycho's working file `domains/npl/fused.json` carries data that
doesn't fit cleanly in OWL — confidence scores, multi-source
conflict logs, regex-extraction flags. Power users can inspect
it; curators usually don't need to.

---

## Final validation checklist

If every box ticks, both stages of the workflow are working on
NPL data:

- [ ] `pytest -q` reports `992 passed, 14 skipped` (Part A.6)
- [ ] `ontozense survey` writes three artifacts under
  `domains/npl/discovery/` (Part C.2)
- [ ] Multi-axis-attested concepts include real NPL terms,
  with `source_presence` set across A/B/C/D (Part C.3)
- [ ] `candidate-graph.json` has a non-empty `audit` array
  citing the rules that suppressed each filtered candidate
  (Part C.4) *(v1.1)*
- [ ] `ontozense draft` writes `draft.owl` and
  `draft-summary.md` (Part D.2)
- [ ] `draft.owl` parses as valid OWL/Turtle (Part D.3)
- [ ] The draft summary lists element counts, validation
  findings, and a curator-review list (Part D.4)
- [ ] *(Optional)* a `source-d.yaml` override behaves as
  expected on re-survey (Part D.5) *(v1.1)*

---

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| `ontozense: command not found` | venv not activated. `.\.venv\Scripts\Activate.ps1` |
| `survey` errors on `--source-a` | The path doesn't exist, or `extract-a` needs Azure keys and `.env` isn't configured. Use the pre-extracted JSON in B.3 instead. |
| `draft` errors with "No candidate-graph.json" | Run `survey` first. |
| `draft.owl` is empty or has zero classes | The candidate-graph is empty — check survey output; you may need richer source extraction. |
| `--format owl-xml` produces unexpected XML | That's RDF/XML serialisation; valid OWL but visually different from Turtle. |

---

## Reference

- **Architecture:** [`docs/superpowers/specs/2026-05-16-tycho-semantic-layer-redesign-design.md`](./superpowers/specs/2026-05-16-tycho-semantic-layer-redesign-design.md)
- **Power-user walkthrough:** [`docs/ontozense-npl-advanced.md`](./ontozense-npl-advanced.md)
- **Profile spec:** [`docs/PROFILE_SPEC.md`](./PROFILE_SPEC.md)
