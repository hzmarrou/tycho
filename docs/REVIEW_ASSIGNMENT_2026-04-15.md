# Independent Review Assignment — Ontozense (2026-04-15)

## Before we hand this off to an external tester

You are reviewing **Ontozense**, a Python package located at
`C:\Users\hzmarrou\OneDrive\python\projects\ontozense`. The pipeline
has reached feature-complete status and we are about to hand it to an
external tester to run on a real-world domain (not NPL). Before that
handoff, we want an independent review.

This review has a narrower scope than a general code review. Your goal
is to answer: **is this actually usable by a third-party tester who
has never seen the code?** Specifically:

1. Does the CLI work end-to-end on the shipped fixtures without
   surprises?
2. Is the documentation (README, tutorial, PLAYBOOK) accurate and
   sufficient for a new user to follow?
3. Are the failure modes honest — does the system tell the user what
   went wrong, or does it silently succeed with bad output?
4. Are there cliff-edges (undocumented assumptions, missing validation,
   path issues) that will trip up the tester?

This is NOT a methodology review. The four-source architecture, the
SPIRES bypass, the AI-RBX deterministic-first pipeline, the confidence
rubric — all of these were reviewed in the previous round
(`docs/REVIEW_2026-04-10.md`). The findings from that review were all
addressed. You do not need to re-review those decisions.

---

## 1. What Ontozense is (short version)

Ontozense auto-generates **rich data dictionaries** from four
complementary sources:

- **Source A** — authoritative domain documents (LLM-powered extraction)
- **Source B** — governance reference (JSON, deterministic)
- **Source C** — database schemas (PostgreSQL or Django, deterministic)
- **Source D** — production code (Python AST + SQL via sqlglot,
  deterministic)

A **router** dispatches files to the right extractor. A **fusion
layer** combines the source outputs with conflict resolution and
per-field provenance. A **lint layer** runs consistency checks
including **structural gap analysis** on the concept graph. A
**bridging module** asks an LLM to suggest bridging concepts for
disconnected clusters. A **query + file-back** pair completes the
Karpathy feedback loop.

Read `docs/PLAYBOOK.md` (the negotiated convention layer) and
`docs/why_the_playbook.md` before the code. The architecture makes
much more sense in that order.

---

## 2. What was added since the last review (2026-04-10)

The previous review covered Steps 1–5 and scaffolds. Since then we
have implemented **Step 4 (real)**, **Step 6**, **Step 7**, **Step 8**,
and **two InfraNodus-inspired enhancements**. The commit trail:

```
24b4b42  feat(source-b): implement governance extractor as JSON reference reader
542a8a3  feat(fusion): four-source fusion layer + CLI command (Step 6)
12c2ca9  feat(lint): consistency checks on fused knowledge base (Step 7)
f5e5858  feat(query,file-back): element lookup + derived artifact filing (Step 8)
2b3f6d9  feat(lint): graph-based structural gap analysis via networkx
2f11913  feat(bridging): LLM-suggested concepts for structural gaps  ← HEAD
```

Your review covers this commit range. Everything before `24b4b42` was
already reviewed.

### The six commits in more detail

**`24b4b42` — Source B real implementation**
- The previous review flagged Source B as a TBD scaffold. We reworked
  it from scratch based on user feedback that the rigid "canonical
  14-column CSV" design was a non-starter.
- New design: a simple JSON file (single object or array) with
  `element_name` (required) plus optional `domain_name`, `definition`,
  `is_critical`, `citation`. Any extra fields are preserved in
  `extra_fields`.
- Source B's role is **validation**, not heavy extraction — the fusion
  layer uses it to confirm Source A concepts exist in the governance
  system.
- Files: `src/ontozense/extractors/governance_extractor.py`,
  `docs/CANONICAL_GOVERNANCE_FORMAT.md` (rewritten),
  `docs/governance_example.json` (18-entry demo file derived from
  OpenNPL ontology), `tests/test_governance_extractor.py` (16 tests).

**`542a8a3` — Fusion layer (Step 6)**
- `src/ontozense/core/fusion.py` (~320 lines) — `FusedElement`,
  `FusionResult`, `FusionEngine`, name normalisation.
- 4-pass pipeline: seed from A → validate with B → enrich with C →
  attach rules from D.
- Matching: normalised string (lowercase, underscores/hyphens →
  spaces, collapsed whitespace). Exact match only; no fuzzy/LLM
  matching yet (documented in PLAYBOOK §13).
- Conflict resolution per PLAYBOOK §4: priority (A>B>C>D default) →
  confidence → recency. Rejected values preserved in
  `merge_conflicts`. Citations are additive (both sources contribute
  complementary references), not competitive.
- `ontozense fuse` CLI command.
- 37 tests in `tests/test_fusion.py`.

**`12c2ca9` — Lint (Step 7)**
- `src/ontozense/core/lint.py` — 4 of 6 PLAYBOOK §9 checks implemented:
  contradictions, orphans, undefined-but-used, coverage gaps.
- Deferred: stale claims (needs persistent state), missing
  cross-references (needs domain semantics).
- `ontozense lint` CLI command.
- 18 tests in `tests/test_lint.py`.

**`f5e5858` — Query + file-back (Step 8)**
- `src/ontozense/core/query.py` — element lookup (exact,
  case-insensitive) and substring search. Rich markdown output.
- `src/ontozense/core/fileback.py` — saves derived artifacts to
  `<domain>/derived/<category>/` with deduplication.
- `ontozense query` and `ontozense file-back` CLI commands.
- Auto file-back when `query --output` + `--domain-dir` both provided.
- 17 tests in `tests/test_query_fileback.py`.
- Also refactored `_reconstruct_fusion_result()` as a shared helper
  reused by both lint and query commands.

**`2b3f6d9` — Structural gap analysis**
- Inspired by the InfraNodus/Karpathy "LLM Wiki" extension: use
  network science to find topological holes the surface-level lint
  checks miss.
- `src/ontozense/core/lint.py` — added `_build_concept_graph()`
  (networkx), `_find_structural_holes()`, `_check_structural_gaps()`.
- Uses `greedy_modularity_communities` (deterministic) for community
  detection and `betweenness_centrality` for bridge concepts.
- `pyproject.toml`: added `networkx>=3.2`.
- 6 tests in `tests/test_structural_gaps.py`.

**`2f11913` — LLM-suggested bridging**
- `src/ontozense/core/bridging.py` — when lint finds structural gaps,
  the LLM suggests bridging concepts via a targeted prompt per gap.
- Uses `litellm.completion()` directly (not OntoGPT subprocess — this
  is a simple completion, not structured extraction).
- Domain-neutral prompt template (verified by domain-neutrality
  regression test).
- Output is file-back-ready markdown, closing the Karpathy feedback
  loop: Lint → LLM bridges → Expert review → File-back.
- `ontozense suggest-bridges` CLI command.
- `pyproject.toml`: added `litellm>=1.40`.
- 9 tests in `tests/test_bridging.py` (with mocked LLM).

---

## 3. Current state by the numbers

| Metric | Value |
|---|---|
| Total source lines (`src/ontozense/`) | 7,594 across 24 Python files + 2 LinkML templates |
| Total test lines (`tests/`) | 5,104 across 17 test files |
| Test count | **354 passing** (0 failing, 0 skipped) |
| Git state | `master` at `2f11913`, clean working tree, no outstanding branches |
| CLI commands | 7 domain commands (`extract-a`, `ingest`, `fuse`, `lint`, `suggest-bridges`, `query`, `file-back`) + 6 legacy ontology commands (`extract`, `convert`, `refine`, `export`, `diff`, `info`) |

---

## 4. The end-to-end flow the tester will run

This is the tutorial we've written for them at
`docs/ontozense-npl-tutorial.md` (sibling repo) and
`docs/CANONICAL_GOVERNANCE_FORMAT.md` (this repo). **Follow the
tutorial yourself as part of the review** — if you can't run it
cleanly, the tester won't either.

Shipped fixtures under `tests/fixtures/`:
- `npl-basel-guidelines.md` (136 KB) — real Basel D403 regulatory
  document
- `synthetic_npl_code/` — 5 files of synthetic Python and SQL
  implementing Basel D403 rules
- `docs/governance_example.json` — 18-entry governance reference file

The complete flow:

```bash
# 0. Setup (needs Azure OpenAI key for Source A only)
pip install -e ".[dev]"
# Edit .env with AZURE_API_KEY, AZURE_API_BASE, AZURE_API_VERSION

# 1. Route preview
ontozense ingest tests/fixtures/npl-basel-guidelines.md --dry-run

# 2. Extract from domain document (LLM call)
ontozense extract-a tests/fixtures/npl-basel-guidelines.md \
  --json output/basel.json

# 3. Fuse with governance + code
ontozense fuse \
  --source-a output/basel.json \
  --source-b docs/governance_example.json \
  --source-d tests/fixtures/synthetic_npl_code \
  --output output/fused.json

# 4. Lint (includes structural gap analysis, no LLM)
ontozense lint output/fused.json

# 5. Bridge suggestions (LLM)
ontozense suggest-bridges output/fused.json --output output/bridges.md

# 6. Query
ontozense query "Default" --fused output/fused.json

# 7. File-back
ontozense file-back output/bridges.md --domain-dir output/npl-domain
```

---

## 5. What I specifically want you to evaluate

### 5.1 Can a new user actually run this?

- **Install** — does `pip install -e ".[dev]"` in a fresh venv succeed
  on the first try? All dependencies resolve?
- **.env** — is `.env.example` provided? Do the error messages when
  credentials are missing actually tell the user what to set?
- **First-run paths** — does `extract-a` work on the shipped fixture
  without any prerequisite setup the tutorial doesn't mention?
- **Path separators** — the project is developed on Windows. Does
  anything assume backslashes in ways that would break on Linux/macOS?
- **Python version** — `pyproject.toml` says `requires-python =
  ">=3.10"`. Does the code actually run on 3.10 cleanly, or does it
  use 3.11+ syntax somewhere?

### 5.2 Is the CLI UX honest?

- **Error messages** — are they specific and actionable, or are they
  generic "extraction failed"?
- **Exit codes** — per PLAYBOOK §8: exit 2 for zero output, exit 3 for
  all-low-confidence. Verify these actually fire with intentionally
  bad inputs (empty document, off-topic document, missing API key).
- **`--help` output** — is it accurate, or do some options reference
  features that changed?
- **Progress feedback** — for the LLM-powered commands (`extract-a`,
  `suggest-bridges`), does the user get any indication that something
  is happening during the 30-60 second wait, or does it look hung?

### 5.3 Does the fusion layer produce sensible output?

Run the full flow. Open `output/fused.json`. Check:
- Is the element count reasonable for the input (not 3, not 300)?
- Do the confidence scores correlate with how grounded each field is?
- Are Source B governance validations visible on the right elements?
- Are Source D business rules attached to matching concepts (not
  randomly)?
- Does the `conflicts[]` array ever contain actually-resolved conflicts
  (proving the conflict detection works)?
- Does `needs_review` flag the right elements (low-confidence ones)?

### 5.4 Does lint find real issues, or is it noise?

Run `ontozense lint output/fused.json` on the shipped fixtures.
Expected output should include:
- Some contradictions between A and B (different definitions for
  "Default" — Source A from Basel, Source B from governance).
- Some orphan terms (concepts Basel mentions once, without
  relationships).
- Coverage gaps (elements where definition or citation is empty).
- Structural gaps (the NPL concept graph should have at least one
  disconnected cluster — e.g., credit-risk cluster vs. collateral
  cluster).

If lint produces **zero findings**, that's suspicious. If it produces
**dozens of findings per element**, that's noise. Somewhere in between
is right.

### 5.5 Does `suggest-bridges` produce useful output?

This one requires an API key. If you have one, run it. Otherwise, read
the code and the tests:
- Does the prompt template make sense? Is it genuinely domain-neutral?
- Would an LLM response to this prompt actually bridge clusters, or
  would it produce generic "maybe add a relationship" noise?
- Does the response parser handle the realistic "LLM deviates from
  format" case gracefully?

### 5.6 Is `file-back` safe?

- Does it refuse to overwrite existing files silently? (It should
  add a timestamp suffix.)
- Does it fail loudly if the domain directory path doesn't exist or
  isn't writable?
- Are the log entries actually grep-parseable per PLAYBOOK §10?

### 5.7 Domain neutrality — still clean?

- Run `pytest tests/test_domain_neutrality.py -v`. It must pass.
- Grep `src/ontozense/` for banking terms yourself: "basel", "npl",
  "borrower", "collateral", "forbearance". The only allowed
  occurrences are in docstring examples explicitly labelled as
  examples (see PLAYBOOK §6).
- The prompt template in `core/bridging.py` is the newest surface
  where a banking term could leak in by accident. Check it carefully.

### 5.8 Are deferred items clearly marked?

The following are known deferred items:
- Synonym maps for cross-source matching (currently exact normalised
  match only)
- Stale claims lint check (needs persistent state)
- Missing cross-references lint check (needs domain semantics)
- Source C CLI wrapper (the parsers work but aren't wired through
  `ontozense extract-c`)
- PDF/DOCX support for Source A (user must convert to .md/.txt first)
- OWL generation from the fused output (exists in the legacy
  `export` command but not wired to the new pipeline)

Verify these are **visible** to the tester — either in docstrings,
CLI help, PLAYBOOK §13, or clearly documented somewhere. The worst
outcome is the tester discovers a missing feature by having it fail
silently.

---

## 6. Specific questions I want direct answers to

Answer each one with a verdict and a brief justification. Disagreement
is welcome.

1. **Will a competent Python user who has never seen this repo be able
   to run the tutorial end-to-end without asking a human?** If no,
   what's the biggest blocker?

2. **Are there any cliff-edges** (undocumented path assumptions,
   missing validations, error paths that explode instead of producing
   a helpful message) a new user would hit?

3. **Is the 354-test suite actually covering what matters, or are
   there critical paths with no tests?** Specifically: does the CLI
   get exercised enough, or mostly just the underlying Python API?

4. **Does the tutorial at `docs/ontozense-npl-tutorial.md`** (in the
   sibling Ontology-Playground repo, but you can find it there)
   **accurately describe what the current code does**? Expected
   outputs in the tutorial — are they what the code actually produces?

5. **Is the confidence scoring still honest?** Previous review
   flagged drift between the code and PLAYBOOK §3. Is it aligned now?
   Are the numbers meaningful to a user looking at the output?

6. **Does `suggest-bridges` justify its existence**, or is it a
   feature we added because it was interesting, not because it's
   useful? Specifically: would a typical user of a fused dictionary
   actually benefit from LLM-suggested bridges, or is it theatre?

7. **Is there anything you'd strongly recommend cutting** before
   handing this to a tester — a feature that's half-finished, a
   documentation section that's confusing, a CLI command that's
   error-prone?

8. **What's the one thing most likely to make the tester give up
   in frustration?**

---

## 7. What the review output should look like

Write your review to `docs/REVIEW_2026-04-15.md` in this repo.
Structure:

```markdown
# Ontozense Tester-Readiness Review — 2026-04-15

## Verdict
One paragraph: is this ready to hand to an external tester, or does
something need to change first?

## What works well
Specific wins. Keep it short.

## Blockers (must fix before handoff)
Numbered list. Severity: blocker / major / minor.

## Tester experience notes
What will happen when a new user runs through the tutorial?

## Answers to the 8 questions in §6
Number them 1–8.

## What I'd cut
Features or docs I'd remove or simplify before handoff.

## What I'd add
Only critical gaps. Not nice-to-haves.
```

3–5 pages is ideal. 10+ pages is too much — be ruthless about what
matters.

---

## 8. House rules

- **Run `pytest -q` on a clean checkout first.** All 354 tests must
  pass. If they don't, stop and report that.
- **Actually run the tutorial** in a fresh venv with a real Azure
  OpenAI key if you have one. Reading the code is not enough —
  testers run the code.
- **Read `docs/PLAYBOOK.md` before reading any core/ module.** The
  code implements the playbook; it makes far more sense in that order.
- **Cite `file_path:line_number`** when flagging issues.
- **Severity labels matter**: blocker (tester will give up), major
  (tester will complain), minor (tester won't notice).
- **Do not suggest stylistic rewrites.** Only report defects that
  affect the tester's experience.

Thank you. Take your time — a thorough handoff review saves a messy
tester experience.
