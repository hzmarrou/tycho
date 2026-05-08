# Tycho Source-C Adapters

This directory holds **example adapters** that produce Tycho's
Source C JSON contract from various upstream schema formats. They are
bundled with the repo as worked examples; they are **NOT part of the
installed `ontozense` Python package**.

## The contract

Tycho's `core/source_c.py` defines the typed contract:

```
SchemaResult
├── models: list[SchemaModel]
│   ├── name, doc, source_file
│   ├── fields: list[SchemaField]
│   │   ├── name, field_type, playground_type
│   │   ├── is_primary_key, is_nullable, max_length
│   │   ├── choices_var, choices_values
│   │   └── id, entity_type           ← profile-mode only
│   ├── relationships: list[SchemaRelationship]
│   │   ├── field_name, from_model, to_model
│   │   ├── on_delete, is_nullable, help_text
│   │   └── (no profile-mode fields)
│   └── id, entity_type               ← profile-mode only
└── source_dir
```

All adapters target this shape and emit it as JSON via
`dump_source_c_json(result, output_path)`. Tycho's fuse command
consumes any conforming JSON via `--source-c source-c.json`.

## Available adapters

| Directory | Upstream format | Status |
|---|---|---|
| [`django/`](django/) | Django models.py (Python AST, no DB connection) | Stable |
| [`postgres/`](postgres/) | Live PostgreSQL via `information_schema` | Stable |

## Writing your own

Examples of formats Tycho doesn't ship adapters for but you could
write one for in 50–100 lines:

- **dbt** — `manifest.json` from a `dbt compile` run
- **SQLAlchemy** — runtime model introspection or AST parsing
- **Pydantic / dataclasses** — Python AST or schema export
- **OpenAPI / JSON Schema** — flat schema files
- **Catalogue exports** — Collibra / Alation / DataHub / Atlas
- **ERWin / Sparx EA** — XMI / XML exports
- **Information Schema dumps** — CSV / JSON from any RDBMS

The pattern is always: read your format → build the typed
dataclasses → optionally call `apply_profile_to_schema(result, profile)`
for profile-mode metadata → `dump_source_c_json(result, path)`.
