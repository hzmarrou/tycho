# Profile Specification

A **profile** tells Ontozense what entity types, predicates, required
fields, and verb canonicalisations apply to a specific domain (ESG,
NPL, healthcare, telecom, ...). Profiles are **user-authored**, live
**outside the engine** (typically under `domains/<name>/profile/`),
and are **opt-in per run** via the `--profile` CLI flag.

This document is the contract between profile authors and the engine.
If you stick to it, your profile loads. If your profile loads,
constrained-mode extraction enforces it across all four sources.

## When to author a profile

You should author a profile when:

- Your domain has a known schema (regulator-mandated entity types,
  industry-standard predicates, a shared business glossary)
- You want **deterministic IDs** so the same concept gets the same
  identifier across runs and sources
- You want **schema validation** (catch entities of the wrong type,
  predicates outside the allowed vocabulary, missing required fields)
- You're extracting from **multiple documents** and need real
  consolidation (vs concatenation)

You don't need a profile for:

- Exploratory work on a brand-new domain
- Quick one-off extractions
- Domains where the entity vocabulary isn't yet stable

Without a profile, Ontozense's behaviour is unchanged from its
unconstrained default.

## Directory layout

A profile is a **directory** containing one required file and a
handful of optional sidecars:

```
profile/
├── schema.json              REQUIRED — types, predicates, IDs, aliases, verbs
├── prompt_fragment.md       OPTIONAL — Source A constrained-extraction prompt
├── alias_map.json           OPTIONAL — overlay/extend schema's alias_map
└── validation_rules.json    OPTIONAL — custom rules beyond schema (Phase 4)
```

Only `schema.json` is mandatory. Everything else extends the schema's
defaults.

## `schema.json` format

The single source of truth. Top-level structure:

```json
{
  "profile_name": "esg",
  "profile_version": "1.0.0",
  "description": "ESG metrics extraction (SASB / TCFD / IFRS S2)",

  "entity_types": { ... },
  "predicates": { ... },

  "id_format": { ... },
  "alias_map": { ... },
  "canonical_verbs": { ... }
}
```

### Required top-level fields

| Field | Type | Description |
|---|---|---|
| `profile_name` | non-empty string | Logical name. Appears in output JSON's `profile_name` metadata. Used in log entries. |
| `profile_version` | non-empty string | Semver string (e.g. `"1.0.0"`). Bump when changing entity types or predicates so downstream consumers can detect schema changes. |
| `entity_types` | non-empty object | Entity type declarations (see below). |
| `predicates` | object | Relationship predicate declarations (see below). May be empty if your domain only needs entities. |

### Optional top-level fields

| Field | Type | Description |
|---|---|---|
| `description` | string | Human-readable summary. |
| `id_format` | object | ID generation strategy (see below). Defaults to `{strategy: "type_label_hash", hash_length: 6}`. |
| `alias_map` | object | Maps lowercased synonyms → canonical labels. Used at extraction time to normalise variant spellings into one canonical form. |
| `canonical_verbs` | object | Maps lowercased verb phrases → canonical predicate names. Used to canonicalise free-form verb phrases the LLM produces. |

### `entity_types`

Maps a type name (PascalCase by convention) to its spec:

```json
"entity_types": {
  "Metric": {
    "required": ["measurement_type", "unit", "code"],
    "optional": ["disaggregations", "description"],
    "subtypes": ["DirectMetric", "CalculatedMetric", "InputMetric"]
  },
  "Industry": {
    "required": [],
    "optional": ["sector", "country"]
  }
}
```

Per type:
- `required` (list[str]): fields every instance must carry. Validation
  flags missing values.
- `optional` (list[str]): fields that may be present.
- `subtypes` (list[str]): finer-grained classifications. Subtypes
  inherit the parent's required/optional fields. The engine treats
  `is_known_type("DirectMetric")` as true if "DirectMetric" is a
  subtype of any declared type.

### `predicates`

Maps a predicate name (PascalCase by convention) to its spec:

```json
"predicates": {
  "IsCalculatedBy": {
    "subject_types": ["CalculatedMetric"],
    "object_types": ["Model"],
    "cardinality": "1:1"
  },
  "ConsistOf": {
    "subject_types": ["Category"],
    "object_types": ["Metric"],
    "cardinality": "1:N"
  }
}
```

Per predicate:
- `subject_types` / `object_types` (list[str]): the entity types
  allowed at each end of this relationship. May reference subtypes.
  All names must be declared in `entity_types` (or be a subtype of one).
- `cardinality`: one of `"1:1"`, `"1:N"`, `"N:1"`, `"N:N"`. Validation
  flags violations.

### `id_format`

```json
"id_format": {
  "strategy": "type_label_hash",
  "hash_length": 6
}
```

Currently only `"type_label_hash"` is supported. ID format:
`{entity_type_lower}_{normalized_label}_{hashN}`. Hash is the first
N hex chars of `SHA-256("{type_lower}|{normalized_label}")`.

`hash_length` must be ≥ 4. Default is 6 (24 bits, ~10⁵ collision-free
entities). Raise it for very large domains.

### `alias_map`

```json
"alias_map": {
  "ghg emissions": "GHG Emissions",
  "carbon emissions": "GHG Emissions",
  "scope 1": "Scope 1 Emissions"
}
```

Lookup is case-insensitive on the **key**. Values are kept verbatim.
Use this to collapse synonymous labels into a single canonical form
before ID generation, so "carbon emissions" (Source A prose) and
"GHG Emissions" (Source B governance) end up with the same ID.

Sidecar `alias_map.json` overlays the schema's map. Use the schema for
domain-wide aliases, the sidecar for deployment-specific ones.

### `canonical_verbs`

```json
"canonical_verbs": {
  "is calculated by": "IsCalculatedBy",
  "calculated using": "IsCalculatedBy",
  "uses formula": "IsCalculatedBy"
}
```

Lookup is case-insensitive on the key. Maps free-form verb phrases
(what the LLM commonly produces) to canonical predicate names. Source
A's relationship extractor uses this before checking
`is_known_predicate()`.

## `prompt_fragment.md`

Optional. When present, this markdown is injected into Source A's LLM
prompt during constrained extraction. It should:

- Describe the domain in 2-3 paragraphs
- List allowed entity types and what each means
- List allowed predicates with subject/object type expectations
- Show 1-2 example extractions in the expected JSON format
- Explicitly forbid the LLM from inventing types or predicates

The engine appends this fragment to the standard system prompt; you
don't need to repeat the JSON output schema or the task framing.

## Validation behaviour (preview — Phase 4)

When the validation stage lands (Phase 4), it will check the fused
output against the profile schema:

- **Entity uniqueness** — IDs are unique
- **Type membership** — every entity has a type declared in
  `entity_types` or a subtype thereof
- **Required fields** — every entity has all `required` fields
  populated for its type
- **Predicate vocabulary** — every relationship predicate is in
  `predicates`
- **Predicate domains** — every relationship's subject/object types
  match the predicate's declared `subject_types` / `object_types`
- **Cardinality** — relationship counts respect `cardinality`

Cascade filtering: when an entity is dropped (e.g. unknown type),
relationships referencing it are dropped too.

## Example: minimal profile

```json
{
  "profile_name": "minimal",
  "profile_version": "1.0.0",
  "description": "Toy profile — concepts that rules apply to",

  "entity_types": {
    "Concept": {
      "required": ["definition"],
      "optional": ["citation"]
    },
    "Rule": {
      "required": ["expression"],
      "optional": ["citation"]
    }
  },

  "predicates": {
    "AppliesTo": {
      "subject_types": ["Rule"],
      "object_types": ["Concept"],
      "cardinality": "N:N"
    }
  },

  "id_format": {
    "strategy": "type_label_hash",
    "hash_length": 6
  },

  "alias_map": {
    "rule": "Rule",
    "regulation": "Rule"
  },

  "canonical_verbs": {
    "applies to": "AppliesTo",
    "governs": "AppliesTo"
  }
}
```

## Example: ESG profile

See `docs/profile-examples/esg/` for a full working profile based on
SASB / TCFD / IFRS S2. Copy it to `domains/<your-domain>/profile/`
and edit to taste.

## Versioning your profile

Bump `profile_version` whenever you:
- Add or remove an `entity_types` key
- Add or remove a `predicates` key
- Change `subject_types` / `object_types` / `cardinality`
- Change `id_format` (this changes every ID — significant!)

You don't need to bump for additions to `alias_map` or
`canonical_verbs` — those are non-breaking enrichments.

Downstream consumers can read `profile_name` and `profile_version`
from the fused output's metadata block to detect schema changes.

## Authoring tips

1. **Start with the entity types you care about.** Predicates can
   come later. A profile with three entity types and no predicates is
   still valid — it just means consolidation works (deterministic
   IDs) but no relationship validation.

2. **Use `subtypes` for refinement, not for new top-level types.**
   If you find yourself adding "DirectMetric" and "CalculatedMetric"
   as top-level types with the same required fields, fold them under
   "Metric" with subtypes.

3. **Author `alias_map` from real extraction outputs.** Run
   unconstrained extraction once, look at the variant spellings the
   LLM produced ("Carbon Emissions", "GHG emissions", "carbon
   footprint"), pick a canonical form, add the others as aliases.

4. **Keep `prompt_fragment.md` short.** ~300 words is enough. Longer
   prompts dilute the LLM's attention to your specific constraints.

5. **Test with a tiny profile first.** Author 3 entity types and 1
   predicate, run on one document, verify the IDs are stable and the
   types are right. Then expand.
