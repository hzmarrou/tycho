# Source B — Governance Reference Format

Source B reads a curated governance reference file in **JSON** format.
Its role in the pipeline is **validation, not extraction**: the fusion
layer uses Source B to confirm that concepts extracted by Source A
(domain documents) actually exist in the governance system, to prefer
governance definitions when they're richer, and to flag governance-only
terms that Source A missed.

Source B is **optional**. The fusion layer works without it.

## Input format

A JSON file containing either a **single object** or an **array of
objects**. Each object must have at least `element_name`.

### Fields

| Field | Type | Required | Description |
|---|---|---|---|
| `element_name` | string | **yes** | The canonical name of the data element. Used as the matching key against Source A concepts. |
| `domain_name` | string | no | The domain this element belongs to (e.g., "Risk Management", "Customer"). |
| `definition` | string | no | The authoritative definition from the governance system. |
| `is_critical` | boolean | no | Whether this element is flagged as a critical data element. Accepts `true`/`false`, `"Yes"`/`"No"`, `"Y"`/`"N"`. |
| `citation` | string | no | References to authoritative systems or tools where this term is defined (e.g., "Collibra, OpenMetadata"). |

Any additional fields in the JSON object are preserved in
`extra_fields` and carried through to the fused output.

### Example

```json
[
  {
    "domain_name": "Risk Management",
    "element_name": "Default",
    "definition": "Default is a status assigned when the entity can no longer meet its obligations.",
    "is_critical": true,
    "citation": "A-lex, Collibra, OpenMetadata"
  },
  {
    "element_name": "Exposure",
    "definition": "The total amount at risk.",
    "is_critical": false
  }
]
```

### What Source B is NOT

- Not an Excel parser. If your governance dictionary is in Excel,
  export the relevant sheet to JSON first (one row → one object).
- Not an LLM-based extractor. Source B reads structured human-curated
  input. Confidence is uniformly 0.95 (the human typed it; we just
  parse it).
- Not a schema or code analyser. Those are Source C and Source D.

## How fusion uses Source B

When Source B is provided, the fusion layer:

1. **Validates Source A concepts** — if a Source A concept also appears
   in Source B (matched by `element_name`, case-insensitive), it gets
   marked as governance-validated and its confidence is boosted.
2. **Prefers governance definitions** — if Source B has a richer
   `definition` than Source A extracted, fusion uses Source B's version.
3. **Adds criticality flags** — `is_critical` and `citation` come from
   Source B since Source A (prose extraction) can rarely extract these
   reliably.
4. **Reports governance-only terms** — Source B entries that don't
   match any Source A concept are flagged as "governance-only" in the
   fused output, meaning the governance system knows about them but
   they weren't found in the domain documents.
