# Changelog

All notable changes to Tycho (the Python package is `ontozense`).

## [1.0.0] — 2026-05

The 7-phase PRD upgrade is complete plus the post-upgrade adapter
refactor (Source C). This is the first stable release.

### Added

- **Profile system** (Phase 1). Optional `--profile <dir>` flag on
  `extract-a` constrains the LLM to a declared vocabulary and
  produces deterministic IDs. See `docs/PROFILE_SPEC.md` and
  `docs/profile-examples/esg/`.
- **Profile-aware Sources B/C/D** (Phase 3). Cross-source ID
  alignment: same canonical (entity_type, label) tuple → same ID
  across sources.
- **Validation stage** (Phase 4). New `ontozense validate` command
  with six structural rules (VR001–VR006) and `flag` / `filter`
  modes.
- **Multi-doc + cross-source consolidation in fusion** (Phase 5).
  `ontozense fuse --source-a` is now repeatable; concepts that share
  an id (profile mode) or normalised name (unconstrained) collapse
  into one element with `corroborating_doc_count` and
  `source_documents` tracked.
- **Typed per-field provenance anchors** (Phase 6). `FieldAnchor`
  on `FieldProvenance` carries page / char offset / line / column /
  segment_id / snippet so reviewers can trace fused fields back to
  exact source spans.
- **Benchmark report** (Phase 7). `ontozense report` produces a
  pipeline-health snapshot (element counts, confidence
  distribution, conflict stats, anchor coverage, multi-doc
  corroboration, profile coverage with subtype-level detail) as
  both JSON (machine-diffable) and Markdown (human-readable).

### Changed (BREAKING)

- **`FusedElement.business_rules` is now `list[BusinessRule]`, not
  `list[str]`.** Each rule carries `rule_type`, `name`, `expression`,
  `description` (the human-readable rendering), `value`,
  `referenced_symbols`, `citations`, `docstring`, `confidence`, and
  an optional `FieldAnchor` (file/line/column/end_line/snippet). The
  Phase 6 `_anchor_from_code_provenance` helper that was a documented
  stub now actively threads source coordinates from `CodeRule`
  through to every typed rule.
  - Migration: anywhere reading a rule, switch from `for rule_str
    in el.business_rules` (string) to `for rule in el.business_rules:
    rule.description` (typed).
  - Pre-1.0 fused JSONs with `business_rules: ["…"]` (raw strings)
    are still loadable: each string wraps in a minimal `BusinessRule`
    with only `description` set.

- **Source C contract is now a JSON file, not a Python parser
  invocation.** `ontozense fuse --source-c <path>` expects a
  `SchemaResult` JSON file produced by an adapter, not a Django
  models directory. The Django parser moved out of the installed
  package to `adapters/django/`.
  - Migration: run
    `python -m adapters.django.django_to_json <models-dir> --output source-c.json`
    first, then feed `source-c.json` to `fuse`.
  - The CLI detects the old usage (passing a directory to
    `--source-c`) and prints the migration command inline.
  - The PostgreSQL `information_schema` adapter also moved to
    `adapters/postgres/` for the same architectural reason.
- **`from ontozense.extractors import DjangoSchemaParser` raises a
  targeted ImportError** explaining the move and the migration
  paths (run the adapter CLI, or sys.path-import from
  `adapters/django/`).

### Removed

- Pre-1.0 hard coupling between Tycho and Django ORM users.
  Anyone with a different schema source (dbt, SQLAlchemy, raw SQL,
  INFORMATION_SCHEMA dump, OpenAPI, catalogue export) can now
  write a 50–100-line adapter targeting the typed
  `ontozense.core.source_c.SchemaResult` contract.

### Notes

- Source C JSON files declare `"schema_version": "1.0"`. Tycho
  rejects unsupported major versions loudly (no more "0 models
  silently parsed" failure mode that the post-Phase-7 review
  flagged).
- All seven phases preserved AC1 byte-identity for the no-profile
  / no-anchor / single-source path: pre-upgrade pipelines that
  worked still produce equivalent output.
- See `docs/PRD.txt`, `docs/REVIEW_*.md`, and the per-phase
  `docs/REVIEW_ASSIGNMENT_PHASE_*.md` files for the upgrade
  history and design rationale.
