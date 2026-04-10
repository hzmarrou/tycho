# Why the Playbook?

`docs/PLAYBOOK.md` is the **negotiated convention layer** of Ontozense — the single document where every "how does Ontozense decide X?" question is answered, in plain English, so both humans and LLMs can read it.

It is **not** code, not a spec, and not a README. It exists because the four-source pipeline has many small judgment calls — which source provides which field, what counts as a high-confidence value, who wins in a conflict, when to flag a routing decision — and those calls need to live in **one** place that everyone can grep.

---

## What it codifies

The playbook is organised into 13 sections. Each one pins down a class of decision that would otherwise drift across docstrings, comments, config files, and human memory.

| § | What it pins down | Why it matters |
|---|---|---|
| 1 | The four sources (A/B/C/D) and what each one defensibly provides | Stops anyone asking one source to produce fields it can't honestly know |
| 2 | **Source-to-field mapping table** — for every rich-DD field: primary source, fallback, "leave empty if neither" | The fusion layer reads this to decide where each field comes from |
| 3 | **Confidence rubric** — field-aware (ENUM / CITATION / NARRATIVE / CATEGORICAL / STRUCTURED) | Implemented in `domain_doc_extractor.py`. Anyone tempted to "just give it 0.8" reads §3 instead |
| 4 | **Conflict resolution order** — priority → confidence → recency → human | Fusion layer's tie-breaker logic comes from here |
| 5 | **Routing rules** — extension table + content-sniff heuristics + multi-source dispatch | The router (`router/router.py`) is an implementation of §5 |
| 6 | **Domain neutrality** — banned terms, allowed exceptions | The regression test enforces it; humans editing `src/` consult §6 |
| 7 | **Provenance requirements** — 6 mandatory fields per claim | The Excel exporter shows missing provenance as a yellow warning |
| 8 | **Failure modes** — exit code 2 (zero output), exit code 3 (all-low-confidence) | Codifies "loud, never silent" |
| 9 | Ingest / Query / Lint trichotomy | The CLI surface |
| 10 | **`log.md` format** — `## [date] op \| key=val` | `log.py` writes it; `grep` reads it |
| 11 | **Citation policy** — every method we use cites a source (SPIRES, AI-BRX, ...) | Stops us inventing methodology |
| 12 | **Model selection findings** — gpt-5.4 vs gpt-5.2 (2.4× richer output) | Justifies the CLI default |
| 13 | "Not in playbook yet" | Honest about open decisions |

---

## Three concrete roles it plays day-to-day

### 1. Reference for the fusion layer

When `core/fusion.py` is written (Step 6), it will literally implement the table in §2 and the rules in §4 — no second-guessing, no scattered constants. The playbook is the spec; the code is the implementation.

### 2. Onboarding doc for a new contributor (or a new LLM session)

Drop `PLAYBOOK.md` into context and the model knows the architecture, the conventions, the banned terms, and the rationale — without anyone having to re-explain anything. The same applies to a human joining the project: one document, in order, gets them productive.

### 3. Negotiation surface

When the rules change ("for healthcare we want governance > regulations, not the other way around"), you edit §4 and the change propagates. The doc is the contract; code follows it.

Without the playbook, these decisions would be scattered across docstrings, comments, config files, and memory — and the system would silently drift.

---

## The pattern it follows

This is adapted from Karpathy's "LLM Wiki" gist: in his model, the human-curated markdown is the **durable artifact** and everything else (LLM state, derived files) is **regenerable from it**.

`PLAYBOOK.md` is Ontozense's version of that — the one file you'd keep if you had to throw everything else away. Code can be rewritten from the playbook. The playbook cannot be rewritten from the code.

---

## How it stays honest

Three properties keep the playbook from becoming stale lore:

1. **It is a living document.** Section history at the bottom records when each decision was made and why. Edits are deliberate and reviewed.
2. **It cites its sources.** Section 11 enforces that every methodological claim has a battle-tested citation (SPIRES, AI-BRX, Karpathy's gist, ...). If we can't cite a source for a method, we don't use it.
3. **Section 13 is honest about gaps.** "Not in this playbook yet" lists the decisions that are still open. When one is made, it gets documented in the playbook *first*, then implemented.

---

## When to consult it

- Before implementing the fusion layer or any cross-source merge logic → §2, §4
- Before adding a new extractor or changing an extractor's output shape → §1, §7
- Before tweaking confidence scores → §3
- Before adding a new file type to the router → §5
- Before adding code to `src/ontozense/` that uses a domain-specific term → §6
- Before changing the CLI's failure behaviour → §8
- Before changing the default LLM model → §12
- When a behaviour surprises you → "check the playbook"
