# Ontozense Playbook

This document codifies the conventions, rules, and decisions that govern how Ontozense extracts, fuses, and refines knowledge. It is the single source of truth for "how we do things." Both humans and LLMs read it. When extraction produces a surprising result, the answer is "check the playbook."

This is a **living document**. It evolves as we encounter edge cases. Edits are deliberate and reviewed.

---

## 1. The four sources

A complete domain ontology is assembled from four complementary sources. Each source provides only the fields it can defensibly produce. No single source has everything.

| Source | What it provides | Tool / method |
|---|---|---|
| **A — Authoritative domain documents** (PDF, DOCX, MD — regulations, internal policies, academic papers, industry standards, vendor specifications, white papers, anything prose-shaped that the domain experts treat as canonical) | Concepts (names), relationships (subject/predicate/object triples), definitions, citations (section/paragraph references), sub-domain organization | OntoGPT/SPIRES with a simple concepts+relationships template, parsing `raw_completion_output` to recover full LLM output, plus a regex-based definitions pass |
| **B — Governance / policy documents** (Excel, CSV, structured PDFs) | Critical-data flags, mandatory/optional flags, the six DQ dimensions: completeness, accuracy, uniqueness, timeliness, consistency, validity | Schema-aware structured parser. Excel column headers map directly to fields. No LLM unless edge cases force it. |
| **C — Database schemas** (PostgreSQL, Django, SQLAlchemy, DDL files) | Entities, properties, types, foreign keys, enum values, NOT NULL constraints | Direct introspection. Already implemented. |
| **D — Production code** (Python, SQL) | Computational rules, thresholds, state transitions, classification logic, business constraints | AST parsing identifies candidates deterministically; LLM labels them with structured-output constraint; validator checks against parsed symbol table. Methodology: AI-RBX paper (`docs/AI-RBX.pdf`). |

The **rich data dictionary** (with all 13 fields populated) is the OUTPUT of the fusion layer, not the extraction target of any single pass. Each source contributes its fields; fusion combines them with provenance.

**On Source A naming:** Source A is *not* limited to formal regulations. It handles any document the domain experts treat as canonical — a regulator's guideline, a bank's internal credit-risk policy, an academic survey paper, an industry consortium's specification, a vendor's reference architecture. The defining property is that the document is **prose-shaped** (not structured rows, not code, not a schema) and **considered authoritative within the chosen knowledge base**. Curation of "what counts as authoritative" is the user's responsibility — Ontozense doesn't validate authoritativeness, only extracts from what the user has chosen to include.

---

## 2. Source-to-field mapping

This table tells the fusion layer where each field in the rich data dictionary comes from. If a field is requested but no source provided it, it stays empty and the gap report flags it.

| Rich data dictionary field | Primary source | Fallback source | If neither |
|---|---|---|---|
| `domain_name` | Source A (document-level) | Source B (sheet name) | leave empty |
| `element_name` | Source C (column name) | Source A (extracted concept) | Source B (row label) |
| `sub_domain` | Source A | Source B | derived from C entity |
| `definition` | Source A (domain document prose) | Source B (governance doc) | leave empty |
| `term_definition` | Source A (formal definition from a standard or glossary) | leave empty |
| `is_critical` | Source B (governance flag) | leave empty (authoritative documents rarely flag this) |
| `citation` | Source A | Source B | leave empty |
| `mandatory_optional` | Source B | Source C (NOT NULL implies M) | leave empty |
| `dq_completeness` | Source B | Source C (NOT NULL) | leave empty |
| `dq_accuracy` | Source B | Source D (validator code) | leave empty |
| `dq_uniqueness` | Source B | Source C (UNIQUE constraint) | leave empty |
| `dq_timeliness` | Source B | leave empty |
| `dq_consistency` | Source B | Source D (cross-field constraint code) | leave empty |
| `dq_validity` | Source B | Source C (CHECK constraint) | Source D (validation code) | leave empty |
| `data_type` | Source C | Source B (declared type) | leave empty |
| `enum_values` | Source C (enum or CHECK) | Source B (declared values) | Source D (CHECK constraint) | leave empty |
| `business_rules` | Source D (extracted from code) | Source A (definitional rules in text) | leave empty |

Honest constraint: **fields marked "leave empty"** are flagged in the gap report. The expert reviewer fills them or accepts the gap. We never invent values.

---

## 3. Confidence scoring rubric

Every extracted field gets a confidence score in `[0.0, 1.0]`. The score is honest about how much evidence supports the value. The rubric is **field-aware**: different field categories use different rules.

### Categories

**ENUM fields** (`is_critical`, `mandatory_optional`)
- `0.85` — value is in the valid set (`Y`/`N`/`Yes`/`No`/`M`/`O`/`Mandatory`/`Optional`)
- `0.30` — value is non-empty but not in the valid set (LLM may have invented a variant)
- `0.00` — empty

**CITATION fields** (`citation`, `source_section`)
- `0.95` — the value appears verbatim in the source text (it's a real quote)
- `0.70` — the value matches a citation regex pattern (`Section X.Y`, `Article N`, `§N`, `Para. N`, `Chapter N`) but isn't verbatim in source
- `0.40` — non-empty but doesn't look like a citation
- `0.00` — empty

**NARRATIVE fields** (`definition`, `term_definition`, the 6 DQ fields when extracted from prose)
- `0.95` — value is a verbatim substring of the source text
- `0.75` — ≥70% of significant words (length > 3) appear in source
- `0.55` — ≥40% of significant words appear in source
- `0.35` — non-empty but minimal word overlap (likely paraphrased or invented)
- `0.00` — empty

**CATEGORICAL fields** (`sub_domain`, `data_type` when from prose)
- `0.70` — non-empty (the LLM is asked to assign a category, not quote one)
- `0.00` — empty

**STRUCTURED-SOURCE fields** (anything from Source C or Source B)
- `0.95` — the field comes from a structured source (database introspection, parsed Excel cell). No LLM involvement, no hallucination risk.
- This is higher than narrative fields because structured sources are deterministic.

**NAME fields** (concept `name`)
- Scored with NARRATIVE rules (verbatim → `0.95`, high overlap → `0.75`, partial → `0.55`, low → `0.35`, empty → `0.00`). Most concept names are short phrases that match verbatim, so the common case is `0.95`.
- A concept that the LLM returns with a name but no definition gets a `FieldConfidence("definition", 0.00, "missing")` entry explicitly added, so its element-level confidence reflects the missing half. Without this, name-only concepts would score `0.95` overall despite being incomplete.

**RELATIONSHIP TRIPLE fields** (S/P/O triples from Source A)
- `0.95` — both subject and object appear verbatim in the source text (fully grounded)
- `0.625` — exactly one endpoint appears verbatim (mixed grounding — average of `0.95` and `0.30`)
- `0.30` — neither endpoint appears verbatim (no source grounding — the LLM invented both)
- The predicate is not scored. Predicates are usually paraphrased verb phrases that rarely match source verbatim.
- Stored as a single `FieldConfidence("triple", ...)` entry, not as separate subject/object scores.

**REGEX-ENRICHED fields** (definitions added by the Source A second pass)
The regex definitions extractor runs as a second pass over the document and produces a new category of scoring rules for the values it contributes:
- `0.85` — the existing LLM concept's name matches a regex-found term exactly; the regex-extracted definition is appended to the concept. Below the verbatim `0.95` because the match is structural (pattern + name) rather than full-text verbatim.
- `0.75` — substring match (the LLM concept name contains the regex term or vice versa); the regex definition is appended.
- `0.40` — a regex-found term does not match any LLM concept and is added as a standalone "regex-only" candidate concept. Both `name` and `definition` score at `0.40`, signalling that the concept passed pattern matching but not LLM judgment and is explicitly a candidate for human review.

### Element-level confidence

The overall confidence for an element is the **average** of its populated fields' scores. An element with one high-confidence field (say `definition` at 0.95) and ten empty fields (each at 0.00) gets an overall confidence of 0.0865 — and is flagged as needing review even though one of its fields is high-quality.

This is intentional. The point is to surface elements where the human will spend their time, not to declare success.

### Review threshold

By default, elements with overall confidence below `0.70` are flagged in the `Needs Review` column of the Excel output. The threshold is configurable per run via `--review-threshold`.

---

## 4. Conflict resolution rules

When two sources provide different values for the same field of the same element, fusion detects a conflict. Resolution happens in this order:

1. **Per-domain priority order.** The user can specify which sources take precedence for a given domain (e.g., for NPL: domain document > governance doc > code; for healthcare: governance doc > domain document > code). Default order if not specified: A > B > C > D.

2. **Confidence within source.** If two sources have equal priority, the one with higher per-field confidence wins.

3. **Recency.** If priority and confidence are tied, the more recently extracted source wins (newer is assumed more current).

4. **Human resolution.** If all three rules are tied, the conflict is flagged unresolved in the gap report and the analyst decides during review.

**Provenance is always preserved.** Even when one source's value wins, the rejected values are recorded in `merge_conflicts` so the analyst can see what was ignored and why.

---

## 5. Routing rules

When a new file lands in the knowledge base, the router decides which source to dispatch it to. Three layers, in order:

### Layer 1 — Deterministic file extension rules

| Extension | Source |
|---|---|
| `.py`, `.dbt`, `.r`, `.scala`, `.java`, `.sas` | D (code) |
| `.sql`, `.ddl` | C (if `CREATE TABLE` patterns) or D (if procedural code) — content-sniff |
| `.csv`, `.xlsx`, `.tsv`, `.ods` | B (governance) — unless content-sniff says otherwise |
| `.json`, `.yaml`, `.yml` matching JSON Schema / OpenAPI / Avro / Protobuf | C (schema) |
| `.pdf`, `.docx`, `.md`, `.txt`, `.html`, `.rst` | A (authoritative domain document) |
| Database connection string | C (live introspection) |
| Git repo URL | D (walk for code) |

### Layer 2 — Content sniffing for ambiguous cases

| Heuristic | Decision |
|---|---|
| Excel: column headers contain `definition`, `critical`, `mandatory`, `completeness`, `accuracy`, `uniqueness`, `timeliness`, `consistency`, `validity` | Source B (governance dictionary) |
| Excel: column headers contain `table`, `column`, `type`, `foreign key`, `nullable`, `primary key` | Source C (schema export) |
| Markdown: contains many `if`/`else`/`def`/`SELECT`, code fences | Source D (code-heavy) |
| Markdown: section headings, paragraphs, defining clauses ("X means Y", "shall be", numbered lists) | Source A (authoritative domain document) |

### Layer 3 — LLM classification (deferred)

For genuinely ambiguous files, an LLM classifier is invoked. NOT implemented in initial release; added when deterministic rules prove insufficient on real uploads.

### Routing rules for the boundaries

- **Multi-source routing.** A file can match more than one source (e.g., a markdown developer guide with both authoritative prose AND code blocks). The default is to dispatch to all matching sources.
- **Skip / reject.** README, license, marketing copy → router emits `skip` with a reason.
- **Human-confirmed by default.** The router proposes a routing decision and asks for confirmation. The `--auto` flag enables auto-routing when confidence > 0.9.

---

## 6. Domain neutrality

The core engine in `src/ontozense/` is domain-agnostic. NPL/banking content lives only in `tests/` and `docs/`.

**Banned terms in `src/ontozense/`** (regression-tested in `tests/test_domain_neutrality.py`):
- npl, borrower, collateral, forbearance, enforcement, basel, ifrs, finrep, eba, counterparty, nplonto, opennpl, obligor

**Acceptable patterns:**
- The word "default" in code comments meaning "default value" (not the banking term)
- Generic example synonym maps in docstrings explicitly labeled as examples (e.g., `{"client": "customer"}`)
- Tests and fixtures using NPL data (NPL is the test case, not the engine)

**To add a new banned term:** edit `tests/test_domain_neutrality.py` `BANNED_TERMS` list.

**To allow a specific occurrence:** add to `ALLOWED_OCCURRENCES` set with a justification comment. Should stay near-empty.

---

## 7. Provenance requirements

Every extracted claim in the rich data dictionary must trace to:

1. **Source document or file** — full path or URL
2. **Source location** — section heading, paragraph number, line number, table cell, column name
3. **Source text snippet** — the actual text the value was drawn from (not invented), truncated to 200 chars
4. **Extractor run** — which extractor (A/B/C/D), with what version, when (ISO timestamp)
5. **Confidence score** — per the rubric in section 3
6. **Conflict status** — empty if no conflict, populated with rejected values if a conflict was detected and resolved

If any of these can't be filled, the value is suspect. The Excel exporter shows missing provenance as a yellow warning.

---

## 8. Failure modes (loud, never silent)

When extraction goes wrong, the system says so loudly. Specific behaviors:

- **0 elements extracted** → CLI exits with code 2, refuses to write Excel/JSON output, prints likely causes
- **All elements have confidence < 0.5** → CLI exits with code 3, writes output anyway (so the human can inspect what was extracted), but explicitly tells the user it's untrustworthy
- **Per-document warnings** when an individual document yielded 0 elements during a multi-doc run
- **Routing decision uncertainty** → router refuses to auto-route if confidence < 0.9
- **OntoGPT subprocess failure** → CLI surfaces the actual stderr from OntoGPT, not a generic "extraction failed"
- **Schema introspection failure** → CLI reports the database error verbatim
- **Unresolved merge conflicts** → fusion exit code reflects this; lint report flags them prominently

The principle: if the human walks away thinking "the run succeeded" but the output is wrong, that's the worst possible failure mode. Every component is designed to make this impossible.

---

## 9. Living knowledge base operations

The knowledge base supports three standing operations:

### Ingest
A new file lands → router classifies → appropriate extractor runs → result merges into the accumulated fused knowledge → log entry written. Triggered by:
- `ontozense ingest <path>`
- `ontozense ingest <directory>` (recursive)
- (Future) Watcher daemon on a folder

A single ingest may touch many derived artifacts: the per-source extraction file, the fused knowledge base, the index, the gap report, the log.

### Query
An analyst asks a question against the accumulated knowledge → result is rendered as Excel, markdown comparison, or rich format → optionally **filed back** as a new derived artifact under `<domain>/derived/analyses/`. Filed-back artifacts become input to subsequent fusion runs.

### Lint
A periodic consistency check across the entire fused knowledge base. Reports:
- **Contradictions** between sources for the same field
- **Stale claims** that newer sources have superseded
- **Orphan terms** mentioned in one source but never used elsewhere
- **Undefined but used** concepts that appear as relationship targets without their own definition
- **Missing cross-references** between related concepts
- **Coverage gaps** where rich-DD fields have no source providing them

Lint is the gap report generalized to operate on the **fused** knowledge base, not on a single extraction.

---

## 10. Per-domain log format

Each domain has its own `log.md` at `<domain>/log.md`. Append-only, grep-parseable.

Format:
```
## [YYYY-MM-DD] <op> | <key1>=<val1> | <key2>=<val2> | ...
```

Examples:
```
## [2026-04-08] ingest | source=basel-d403.pdf | route=A | confidence=0.95 | reason=md_with_section_headings
## [2026-04-08] extract-a | source=basel-d403.pdf | concepts=47 | relationships=23 | confidence_avg=0.71 | log=output/npl/derived/source_a/basel-d403.json
## [2026-04-08] extract-b | source=ssfabn.xlsx | rows=98 | columns_mapped=12 | unmapped=0
## [2026-04-08] fuse | sources=A+B+C | entities=22 | relationships=25 | properties=170 | conflicts=3
## [2026-04-08] lint | orphans=4 | contradictions=2 | stale=0 | undefined_used=1 | gaps=8
## [2026-04-08] query | "compare default definitions" | result=output/npl/derived/analyses/default-comparison.md
```

Grep examples:
```bash
grep "^## " npl/log.md | tail -10           # last 10 operations
grep "ingest" npl/log.md                    # all ingest operations
grep "conflicts=[1-9]" npl/log.md           # operations that had conflicts
```

---

## 11. Citation policy

Every methodological claim in our docs, prompts, and design rationale cites its source. We do not invent methodology.

Currently cited:
- **SPIRES** (Caufield et al. 2024, *Bioinformatics*) — `docs/SPIRES.md` — Source A concept/relationship identification
- **AI-RBX methodology** — `docs/AI-RBX.pdf` — Source D code-based business rule extraction
- **Karpathy "LLM Wiki" gist** — for the Ingest/Query/Lint trichotomy and append-only log pattern (Step 1 of plan)
- **Direct database introspection** — well-known engineering practice, no specific citation needed

If we add a new technique, it goes in this list with a citation. If we can't cite a battle-tested source for a method, we don't use it.

---

## 12. Model selection findings

Documented results from real Basel D403 extractions during Step 2 verification.
The same input (`tests/fixtures/npl-basel-guidelines.md`), the same template
(`templates/domain_doc_extraction.yaml`), the same regex enrichment pass —
only the model differs.

| Model | LLM concepts | Total concepts | Relationships | LLM at ≥80% | Notes |
|---|---:|---:|---:|---:|---|
| `azure/gpt-5.2` | 11 | 17 (11 + 6 regex) | 18 | 11 of 11 | conservative; misses several reporting fields and state transitions |
| `azure/gpt-5.4` | **26** | **30** (26 + 4 regex) | **24** | **25 of 26** | catches reporting fields (gross carrying amount, value adjustments), state transitions (continuous repayment period, probation period), business rule constraints (collateralisation has no direct influence) |

**Finding:** model choice dominates prompt engineering for Source A. The
template, regex pass, and term filter together contribute maybe 20-30% to
output quality. Switching from `gpt-5.2` to `gpt-5.4` more than **doubles**
LLM-validated concept count (11 → 26) at the same or higher quality, with
no template change.

**Recommendation:** Use `azure/gpt-5.4` (or newer) as the default for
Source A extraction. This is now the CLI default in `extract-a`.

**Why gpt-5.4 is better here:** It is more willing to recognize reporting
fields, state transitions, and business rule subjects as concepts, while
gpt-5.2 was overly conservative and stayed at the level of "core
definitional terms" only. gpt-5.4 also produces relationship triples that
capture constraints (`collateralisation has no direct influence on
categorisation of non-performing exposures`) — exactly the business-rule
shape we want.

**What this implies for other Sources:** Source D (code extraction via
AI-RBX methodology) will likely show the same model-sensitivity. Source B
(structured Excel parser) is deterministic and shouldn't depend on model
choice. Source C (database introspection) is also deterministic. Track
model-vs-output comparisons whenever a new source lands.

**Cost note (informal):** The gpt-5.4 run cost roughly the same as the
gpt-5.2 run for a 140KB document — both well under $1 per extraction.
The output is more than 2× richer for the same money. This is a good
default.

## 13. What is NOT in this playbook (yet)

Things we'll add as decisions are made:

- Per-domain authority order (currently default A > B > C > D for all domains)
- Per-domain naming normalization rules (synonym maps live in domain config, not in code)
- Per-step model selection criteria (default for Source A is `azure/gpt-5.4` per §12; Sources B/C are deterministic and model-independent; Source D's LLM labelling pass will need its own default once implemented)
- Cost / latency budgets (per-document, per-domain)
- Multi-tenant / SaaS conventions (deferred — single-user CLI for now)
- Schema-evolution / versioning UI conventions

When one of these decisions is made, document it here first, then implement.

---

## Document history

- **2026-04-08** — Initial version. Created after the first real Basel D403 extraction revealed that the original 13-field-from-one-source approach was wrong. Established the four-source architecture, the source-to-field mapping, the confidence rubric, the conflict resolution rules, the routing rules, and the Karpathy-inspired ingest/query/lint operations.
