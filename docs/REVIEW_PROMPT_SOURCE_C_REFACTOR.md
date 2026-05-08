# Review prompt — Source C adapter refactor (Tycho)

Paste everything below this line into GPT 5.5.

---

You are reviewing a refactor of an open-source Python project called
**Tycho** (formerly Ontozense). Tycho is an ontology / data-dictionary
extractor that fuses information from four sources (authoritative
documents via LLM, governance JSON, database schema, production code)
into a typed rich data dictionary.

The refactor in question is commit `9c90036` on
`https://github.com/hzmarrou/tycho` — branch `main`. It splits the
"Source C" (database schema) extractor out of the installed Python
package and into a separate `adapters/` directory. The motivation:
the previous design hard-coupled Tycho to Django ORM users; the new
design exposes a typed `SchemaResult` JSON contract that any adapter
can target (Django, dbt, SQLAlchemy, INFORMATION_SCHEMA, OpenAPI,
catalogue exports, etc.).

## Files to focus on

Please read these files from the repo (commit `9c90036`):

1. `src/ontozense/core/source_c.py` — the new typed contract +
   JSON helpers + `apply_profile_to_schema` function.
2. `adapters/django/django_schema.py` — the Django parser, moved
   out of the package.
3. `adapters/django/django_to_json.py` — the adapter's CLI entry
   point.
4. `adapters/README.md` and `adapters/django/README.md` — the
   adapter-authoring docs.
5. `src/ontozense/cli.py` — search for `def fuse(` and read how
   `--source-c` is now wired (lines around 1660–1700).
6. `tests/test_source_c_contract.py` — the new core contract tests.
7. `adapters/django/tests/conftest.py` and
   `adapters/django/tests/test_django_source_c_profile.py` — the
   adapter test pattern (sys.path manipulation, end-to-end parser
   tests).
8. `pyproject.toml` — see `[tool.pytest.ini_options]` for the
   test-path extension.

For context on what was before: the file `src/ontozense/extractors/django_schema.py`
existed before this commit and contained both the typed dataclasses
AND the Django parser. The refactor split them.

## What I want you to evaluate

### 1. Architectural soundness

- Is "adapters live outside the installed package, the package only
  owns the typed contract" the right boundary? Specifically: is
  there anything in `core/source_c.py` that probably belongs
  back in an adapter, or vice versa?
- The contract is versioned via a `schema_version` field
  (currently "1.0"). Is that mechanism enough, or would you push
  for something else (e.g. JSON Schema validation, a Pydantic
  model, semantic versioning across multiple adapter versions)?
- The `apply_profile_to_schema` function lives in core but is
  intended to be called by adapters. Is that the right call, or
  should profile-application happen in core *after* the adapter
  emits raw JSON (so adapters never touch profiles)?

### 2. JSON contract design

- Look at `SchemaField.to_json_dict()`, `SchemaModel.to_json_dict()`,
  `SchemaResult.to_json_dict()`. The contract omits `id` and
  `entity_type` keys when they're empty. Is that the right policy,
  or should they always be emitted (with empty defaults)?
- The `from_json_dict()` deserialisers use `.get()` with defaults
  so missing keys don't crash. Is that the right policy for forward
  compatibility, or would you push for stricter validation?
- Is anything missing from the contract? (e.g. column comments,
  table comments distinct from `doc`, schema name, catalog name,
  database vendor, indexes, unique constraints)

### 3. Adapter pattern

- The Django adapter uses a `sys.path.insert` trick in its tests'
  `conftest.py` to import `django_schema` directly. Is that
  pattern reasonable for "non-installed but discoverable" adapter
  modules, or would you push for something different (e.g. install
  adapters as namespace packages, use plugin entry points,
  publish them as separate PyPI distributions)?
- Adapter README and adapters/README — do they tell an adapter
  author enough to write their own?
- The CLI calls `load_source_c_json` and surfaces clean errors.
  Anything missing from the CLI UX?

### 4. Testing strategy

- `tests/test_source_c_contract.py` tests the core module in
  isolation. `adapters/django/tests/test_django_source_c_profile.py`
  tests the parser end-to-end. The boundary between the two is:
  core tests use synthetic `SchemaResult` fixtures (no Django code
  loaded); adapter tests parse actual Django-shaped strings. Is
  that the right boundary?
- Anything obviously missing? (e.g. a test that the JSON output of
  the Django adapter is consumable by `fuse --source-c`, an
  end-to-end roundtrip, schema_version migration)

### 5. Backward compatibility

- The previous `fuse --source-c` accepted a directory path. The new
  one expects a JSON file. The CLI errors clearly when a directory
  is given but doesn't suggest the migration path. Is that fine, or
  worth a note like "Did you mean to run `python -m
  adapters.django.django_to_json` first?" in the error message?
- The `extractors/__init__.py` previously exported
  `DjangoSchemaParser`. It now exports only `SchemaResult` (re-
  imported from `core.source_c`). Will this break anyone importing
  `from ontozense.extractors import DjangoSchemaParser`? Worth
  noting in a CHANGELOG or release notes? 

### 6. Anything else worth flagging

Concerns about names, docstrings, dataclass design, documentation
gaps, things a future maintainer would trip over.

## Output format

Please reply in this shape, sections in order:

```
## Verdict

One or two sentences. "Sound and ready" / "Needs X before merge" /
"Significant concern: …".

## What works well

3–5 bullet points, brief.

## Issues

Numbered list. Each item:

   N. [severity: blocker | major | minor | nit] Brief title.
      File path : line range or "design".
      Specific concern.
      Suggested fix.

## Anything else

Optional. Closing thoughts, future-work suggestions, or "n/a".
```

Don't write more than ~3 pages. Concrete > abstract; specific file
paths and line numbers > general principles. If you can't access the
repo on `github.com/hzmarrou/tycho`, say so up front and ask for the
relevant files to be pasted.
