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

### B.3 *(Skip-the-LLM shortcut)* — provide a pre-extracted Source A

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

If you have Azure OpenAI keys in `.env`, skip B.3 and let
`survey` extract from the markdown directly.

---

## Part C — Survey the NPL sources

A single command extracts (or reuses) Source A, merges in Source
B governance, **and (new in v1.1) parses Source D Python code into
first-class candidates** — all into one candidate graph for
inspection.

### C.1 Run survey (A + B + D)

```powershell
ontozense survey `
  --source-a domains/npl/sources/source-a.json `
  --source-b domains/npl/sources/governance.json `
  --source-d domains/npl/sources/npl-code `
  --domain-dir domains/npl
```

(If you skipped B.3 and have Azure OpenAI configured, replace
`--source-a domains/npl/sources/source-a.json` with
`--source-a domains/npl/sources/npl-basel-guidelines.md` to run
fresh LLM extraction.)

> **Source D in v1.1 (changed behaviour):** `--source-d` is now an
> active participant in the candidate graph at the **survey** stage,
> not just at `draft`. The deterministic AST extractor walks the
> directory and emits entity candidates for classes / dataclasses /
> Pydantic models, attribute candidates for typed fields, vocabulary
> candidates for `Enum` subclasses, rule candidates for validation
> functions (`validate_*` / `check_*` / `assert_*`), and behaviour
> candidates for other methods — all at *survey* time. No LLM call
> involved.
>
> **Source C (SQL DDL):** also accepted (`--source-c file.sql`),
> with the same first-class treatment as Source D. The bundled NPL
> fixture doesn't ship a `CREATE TABLE` schema, so this tutorial
> omits Source C. See
> [`docs/ontozense-npl-advanced.md`](./ontozense-npl-advanced.md)
> Part E for a worked Source C example.

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
g = json.load(open("domains/npl/discovery/candidate-graph.json"))
print(f"concepts:      {len(g['concepts'])}")
print(f"relationships: {len(g['relationships'])}")
print(f"audit:         {len(g.get('audit', []))}  (v1.1 — suppressed candidates)")
print()

# Multi-axis attestation: A=docs, B=governance, C=schema, D=code.
two_axis = [c for c in g["concepts"]
            if sum(c["source_presence"].values()) >= 2]
strong = [c for c in g["concepts"] if c.get("strength") == "strong"]
print(f"multi-axis attested (>= 2 sources):  {len(two_axis)}")
print(f"strength=strong (boosted or default): {len(strong)}")
print()
print("sample multi-axis-attested labels:",
      sorted({c["label"] for c in two_axis})[:10])
'@ | python
```

✓ **Expected (v1.1):**
- `concepts` is at least the union of A + B + D, with cross-source
  merges deduplicated by canonical (singularised) label.
- `audit` is a non-zero number when Source D contains suppressed
  items (private classes prefixed `_`, classes in `tests/` etc.).
- `multi-axis attested` includes the concepts attested in at least
  2 of (semantic A/B, structural C, executable D). These are the
  highest-confidence concepts — the corroboration tier boost
  promotes them to `strong`.
- Sample labels are NPL business words (`Borrower`, `Loan`,
  `Forbearance`, `Collateral`, …), not `tmp_*` / `*_id`
  code-shaped names. Suppressed shapes appear in the `audit` block,
  not the main `concepts` list.

### C.4 (Optional) Inspect what got suppressed

```powershell
@'
import json
g = json.load(open("domains/npl/discovery/candidate-graph.json"))
for entry in g.get("audit", [])[:5]:
    print(f"- {entry['label']}  ({entry['source_type']})")
    print(f"    {entry['suppression_reason']}")
'@ | python
```

✓ **Expected:** each entry has a `label`, a `source_type`, and a
human-readable `suppression_reason` that names the rule which
filtered it (e.g. *"Default Source D suppression: path matches
pattern 'tests/**'"*). This is what the curator inspects to decide
whether to bring something back via a per-domain YAML override
(see Part D.5 below).

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
  with `source_presence` set across A/B/D (Part C.3)
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
