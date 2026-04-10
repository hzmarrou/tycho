# Canonical Governance CSV Format

This document defines the **single canonical CSV format** that Source B (the
governance extractor) accepts. It is the contract between Ontozense and any
governance / data quality dictionary that the user wants to import.

## Why a single canonical format

Real-world governance dictionaries are arbitrarily shaped: 3-level merged
header hierarchies, customer-specific column names, multi-sheet workbooks,
domain-specific value conventions. There is no way to write one parser that
handles every layout.

Source B explicitly does **not** try to be that parser. It accepts ONE
format, defined here. Customers convert their existing dictionaries to this
format before uploading. Ontozense does not ship conversion tooling — that
is the customer's responsibility (or a one-time consulting deliverable).

This is the same trade-off documented in `PLAYBOOK.md` §1: Source B is for
**human-supplied structured input**, not for prose extraction. We parse,
not interpret.

## File requirements

- **Format**: CSV (comma-separated). No Excel, no TSV, no fixed-width.
- **Encoding**: UTF-8.
- **First row**: header row with column names matching the canonical names below (case-insensitive, leading/trailing whitespace ignored).
- **One row per data element**.
- **Unknown columns are ignored** with a warning. The parser does not fail on extra columns.
- **Missing optional columns are fine.** Only `element_name` is required.

## Canonical columns

| Column name | Required | Type | Allowed values | Purpose |
|---|---|---|---|---|
| `element_name` | ✓ | string | non-empty | Identifier of the data element. The unique key for the row. |
| `domain` | optional | string | any | Top-level domain this element belongs to. |
| `sub_domain` | optional | string | any | Sub-domain or category within the domain (e.g. "Customer", "Order", "Payment"). |
| `definition` | optional | string | any | Plain-language definition of the element. |
| `term_definition` | optional | string | any | Formal or glossary-style definition (often from a controlled vocabulary). |
| `is_critical` | optional | enum | `Y`, `N`, `Yes`, `No`, empty | Critical Data Element flag. |
| `mandatory_optional` | optional | enum | `M`, `O`, `Mandatory`, `Optional`, empty | Mandatory or optional to populate. |
| `citation` | optional | string | any | Section/paragraph reference (e.g. `"Section 3.1"`, `"§14"`, `"Annex II Table F18"`). |
| `dq_completeness` | optional | string | any | Completeness rule text. |
| `dq_accuracy` | optional | string | any | Accuracy rule text. |
| `dq_uniqueness` | optional | string | any | Uniqueness rule text. |
| `dq_timeliness` | optional | string | any | Timeliness rule text. |
| `dq_consistency` | optional | string | any | Consistency rule text. |
| `dq_validity` | optional | string | any | Validity rule text (allowed values, format constraints). |

## Example

```csv
element_name,sub_domain,definition,is_critical,mandatory_optional,dq_completeness,dq_validity
customer_id,Customer,Unique identifier of a customer record,Y,M,Required for all rows,UUID format
order_total,Order,Total monetary value of an order,Y,M,Required if order_status != cancelled,Non-negative decimal
return_reason,Order,Free-text reason for product return,N,O,,
```

## Row validation rules

A row is rejected (with a warning, not a hard failure) if:
- `element_name` is empty or missing.
- `is_critical` has a value not in the allowed enum.
- `mandatory_optional` has a value not in the allowed enum.

A row that passes validation is converted to one `GovernanceRecord` and
becomes input to the fusion layer.

## What Source B is NOT

- Not an Excel parser (no openpyxl involvement at the boundary).
- Not a fuzzy header matcher (column names must match canonical names).
- Not a multi-sheet processor (one CSV file = one input).
- Not a converter for arbitrary customer formats. If your governance dictionary
  is in a different shape, write a converter as a one-time job; Source B
  reads its output.
- Not LLM-backed. Parsing is deterministic.
