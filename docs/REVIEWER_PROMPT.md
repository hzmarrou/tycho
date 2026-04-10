# Code Review Request — Ontozense Phase 1 Implementation

You are reviewing the first implementation slice of **Ontozense**, a Python package at `C:\Users\hzmarrou\OneDrive\python\projects\ontozense`.

This is **not a syntax review.** I want you to evaluate whether the implementation faithfully reflects the methodology and design decisions we agreed upon, whether the LinkML template is well-designed for the actual goal, and whether the extraction semantics are honest and defensible. The decoupling check is one of several review priorities — not the main one.

---

## 1. Project background — what Ontozense is and why it exists

Ontozense is a Python package whose eventual product is a **SaaS for auto-generating ontologies for any business domain** from a curated knowledge base of authoritative documents.

### The user's problem
Domain experts (in regulated industries: banking, insurance, healthcare, etc., but also any domain with formal documentation: manufacturing, retail, telecom) currently spend **months** manually building **data dictionaries** from authoritative domain documents (regulations, internal policies, standards, vendor specs, academic surveys). A data dictionary is a structured artifact: one row per data element, with columns like definition, sub-domain, criticality, citation, and data quality rules. These dictionaries become the foundation for downstream ontologies, semantic layers (Microsoft Fabric IQ, Snowflake), data governance, and compliance audits.

### The Ontozense value proposition
Auto-generate **60-70%** of the data dictionary so the expert reviews and fills the remaining 30-40% — instead of starting from a blank Excel. The expert is not replaced; they are accelerated.

### The architecture we agreed upon
A **three-pass pipeline** that combines complementary sources:

| Pass | Source | Method | Status |
|---|---|---|---|
| Pass 1 | Authoritative domain documents (regulations, internal policies, academic papers, vendor specs — anything prose-shaped that the domain experts treat as canonical) | OntoGPT + SPIRES (peer-reviewed methodology) | **Single-document extraction implemented in this review.** Multi-doc merge is the next implementation step. |
| Pass 2 | Production code (Python, SQL) | AST parsing + LLM labeling, following the AI-RBX methodology described in `docs/AI-RBX.pdf` (93% expert agreement at 3.4M LoC) | NOT yet implemented |
| Pass 3 | Database schema | Direct introspection (PostgreSQL, Django) | Already implemented earlier — exists in `extractors/pg_schema.py` and `extractors/django_schema.py` |
| Fusion | Combines all three | Match/merge with provenance + grounding | NOT yet implemented |

The eventual ontology includes definitions from documents, business rules from code, and structure from the schema — each annotation traceable to its source.

### Why a data dictionary, not "an ontology"
The previous Ontozense prototype extracted generic "concepts and relationships" from documents using a generic LinkML template. On Basel D403 it produced **74 concepts but only 3 useful definitions** that mapped to anything real. The signal-to-noise ratio was 4%.

We discussed why and concluded:
- An ontology graph (entities + relationships) is the *wrong intermediate representation* for what authoritative domain documents actually contain
- Authoritative domain documents define **fields** (data elements), not entities or relationships
- The data dictionary format mirrors what experts actually produce manually — so if we generate it, the human reviews in their existing workflow (Excel)
- The data dictionary becomes input to a later **fusion** step that combines it with schema (entities/relationships) and code (business rules) to form the actual ontology

This was a deliberate methodological pivot from "extract an ontology" to "extract a data dictionary." It is the most important design decision in this phase. **Verify that the implementation faithfully reflects this pivot — that the template and extractor target a data dictionary, not a generic ontology.**

---

## 2. Methodological foundation — what we're standing on

I'm allergic to building on unvalidated foundations. We agreed that each pass must use a battle-tested or peer-reviewed method, not invent something new.

### Pass 1 — SPIRES + OntoGPT
- **SPIRES** (Caufield et al., 2024, *Bioinformatics*) — Structured Prompt Interrogation and Recursive Extraction of Semantics. Peer-reviewed. The full paper is at `docs/SPIRES.md` in this repo.
- **OntoGPT** — the open-source Python implementation of SPIRES from the Monarch Initiative. Used in production for extracting biomedical knowledge from literature. Battle-tested.
- **The contract:** We provide a **LinkML template** describing the desired output schema. SPIRES generates structured prompts, calls the LLM, parses results, optionally grounds entities to ontology terms, and returns instances conforming to the schema.
- **The constraint:** SPIRES handles up to **2 levels of class nesting** reliably. Anything deeper degrades.

### Pass 2 — AI-RBX methodology (future, not in this review)
- **AI-RBX** — paper at `docs/AI-RBX.pdf` describing reverse-engineering of business rules from legacy COBOL/PL/I codebases using deterministic AST parsing + LLM labeling with structured outputs.
- **Reported results:** 93% agreement with expert-authored business rules on 3.4M LoC, 70% effort reduction, 3.2-3.3× speedup. Published with explicit error taxonomy.
- We agreed to follow this methodology for Pass 2 because it matches the structure we need: parse first (deterministic, no hallucination risk), then LLM-label (constrained by structured output schemas), then validate against the parsed symbol table.

### What we explicitly rejected
- **Pure LLM prompting for business rules** — too much hallucination risk in regulated domains
- **OrionBelt-style monolithic editor** — wrong shape for our pipeline; also BSL-licensed (can't reuse code)
- **Authoring rules from natural language** (Vishal Mysore's dev.to article approach) — wrong direction; we need to *recover* rules from existing code, not author new ones
- **A generic "concept + relationship" extractor** — proven to produce noise, see the 4% NPL result above

### Verify this in your review
1. Does the LinkML template adhere to SPIRES design rules (≤2 levels of nesting, identifier field present, attribute descriptions actually informative for the LLM)?
2. Does the extractor wrap OntoGPT correctly, or does it bypass SPIRES and reimplement extraction?
3. Are we using OntoGPT *as designed*, or are we forcing a square peg into a round hole?
4. Is the dataclass design compatible with what SPIRES outputs? (Look at `_parse_ontogpt_output` in `dd_extractor.py` and compare to actual OntoGPT output formats.)

---

## 3. The LinkML template — the most important artifact

The LinkML template at `src/ontozense/templates/data_dictionary.yaml` is the single most important file in this implementation. **It IS the instructions to the LLM.** Whatever the template says, that's what gets extracted. Everything downstream depends on it.

### What the template should achieve

For each document fed to OntoGPT, the template should guide the LLM to extract:

1. **The document-level domain** (what business area this document covers)
2. **A list of data elements**, where each element has:
   - A canonical name (the identifier)
   - A sub-domain (which entity/area within the document)
   - A definition (quoted or paraphrased from the source)
   - A formal term definition (if one is given)
   - A criticality flag (mandated by an authoritative source or not)
   - A citation (section/paragraph reference within the source document)
   - A mandatory/optional flag
   - Six data quality dimensions: completeness, accuracy, uniqueness, timeliness, consistency, validity

This shape is intentionally chosen because it matches what enterprise data dictionary tools accept and what data governance experts already recognize. It is **not** modeled after any specific banking spreadsheet (`docs/ssfabn.xlsx` is one example reference, but the template must work for healthcare, manufacturing, retail — any domain).

### Review criteria for the template

1. **SPIRES compliance**
   - Is the structure ≤2 levels of class nesting?
   - Does the root class have `tree_root: true`?
   - Does each class have an `identifier` attribute where appropriate?
   - Are all attributes flat strings (so the LLM can fill them) rather than complex nested objects beyond the SPIRES limit?

2. **Description quality** (the LLM literally reads these as instructions)
   - Are descriptions specific enough that the LLM will know what to extract?
   - Are they instructional (telling the LLM what to do) or just declarative (defining the field for documentation)?
   - Do they tell the LLM what to do when information is missing? (E.g., "leave empty if not stated" — important to suppress hallucination)
   - Are there enough examples to constrain the LLM, but few enough not to bias toward a specific domain?

3. **Domain neutrality**
   - Run a search: do any banking/healthcare/manufacturing terms appear in the descriptions?
   - The template MUST be domain-agnostic. If it mentions "Loan", "Patient", or "Order" anywhere, that's a leak.

4. **Trade-off honesty**
   - The 6 DQ fields (completeness, accuracy, uniqueness, timeliness, consistency, validity) are flat strings rather than a nested DQ class. This is forced by the SPIRES 2-level nesting limit. Is this trade-off documented?
   - Are there fields that look like they should be enums but are strings? Why?

5. **What should the template guide us to extract that it currently doesn't?**
   - Is there any obvious missing field that experts would expect in a data dictionary?
   - Conversely, is there any field that's redundant or that the LLM will struggle to fill reliably?

### How to validate the template
You should not just read the template — you should evaluate it against an actual document. The test fixture is at `tests/fixtures/npl-basel-guidelines.md` (the Basel D403 NPL document, ~1700 lines). Look at Sections 3 and 4 of that document. Then look at the template fields. Ask: **for each section heading in the document, what data elements would an expert create, and would this template capture them?**

If the template would miss something a human expert would naturally extract, that's a P1 issue.

---

## 4. Extraction semantics — confidence, provenance, honesty

### What we agreed upon
- **Confidence is non-negotiable.** Every extracted field gets a score. Hallucinated content must score lower than verbatim quotes.
- **Provenance is non-negotiable.** Every extracted element must trace back to a source location (document, section, snippet) so a human reviewer can verify.
- **Honest failure modes.** If the extraction produces nothing useful, the system must say so loudly — not silently produce a clean-looking but worthless output.

### What was implemented (after the first review round)

#### Confidence scoring (`_score_field` in `dd_extractor.py`)
Field-aware scoring with five categories:

| Field type | Examples | Scoring rule |
|---|---|---|
| ENUM | `is_critical`, `mandatory_optional` | `0.85` if value is in valid set (Y/N, M/O); `0.3` if not |
| REFERENCE | `citation` | `0.95` if verbatim citation in source; `0.7` if matches citation regex pattern; `0.4` if non-citation text |
| NARRATIVE | `definition`, `term_definition`, all 6 DQ fields | `0.95` if verbatim in source; `0.75` if ≥70% token overlap; `0.55` if ≥40% overlap; `0.35` otherwise |
| CATEGORICAL | `sub_domain` | `0.7` if non-empty (LLM is asked to assign a category, not quote one) |
| (default) | anything else | `0.5` if non-empty |

**Review questions:**
- Are these thresholds defensible? Why 0.95 for verbatim, 0.75 for high overlap?
- Is the citation regex (`REFERENCE_PATTERN`) robust enough? What citation styles will it miss?
- The token overlap calculation skips short words (≤3 chars) — is this the right call?
- What are the failure modes? Can you construct an example where the scorer is overconfident?

#### Provenance tracking (`_find_best_snippet` in `dd_extractor.py`)
Multi-anchor lookup that tries (in order):
1. Long verbatim phrases from `definition` or `term_definition`
2. The element name
3. The citation text
4. Significant 5-grams of the definition

Returns the first hit. The snippet is a substring of the source text, never invented.

**Review questions:**
- Are these anchors enough? What would still produce empty provenance?
- Is the 5-gram fallback meaningful, or noise?
- The implementation is case-insensitive substring matching — does this miss anything important (e.g., paraphrased definitions)?

#### Honest failure modes (`extract-dd` CLI)
- **0 elements extracted** → exit code 2, refuses to write output, prints likely causes
- **All elements have confidence < 0.5** → exit code 3, writes output anyway (so the human can see what was extracted) but explicitly tells the user it's untrustworthy
- **Per-document extraction warnings** when an individual document yielded 0 elements

**Review questions:**
- Are the exit codes documented somewhere?
- Are the warning messages actionable, or just complaints?
- Is there any case where the CLI silently writes garbage output?

---

## 5. Domain decoupling

The core engine in `src/ontozense/` MUST be domain-agnostic. NPL/banking is the test case (lives in `tests/`), not the product. We had several leaks early in implementation that I cleaned up: hardcoded NPL synonym maps, banking examples in template descriptions, NPL-specific function names, hardcoded schema names. I added a regression test (`tests/test_domain_neutrality.py`) that scans `src/ontozense/` for banned terms and fails the build if any are found.

**Review criteria:**
1. Run `pytest tests/test_domain_neutrality.py` — does it pass?
2. Run `grep -ri "npl\|loan\|borrower\|collateral\|forbearance\|basel\|ifrs\|finrep\|eba\|counterparty" src/ontozense/` — should produce no output. If it produces output, those are leaks.
3. Are there *implicit* domain assumptions baked in that the regex won't catch? E.g., a function whose behavior only makes sense in a banking context?
4. The schema_refiner has an injectable `synonym_map` parameter — verify there are no hardcoded synonyms anywhere in `src/`.
5. The `NamingPolicy` dataclass in `manager.py` was extracted from a previous "Fabric IQ-only" implementation. Verify Fabric IQ is now genuinely one example among many, not a privileged default.

---

## 6. What's actually implemented in this review

This session covers **two slices of the plan**:

- **Implementation step "Phase 1"** — Pass 1 single-document extraction
- **Implementation step "Phase 3"** — Excel and gap report exporters
- **CLI wiring** — `extract-dd` command running the above end-to-end

### Files

| File | Purpose | New / Modified |
|---|---|---|
| `src/ontozense/templates/data_dictionary.yaml` | LinkML template — **most important file** | New |
| `src/ontozense/extractors/dd_extractor.py` | Pass 1 extractor: dataclasses, OntoGPT wrapper, confidence + provenance | New |
| `src/ontozense/exporters/excel.py` | Excel output (with confidence, provenance, needs-review columns) | New |
| `src/ontozense/exporters/gap_report.py` | Coverage stats and suggested actions, console + markdown | New |
| `src/ontozense/cli.py` | Added `extract-dd` command | Modified |
| `src/ontozense/core/schema_refiner.py` | Removed hardcoded NPL synonyms; injectable synonym_map | Modified |
| `src/ontozense/core/manager.py` | Refactored Fabric IQ rules into generic NamingPolicy | Modified |
| `src/ontozense/extractors/pg_schema.py` | Defaults: schema=`public`, no hardcoded password | Modified |
| `src/ontozense/extractors/django_schema.py` | Renamed `parse_openNPL()` → `parse_django_app()` | Modified |
| `tests/test_dd_extractor.py` | Unit tests with mocked OntoGPT | New (28 tests) |
| `tests/test_excel_export.py` | Excel + gap report tests | New (15 tests) |
| `tests/test_domain_neutrality.py` | Regression test against domain leaks | New (1 test) |
| `tests/test_schema_refiner.py` | Updated to use injected `NPL_SYNONYMS` constant | Modified |

### What is NOT implemented (do not review — these files don't exist)

| Plan step | Description | Tracked task |
|---|---|---|
| Phase 2 | Multi-document merge for Pass 1 (`core/dd_merger.py`) | #20 |
| Phase 4 | Pass 2 code extraction (`extractors/code_extractor.py`) | #22 |
| Phase 4 fixture | Synthetic NPL codebase at `tests/fixtures/synthetic_npl_code/` | #21 |
| Phase 5 | Fusion layer (`core/fusion.py`) | #24 |
| Phase 6 | CLI commands `extract-code`, `fuse`, `pipeline` | #26 |

You should not review these (they don't exist yet), but please verify that the Phase 1 + 3 code is structured in a way that doesn't make Phase 2/4/5/6 harder to add later.

### Test verification
```bash
cd C:\Users\hzmarrou\OneDrive\python\projects\ontozense
.venv\Scripts\python -m pytest tests/ -v
```
Expected: **71 tests pass, 0 failures.** Breakdown:
- `test_dd_extractor.py` — 28 tests
- `test_excel_export.py` — 15 tests
- `test_domain_neutrality.py` — 1 test
- `test_npl_pipeline.py` — 14 tests (existing, must not regress)
- `test_schema_refiner.py` — 10 tests (existing, modified for injected synonym_map)

### What is NOT verified yet
**No real LLM run has been performed against `tests/fixtures/npl-basel-guidelines.md`.** All 71 tests use mocked OntoGPT output. The next step after this review will be to run `extract-dd` against the actual Basel D403 document with Azure OpenAI and inspect the result. This means we don't yet know if the template actually produces good extractions on real text — only that the parsing/scoring/export pipeline works correctly given hypothetical OntoGPT output.

**This is itself something to flag as a risk in your review.** A template that looks well-designed on paper may produce poor extractions in practice. The test suite gives us syntactic confidence, not semantic confidence.

---

## 7. Review priorities

### Priority 1 — Methodological fidelity
**This is the most important review category.** Are we faithful to SPIRES + OntoGPT, or have we drifted?
- Read `docs/SPIRES.md` (Section 3, "Algorithm") if you haven't already
- Verify the template and extractor match the SPIRES contract (LinkML schema → structured prompt → recursive extraction)
- Verify we're using OntoGPT *as designed*, not bypassing it or fighting against it
- Flag any case where the implementation contradicts SPIRES/OntoGPT design assumptions

### Priority 2 — LinkML template quality
**The template is the most important artifact.** It IS the instructions to the LLM. Garbage in, garbage out.
- Read the template (`src/ontozense/templates/data_dictionary.yaml`) carefully
- Evaluate against the criteria in Section 3 above (SPIRES compliance, description quality, domain neutrality, trade-off honesty)
- Hypothetically: if you fed Basel D403 (`tests/fixtures/npl-basel-guidelines.md`) Sections 3 and 4 to an LLM with this template, what would you expect it to extract? Is the template specific enough to guide that extraction?
- Flag missing or redundant fields

### Priority 3 — Extraction semantics
- Is confidence scoring honest, or overconfident?
- Is provenance fidelity actually achieved, or does it have failure modes the tests don't cover?
- Are honest failure modes loud enough? Can a user run the CLI, get back garbage, and not realize it?

### Priority 4 — Domain decoupling
- Run the regression test
- Look for implicit domain assumptions the regex won't catch
- This is *not* the main review focus this round, but it should still pass

### Priority 5 — Plan adherence
The implementation plan is at `C:\Users\hzmarrou\.claude\plans\optimized-puzzling-cupcake.md`. Does what was implemented match what we agreed to build? Flag deviations or shortcuts.

### Priority 6 — Forward-looking risk
Does the current code create technical debt that will make Phase 2/4/5/6 harder? Specifically:
- Will the dataclass design accommodate multi-document merge (Phase 2) without rework?
- Will the confidence/provenance design accommodate fusion with code-extracted rules (Phase 5)?
- Are there hidden assumptions baked into Phase 1 that will surface as bugs in Phase 5?

---

## 8. Output format for your review

Please structure as:

1. **Methodological verdict** — pass/fail. Are we faithful to SPIRES + OntoGPT? Cite specific lines if you find drift.
2. **Template verdict** — pass/fail with detailed feedback. Is this template likely to produce useful extractions on a real authoritative domain document? What would you change?
3. **P1 issues** (must fix before merging) — methodological, template, or extraction quality issues
4. **P2 issues** (should fix soon)
5. **P3 issues** (nice to have / improvements)
6. **Decoupling verdict** — pass/fail with details
7. **Plan adherence** — what's missing, what's extra, what's drifted
8. **Risk register** — what worries you about how this code will behave in production or in upcoming phases
9. **Praise** — briefly, what was done well (calibration)

---

## 9. Operating principles to enforce

The user has been explicit about a few principles throughout the project. Use these as a compass:

1. **"We must not fool ourselves."** Every claim should be defensible. If the code says something is "extracted with high confidence," that needs to be honest about what evidence supports it.

2. **Provenance is non-negotiable.** Every extracted item must trace back to its source. Verify the dataclasses and exporters preserve this end-to-end, not just at the top level.

3. **Honest failure modes.** When extraction fails (no definitions found, low confidence, conflicts), the system should TELL THE USER, not silently produce a clean-looking but wrong result.

4. **The human is the final authority.** Ontozense produces a 60-70% draft. The expert reviews and augments. Verify the output format is one the human can actually review (Excel with clear flags on what needs attention).

5. **Battle-tested over invented.** We don't invent extraction algorithms. Pass 1 uses SPIRES (peer-reviewed). Pass 2 will use AI-RBX (industrially validated). Pass 3 uses direct introspection (boring and reliable). If you find any place where we're inventing instead of standing on existing work, flag it.

6. **Domain-agnostic core.** The engine works for any domain. NPL is the test case, not the product.

7. **Each phase ships independently.** Phase 1 + 3 should be useful on their own, even before Phase 2/4/5/6 land. Verify this is true.

---

## 10. Be critical

Don't sugarcoat. The user explicitly asked for honest, critical review. If the template is poorly designed, say so. If we're misusing OntoGPT, say so. If the confidence scoring is theatre, say so. If the implementation has drifted from what we agreed upon, say so. The user is more interested in fixing real problems than in being told the work is good.

If you find that the implementation looks fine but is structurally on the wrong track, say that even more clearly — that's the most expensive kind of mistake to catch later.

Thank you for the careful review.
