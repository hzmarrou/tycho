# Independent Review Assignment — Ontozense (2026-04-10)

You are reviewing **Ontozense**, a Python package located at
`C:\Users\hzmarrou\OneDrive\python\projects\ontozense`.

This is an **independent review**. You do not see the conversation history
that produced this code. That is intentional. We want you to challenge our
assumptions, not validate them. Where you disagree, say so clearly and
propose what you would do instead.

This is **not a syntax / lint review.** Linters and formatters already pass.
We want your judgement on **architecture**, **methodology faithfulness**,
**domain neutrality**, **honest failure modes**, **scoring rigor**, and
**test coverage of the things that actually matter**.

The review is being requested at a milestone: **Steps 1–5 of an 8-step
plan are complete (MVP scope). Step 6 (the fusion layer) is the next thing
we will build.** Your review should help us decide whether the foundations
are sound enough to build the fusion layer on top, or whether something
needs to change first.

---

## 1. What Ontozense is, and why it exists

### 1.1 The user problem

Domain experts in regulated industries (banking, insurance, healthcare,
pharma, manufacturing — any domain with formal authoritative documentation)
spend **months** manually building a **rich data dictionary** for each
domain. A rich data dictionary is a structured artifact: one row per data
element, with columns like:

```
domain_name | sub_domain | element_name | definition | term_definition |
is_critical | citation | mandatory_optional | dq_completeness |
dq_accuracy | dq_uniqueness | dq_timeliness | dq_consistency | dq_validity
```

These dictionaries become the foundation for downstream ontologies,
semantic layers (Microsoft Fabric IQ, Snowflake), data governance,
compliance audits, and business glossaries.

The expert isn't producing the dictionary from imagination. They are
**reading** authoritative documents, governance spreadsheets, code, and
schemas, and assembling the rows by hand. Most of this is mechanical
extraction; the part that genuinely needs human judgment is small.

### 1.2 The Ontozense value proposition

Auto-generate **60–70%** of the rich data dictionary so the expert
**reviews and fills the remaining 30–40%** instead of starting from a
blank Excel. The expert is not replaced — they are accelerated.

Output is read in **Excel** (the expert's existing workflow) and **Microsoft
Playground / Fabric IQ** (the downstream ontology consumer).

### 1.3 The methodological pivot you should know about

An earlier prototype tried to extract a rich 13-field data dictionary
**directly** from authoritative documents using a single LinkML template
and OntoGPT/SPIRES. On Basel D403 it produced **1 structured element from
26 the LLM identified**. We investigated and found:

1. SPIRES recursion passes only the matched value (e.g. `"Customer
   Identifier"`) to per-element calls, **not** the original document. So
   per-element attribute extraction has no source context — it has to
   invent.
2. Most of the 13 fields don't even *live in* prose documents. They live
   in governance spreadsheets, in code, or in the schema. Asking the LLM
   to extract them from a regulation is asking it to hallucinate.

The corrected architecture is the **four-source pipeline** described in
section 2. The single most important design decision: **the rich data
dictionary is the OUTPUT of the fusion layer, NOT the extraction target
of any single source.** Each source contributes only the fields it can
defensibly produce. Fusion combines them with provenance.

**The first thing I want you to verify** is that the implementation
faithfully reflects this pivot.

---

## 2. The architecture (four sources + router + fusion)

```
                  ┌───────────────────────────────────────────────────┐
                  │   Living Knowledge Base (folder, S3, SaaS UI)     │
                  │   ┌────────┐ ┌────────┐ ┌────────┐ ┌──────────┐  │
                  │   │basel.pdf│ │gov.csv │ │rules.py│ │schema.sql│  │
                  │   └───┬────┘ └───┬────┘ └───┬────┘ └────┬─────┘  │
                  └───────┼──────────┼──────────┼───────────┼────────┘
                          │          │          │           │
                          ▼          ▼          ▼           ▼
                     ┌────────────────────────────────────────────┐
                     │                  ROUTER                    │
                     │  L1: file-extension rules                  │
                     │  L2: content sniffing                      │
                     │  L3: LLM classifier (deferred)             │
                     └─────┬──────┬──────┬──────┬─────────────────┘
                           ▼      ▼      ▼      ▼
                      Source A Source B Source C Source D
                      (docs)   (gov.)   (schema) (code)
                           │      │      │      │
                           └──────┴──────┴──────┘
                                  │
                                  ▼
                         ┌──────────────────────┐
                         │   FUSION LAYER       │  ← NOT YET BUILT
                         │  Match by name       │     (Step 6)
                         │  Track provenance    │
                         │  Detect conflicts    │
                         │  Resolve via PLAYBOOK│
                         └─────────┬────────────┘
                                  │
                  ┌───────────────┼───────────────┐
                  ▼               ▼               ▼
            ┌──────────┐    ┌──────────┐    ┌──────────┐
            │  INGEST  │    │   LINT   │    │  QUERY   │  ← Steps 7+8
            └──────────┘    └──────────┘    └──────────┘
```

The four sources (and what each one defensibly provides):

| Source | Type of artifact | Provides | Method | Status |
|---|---|---|---|---|
| **A** | Authoritative domain documents (PDF, DOCX, MD, HTML) — regulations, internal policies, academic papers, vendor specs, anything **prose-shaped** the experts treat as canonical | Concepts (names), relationships (S/P/O triples), definitions, citations | OntoGPT + SPIRES (Caufield 2024, peer-reviewed), reading `raw_completion_output` to bypass SPIRES recursion limit, plus a regex-based definitions second pass | ✅ Complete |
| **B** | Governance / data quality spreadsheets (Excel, **canonical CSV** in MVP) | `is_critical`, `mandatory_optional`, the six DQ dimensions, citations | Schema-aware structured parser. **Canonical CSV format only** in MVP (14 named columns). No fuzzy header matching, no LLM. | 🟡 **TBD scaffold** — public API locked, raises `NotImplementedError`, canonical column list defined |
| **C** | Database schemas (PostgreSQL live introspection or Django model AST) | Entities, properties, types, FKs, enum values, NOT NULL | Direct introspection — no LLM | ✅ Inherited from earlier work |
| **D** | Production code (Python, SQL) | Computational rules, thresholds, state transitions, classification logic, constraints | AST parsing (Python `ast`, `sqlglot` for SQL) deterministic first; LLM labelling step + symbol-table validator deferred. **Methodology: AI-RBX (`docs/AI-RBX.pdf`)** — 93% expert agreement at 3.4M LoC. | ✅ Deterministic layer complete (MVP) |

**Behind everything sits `docs/PLAYBOOK.md`** — the negotiated convention
layer that codifies source-to-field mapping, confidence rubric, conflict
resolution rules, routing rules, domain neutrality, provenance
requirements, failure modes, log format, citation policy, and model
selection findings. **Read it before reading any code.** Both humans and
LLMs are expected to read it.

`docs/why_the_playbook.md` is a one-page rationale for why the playbook
exists at all.

---

## 3. What is in scope for this review

### 3.1 What's been built (Steps 1–5, MVP)

| Step | What | Files |
|---|---|---|
| **1.1** | `PLAYBOOK.md` — single source of truth for conventions | `docs/PLAYBOOK.md` (327 lines, 13 sections) |
| **1.2** | Per-domain `log.md` writer (Karpathy gist pattern — append-only, grep-parseable) | `src/ontozense/log.py` (108 lines), `tests/test_log.py` (20 tests) |
| **2.1** | Simpler LinkML template — concepts + relationships only (replaces 13-field template that didn't work) | `src/ontozense/templates/domain_doc_extraction.yaml` |
| **2.2** | **Source A extractor** — wraps OntoGPT, parses `raw_completion_output` directly to bypass SPIRES recursion bug, multi-anchor provenance lookup, field-aware confidence scoring | `src/ontozense/extractors/domain_doc_extractor.py` (492 lines), `tests/test_domain_doc_extractor.py` |
| **2.2b** | **Source A second pass** — regex-based definitions extractor (bold-colon, "X is defined as", "X means", "X refers to", numbered lists) | `src/ontozense/extractors/definitions_extractor.py` (270 lines), `tests/test_definitions_extractor.py` |
| **2.5** | CLI: `extract-a` command, `--skip-definitions-pass`, `--review-threshold`, `--domain-dir` for log writes, default model `azure/gpt-5.4` | `src/ontozense/cli.py:extract_a` |
| **3** | **Router** — file extension rules + content sniffing for ambiguous cases. Returns `RoutingDecision(primary_source, confidence, reasoning, alternatives, is_skip, is_multi_source)`. CLI: `ingest` command with `--auto`, `--dry-run`, `--recursive`. | `src/ontozense/router/router.py` (572 lines), `tests/test_router.py` (54 tests) |
| **4** | **Source B scaffold** — `GovernanceRecord` and `GovernanceExtractionResult` dataclasses with all 14 canonical fields. `extract_from_file()` raises `NotImplementedError`. Public API locked so the fusion layer can be designed against the shape. | `src/ontozense/extractors/governance_extractor.py` (160 lines), `docs/CANONICAL_GOVERNANCE_FORMAT.md` |
| **5** | **Source D code extractor** — deterministic layer only. Python AST extracts UPPER_SNAKE_CASE constants, function defs (with docstrings + symbol table), if-statements as conditional rules, comment citations. SQL via `sqlglot` extracts CREATE VIEW/TABLE, ALTER TABLE ADD CONSTRAINT CHECK, WHERE clauses, `--` comment citations. Generic citation regex matches `Section`, `§`, `Article`, `Para`, `Chapter`, `Annex`, `ITS`, `RTS`, `Directive`, `Regulation`. | `src/ontozense/extractors/code_extractor.py` (564 lines), synthetic NPL fixtures under `tests/fixtures/synthetic_npl_code/` (no test file yet) |

**Domain neutrality regression test (`tests/test_domain_neutrality.py`)
must always pass.** It greps `src/ontozense/` for banned banking terms
(npl, borrower, collateral, basel, ifrs, finrep, eba, counterparty, ...)
with word-boundary matching and fails the build if any leak in.

### 3.2 What is **not** in scope (don't review what isn't there)

- **Step 6 — Fusion layer** (`core/fusion.py`) — not started yet
- **Step 7 — Lint as standing operation** — not started
- **Step 8 — File-back of query results as derived artifacts** — not started
- Source B real implementation (only the locked-API scaffold exists)
- Source D LLM labelling pass + symbol-table validator (AI-RBX steps 2 & 3)
- `extract-d` CLI command — not wired yet
- Watcher daemon, SaaS API, embedding-based retrieval, multi-tenant infra

These are deliberately deferred. **Do not** ding the review for their
absence — but **do** flag if you think the current foundations make any
of them harder to build than they should be.

### 3.3 Test status

- **206 tests passing** (`pytest -q`) at the time this assignment was
  written.
- Test file count: 9 (`tests/test_*.py`).
- Source line count: 6,704 across 22 files in `src/ontozense/`.

---

## 4. Reference documents — read these in this order

1. **`docs/PLAYBOOK.md`** — the convention layer. 13 sections. Most
   important. Pay attention to §2 (source-to-field mapping), §3
   (confidence rubric), §4 (conflict resolution), §5 (routing rules), §6
   (domain neutrality), §7 (provenance), §8 (failure modes), §10 (log
   format), §12 (model selection findings).
2. **`docs/why_the_playbook.md`** — one-page rationale for why the
   playbook exists. Skim.
3. **`docs/CANONICAL_GOVERNANCE_FORMAT.md`** — the locked Source B input
   format. Explains why we rejected fuzzy header matching and chose a
   canonical CSV.
4. **`docs/SPIRES.md`** + `docs/SPIRES.pdf` — methodology citation for
   Source A. Caufield et al. 2024, *Bioinformatics*. Explains the
   recursion-based zero-shot extraction and the recursion limitation we
   work around by reading `raw_completion_output`.
5. **`docs/AI-RBX.pdf`** — methodology citation for Source D.
   *Leveraging Generative AI for Extracting Business Requirements*.
   Validates the **deterministic-parsing-first → LLM-labelling-second →
   symbol-table-validator-third** pipeline at 3.4M LoC scale, 93% expert
   agreement, 70% effort reduction. We have implemented step 1 only.

---

## 5. Specific things to evaluate

For each one: **state your finding, then your recommendation if any.**
"Looks fine" is a valid finding when it's true.

### 5.1 Faithfulness to the methodological pivot

- Does any single extractor try to produce the rich 13-field data
  dictionary directly? (It shouldn't.)
- Does each extractor honestly limit itself to the fields it can defend?
- Are the public dataclasses (`Concept`, `Relationship`,
  `GovernanceRecord`, `SchemaModel`, `CodeRule`) shaped so that the
  future fusion layer can combine them without coupling?

### 5.2 SPIRES bypass — does it actually work?

`domain_doc_extractor.py` reads `raw_completion_output` from the OntoGPT
result instead of (or in addition to) `extracted_object`, because SPIRES
recursion drops items the LLM identifies. **Verify:**
- Is the parsing of `raw_completion_output` defensive against malformed
  LLM output?
- Are concepts extracted via this path correctly tagged with their
  provenance (source document, location, snippet)?
- §12 of the playbook documents that gpt-5.4 produces **2.4× more
  LLM-validated concepts** than gpt-5.2 with the same template. Does the
  CLI actually default to gpt-5.4? Is the model configurable?

### 5.3 Confidence scoring rubric (PLAYBOOK §3)

Read PLAYBOOK §3 carefully — it describes a **field-aware** rubric with
five categories (ENUM, CITATION, NARRATIVE, CATEGORICAL, STRUCTURED) and
specific score values per category.

Then check `domain_doc_extractor.py`:
- Are the rubric values implemented exactly as documented?
- Element-level confidence is the **average of populated field scores**
  (per §3). Is the implementation honest about empty fields, or does it
  silently skip them and inflate the average?
- A name-only concept with no definition should score around 0.475
  (because the missing `definition` field contributes a 0.0). Verify
  this with a quick test or code read.
- A relationship with neither endpoint matching source text should
  score 0.30, not 0.5. Verify.

### 5.4 Honest failure modes (PLAYBOOK §8)

- Does the CLI actually exit with **code 2** when extraction produces
  zero elements?
- Does it exit with **code 3** when all elements are below the review
  threshold?
- Per-document warnings on multi-doc runs?
- OntoGPT subprocess stderr surfaced verbatim, not "extraction failed"?

Look at `cli.py:extract_a` and the OntoGPT wrapper.

### 5.5 Domain neutrality

- Run `pytest tests/test_domain_neutrality.py -v`. Confirm it passes and
  inspect what it actually checks.
- Read `code_extractor.py`'s citation regex (`_CITATION_RE`). Does it
  contain any banking-specific vocabulary? (It shouldn't — the regex
  matches generic legal/spec citation patterns: Section, §, Article,
  Paragraph, Chapter, Annex, ITS, RTS, Directive, Regulation.)
- Run the code extractor against `src/ontozense/` itself (it's
  domain-neutral by construction) and verify it produces structured output
  without complaining. Quick smoke test:
  ```python
  from src.ontozense.extractors.code_extractor import CodeExtractor
  result = CodeExtractor().extract_from_directory('src/ontozense')
  print(len(result.rules))   # we got 151 last time
  ```

### 5.6 AI-RBX faithfulness for Source D

`docs/AI-RBX.pdf` defines a 4-step pipeline: (1) deterministic parsing,
(2) LLM labelling, (3) symbol-table validator, (4) provenance.

We have implemented **step 1** only. The dataclasses (`CodeRule`,
`CodeProvenance`, `CodeExtractionResult`) are designed to accommodate
steps 2–3 in a follow-up. **Verify:**
- Are the deterministic candidates structured well enough that an LLM
  labelling step can consume them without re-parsing source code?
- Does each candidate carry a `referenced_symbols` list that the future
  validator can check against?
- Does each candidate carry full provenance (file, line, column,
  snippet) for step 4?
- Is there anything in the deterministic pass that bakes in NPL or
  banking assumptions and would have to be undone before the LLM step?

### 5.7 Router design (PLAYBOOK §5)

- Does the router correctly dispatch the obvious cases (`.py` → D,
  `.csv` → B, `.pdf` → A, etc.)?
- Does content sniffing handle the ambiguous cases? (`.sql` could be C
  schema DDL or D procedural code; `.xlsx` could be B governance or C
  schema export; `.md` could be A prose or D code-heavy.)
- Multi-source dispatch: a markdown file with both prose and code blocks
  can route to A and D simultaneously. Is this implemented?
- Are skip cases (README, LICENSE, marketing copy) handled?
- The `--auto` flag is supposed to auto-route only when confidence > 0.9.
  Verify the threshold.

### 5.8 Source B scaffold

Read `governance_extractor.py` and `docs/CANONICAL_GOVERNANCE_FORMAT.md`.

- Is the public API (the dataclass shapes) something the fusion layer can
  realistically consume?
- Is the canonical-CSV-only decision sensible, or are we underselling
  what Source B should do? (Note our reasoning: customers convert their
  format upstream once, then the parser is deterministic and trustworthy.
  We rejected fuzzy header matching because it leads to silent
  misclassification.)
- Should the scaffold raise `NotImplementedError` like it does, or
  should we instead ship an empty-but-valid parser that returns zero
  rows? Argue both sides briefly.

### 5.9 Test coverage of the things that matter

206 tests. Check that:
- Domain neutrality regression test exists and is comprehensive.
- Confidence rubric is tested at the **boundary cases**, not just happy
  paths (empty values, name-only concepts, all-narrative-paraphrased,
  citations that match the regex but aren't verbatim).
- Router has tests for every branch in PLAYBOOK §5 (extension rules,
  content sniffing, multi-source, skip).
- The SPIRES bypass (`raw_completion_output` parsing) is tested with
  realistic mocked OntoGPT output that includes the recursion-truncated
  shape.
- The definitions extractor has tests for the false-positive cases (the
  reason it has a `_TERM_BLOCKLIST_PREFIXES` filter — sentence fragments
  that *look* like definitions but aren't).

What's **not** tested that you think should be? What's tested that
doesn't matter?

### 5.10 Honest about what's not done

- Are the deferred items (Source B real impl, Source D LLM labelling +
  validator, Steps 6–8) **clearly marked** in code, in the playbook, in
  the CLI help, and in the dataclasses?
- Or do they look complete-but-broken? (The worst failure mode is "the
  human walks away thinking the run succeeded but the output is wrong"
  — PLAYBOOK §8.)

---

## 6. Specific questions I want answered

Answer each one directly. Brief is fine. Disagreement is welcome.

1. **Is the four-source architecture sound?** Or is there a fifth source
   (or a missing dimension) that we are pretending isn't there?
2. **Is the "fusion-as-output, not extraction-target" pivot
   correctly implemented?** Or has it leaked back into one of the
   extractors?
3. **Is the playbook the right level of abstraction?** Too abstract? Too
   prescriptive? Should anything in it be code instead, or vice versa?
4. **Is the field-aware confidence rubric defensible?** Would you score
   any category differently? Are the per-category numbers reasonable?
5. **Does the SPIRES `raw_completion_output` bypass scare you?** It is a
   workaround for an upstream library limitation. What happens when
   OntoGPT changes the output shape?
6. **Is the AI-RBX deterministic-first pipeline preserved correctly?**
   Will steps 2 (LLM labelling) and 3 (validator) actually be cleanly
   addable on top of what's there, or will they require restructuring?
7. **Is the router going to scale?** Three layers, content sniffing for
   ambiguous formats, multi-source dispatch. What breaks first as the
   knowledge base grows?
8. **Is the canonical-CSV decision for Source B sensible?** Or should we
   bite the bullet and parse Excel with fuzzy header matching now?
9. **Is the per-domain `log.md` actually useful** as an audit trail, or
   is it engineering theatre? Would you replace it with structured
   logging (JSONL)?
10. **Are we ready to build Step 6 (the fusion layer)?** What, if
    anything, has to change first?

---

## 7. What the review output should look like

Please produce a single markdown file `docs/REVIEW_2026-04-10.md` (or
similar — name it after today's date). Structure:

```markdown
# Ontozense Independent Review — 2026-04-10

## Verdict
One paragraph: should we proceed to Step 6 (fusion layer) on the current
foundations, or does something need to change first?

## Strengths
What's actually good. Be specific.

## Issues
Numbered list. For each: severity (blocker / major / minor / nit), what
the issue is, where in the code, what to do about it.

## Answers to the 10 questions in §6
Number them 1–10.

## Things I would do differently
Where you disagree with our approach. Argue your case briefly.

## Test coverage notes
What's missing, what's redundant.

## Recommended next steps
Concrete, ordered.
```

A 5-page review is fine. A 30-page review is too much. Be ruthless about
what matters.

---

## 8. House rules

- **Run `pytest -q` first.** If it doesn't pass on a clean checkout,
  stop and report that. The 206 tests should all pass.
- **Read `docs/PLAYBOOK.md` before reading any code.** The code is
  organized to implement the playbook — it makes far more sense in that
  order.
- **Be specific.** "The error handling could be better" is useless.
  "`domain_doc_extractor.py:347` swallows `JSONDecodeError` silently and
  returns an empty list — should re-raise as a custom exception so the
  CLI can surface it under PLAYBOOK §8" is useful.
- **Cite line numbers using `file_path:line_number` format** so we can
  jump to the source.
- **Disagree with us where you disagree.** This is an independent review.
  Validation is not the goal — finding what we missed is the goal.
- **Do not recommend stylistic rewrites** unless they actually fix a
  defect. We don't want a refactoring sprint; we want to know whether
  the foundations are sound enough for Step 6.

Thank you. Take your time.
