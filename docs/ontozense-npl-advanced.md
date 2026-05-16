# Ontozense — NPL Power-User Walkthrough (every pipeline command in isolation)

This tutorial walks the underlying pipeline command-by-command —
`extract-a`, `discover`, `induce-profile`, `fuse`, `validate`,
`lint`, `report`. For the recommended two-command flow using the
new `survey` and `draft` orchestrators, see
[`docs/ontozense-npl-validation.md`](./ontozense-npl-validation.md).

Use this advanced version when you want to:

- Inspect each intermediate artifact between stages.
- Test specific edge cases (e.g. only Source B, or only Source A,
  or a hand-authored profile vs an induced one).
- Build CI pipelines that need fine-grained control over which
  stage runs when.

---

## Part A — Setup

### A.1 Prerequisites

You need:

- **Python 3.11, 3.12, or 3.13** (Ontozense is tested on 3.11–3.13).
  Check with `python --version`.
- **Git** (to clone the repo). Check with `git --version`.
- **PowerShell 7+** (on Windows). Check with `$PSVersionTable.PSVersion`.
- **[uv](https://github.com/astral-sh/uv)** — modern Python package
  manager. Install via `winget install --id=astral-sh.uv` or follow
  the [uv install docs](https://docs.astral.sh/uv/getting-started/installation/).
  Check with `uv --version`.
- **(Optional) Azure OpenAI access** — only needed if you want to
  run Source A extraction from scratch (Section C.1 Option A). The
  rest of the tutorial runs without it.

If any of the above are missing, install them first.

### A.2 Clone the repository

Pick a folder for your workspace and clone:

```powershell
cd C:\Users\$env:USERNAME\projects     # or wherever you keep code
git clone https://github.com/hzmarrou/tycho.git
cd tycho
```

✓ **Expected:** the clone completes without errors and you're now
inside the `tycho` folder. Verify:

```powershell
Get-ChildItem
# Expected: directories like docs/, src/, tests/, plus pyproject.toml, README.md
```

### A.3 Install Ontozense with `uv`

A single command creates an isolated `.venv`, installs Ontozense
in editable mode, and pulls every development dependency
(including `pytest`):

```powershell
uv sync
```

✓ **Expected:** `uv` reports something like
`Resolved N packages` → `Installed N packages`. A new `.venv\`
directory exists at the repo root.

> If you prefer `pip` over `uv`, the manual equivalent is:
> ```powershell
> python -m venv .venv
> .\.venv\Scripts\Activate.ps1
> pip install -e ".[dev]"
> ```
> The rest of the tutorial assumes you used `uv`.

### A.4 Activate the venv

```powershell
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks the activation script, run this once per
session and retry:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope Process
```

✓ **Expected:** your prompt now starts with `(ontozense)` (or
`(.venv)` depending on `uv`'s configuration) — the venv is active.

Verify the CLI is reachable and lists the discovery commands:

```powershell
ontozense --help
```

(No pipe — Rich-formatted output piped through `Select-Object`
can crash on legacy Windows consoles. Just scroll the output.)

✓ **Expected:** the help banner lists `discover`, `induce-profile`,
`rebuild`, `extract-a`, `fuse`, `validate`, `lint`, and `report`.

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

## Part B — Set up the NPL workspace

Ontozense uses a per-domain workspace folder at
`domains/<domain-name>/`. **The `domains/` directory is in
`.gitignore`** — your fresh clone has none of these files yet. In
this part you'll create the workspace and copy the NPL source
files into it.

### B.1 Where source files come from

These files **do** ship with the repo (committed). You'll copy
each one into your workspace:

| Source-of-truth path (committed) | Purpose |
|---|---|
| `tests/fixtures/npl-basel-guidelines.md` | Basel D403 NPL guidance (~1700 lines of regulatory text) — Source A document |
| `docs/governance_example.json` | 18 NPL governance terms (Borrower, Collateral, Loan, …) — Source B |
| `tests/fixtures/synthetic_npl_code/` | NPL business-rule code (classification, forbearance, materiality, reporting, transitions) — Source D |
| `docs/profile-examples/npl/` | Hand-authored canonical NPL profile (used as the Path 2 reference) — read in place, no copy needed |
| `tests/fixtures/nplo-reference.owl` | Open Risk NPLO reference ontology — used for cross-reference, no copy needed |

### B.2 Create the workspace folder

```powershell
New-Item -ItemType Directory -Path domains\npl\sources -Force | Out-Null
```

✓ **Expected:** the folder `domains\npl\sources\` now exists. Verify:

```powershell
Test-Path domains\npl\sources
# Expected: True
```

### B.3 Copy the source files into the workspace

```powershell
# Source A document
Copy-Item tests\fixtures\npl-basel-guidelines.md `
  domains\npl\sources\npl-basel-guidelines.md

# Source B governance JSON (renamed to a workspace-friendly name)
Copy-Item docs\governance_example.json `
  domains\npl\sources\governance.json

# Source D code directory (recursive)
Copy-Item -Recurse tests\fixtures\synthetic_npl_code `
  domains\npl\sources\npl-code
```

### B.4 Verify the workspace

```powershell
Get-ChildItem domains\npl\sources\
```

✓ **Expected:** three entries —

```text
governance.json
npl-basel-guidelines.md
npl-code  (directory)
```

And the Source D sub-areas:

```powershell
Get-ChildItem domains\npl\sources\npl-code\
```

✓ **Expected:** five subdirectories — `classification`,
`forbearance`, `materiality`, `reporting`, `transitions`.

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
ontozense extract-a domains/npl/sources/npl-basel-guidelines.md `
  --json domains/npl/sources/source-a.json `
  --domain-dir domains/npl
```

(Uses the copy you placed in the workspace in Section B.3.)

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

> **Note on Source D:** the `discover` command also accepts
> `--source-c` and `--source-d` flags, but the candidate-graph
> builder doesn't extract from those payloads in the current
> implementation. Source D's code-extractor runs in the
> profile-aware pipeline (Section D.1's `fuse`), so we'll bring it
> in there. For this discovery step, just feed Source A + B.

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

This is where **Source D enters the picture.** `fuse` accepts a
`--source-d <directory>` pointing at a tree of Python / SQL files;
the code-extractor walks it via AST analysis and contributes the
discovered identifiers, type hints, and business-rule comments
into the fused dictionary.

```powershell
ontozense fuse `
  --source-a domains/npl/sources/source-a.json `
  --source-b domains/npl/sources/governance.json `
  --source-d domains/npl/sources/npl-code `
  --output domains/npl/fused.json `
  --domain-dir domains/npl
```

✓ **Expected:** a fused dictionary at `domains/npl/fused.json`
containing elements from all three sources, each carrying
per-field provenance. The fuse command prints a summary; look for
non-zero counts on the "Source A" and "Source D" lines (Source B
contributions are merged into existing elements rather than
adding new ones, so its summary may show 0 *new* elements while
still enriching the others).

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
| `uv sync` or `pip install` fails on a dependency | Make sure you're on Python 3.11, 3.12, or 3.13. Older versions are not supported. |
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
