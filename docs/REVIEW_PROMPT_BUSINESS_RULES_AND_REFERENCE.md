# Review prompt — typed BusinessRule + reference-benchmark mode (Tycho)

Paste everything below this line into GPT 5.5.

---

You are reviewing **Tycho** (formerly Ontozense), an ontology /
data-dictionary extractor that fuses information from four sources
into a typed rich data dictionary.

You've reviewed three earlier rounds on this project. This is the
**final code-review round** before the project's wrap-up phase
moves to real-data validation runs and a v1.0.0 release tag.

Two commits to review on `https://github.com/hzmarrou/tycho` (branch
`main`):

1. **`abeea81`** — wrap-up #1: typed `BusinessRule`. Restructures
   `FusedElement.business_rules` from `list[str]` to
   `list[BusinessRule]` with anchor support. Activates the
   dormant `_anchor_from_code_provenance` helper Phase 6 defined.
2. **`8103235`** — wrap-up #3: reference-benchmark mode. Adds a
   `--reference <ref.json>` flag to `ontozense report` that compares
   the fused output against a curated reference data dictionary
   and emits precision / recall / F1 for elements and
   relationships.

The earlier work (Phases 1–7, Source C refactor, Source B anchors,
subtype coverage) is **out of scope** here — already cleared.

## Files to focus on

For commit `abeea81` (typed BusinessRule):

1. `src/ontozense/core/fusion.py` — see new `BusinessRule`
   dataclass (≈line 140), the changed
   `FusedElement.business_rules` annotation (≈line 173),
   `_build_business_rule()` classmethod (≈line 680), and the
   updated `_merge_source_d` (≈line 600).
2. `src/ontozense/core/query.py` — search for `business_rules`
   to see the `.description`/`str()` fallback rendering pattern.
3. `src/ontozense/cli.py` — see `_serialize_business_rule()`,
   `_business_rule_from()` (the deserialiser with the pre-1.0
   string-payload backward-compat path), and the two call sites
   in `_serialize_element()` and the inline `fuse` output.
4. `tests/test_business_rules.py` — 8 new tests across 4 classes.
5. `CHANGELOG.md` — entry under "Changed (BREAKING)" documents
   the `list[str] → list[BusinessRule]` migration.

For commit `8103235` (reference-benchmark mode):

6. `src/ontozense/core/benchmark.py` — see new
   `ReferenceComparison` dataclass, `_element_match_key()` helper,
   `_f1()` helper, `_compute_reference_comparison()`, and the
   markdown-render block at the bottom of `render_markdown()`.
7. `src/ontozense/cli.py` — search for `--reference` to see the
   new flag and the load + parse-error UX.
8. `tests/test_phase7_benchmark.py` — new `TestReferenceComparison`
   (8 tests) and `TestCliReferenceFlag` (3 tests).

## What I want you to evaluate

### A — Typed BusinessRule (commit `abeea81`)

#### A1. Dataclass shape

`BusinessRule` has 10 fields: `rule_type`, `name`, `expression`,
`description`, `value`, `referenced_symbols`, `citations`,
`docstring`, `confidence`, `anchor`. Each maps to a `CodeRule`
field except `description` (the human-readable rendering, the
former `list[str]` payload).

- Are any fields missing? Are any redundant?
- `value: Optional[str] = None` — was originally `Optional[object]`
  on `CodeRule`. The build helper does `str(rule.value)` to
  flatten. Is that loss-of-fidelity acceptable, or should
  `BusinessRule.value` preserve the original type?

#### A2. The `_business_rule_from` backward-compat path

When reading a pre-1.0 fused JSON where `business_rules` is a
`list[str]`, the deserialiser wraps each string in a minimal
`BusinessRule` with only `description` set:

```python
def _business_rule_from(item) -> BusinessRule:
    if isinstance(item, str):
        return BusinessRule(rule_type="", name="", expression="",
                            description=item)
    ...
```

- Is this right, or would you push for refusing pre-1.0 payloads
  loudly with a migration message?
- The `_serialize_business_rule()` has the symmetric fallback for
  raw strings (in case anything sneaks them into a typed list).
  Belt-and-braces, or paranoid?

#### A3. AC1 implications of the breaking change

Pre-1.0 unconstrained pipelines that emitted `business_rules` saw
a JSON shape of `list[str]`. Tycho 1.0 emits `list[dict]` for the
same input. This is documented in CHANGELOG under "Changed
(BREAKING)". The version was already at 1.0.0 (bumped during the
Source C refactor).

- Was that the right call? An alternative was to keep the JSON
  shape `list[str]` (rendering only `description`) but expose
  the typed metadata as `business_rule_objects` (parallel field).
- Anything in the upgrade narrative that should mention this
  isn't?

#### A4. Activation of `_anchor_from_code_provenance`

The helper was a documented stub since Phase 6. `abeea81` activates
it via `_build_business_rule()`. Trace the path:
`CodeRule.provenance.{file_path, line, column, end_line, snippet}`
→ `FieldAnchor(line, column, end_line, snippet, segment_id=file_path)`.

- Is `segment_id=file_path` the right mapping? Source A used
  `segment_id` for section headings; Source B used it for the
  filename. Source D's choice of "file path" is consistent with B
  but inconsistent with A. Is that OK?
- Is the per-rule anchor independent of the per-element anchor on
  field_provenance? (i.e. does fusion store BOTH the rule's
  anchor AND a separate field anchor?) Look at `_merge_source_d`
  — it appends a `BusinessRule` but does NOT call `_set_field`
  for any element-level field. Is that intentional?

### B — Reference-benchmark mode (commit `8103235`)

#### B1. Element matching strategy

`_element_match_key(el)` returns `f"id:{eid}"` if the element has
a profile-mode `extra_fields["id"]`, else
`f"name:{normalise_name(el.element_name)}"`. The `id:` / `name:`
prefix prevents an element with id `"Customer"` colliding with a
name match on `"Customer"`.

- Is the prefix scheme robust enough? What if a real id literal
  happens to start with `"name:"`? (Edge case but worth a sanity
  check.)
- Should the matching key family include `entity_type` to avoid
  conflating different-type entities that happen to share a
  normalised name? The current code matches `"Default"` (a
  Concept) against `"Default"` (a Rule) by name.

#### B2. Relationship matching

`_rel_key(rel)` is `(normalise_name(subj), pred.lower(),
normalise_name(obj))`. Source is intentionally NOT in the key —
the same triple from A and from C count as one match.

- Is that right, or should the source be in the key (so the
  reference can prescribe "this relationship should be confirmed
  by source X")?
- Lowercased predicate: matches benchmark profile-coverage policy
  but means a profile with both "MapsTo" and "maps_to" as
  distinct predicates would have those collide here. Edge case
  worth flagging?

#### B3. Field-level coverage gap

The current implementation reports element-level and
relationship-level P/R/F1, but doesn't compute "for matched
elements, what % of reference fields did fusion populate?" —
e.g. the reference says element X has `data_type=string` and
`is_critical=true`, fusion produced X but only with `data_type`.

- Is this a real gap worth filling now, or fine to defer?

#### B4. Edge cases

- Empty reference vs nonempty fused → all P=R=F1=0.
  ✓ tested.
- Empty fused vs nonempty reference → all 0. ✓ tested.
- Both empty → all 0. (Implicit; not explicitly tested.)
- Reference has the same element twice (duplicate `element_name`
  with the same id) → my dict comprehension silently drops the
  second; the count is correct but `missing_elements` /
  `extra_elements` may not. Worth surfacing or fine?
- Profile mode with id collisions across reference and fused
  (different surface names, same id, different content) — what
  should happen? My code says "match" (because they share the
  ID); reasonable but worth confirming.

#### B5. Markdown rendering

The reference section in markdown shows a P/R/F1/TP/FP/FN table
plus truncated missing/extra lists (cap 20, "…" if longer).

- Is the cap the right policy, or should the full list go
  somewhere (e.g. an appendix-style block at the end of the
  report)?

### C — Anything else

Concerns about: dataclass design, naming, documentation, missing
tests, AC1 contract clarity, things a future maintainer would
trip over. Don't redo the architectural review of earlier work.

## Output format

```
## Verdict
One or two sentences.

## What works well
3–5 brief bullets.

## Issues
Numbered:

   N. [severity: blocker | major | minor | nit] Brief title.
      File path : line range or "design".
      Specific concern.
      Suggested fix.

## Anything else
"n/a" is fine.
```

3 pages max. Specific file paths > general principles. If you
can't access `github.com/hzmarrou/tycho`, ask for the relevant
files to be pasted up front.
