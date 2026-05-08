# Django Source C Adapter

This is one example of how to produce a Tycho **Source C JSON** file
from an upstream schema format. It reads Django `models.py` files via
Python AST (no Django runtime, no live database) and emits a typed
`SchemaResult` JSON conforming to the contract defined in
[`ontozense.core.source_c`](../../src/ontozense/core/source_c.py).

The adapter is **bundled with the Tycho repo as a worked example**
but is NOT part of the installed `ontozense` Python package. Tycho's
core consumes the JSON; the adapter just produces it.

## Usage

```bash
# Plain (unconstrained) mode
python -m adapters.django.django_to_json /path/to/django/app \
  --output source-c.json

# Profile mode — populates id and entity_type via the profile
python -m adapters.django.django_to_json /path/to/django/app \
  --profile /path/to/profile/dir \
  --output source-c.json
```

Then feed the JSON to Tycho:

```bash
ontozense fuse --source-c source-c.json …
```

## What the adapter parses

| Django construct | Source C field |
|---|---|
| `class Foo(models.Model)` | `SchemaModel(name="Foo")` |
| `name = models.CharField(max_length=20)` | `SchemaField(name="name", field_type="CharField", playground_type="string", max_length=20)` |
| `models.IntegerField(null=True)` | `SchemaField(is_nullable=True)` |
| `models.CharField(choices=STATUS_CHOICES)` | `SchemaField(playground_type="enum", choices_var="STATUS_CHOICES", choices_values=["active", "paid", …])` |
| `models.ForeignKey(Counterparty, …)` | `SchemaRelationship(from_model="…", to_model="Counterparty")` |
| `models.OneToOneField(…)`, `models.ManyToManyField(…)` | `SchemaRelationship(…)` |

`STATUS_CHOICES = [(0, 'Active'), (1, 'Paid')]` definitions in a
`*_choices.py` file are also picked up — the adapter reads them in a
first pass and resolves the labels into `choices_values`.

## What it doesn't do

- **Doesn't connect to a database.** AST-only, source-of-truth is
  the Python code. If the live DB schema diverges from the models
  (raw migrations, manual columns), this adapter won't see it.
- **Doesn't handle non-Django ORMs.** SQLAlchemy, Pydantic, dbt, raw
  SQL DDL — write a separate adapter targeting the same JSON contract.
- **Doesn't extract docstrings beyond the class docstring.** Per-field
  `help_text` is captured; per-field comments are not.

## Writing your own adapter

The Source C contract is the typed dataclasses in
[`ontozense.core.source_c`](../../src/ontozense/core/source_c.py):

- `SchemaResult` (top-level: a list of `SchemaModel`)
- `SchemaModel` (one entity / table)
- `SchemaField` (one column / attribute)
- `SchemaRelationship` (one foreign-key edge)

Build the dataclasses from your source format, optionally call
`apply_profile_to_schema(result, profile)` for profile-mode metadata,
then `dump_source_c_json(result, output_path)` and you're done.

A 50-line adapter targeting `INFORMATION_SCHEMA` from any RDBMS is
plenty.
