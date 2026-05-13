# Ontozense Profile Induction Architecture

## Purpose

This document defines a concrete architecture for extending Ontozense from
its current **profile-application** model into a two-pass
**profile-induction + constrained rebuild** system.

The intent is to be explicit enough that an AI coding agent can implement
the design in phases without redefining the architecture.

## Decision

Ontozense should support **two distinct workflows**:

1. **Known-profile workflow**: keep the current pipeline for domains where
   the user already has a profile.
2. **Discovery workflow**: add a new pipeline that first discovers the
   candidate domain concept universe, induces a draft profile, then
   re-runs the existing constrained pipeline using that induced profile.

This means the current profile-driven implementation stays. It becomes
the **second pass** of a larger system.

### Chosen rollout stance

This architecture adopts **Path 1**:

- the current profile-first pipeline remains the **default and primary**
  product workflow
- discovery/induction is added as a **new workflow alongside it**
- users choose discovery only when they do not already have a usable
  domain profile

Path 2 is explicitly out of scope for this architecture. We are not
re-centering the whole product around discovery-first in this phase.

## Non-Goals

- Do not remove or break the current `--profile` workflow.
- Do not hardcode ESG or any other domain into core logic.
- Do not turn the candidate graph into the final semantic layer.
- Do not require full automation of profile approval in v1. Human review
  remains part of the workflow.

## Target Workflow

The target end-to-end flow is:

1. **Candidate extraction**
   - Extract broad candidates from Sources A/B/C/D with minimal filtering.
   - Keep concepts that may be noisy, technical, local, or uncertain.
   - Preserve provenance and cross-source evidence.
2. **Candidate graph build**
   - Normalize aliases where possible.
   - Merge duplicate concepts across sources.
   - Attach source evidence, schema/code links, and graph relationships.
3. **Profile induction**
   - Score each candidate for business relevance.
   - Classify candidates into:
     - core business concepts
     - supporting technical concepts
     - noise / out-of-scope
   - Infer candidate entity types, predicates, required attributes, and
     normalization hints.
   - Emit a draft profile directory.
4. **Human review**
   - User inspects and edits the induced profile.
5. **Constrained rebuild**
   - Re-run extraction/fusion/validation using the approved profile.
   - Produce a clean semantic layer and final fused output.

## End User Workflows

Under Path 1, end users have two entry paths.

### Workflow A: known-profile

Use this when the domain team already knows the ontology/profile shape.

User flow:

1. prepare or reuse a profile directory
2. run extraction with `--profile`
3. run fusion
4. run validation
5. run lint and report

This is the existing main workflow and remains the default one in docs
and UX.

### Workflow B: discovery-first

Use this when the domain team does not yet know what should be in scope.

User flow:

1. run `discover`
2. inspect the candidate graph and mappings
3. run `induce-profile`
4. review and edit the induced profile
5. run `rebuild`
6. run validate/lint/report as usual

The discovery workflow is additive. It does not replace Workflow A.

## Architecture Overview

### Existing pipeline to preserve

Current profile-aware pipeline remains:

`extract-a/b/c/d -> fuse -> validate -> lint -> report`

This remains the canonical path when the user already has a profile.

### New discovery pipeline to add

New pipeline:

`discover -> induce-profile -> extract-a/b/c/d --profile induced -> fuse -> validate -> lint -> report`

### Core principle

The **candidate graph** and the **final semantic graph** are different
artifacts with different purposes.

- Candidate graph: broad recall, noisy allowed, optimized for discovery.
- Final semantic graph: profile-constrained, cleaner, optimized for AI
  grounding and downstream use.

## New Artifacts

The system should produce five named artifacts.

### 1. Candidate graph

Purpose:
- broad merged concept universe across all sources

Suggested file:
- `candidate-graph.json`

Contents:
- nodes: candidate concepts/entities
- edges: candidate relationships
- per-node evidence from A/B/C/D
- source-specific mappings
- confidence and relevance signals

### 2. Candidate provenance map

Purpose:
- trace every candidate concept back to raw source evidence

Suggested file:
- `candidate-provenance.json`

Contents:
- concept id -> list of evidence entries
- source type
- source artifact path
- anchor/snippet
- extraction metadata

### 3. Induced profile

Purpose:
- a draft user-editable profile generated from the candidate graph

Suggested directory:
- `domains/<domain>/induced-profile/`

Contents:
- `schema.json`
- `prompt_fragment.md`
- `alias_map.json`
- `induction_report.json`

### 4. Final semantic graph / fused output

Purpose:
- profile-constrained final graph for downstream use

This reuses the current fused output shape and validation outputs.

### 5. Mapping layer

Purpose:
- connect semantic concepts to data schema objects and code artifacts

Suggested file:
- `concept-mappings.json`

Contents:
- concept -> schema model/field links
- concept -> code rule/function/table links

## New CLI Commands

Add three new top-level commands.

### `ontozense discover`

Purpose:
- run broad candidate extraction and build the candidate graph

Inputs:
- same source inputs as `fuse`
- optional `--domain-dir`
- optional `--profile` only for light normalization, not filtering

Outputs:
- `candidate-graph.json`
- `candidate-provenance.json`
- `concept-mappings.json`

Important behavior:
- should not require a profile
- should not drop candidates simply because they are out of profile
- should preserve noisy concepts if they have evidence

### `ontozense induce-profile`

Purpose:
- score candidates and emit a draft profile

Inputs:
- `candidate-graph.json`
- optional weighting config
- optional output directory

Outputs:
- draft profile directory
- `induction_report.json`

### `ontozense rebuild`

Purpose:
- run the existing constrained pipeline using an approved profile

This can initially be a thin orchestration wrapper around existing
commands:

- extract-a/b/c/d with `--profile`
- fuse
- validate
- lint
- report

Important UX rule:
- `rebuild` is part of the discovery workflow only
- it must not replace or rename the current direct commands for
  profile-aware users

## Data Model

Add new core types under `src/ontozense/core/`.

### `CandidateConcept`

Fields:
- `candidate_id: str`
- `label: str`
- `normalized_label: str`
- `suggested_entity_type: str`
- `classification: str`
- `summary_definition: str`
- `source_presence: dict[str, bool]`
- `source_counts: dict[str, int]`
- `schema_links: list[SchemaLink]`
- `code_links: list[CodeLink]`
- `governance_links: list[GovernanceLink]`
- `authoritative_evidence_count: int`
- `graph_degree: int`
- `relevance_score: float`
- `relevance_breakdown: dict[str, float]`
- `provenance: list[EvidenceEntry]`
- `aliases: list[str]`
- `status: str`

Classification allowed values:
- `core_business`
- `supporting_technical`
- `noise`
- `unknown`

Status allowed values:
- `candidate`
- `selected`
- `rejected`

### `CandidateRelationship`

Fields:
- `subject_candidate_id: str`
- `predicate: str`
- `object_candidate_id: str`
- `canonical_predicate: str`
- `source_presence: dict[str, bool]`
- `relevance_score: float`
- `provenance: list[EvidenceEntry]`

### `EvidenceEntry`

Fields:
- `source_type: str`  (`A`, `B`, `C`, `D`)
- `source_artifact: str`
- `anchor: dict | None`
- `snippet: str`
- `raw_label: str`
- `raw_type: str`
- `confidence: float`

### `InductionReport`

Fields:
- `domain_name: str`
- `generated_at: str`
- `candidate_count: int`
- `selected_core_count: int`
- `selected_supporting_count: int`
- `rejected_count: int`
- `scoring_weights: dict[str, float]`
- `top_candidates: list[dict]`
- `rejected_examples: list[dict]`
- `predicate_suggestions: list[dict]`
- `required_field_suggestions: dict[str, list[str]]`
- `review_notes: list[str]`

## Discovery Stage Design

### Goal

Create a broad, merged concept universe without prematurely enforcing a
final semantic boundary.

### Source behavior

#### Source A

Use existing extraction, but run in broad mode by default:
- no strict profile filtering
- preserve extracted concepts and relationships
- keep definitions and provenance

Future enhancement:
- optional segmentation for long PDFs/documents

#### Source B

Emit governance records as candidate concepts and attributes:
- `element_name`
- governance fields
- evidence that concept exists in governed metadata

#### Source C

Emit models and fields as candidate technical concepts:
- schema object names
- data types
- relationships such as model-field or foreign-key structure

#### Source D

Emit candidate business rules and referenced terms:
- rule attachment targets
- symbolic names
- threshold/classification logic

### Candidate merge rules

Discovery needs its own merge layer, separate from final fusion.

Merge key priority:

1. existing profile-mode `id` if present
2. normalized canonical label
3. alias-expanded label
4. source-specific fallback key

Discovery merge should be conservative:
- merge only when confidence is high
- if ambiguous, keep separate candidates and record ambiguity

### Candidate graph builder

Add a new module:
- `src/ontozense/core/candidate_graph.py`

Responsibilities:
- ingest source outputs
- create `CandidateConcept` and `CandidateRelationship`
- aggregate evidence
- compute source presence counts
- attach schema/code/governance mappings
- compute basic graph features

## Relevance Scoring Design

### Goal

Estimate which candidates belong in the domain semantic layer.

### Initial scoring model

Implement a transparent weighted scoring model first. Do not start with
an opaque ML classifier.

Suggested normalized signals:

- `authoritative_frequency`
  - occurrence count in Source A authoritative docs
- `governance_presence`
  - binary or weighted signal from Source B
- `schema_linkage`
  - linked to Source C models/fields
- `code_usage`
  - referenced in Source D rules or transformations
- `graph_centrality`
  - degree / connectivity within candidate graph
- `definition_richness`
  - presence and quality of definitions
- `business_naming_signal`
  - name looks like domain/business term rather than a local technical
    implementation detail

Initial default weights:

- authoritative_frequency: `0.25`
- governance_presence: `0.20`
- schema_linkage: `0.15`
- code_usage: `0.10`
- graph_centrality: `0.10`
- definition_richness: `0.10`
- business_naming_signal: `0.10`

### Classification thresholds

Start with simple defaults:

- `>= 0.70` -> `core_business`
- `>= 0.40 and < 0.70` -> `supporting_technical`
- `< 0.40` -> `noise`

These thresholds must be configurable.

### Explainability requirement

Every candidate must carry:
- total relevance score
- per-signal contribution
- short explanation string

This is required so humans can review why a concept was selected or
rejected.

## Profile Induction Design

Add a new module:
- `src/ontozense/core/profile_induction.py`

Responsibilities:
- select core concepts from candidate graph
- infer entity types
- infer predicate vocabulary
- infer alias map
- infer required fields by type
- write a draft profile directory
- write the induction report

### Entity type induction

Do not invent arbitrary new types in v1.

Instead:
- prefer existing type hints from source outputs
- cluster candidates under a limited set of induced top-level types
- require human review for type additions

Initial strategy:

1. reuse known type hints from:
   - Source A profile-style `entity_type` when available
   - Source C schema object categories
   - Source D attached entity types
2. for candidates without stable type hints, assign:
   - `Concept` if business-like
   - `TechnicalArtifact` if technical-like
3. mark low-confidence type guesses in the induction report

### Predicate induction

Build candidate predicates from discovered relationships.

Initial strategy:
- normalize verb phrases
- group similar phrases
- rank by support and reuse
- emit a conservative canonical set

Rules:
- only predicates above support threshold go into the draft profile
- low-support predicates stay in the induction report as suggestions

### Required field induction

Use evidence from observed populated attributes.

Suggested rule:
- if an attribute appears on >= 70% of selected candidates of a given
  type and comes from authoritative/governed evidence, suggest it as
  `required`
- otherwise suggest it as `optional`

### Alias induction

Use observed merges and near-duplicates:
- exact case/punctuation variants
- acronym/expanded form
- governance/schema naming differences

Every induced alias must include supporting evidence in the induction
report.

## Human Review Model

The induced profile is **not** automatically trusted as final truth.

Required review loop:

1. user runs `discover`
2. user runs `induce-profile`
3. user reviews:
   - `schema.json`
   - `alias_map.json`
   - `prompt_fragment.md`
   - `induction_report.json`
4. user edits if needed
5. user runs `rebuild`

## Constrained Rebuild Design

The constrained rebuild should reuse the current mature pipeline rather
than invent a second implementation.

Reuse:
- current profile loader
- Source A/B/C/D profile-aware extraction paths
- current fusion
- current validation
- current lint
- current benchmark/reporting

The only new orchestration needed is a convenience command that runs the
existing steps in order.

## Module Layout

New modules to add:

- `src/ontozense/core/candidate_graph.py`
- `src/ontozense/core/relevance.py`
- `src/ontozense/core/profile_induction.py`
- `src/ontozense/core/discovery_contracts.py`

CLI wiring:

- add `discover` command in `src/ontozense/cli.py`
- add `induce-profile` command in `src/ontozense/cli.py`
- add `rebuild` command in `src/ontozense/cli.py`

Suggested responsibilities:

### `discovery_contracts.py`

Pure dataclasses / serialization:
- `CandidateConcept`
- `CandidateRelationship`
- `EvidenceEntry`
- `InductionReport`

### `candidate_graph.py`

Graph construction:
- source ingestion
- merge logic
- evidence aggregation
- graph features

### `relevance.py`

Scoring and classification:
- compute scores
- produce explanations
- configurable weights/thresholds

### `profile_induction.py`

Profile emission:
- select candidates
- infer profile fields
- write profile directory and report

## File and Directory Outputs

Recommended discovery workspace under `domain_dir`:

`domains/<name>/discovery/`

Files:
- `candidate-graph.json`
- `candidate-provenance.json`
- `concept-mappings.json`
- `induction-report.json`

Recommended induced profile location:

`domains/<name>/induced-profile/`

Files:
- `schema.json`
- `alias_map.json`
- `prompt_fragment.md`
- `induction_report.json`

## Backward Compatibility

Backward compatibility is non-negotiable.

Rules:
- all existing commands keep current behavior
- no existing JSON contracts change unless behind a new command or
  optional field addition
- `--profile` workflow remains byte-compatible where previous reviews
  required it
- new discovery artifacts must be separate from fused output artifacts

UX compatibility rules:
- README quick-start should continue to lead with the current
  profile-first workflow
- discovery should be documented as an additional path, not as the only
  supported path

## Incremental Delivery Plan

Implement in five phases.

### Phase 1: discovery contracts + candidate graph

Deliver:
- dataclasses + JSON serialization
- candidate graph builder that can ingest current source outputs
- `discover` CLI command

Exclude:
- scoring
- profile writing

### Phase 2: relevance scoring

Deliver:
- weighted scoring model
- candidate classification
- explainable score breakdowns

### Phase 3: draft profile emission

Deliver:
- `induce-profile` CLI command
- emitted draft profile directory
- induction report

### Phase 4: rebuild orchestration

Deliver:
- `rebuild` command that wraps existing constrained pipeline

### Phase 5: refinement features

Deliver:
- optional segmentation
- richer predicate clustering
- active-learning style review improvements

## Testing Strategy

Add dedicated tests for each stage.

### Discovery tests

- source outputs convert into candidate concepts
- evidence aggregation preserves provenance
- conservative merge logic does not over-merge
- ambiguous labels remain split

### Relevance tests

- scoring is deterministic
- thresholds classify as expected
- score explanations include all required signals

### Profile induction tests

- emitted `schema.json` validates with current profile loader
- alias map contains evidence-backed entries
- required/optional field suggestions follow thresholds

### Rebuild tests

- uses emitted profile with existing extraction/fusion/validation path
- preserves current known-profile behavior

### End-to-end tests

- `discover -> induce-profile -> rebuild` on a toy domain fixture
- final semantic layer is smaller/cleaner than candidate graph

## Acceptance Criteria

This architecture is implemented correctly when:

1. Ontozense can build a candidate graph without requiring a profile.
2. The candidate graph preserves cross-source evidence and provenance.
3. Ontozense can emit a draft profile directory from the candidate graph.
4. The draft profile loads with the existing profile loader.
5. The current profile-driven pipeline can be re-used unchanged as the
   constrained second pass.
6. Existing profile-first workflows remain intact.
7. The discovery workflow produces artifacts clear enough for a human to
   review and refine.

## Recommendation to the Coding Agent

Implement this architecture by **adding** discovery/induction modules,
not by rewriting the existing profile-aware extraction/fusion path.

Priority order:

1. candidate graph contracts
2. discovery CLI
3. relevance scoring
4. profile induction writer
5. rebuild orchestration

Do not start with automatic ontology perfection. Start with:
- transparent scoring
- explicit artifacts
- human-reviewable profile output
- reuse of the current constrained pipeline for the final pass
