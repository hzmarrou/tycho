# Ontozense — NPL Validation Tutorial (for new users)

This tutorial takes you from a blank machine to a fully-validated
Ontozense install on real NPL (Non-Performing Loans) data. By the
end you'll have:

1. Cloned the repository and installed the CLI.
2. Run the test suite to confirm the install is healthy.
3. Built a candidate-concept graph from real NPL inputs using the
   new **discovery workflow** (Path 1).
4. Scored the candidates and emitted a draft profile automatically.
5. Run the **profile-aware pipeline** (Path 2) on the same data
   against a hand-authored reference profile.
6. Confirmed both paths converge on the same core business
   concepts.

Each step has a `✓ Expected:` checkpoint so you can verify the run
is healthy before moving on.

> **Who this is for:** anyone with basic Python and command-line
> familiarity. No prior knowledge of Ontozense, ontologies, or
> NPL is assumed. The shell snippets below are written for
> **PowerShell 7+** on Windows; if you're on macOS / Linux the
> commands are nearly identical (swap `` ` `` line continuations
> for `\` and `Select-Object` / `Select-String` for `head` /
> `grep`).

## What you'll be working with

**Ontozense** auto-generates rich data dictionaries and domain
ontologies from four complementary sources:

- **Source A** — authoritative documents (regulations, guidance)
- **Source B** — governance JSON (curated business terms)
- **Source C** — database schemas
- **Source D** — production code

It supports two workflows:

- **Path 1 — Discovery:** start from raw sources, *induce* a draft
  profile (entity types, vocabulary) automatically. Best when you
  don't yet have a profile.
- **Path 2 — Profile-aware:** start from a human-authored profile,
  use it to constrain extraction. Best when you have a curated
  ontology to work with.

The NPL (Non-Performing Loans) domain ships with sample data
covering both paths, so you can validate both ends in one sitting.

---

## Part A — Setup

### A.1 Prerequisites

You need:

- **Python 3.11 or 3.12** (Ontozense is tested on these).
  Check with `python --version`.
- **Git** (to clone the repo). Check with `git --version`.
- **PowerShell 7+** (on Windows). Check with `$PSVersionTable.PSVersion`.
- **(Optional) Azure OpenAI access** — only needed if you want to
  run Source A extraction from scratch. If you have an existing
  `source-a.json` (Section B.4 Option B), you can skip this.

If any of the above are missing, install them first.

### A.2 Clone the repository

Pick a folder for your workspace and clone:

```powershell
cd C:\Users\$env:USERNAME\projects     # or wherever you keep code
git clone https://github.com/hzmarrou/tycho.git ontozense
cd ontozense
```

✓ **Expected:** the clone completes without errors and you're now
inside the `ontozense` folder. Verify:

```powershell
Get-ChildItem | Select-Object -First 10
# Expected: directories like docs/, src/, tests/, plus pyproject.toml, README.md
```

### A.3 Create a Python virtual environment

A venv keeps Ontozense's dependencies isolated from any other
Python projects on your machine.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks the activation script, run this once per
session and retry:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope Process
```

✓ **Expected:** your prompt now starts with `(.venv)`, indicating
the venv is active.

### A.4 Install Ontozense

```powershell
pip install -e ".[dev]"
```

This installs Ontozense in editable mode plus the development
dependencies (including `pytest`).

✓ **Expected:** the install completes without errors and the
`ontozense` command is available:

```powershell
ontozense --help | Select-Object -First 5
```

The help banner should list commands including `discover`,
`induce-profile`, `rebuild`, `extract-a`, `fuse`, `validate`,
`lint`, and `report`.

### A.5 (Optional) Configure Azure OpenAI

Source A extraction calls an LLM. If you have Azure OpenAI access,
create a `.env` file in the repo root:

```env
AZURE_API_KEY=your-azure-openai-key
AZURE_API_BASE=https://your-resource.openai.azure.com
AZURE_API_VERSION=2024-12-01-preview
OPENAI_API_KEY=your-azure-openai-key
```

If you don't have keys, that's fine — skip Section B.4 Option A
and reuse a pre-extracted `source-a.json` (Option B).

### A.6 Run the test suite

This confirms the install is fundamentally healthy.

```powershell
pytest -q
```

✓ **Expected:** `834 passed, 14 skipped` (or higher, if commits
have landed since this tutorial was written). Zero failures.

If you see failures here, **stop**. Don't continue with NPL
validation until the regression suite is clean.

---

## Part B — Tour the NPL inputs

Before running anything, take 60 seconds to look at what you'll
be feeding in. All NPL inputs ship with the repo:

| File | What it is | Fed into |
|---|---|---|
| `tests/fixtures/npl-basel-guidelines.md` | Basel D403 NPL guidance (1700+ lines of regulatory text) | Source A (Path 1 + Path 2) |
| `domains/npl/sources/governance.json` | 18 NPL governance terms — Borrower, Collateral, Loan, etc. | Source B (Path 1 + Path 2) |
| `tests/fixtures/synthetic_npl_code/` | Sample NPL business-rule code (classification, forbearance, …) | Source D |
| `docs/profile-examples/npl/` | A hand-authored canonical NPL profile (7 entity types, 12 subtypes) | Path 2 reference profile |
| `tests/fixtures/nplo-reference.owl` | Open Risk NPLO reference ontology (OWL) | Cross-reference for comparison |

Confirm the NPL workspace is in place:

```powershell
Get-ChildItem domains\npl\sources\
# Expected: governance.json
```

---

## Part C — Path 1: Discovery workflow

In this path, Ontozense reads raw NPL sources and *induces* a
draft profile automatically. You'll end up with a `schema.json`,
an `induction_report.json`, and supporting files — a starting
point for human review.

### C.1 Build Source A (extract or reuse)

Source A extraction is the only LLM-driven step. There are two
ways to get a Source A JSON:

**Option A — fresh extraction (needs Azure OpenAI key, ~30-60s):**

```powershell
ontozense extract-a tests/fixtures/npl-basel-guidelines.md `
  --json domains/npl/sources/source-a.json `
  --domain-dir domains/npl
```

**Option B — reuse a pre-extracted Source A (no keys needed):**

If `domains/npl/sources/source-a.json` already exists (e.g. you
ran a fresh extraction earlier or someone else's lives in the
workspace), just continue to C.2 — the rest of the discovery
workflow is fully deterministic given a fixed Source A.

✓ **Expected (either option):** the JSON file exists and contains
`concepts` and `relationships` arrays:

```powershell
@'
import json
d = json.load(open("domains/npl/sources/source-a.json"))
print(f"concepts={len(d['concepts'])} relationships={len(d['relationships'])}")
'@ | python
```

✓ **Expected:** roughly `concepts=40-80, relationships=20-50`.
The exact numbers vary by ±20% because Source A is LLM-based.

### C.2 Build the candidate graph

```powershell
ontozense discover `
  --source-a domains/npl/sources/source-a.json `
  --source-b domains/npl/sources/governance.json `
  --domain-dir domains/npl
```

✓ **Expected output:**

```text
Discovery artifacts written to domains/npl/discovery
```

Three files are created:

```powershell
Get-ChildItem domains\npl\discovery\
# Expected: candidate-graph.json  candidate-provenance.json  concept-mappings.json
```

### C.3 Inspect the candidate graph

This tells you whether the sources merged sensibly:

```powershell
@'
import json
g = json.load(open("domains/npl/discovery/candidate-graph.json"))
print(f"concepts: {len(g['concepts'])}")
print(f"relationships: {len(g['relationships'])}")
both = [c for c in g["concepts"]
        if c["source_presence"]["A"] and c["source_presence"]["B"]]
print(f"concepts in BOTH Source A and Source B: {len(both)}")
print("sample cross-source labels:", sorted({c["label"] for c in both})[:10])
'@ | python
```

✓ **Expected:**

- `concepts`: more than Source A's count alone (Source B's 18
  governance records have been merged in).
- `relationships`: same count as Source A's relationships (Source
  B doesn't carry edges).
- `concepts in BOTH Source A and Source B`: typically 5-12 of the
  governance terms also appear in the Basel document — usually
  `Borrower`, `Collateral`, `Loan`, etc.
- The sample labels are NPL-domain words (Borrower, Loan,
  Collateral) — **not** code-shaped names like `tmp_*` or `*_id`.

### C.4 Confirm every candidate is traceable

A core invariant: every candidate must have a non-empty
`provenance` entry, so a reviewer can trace any candidate back
to the source row it came from.

```powershell
@'
import json
g = json.load(open("domains/npl/discovery/candidate-graph.json"))
p = json.load(open("domains/npl/discovery/candidate-provenance.json"))
graph_ids = {c["candidate_id"] for c in g["concepts"]}
prov_ids = {e["candidate_id"] for e in p["concepts"]}
print("graph == provenance ids:", graph_ids == prov_ids)
empty = [e for e in p["concepts"] if not e["provenance"]]
print("concepts with empty provenance:", len(empty))
'@ | python
```

✓ **Expected:**

```text
graph == provenance ids: True
concepts with empty provenance: 0
```

### C.5 Score candidates and emit the induced profile

The scoring stage classifies each candidate as `core_business`,
`supporting_technical`, or `noise`. The selected ones form the
induced profile's entity-type subtypes.

```powershell
ontozense induce-profile `
  domains/npl/discovery/candidate-graph.json `
  --domain-name npl `
  --output-dir domains/npl/induced-profile
```

✓ **Expected output:**

```text
Induced profile written to domains/npl/induced-profile
  Candidates: N total — core_business=X, supporting_technical=Y, rejected=Z
  Top selected (by score):
    - <label> (score=0.XXX, classification=core_business)
    ...
```

Where:
- `N` ≈ the candidate-graph count from C.3
- `X` (core_business) is typically 5-15 for NPL — these are the
  high-confidence business concepts
- `Y` (supporting_technical) is usually a smaller number
- `X + Y + Z == N` exactly (every candidate is accounted for)

### C.6 Verify the induced profile is loadable

The profile must round-trip through Ontozense's profile loader
without errors. This is the hard correctness check.

```powershell
@'
from ontozense.core.profile import load_profile
p = load_profile("domains/npl/induced-profile")
print("profile_name:", p.profile_name)
print("top-level entity types:", list(p.entity_types.keys()))
for name, et in p.entity_types.items():
    head = et.subtypes[:8]
    tail = "..." if len(et.subtypes) > 8 else ""
    print(f"  {name} subtypes ({len(et.subtypes)}):", head, tail)
'@ | python
```

✓ **Expected:**

```text
profile_name: npl
top-level entity types: ['Concept', 'TechnicalArtifact']    # or just ['Concept'] if no supporting band
  Concept subtypes (N): ['Borrower', 'Collateral', 'Loan', ...]
  TechnicalArtifact subtypes (M): [...]
```

If this raises `ProfileError`, the induced schema is malformed —
**stop** and file an issue against the repository.

### C.7 Compare induced vs canonical NPL profile

The canonical profile (`docs/profile-examples/npl/`) was authored
by hand from the Open Risk NPLO ontology. Comparing it to the
induced profile tells you whether Ontozense found the concepts
a human expert would.

```powershell
@'
from ontozense.core.profile import load_profile

canonical = load_profile("docs/profile-examples/npl")
induced = load_profile("domains/npl/induced-profile")

canonical_labels = set()
for et in canonical.entity_types.values():
    canonical_labels.add(et.name.lower())
    canonical_labels.update(s.lower() for s in et.subtypes)

induced_labels = set()
for et in induced.entity_types.values():
    induced_labels.update(s.lower() for s in et.subtypes)

overlap = canonical_labels & induced_labels
print(f"canonical type/subtype count: {len(canonical_labels)}")
print(f"induced subtype count:        {len(induced_labels)}")
print(f"overlap on lowercased label:  {len(overlap)}")
print(f"sample overlap: {sorted(overlap)[:10]}")
'@ | python
```

✓ **Expected:** the overlap typically includes core NPL concepts
like `borrower`, `loan`, `collateral`, possibly
`corporateborrower`, `forbearance`. Don't expect a full match —
the canonical profile has more hand-authored subtypes than the
LLM extraction surfaces. But if the overlap is **zero or near
zero**, something has gone wrong upstream (Source A extraction
failed, alias resolution didn't fire, etc.).

### C.8 Inspect the induction report

The induction report is the audit trail. A human reviewer would
read it before approving the induced profile.

```powershell
@'
import json
r = json.load(open("domains/npl/induced-profile/induction_report.json"))
print("domain:", r["domain_name"])
print("counts:", {k: r[k] for k in [
    "candidate_count",
    "selected_core_count",
    "selected_supporting_count",
    "rejected_count",
]})
print("weights:", r["scoring_weights"])
print("thresholds:", r["scoring_thresholds"])
print("top 5 selected:")
for c in r["top_candidates"][:5]:
    print(f"  - {c['label']} (score={c['score']:.3f}, {c['classification']})")
print("review notes:", r["review_notes"][:3])
'@ | python
```

✓ **Expected:**

- `weights` is a dict of 7 signal names (authoritative_frequency,
  governance_presence, etc.) summing to 1.0.
- `thresholds` is `{"core_business": 0.7, "supporting_technical": 0.4}`.
- `top 5 selected` lists NPL business concepts with scores ≥ 0.40.
- `review_notes` is typically empty (or contains audit
  explanations for any dropped candidates).

### C.9 Print the rebuild plan

`rebuild` doesn't actually run the rebuild pipeline — it prints
the chain of commands you'd run by hand to use the induced
profile in production.

```powershell
ontozense rebuild `
  --profile domains/npl/induced-profile `
  --domain-dir domains/npl
```

✓ **Expected output:** a numbered plan listing `extract-a`,
`fuse`, `validate`, `lint`, `report` in order, each with the
exact flags that command accepts, plus a closing note that the
chain must be run manually.

You don't need to run the commands listed here — Part D below
runs the same chain against the canonical profile so you can
compare.

---

## Part D — Path 2: Profile-aware pipeline

Now run the existing profile-aware pipeline against the
hand-authored canonical NPL profile. This confirms the
pre-existing functionality still works alongside the new
discovery workflow.

### D.1 Fuse with the canonical profile

```powershell
ontozense fuse `
  --source-a domains/npl/sources/source-a.json `
  --source-b domains/npl/sources/governance.json `
  --output domains/npl/fused.json `
  --domain-dir domains/npl
```

✓ **Expected:** a fused dictionary at `domains/npl/fused.json`
containing concepts and relationships, each carrying per-field
provenance.

### D.2 Validate against the canonical profile

```powershell
ontozense validate domains/npl/fused.json `
  --profile docs/profile-examples/npl `
  --domain-dir domains/npl
```

✓ **Expected:** validation completes and prints a structured
report. Some findings are normal (governance terms that don't
appear in the canonical schema, etc.) — what matters is that the
command runs cleanly without errors.

### D.3 Lint

```powershell
ontozense lint domains/npl/fused.json `
  --domain-dir domains/npl
```

✓ **Expected:** lint runs and reports any contradictions, orphan
terms, undefined-but-used elements, coverage gaps, and
structural holes. NPL inputs typically produce a handful of
structural-gap findings.

### D.4 Report

```powershell
ontozense report domains/npl/fused.json `
  --profile docs/profile-examples/npl `
  --markdown domains/npl/report.md
```

✓ **Expected:** `domains/npl/report.md` exists and includes six
benchmark sections — element counts, confidence, conflicts,
anchors, corroboration, and profile coverage.

---

## Part E — Side-by-side comparison

Open both profiles side by side for a final visual check:

```powershell
Get-Content docs/profile-examples/npl/schema.json | python -m json.tool | Select-Object -First 30
Get-Content domains/npl/induced-profile/schema.json | python -m json.tool | Select-Object -First 30
```

✓ **Expected:**

- Both load as valid JSON.
- Both have `profile_name`, `profile_version`, `entity_types`,
  `predicates`, `id_format`, `alias_map`, `canonical_verbs`.
- The canonical profile has rich subtypes per type (`Borrower`,
  `CorporateBorrower`, `IndividualBorrower`, …).
- The induced profile groups discovered candidates under
  `Concept` and `TechnicalArtifact`.

---

## Final validation checklist

Tick each item to confirm Ontozense is working end-to-end on NPL
data:

- [ ] `pytest -q` reports `834 passed, 14 skipped` (Section A.6)
- [ ] `ontozense discover` writes three artifacts under
  `domains/npl/discovery/` (Section C.2)
- [ ] Every concept in `candidate-graph.json` has a non-empty
  provenance entry (Section C.4)
- [ ] `ontozense induce-profile` reports a console summary with
  `core_business + supporting_technical + rejected ==
  candidate_count` (Section C.5)
- [ ] `load_profile('domains/npl/induced-profile')` returns a
  `Profile` with `profile_name == 'npl'` and `'Concept'` in its
  entity types (Section C.6)
- [ ] Induced and canonical profiles share several core NPL
  labels (e.g. `borrower`, `loan`, `collateral`) (Section C.7)
- [ ] `induction_report.json` records `scoring_weights` and
  `scoring_thresholds` verbatim (Section C.8)
- [ ] `ontozense rebuild` prints a numbered plan referencing
  `extract-a`, `fuse`, `validate`, `lint`, `report` (Section C.9)
- [ ] `ontozense fuse` writes `domains/npl/fused.json` against
  the canonical profile (Section D.1)
- [ ] `ontozense validate` runs without errors (Section D.2)
- [ ] `ontozense lint` runs and reports structural findings
  (Section D.3)
- [ ] `ontozense report` writes a markdown benchmark to
  `domains/npl/report.md` (Section D.4)

If every box is ticked, both the discovery workflow and the
profile-aware pipeline are working correctly on NPL data.

---

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| `ontozense: command not found` | The venv isn't activated. Run `.\.venv\Scripts\Activate.ps1` from the repo root. |
| `Set-ExecutionPolicy` error when activating venv | Once per session: `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope Process`, then retry. |
| `pip install` fails on a dependency | Make sure you're on Python 3.11 or 3.12. Older versions are not supported. |
| `discover` exits 2 with "invalid JSON" | Bad input file. Re-run `extract-a` or fix the governance JSON. |
| `induce-profile` exits 2 with "concept entry [N] is malformed" | The candidate-graph.json has a malformed concept entry. Check that index in the file. |
| `load_profile('induced-profile')` raises `ProfileError` | The induced schema is malformed. File an issue against the repository. |
| `discover --profile ...` doesn't change the candidate count | Either the profile's `alias_map` is empty, or no source label matches an alias key. Inspect `docs/profile-examples/npl/alias_map.json`. |
| `induce-profile` reports `selected_core_count == 0` | Scoring thresholds are too tight, or the source extraction didn't surface high-evidence concepts. Try `--thresholds` with a relaxed `core_business` cut-off (e.g. `0.50`). |
| Source A extraction times out | Azure OpenAI rate limit or model quota. Reuse a pre-extracted `source-a.json` (Section C.1 Option B). |
| Here-string runs but Python errors on quoting | Make sure the here-string opens with `@'` and closes with `'@`, each on its own line with the closing token at column 0. Single-quoted here-strings preserve the literal Python code; double-quoted (`@"..."@`) would interpolate `$variables`. |

---

## Reference

If you want to go deeper after the validation pass:

- **Narrative tutorial** (Path 2 only, slower walkthrough):
  [`docs/ontozense-npl-tutorial.md`](./ontozense-npl-tutorial.md)
- **Architecture (discovery workflow):**
  [`docs/PROFILE_INDUCTION_ARCHITECTURE.md`](./PROFILE_INDUCTION_ARCHITECTURE.md)
- **Implementation plan (discovery workflow):**
  [`docs/PROFILE_INDUCTION_IMPLEMENTATION_PLAN.md`](./PROFILE_INDUCTION_IMPLEMENTATION_PLAN.md)
- **Profile specification:**
  [`docs/PROFILE_SPEC.md`](./PROFILE_SPEC.md)
- **Repository main page:** the project's `README.md`
