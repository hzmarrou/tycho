# Review prompt — Source B anchors + Source C refactor fixes (Tycho)

Paste everything below this line into GPT 5.5.

---

You are reviewing two consecutive commits on **Tycho** (formerly
Ontozense), an ontology / data-dictionary extractor. Tycho fuses
information from four sources (authoritative documents via LLM,
governance JSON, database schema via adapter, production code) into a
typed rich data dictionary.

You reviewed an earlier refactor on this same project — commit
`9c90036` — and flagged four issues (`schema_version` not enforced,
`DjangoSchemaParser` import path break, missing e2e test, CLI hint).
This review covers the follow-up commits that addressed those plus
the next piece of work.

The repo is at `https://github.com/hzmarrou/tycho` (branch `main`).
Two commits to review:

1. **`d736d56`** — fixes the four issues from your previous review.
2. **`c2b39b6`** — Source B (governance JSON) anchor extraction:
   captures line / column / snippet of each entry in the source
   file and threads it into `FieldAnchor` metadata at fusion.

The rest of the project (Phases 1–7, the Source C refactor itself)
was already cleared in earlier reviews and is **out of scope** here.

## Files to focus on

For commit `d736d56` (review-fix follow-up):

1. `src/ontozense/core/source_c.py` — see new `SourceCContractError`
   exception and the validation in `load_source_c_json`.
2. `src/ontozense/extractors/__init__.py` — see the `__getattr__`
   shim that intercepts `DjangoSchemaParser` imports.
3. `src/ontozense/cli.py` — search for `source_c_dir` (≈line 1665)
   to see the directory-input migration hint and the new
   `SourceCContractError` catch block.
4. `pyproject.toml` — note the `version = "1.0.0"` bump.
5. `CHANGELOG.md` — first-ever changelog, documents the upgrade
   and the Source C breaking change.
6. `tests/test_source_c_contract.py` — new test classes
   `TestLoaderContractValidation` (6 tests),
   `TestCliSourceC` (2 tests), `TestEndToEndAdapterToFuse` (1
   test), `TestDjangoSchemaParserImportShim` (2 tests).

For commit `c2b39b6` (Source B anchors):

7. `src/ontozense/extractors/governance_extractor.py` — new
   `source_anchor` field on `GovernanceRecord`; new
   `_parse_with_positions`, `_compute_line_starts`,
   `_offset_to_line_column` helpers; deferred FieldAnchor import.
8. `src/ontozense/core/fusion.py` — see `_merge_source_b` (≈line
   400). Notice `b_anchor = getattr(rec, "source_anchor", None)`
   is threaded into every `_set_field` call, plus the citation
   merge falls back to B's anchor when A is unanchored.
9. `tests/test_governance_extractor.py` — new `TestSourceBAnchors`
   class (6 tests).
10. `tests/test_phase6_provenance_anchors.py` — new
    `TestSourceBAnchorThreading` class (3 tests).

## What I want you to evaluate

### A — Source C refactor fixes (commit `d736d56`)

#### A1. `schema_version` validation strictness

`load_source_c_json` now raises `SourceCContractError` when:
- the root isn't a JSON object;
- `schema_version`'s major isn't in `SUPPORTED_MAJOR_VERSIONS = {"1"}`;
- the `models` key is missing or not a list.

Pre-versioning files (no `schema_version` key at all) still load,
defaulting to `"1.0"`.

- Is the strictness right, or too strict / too loose?
- Should `SUPPORTED_MAJOR_VERSIONS` ever be a property of the
  installed Tycho version, not a hardcoded set? (For future
  multi-major support.)
- Is the no-`schema_version`-tolerated-as-1.0 default right?
  Argument for: backward compat with adapter outputs from before
  the field existed. Argument against: silently accepting unversioned
  files in 5 years' time when the contract has moved on.

#### A2. The `__getattr__` ImportError shim

`src/ontozense/extractors/__init__.py` defines a module-level
`__getattr__` that raises a targeted `ImportError` when someone tries
`from ontozense.extractors import DjangoSchemaParser`, with both
migration paths in the message. Other unknown attribute lookups still
raise plain `AttributeError`.

- Is the shim's error message clear enough for a user hitting it
  cold? Does it tell them what to do?
- Module-level `__getattr__` is a Python 3.7+ feature; is this the
  right pattern, or would you push for a deprecated stub class
  that raises at instantiation time instead?
- Should this shim live forever, or be removed in some future
  major version?

#### A3. The end-to-end smoke test

`TestEndToEndAdapterToFuse::test_synthetic_schemaresult_dump_then_fuse_consumes`
constructs a `SchemaResult` programmatically, dumps it via
`dump_source_c_json` (the documented adapter API), then runs `fuse
--source-c <json>` and asserts a Source-C-contributed field
(`data_type`) bubbles through.

- Is "construct SchemaResult, dump, fuse" the right e2e shape, or
  should the test go further and actually invoke the bundled
  Django adapter as a subprocess?
- Anything missing from this single test that a future refactor
  would silently break without surfacing here?

#### A4. CLI directory-input migration hint

When `--source-c` is passed a directory (the pre-1.0 input shape),
the CLI now refuses but prints the inline migration command:
`python -m adapters.django.django_to_json <models_dir> --output source-c.json`.

- Is the hint specific enough? It assumes the user has Django
  models. What if they have something else?
- Should the CLI try to detect the source format heuristically and
  point at the right adapter?

### B — Source B anchor extraction (commit `c2b39b6`)

#### B1. The position-tracking JSON parser

`_parse_with_positions(text)` walks JSON manually using
`json.JSONDecoder.raw_decode()` to record each entry's character
offset in the source file. Supports both single-object inputs and
top-level arrays.

- Is the approach sound? Alternatives I considered: `ijson`
  streaming parser (third-party dep), regex search for
  `"element_name": "..."` (fragile on multi-occurrence values),
  custom tokenizer (overkill).
- Edge cases: entries containing brace-quoted strings (`"foo": "{"`),
  JSON5 trailing commas, single-quoted JSON, bool/null at top level
  — does the parser handle / fail-loudly on any of these?
- Numerical correctness: for a pretty-printed array
  `[\n  {…},\n  {…}\n]`, are the (line, column) anchors of each
  entry correct (1-indexed, both)?

#### B2. The deferred-import circular-import fix

`governance_extractor.py` imports `FieldAnchor` from `core.fusion`
inside `extract_from_file()` rather than at module load. The reason:
`core.fusion` already imports from `extractors` at module load, so a
top-level `from ..core.fusion import FieldAnchor` creates a cycle.

- Is the deferred import the right fix, or would you push for
  moving `FieldAnchor` to a smaller leaf module (e.g.
  `core/anchor.py`) so both `fusion` and `governance_extractor` can
  import it without cycling?
- The `TYPE_CHECKING` import is there for type-checker happiness;
  is that pattern the cleanest, or would you push for using a
  string literal annotation instead?

#### B3. The `_merge_source_b` anchor threading

`b_anchor = getattr(rec, "source_anchor", None)` is read once per
record and threaded into every `_set_field` call for B-contributed
fields (definition, is_critical, domain_name). The A+B citation
merge path uses `existing.anchor or b_anchor` — A's anchor wins if
present, B's is the fallback.

- Is "same anchor for every B field" the right shape? Source B
  records don't have per-field anchors (the whole entry has one
  position in the source file), so this is structurally OK — but
  worth your second opinion.
- Is the citation merge logic correct? Specifically: A's anchor
  is preserved when A is anchored; B's takes over when A isn't.
  But if BOTH are anchored, B's anchor data is silently dropped.
  Is that right, or should we record the A+B merge with both
  anchors somehow?
- The `getattr(rec, "source_anchor", None)` defensive default —
  is that justified, or should we hard-require the field on
  `GovernanceRecord` (which it now is in the dataclass anyway)?

#### B4. Test coverage for Source B anchors

`TestSourceBAnchors` covers: array entries on distinct lines,
filename in `segment_id`, snippet starts with `{`, single-object
anchored at offset 0, column reflects indentation, programmatic
records have no anchor.

- Anything obviously missing? Unicode in snippets, very large
  files, files with BOM, anchors when `extract_from_file` reads a
  file with mixed line endings?
- The threading tests in `TestSourceBAnchorThreading` cover B-only
  records and the A+B citation merge with/without A's anchor.
  Is the matrix complete?

### C — Anything else worth flagging

Concerns about: dataclass design, naming, docstrings, documentation
gaps, unhandled error paths, things a future maintainer would trip
over. Don't redo the architectural review you already did on
`9c90036`.

## Output format

```
## Verdict

One or two sentences. Specific to these two commits.

## What works well

3–5 brief bullets.

## Issues

Numbered. Each:

   N. [severity: blocker | major | minor | nit] Brief title.
      File path : line range or "design".
      Specific concern.
      Suggested fix.

## Anything else

Optional closing notes. "n/a" is fine.
```

3 pages max. Concrete > abstract. Specific file paths and line
numbers > general principles. If you can't access
`github.com/hzmarrou/tycho`, say so up front and ask for the relevant
files to be pasted.
