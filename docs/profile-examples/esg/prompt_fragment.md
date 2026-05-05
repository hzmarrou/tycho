# ESG Domain Constraints

You are extracting structured ESG (Environmental, Social, Governance)
metric definitions from sustainability disclosure frameworks such as
SASB, TCFD, and IFRS S2. The output you produce will feed a rich data
dictionary used by data governance teams to operationalise reporting
obligations.

## Allowed entity types

Extract entities only of these types. Do not invent new types.

- **Industry** — a sector or industry classification (e.g. "Commercial
  Banks", "Oil & Gas Refining"). Optional fields: `sector`, `country`,
  `standard_reference`.

- **ReportingFramework** — a published disclosure standard
  (e.g. "SASB Commercial Banks Standard", "TCFD Recommendations").
  Optional fields: `version`, `year`, `publisher`.

- **Category** — a topical grouping within a framework
  (e.g. "Data Security", "Financed Emissions"). Required: `section_title`.
  Optional: `section_id`, `page_range`.

- **Metric** — a measurable indicator. Required: `measurement_type`
  (Quantitative / Qualitative), `metric_type` (DirectMetric /
  CalculatedMetric / InputMetric), `unit` (e.g. "tonnes CO2e",
  "USD millions"), `code` (the framework's identifier such as
  "FN-CB-230a.1"), `description`.

  Subtypes (use `metric_type`):
  - **DirectMetric** — measured directly, no formula needed.
  - **CalculatedMetric** — computed from other metrics. Must have an
    `IsCalculatedBy` relationship to a Model.
  - **InputMetric** — used as an input to one or more Models.

- **Model** — a calculation specification. Required: `description`,
  `equation`, `input_variables` (list of strings).

## Allowed predicates

Use only these predicate names. Do not invent new ones.

- `ReportUsing` (Industry → ReportingFramework, 1:1)
- `Include` (ReportingFramework → Category, 1:N)
- `ConsistOf` (Category → Metric, 1:N)
- `IsCalculatedBy` (CalculatedMetric → Model, 1:1)
- `RequiresInputFrom` (Model → InputMetric, 1:N)

## Output rules

- Every CalculatedMetric must have an `IsCalculatedBy` relationship.
  If you can't find a Model for it, downgrade it to a DirectMetric.
- Every Model's `input_variables` must reference InputMetrics that
  appear elsewhere in the extraction.
- Do not produce orphan entities — every entity must be reachable
  from a `ReportUsing` chain.
- If a metric's unit is not specified in the source, set
  `"unit": "N/A"` rather than guessing.

## Example shape

```
Industry: "Commercial Banks"
  --[ReportUsing]--> ReportingFramework: "SASB Commercial Banks Standard"
    --[Include]--> Category: "Data Security"
      --[ConsistOf]--> Metric "Data Breach Composite":
                         metric_type: CalculatedMetric
                         unit: "Number, Percentage (%)"
                         code: "FN-CB-230a.1"
        --[IsCalculatedBy]--> Model "Data Breach Composite Model":
                                equation: "(breaches / total_records) * 100"
                                input_variables: ["breaches", "total_records"]
          --[RequiresInputFrom]--> InputMetric "breaches"
          --[RequiresInputFrom]--> InputMetric "total_records"
```

When in doubt, prefer fewer high-quality entities to many speculative
ones. The downstream validation stage will filter unknown types and
predicates anyway, so emitting them wastes effort.
