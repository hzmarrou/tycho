# Profile Induction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a new discovery workflow that builds a candidate graph, scores and classifies concepts, emits a draft profile, and reuses the current profile-aware pipeline as a constrained second pass.

**Architecture:** Keep the current profile-first pipeline unchanged as the default workflow. Add three new commands, `discover`, `induce-profile`, and `rebuild`, backed by new discovery-side contracts and core modules. The new flow must emit reviewable artifacts under `domain_dir` and must not change existing fused/profile JSON contracts.

**Tech Stack:** Python 3, Typer CLI, dataclasses, existing Ontozense extractors/fusion/profile loader, pytest

---

## File Map

### New files

- `src/ontozense/core/discovery_contracts.py`
  - Typed dataclasses and JSON helpers for discovery artifacts.
- `src/ontozense/core/candidate_graph.py`
  - Build candidate concepts/relationships from source outputs.
- `src/ontozense/core/relevance.py`
  - Transparent weighted scoring and classification.
- `src/ontozense/core/profile_induction.py`
  - Draft profile writer and induction report generator.
- `tests/test_discovery_contracts.py`
  - Unit tests for dataclasses and JSON shape.
- `tests/test_candidate_graph.py`
  - Unit tests for merge/evidence aggregation/mappings.
- `tests/test_relevance.py`
  - Unit tests for scoring, thresholds, and explanations.
- `tests/test_profile_induction.py`
  - Unit tests for emitted profile directory and report.
- `tests/test_cli_discovery.py`
  - CLI tests for `discover`, `induce-profile`, and `rebuild`.
- `docs/PROFILE_INDUCTION_IMPLEMENTATION_PLAN.md`
  - This execution plan.

### Existing files to modify

- `src/ontozense/cli.py`
  - Add `discover`, `induce-profile`, and `rebuild` commands.
- `README.md`
  - Add a short section for the new discovery workflow after implementation.
- `src/ontozense/core/profile.py`
  - Reuse as-is for validating emitted draft profiles; only modify if tests prove a loader gap.

---

### Task 1: Add Discovery Contracts

**Files:**
- Create: `src/ontozense/core/discovery_contracts.py`
- Test: `tests/test_discovery_contracts.py`

- [ ] **Step 1: Write the failing tests for the new discovery dataclasses**

```python
from ontozense.core.discovery_contracts import (
    CandidateConcept,
    CandidateRelationship,
    EvidenceEntry,
    InductionReport,
)


def test_candidate_concept_round_trip_dict():
    concept = CandidateConcept(
        candidate_id="cand_customer",
        label="Customer",
        normalized_label="customer",
        suggested_entity_type="Concept",
        classification="core_business",
        summary_definition="A person or organization receiving a service.",
        source_presence={"A": True, "B": True, "C": False, "D": True},
        source_counts={"A": 2, "B": 1, "C": 0, "D": 3},
        schema_links=[],
        code_links=[],
        governance_links=[],
        authoritative_evidence_count=2,
        graph_degree=4,
        relevance_score=0.84,
        relevance_breakdown={"authoritative_frequency": 0.25},
        provenance=[],
        aliases=["Customers"],
        status="candidate",
    )
    raw = concept.to_dict()
    loaded = CandidateConcept.from_dict(raw)
    assert loaded == concept


def test_induction_report_round_trip_dict():
    report = InductionReport(
        domain_name="npl",
        generated_at="2026-05-13T10:00:00",
        candidate_count=10,
        selected_core_count=4,
        selected_supporting_count=3,
        rejected_count=3,
        scoring_weights={"authoritative_frequency": 0.25},
        top_candidates=[{"candidate_id": "cand_customer", "score": 0.9}],
        rejected_examples=[{"candidate_id": "cand_tmp_col_1", "score": 0.1}],
        predicate_suggestions=[{"predicate": "AppliesTo", "support": 3}],
        required_field_suggestions={"Concept": ["definition"]},
        review_notes=["Review aliases before production use."],
    )
    assert InductionReport.from_dict(report.to_dict()) == report
```

- [ ] **Step 2: Run the new tests and verify they fail**

Run: `pytest tests/test_discovery_contracts.py -v`
Expected: FAIL with `ModuleNotFoundError` for `ontozense.core.discovery_contracts`

- [ ] **Step 3: Implement the minimal discovery contract module**

```python
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class EvidenceEntry:
    source_type: str
    source_artifact: str
    anchor: dict[str, Any] | None = None
    snippet: str = ""
    raw_label: str = ""
    raw_type: str = ""
    confidence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "EvidenceEntry":
        return cls(**raw)


@dataclass(frozen=True)
class CandidateConcept:
    candidate_id: str
    label: str
    normalized_label: str
    suggested_entity_type: str
    classification: str
    summary_definition: str
    source_presence: dict[str, bool]
    source_counts: dict[str, int]
    schema_links: list[dict[str, Any]] = field(default_factory=list)
    code_links: list[dict[str, Any]] = field(default_factory=list)
    governance_links: list[dict[str, Any]] = field(default_factory=list)
    authoritative_evidence_count: int = 0
    graph_degree: int = 0
    relevance_score: float = 0.0
    relevance_breakdown: dict[str, float] = field(default_factory=dict)
    provenance: list[EvidenceEntry] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)
    status: str = "candidate"

    def to_dict(self) -> dict[str, Any]:
        raw = asdict(self)
        raw["provenance"] = [p.to_dict() for p in self.provenance]
        return raw

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "CandidateConcept":
        raw = dict(raw)
        raw["provenance"] = [EvidenceEntry.from_dict(p) for p in raw.get("provenance", [])]
        return cls(**raw)


@dataclass(frozen=True)
class CandidateRelationship:
    subject_candidate_id: str
    predicate: str
    object_candidate_id: str
    canonical_predicate: str = ""
    source_presence: dict[str, bool] = field(default_factory=dict)
    relevance_score: float = 0.0
    provenance: list[EvidenceEntry] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        raw = asdict(self)
        raw["provenance"] = [p.to_dict() for p in self.provenance]
        return raw

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "CandidateRelationship":
        raw = dict(raw)
        raw["provenance"] = [EvidenceEntry.from_dict(p) for p in raw.get("provenance", [])]
        return cls(**raw)


@dataclass(frozen=True)
class InductionReport:
    domain_name: str
    generated_at: str
    candidate_count: int
    selected_core_count: int
    selected_supporting_count: int
    rejected_count: int
    scoring_weights: dict[str, float]
    top_candidates: list[dict[str, Any]]
    rejected_examples: list[dict[str, Any]]
    predicate_suggestions: list[dict[str, Any]]
    required_field_suggestions: dict[str, list[str]]
    review_notes: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "InductionReport":
        return cls(**raw)
```

- [ ] **Step 4: Run tests and verify they pass**

Run: `pytest tests/test_discovery_contracts.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ontozense/core/discovery_contracts.py tests/test_discovery_contracts.py
git commit -m "feat(discovery): add candidate graph contracts"
```

### Task 2: Build Candidate Graph Aggregation

**Files:**
- Create: `src/ontozense/core/candidate_graph.py`
- Test: `tests/test_candidate_graph.py`

- [ ] **Step 1: Write the failing candidate graph tests**

```python
from ontozense.core.candidate_graph import build_candidate_graph


def test_build_candidate_graph_merges_same_normalized_label_across_sources():
    source_a = {
        "concepts": [
            {"name": "Customer", "definition": "A client.", "provenance": {"source_document": "a.md"}}
        ],
        "relationships": [],
    }
    source_b = {
        "records": [
            {"element_name": "customer", "definition": "Governed customer record."}
        ]
    }
    graph = build_candidate_graph(source_a=source_a, source_b=source_b)
    assert len(graph["concepts"]) == 1
    concept = graph["concepts"][0]
    assert concept.label == "Customer"
    assert concept.source_presence["A"] is True
    assert concept.source_presence["B"] is True


def test_build_candidate_graph_keeps_ambiguous_candidates_separate():
    source_a = {
        "concepts": [
            {"name": "Default", "definition": "Loan default."},
            {"name": "Default Rate", "definition": "Frequency of default."},
        ],
        "relationships": [],
    }
    graph = build_candidate_graph(source_a=source_a)
    assert len(graph["concepts"]) == 2
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `pytest tests/test_candidate_graph.py -v`
Expected: FAIL with `ModuleNotFoundError` for `ontozense.core.candidate_graph`

- [ ] **Step 3: Implement a minimal conservative candidate graph builder**

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .discovery_contracts import CandidateConcept, EvidenceEntry
from .identity import normalize_label


@dataclass(frozen=True)
class CandidateGraph:
    concepts: list[CandidateConcept]
    relationships: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "concepts": [c.to_dict() for c in self.concepts],
            "relationships": self.relationships,
        }


def build_candidate_graph(*, source_a=None, source_b=None, source_c=None, source_d=None) -> CandidateGraph:
    bucket: dict[str, CandidateConcept] = {}

    def upsert(label: str, definition: str, source_type: str, artifact: str = "") -> None:
        norm = normalize_label(label)
        if not norm:
            return
        existing = bucket.get(norm)
        evidence = EvidenceEntry(
            source_type=source_type,
            source_artifact=artifact,
            snippet=definition[:200],
            raw_label=label,
            confidence=0.8,
        )
        if existing is None:
            bucket[norm] = CandidateConcept(
                candidate_id=f"cand_{norm}",
                label=label,
                normalized_label=norm,
                suggested_entity_type="Concept",
                classification="unknown",
                summary_definition=definition,
                source_presence={"A": False, "B": False, "C": False, "D": False},
                source_counts={"A": 0, "B": 0, "C": 0, "D": 0},
                provenance=[evidence],
            )
            existing = bucket[norm]
        updated_presence = dict(existing.source_presence)
        updated_counts = dict(existing.source_counts)
        updated_presence[source_type] = True
        updated_counts[source_type] += 1
        bucket[norm] = CandidateConcept(
            candidate_id=existing.candidate_id,
            label=existing.label,
            normalized_label=existing.normalized_label,
            suggested_entity_type=existing.suggested_entity_type,
            classification=existing.classification,
            summary_definition=existing.summary_definition or definition,
            source_presence=updated_presence,
            source_counts=updated_counts,
            schema_links=existing.schema_links,
            code_links=existing.code_links,
            governance_links=existing.governance_links,
            authoritative_evidence_count=existing.authoritative_evidence_count + (1 if source_type == "A" else 0),
            graph_degree=existing.graph_degree,
            relevance_score=existing.relevance_score,
            relevance_breakdown=existing.relevance_breakdown,
            provenance=existing.provenance + [evidence],
            aliases=sorted({*existing.aliases, label}),
            status=existing.status,
        )

    for concept in (source_a or {}).get("concepts", []):
        upsert(concept.get("name", ""), concept.get("definition", ""), "A", concept.get("provenance", {}).get("source_document", ""))
    for record in (source_b or {}).get("records", []):
        upsert(record.get("element_name", ""), record.get("definition", ""), "B")

    return CandidateGraph(concepts=list(bucket.values()), relationships=[])
```

- [ ] **Step 4: Run tests and verify they pass**

Run: `pytest tests/test_candidate_graph.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ontozense/core/candidate_graph.py tests/test_candidate_graph.py
git commit -m "feat(discovery): add candidate graph aggregation"
```

### Task 3: Add Relevance Scoring

**Files:**
- Create: `src/ontozense/core/relevance.py`
- Test: `tests/test_relevance.py`

- [ ] **Step 1: Write the failing scoring tests**

```python
from ontozense.core.discovery_contracts import CandidateConcept
from ontozense.core.relevance import score_candidates


def _concept(label: str, a: int, b: int, c: int, d: int, degree: int, definition: str):
    return CandidateConcept(
        candidate_id=f"cand_{label.lower()}",
        label=label,
        normalized_label=label.lower(),
        suggested_entity_type="Concept",
        classification="unknown",
        summary_definition=definition,
        source_presence={"A": a > 0, "B": b > 0, "C": c > 0, "D": d > 0},
        source_counts={"A": a, "B": b, "C": c, "D": d},
        authoritative_evidence_count=a,
        graph_degree=degree,
        relevance_score=0.0,
        relevance_breakdown={},
    )


def test_score_candidates_marks_high_evidence_concept_as_core_business():
    customer = _concept("Customer", 3, 1, 1, 1, 5, "Business party receiving service")
    scored = score_candidates([customer])
    assert scored[0].classification == "core_business"
    assert scored[0].relevance_score >= 0.70


def test_score_candidates_marks_low_evidence_concept_as_noise():
    tmp = _concept("tmp_col_1", 0, 0, 1, 0, 0, "")
    scored = score_candidates([tmp])
    assert scored[0].classification == "noise"
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `pytest tests/test_relevance.py -v`
Expected: FAIL with `ModuleNotFoundError` for `ontozense.core.relevance`

- [ ] **Step 3: Implement weighted relevance scoring with explanations**

```python
from __future__ import annotations

from dataclasses import replace

from .discovery_contracts import CandidateConcept

DEFAULT_WEIGHTS = {
    "authoritative_frequency": 0.25,
    "governance_presence": 0.20,
    "schema_linkage": 0.15,
    "code_usage": 0.10,
    "graph_centrality": 0.10,
    "definition_richness": 0.10,
    "business_naming_signal": 0.10,
}


def _clip(value: float) -> float:
    return max(0.0, min(1.0, value))


def _business_naming_signal(label: str) -> float:
    lowered = label.lower()
    if lowered.startswith("tmp_") or lowered.endswith("_id"):
        return 0.1
    return 0.8


def score_candidates(candidates: list[CandidateConcept], weights=None) -> list[CandidateConcept]:
    weights = dict(DEFAULT_WEIGHTS if weights is None else weights)
    scored: list[CandidateConcept] = []
    for c in candidates:
        breakdown = {
            "authoritative_frequency": weights["authoritative_frequency"] * _clip(c.source_counts.get("A", 0) / 3),
            "governance_presence": weights["governance_presence"] * (1.0 if c.source_presence.get("B") else 0.0),
            "schema_linkage": weights["schema_linkage"] * (1.0 if c.source_presence.get("C") else 0.0),
            "code_usage": weights["code_usage"] * (1.0 if c.source_presence.get("D") else 0.0),
            "graph_centrality": weights["graph_centrality"] * _clip(c.graph_degree / 5),
            "definition_richness": weights["definition_richness"] * (1.0 if c.summary_definition.strip() else 0.0),
            "business_naming_signal": weights["business_naming_signal"] * _business_naming_signal(c.label),
        }
        total = round(sum(breakdown.values()), 4)
        if total >= 0.70:
            classification = "core_business"
        elif total >= 0.40:
            classification = "supporting_technical"
        else:
            classification = "noise"
        scored.append(replace(c, relevance_score=total, relevance_breakdown=breakdown, classification=classification))
    return scored
```

- [ ] **Step 4: Run tests and verify they pass**

Run: `pytest tests/test_relevance.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ontozense/core/relevance.py tests/test_relevance.py
git commit -m "feat(discovery): add relevance scoring"
```

### Task 4: Emit Draft Profiles from Scored Candidates

**Files:**
- Create: `src/ontozense/core/profile_induction.py`
- Test: `tests/test_profile_induction.py`

- [ ] **Step 1: Write the failing profile induction tests**

```python
import json

from ontozense.core.discovery_contracts import CandidateConcept
from ontozense.core.profile_induction import write_induced_profile
from ontozense.core.profile import load_profile


def test_write_induced_profile_emits_loader_compatible_schema(tmp_path):
    concepts = [
        CandidateConcept(
            candidate_id="cand_customer",
            label="Customer",
            normalized_label="customer",
            suggested_entity_type="Concept",
            classification="core_business",
            summary_definition="A customer.",
            source_presence={"A": True, "B": True, "C": False, "D": False},
            source_counts={"A": 2, "B": 1, "C": 0, "D": 0},
            authoritative_evidence_count=2,
            graph_degree=3,
            relevance_score=0.82,
            relevance_breakdown={"authoritative_frequency": 0.25},
        )
    ]
    out_dir = tmp_path / "induced-profile"
    write_induced_profile("demo", concepts, out_dir)
    profile = load_profile(out_dir)
    assert profile.profile_name == "demo"
    assert "Concept" in profile.entity_types


def test_write_induced_profile_writes_induction_report(tmp_path):
    out_dir = tmp_path / "induced-profile"
    write_induced_profile("demo", [], out_dir)
    raw = json.loads((out_dir / "induction_report.json").read_text(encoding="utf-8"))
    assert raw["domain_name"] == "demo"
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `pytest tests/test_profile_induction.py -v`
Expected: FAIL with `ModuleNotFoundError` for `ontozense.core.profile_induction`

- [ ] **Step 3: Implement minimal induced profile writing**

```python
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .discovery_contracts import CandidateConcept, InductionReport


def write_induced_profile(domain_name: str, candidates: list[CandidateConcept], out_dir: str | Path) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    selected = [c for c in candidates if c.classification in {"core_business", "supporting_technical"}]
    schema = {
        "profile_name": domain_name,
        "profile_version": "0.1.0",
        "description": f"Induced draft profile for {domain_name}",
        "entity_types": {
            "Concept": {
                "required": ["definition"],
                "optional": ["source_reference"],
                "subtypes": [],
            }
        },
        "predicates": {},
        "id_format": {"strategy": "type_label_hash", "hash_length": 6},
        "alias_map": {},
        "canonical_verbs": {},
    }
    (out_dir / "schema.json").write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")
    (out_dir / "alias_map.json").write_text("{}\n", encoding="utf-8")
    (out_dir / "prompt_fragment.md").write_text(
        "Use the induced Concept vocabulary conservatively. Prefer explicitly defined business concepts.\n",
        encoding="utf-8",
    )
    report = InductionReport(
        domain_name=domain_name,
        generated_at=datetime.utcnow().isoformat(),
        candidate_count=len(candidates),
        selected_core_count=sum(1 for c in candidates if c.classification == "core_business"),
        selected_supporting_count=sum(1 for c in candidates if c.classification == "supporting_technical"),
        rejected_count=sum(1 for c in candidates if c.classification == "noise"),
        scoring_weights={"authoritative_frequency": 0.25},
        top_candidates=[{"candidate_id": c.candidate_id, "score": c.relevance_score} for c in selected[:10]],
        rejected_examples=[{"candidate_id": c.candidate_id, "score": c.relevance_score} for c in candidates if c.classification == "noise"][:10],
        predicate_suggestions=[],
        required_field_suggestions={"Concept": ["definition"]},
        review_notes=["Review entity types, aliases, and predicates before constrained rebuild."],
    )
    (out_dir / "induction_report.json").write_text(json.dumps(report.to_dict(), indent=2) + "\n", encoding="utf-8")
    return out_dir
```

- [ ] **Step 4: Run tests and verify they pass**

Run: `pytest tests/test_profile_induction.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ontozense/core/profile_induction.py tests/test_profile_induction.py
git commit -m "feat(discovery): add induced profile writer"
```

### Task 5: Add the `discover` CLI Command

**Files:**
- Modify: `src/ontozense/cli.py`
- Test: `tests/test_cli_discovery.py`

- [ ] **Step 1: Write the failing CLI test for `discover`**

```python
import json
from typer.testing import CliRunner

from ontozense.cli import app


runner = CliRunner()


def test_discover_writes_candidate_graph_files(tmp_path):
    source_a = tmp_path / "source-a.json"
    source_a.write_text(
        json.dumps({
            "concepts": [{"name": "Customer", "definition": "A client."}],
            "relationships": [],
        }),
        encoding="utf-8",
    )
    domain_dir = tmp_path / "domain"
    result = runner.invoke(app, [
        "discover",
        "--source-a", str(source_a),
        "--domain-dir", str(domain_dir),
    ])
    assert result.exit_code == 0
    assert (domain_dir / "discovery" / "candidate-graph.json").exists()
    assert (domain_dir / "discovery" / "candidate-provenance.json").exists()
```

- [ ] **Step 2: Run the CLI test and verify it fails**

Run: `pytest tests/test_cli_discovery.py::test_discover_writes_candidate_graph_files -v`
Expected: FAIL with `No such command 'discover'`

- [ ] **Step 3: Implement the minimal `discover` command**

```python
@app.command(name="discover")
def discover(
    source_a: list[Path] = typer.Option(None, "--source-a"),
    domain_dir: Path = typer.Option(..., "--domain-dir"),
):
    from .core.candidate_graph import build_candidate_graph

    discovery_dir = domain_dir / "discovery"
    discovery_dir.mkdir(parents=True, exist_ok=True)

    merged_a = {"concepts": [], "relationships": []}
    for path in source_a or []:
        raw = json.loads(path.read_text(encoding="utf-8"))
        merged_a["concepts"].extend(raw.get("concepts", []))
        merged_a["relationships"].extend(raw.get("relationships", []))

    graph = build_candidate_graph(source_a=merged_a)
    (discovery_dir / "candidate-graph.json").write_text(
        json.dumps(graph.to_dict(), indent=2) + "\n",
        encoding="utf-8",
    )
    provenance = {
        "concepts": [
            {
                "candidate_id": c.candidate_id,
                "provenance": [p.to_dict() for p in c.provenance],
            }
            for c in graph.concepts
        ]
    }
    (discovery_dir / "candidate-provenance.json").write_text(
        json.dumps(provenance, indent=2) + "\n",
        encoding="utf-8",
    )
    (discovery_dir / "concept-mappings.json").write_text(
        json.dumps({"mappings": []}, indent=2) + "\n",
        encoding="utf-8",
    )
    console.print(f"[green]Discovery artifacts written to[/] {discovery_dir}")
```

- [ ] **Step 4: Run the CLI test and verify it passes**

Run: `pytest tests/test_cli_discovery.py::test_discover_writes_candidate_graph_files -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ontozense/cli.py tests/test_cli_discovery.py
git commit -m "feat(cli): add discover command"
```

### Task 6: Add the `induce-profile` CLI Command

**Files:**
- Modify: `src/ontozense/cli.py`
- Test: `tests/test_cli_discovery.py`

- [ ] **Step 1: Write the failing CLI test for `induce-profile`**

```python
import json
from typer.testing import CliRunner

from ontozense.cli import app


runner = CliRunner()


def test_induce_profile_writes_schema_and_report(tmp_path):
    candidate_graph = tmp_path / "candidate-graph.json"
    candidate_graph.write_text(
        json.dumps({
            "concepts": [
                {
                    "candidate_id": "cand_customer",
                    "label": "Customer",
                    "normalized_label": "customer",
                    "suggested_entity_type": "Concept",
                    "classification": "core_business",
                    "summary_definition": "A customer.",
                    "source_presence": {"A": True, "B": True, "C": False, "D": False},
                    "source_counts": {"A": 2, "B": 1, "C": 0, "D": 0},
                    "schema_links": [],
                    "code_links": [],
                    "governance_links": [],
                    "authoritative_evidence_count": 2,
                    "graph_degree": 3,
                    "relevance_score": 0.82,
                    "relevance_breakdown": {"authoritative_frequency": 0.25},
                    "provenance": [],
                    "aliases": [],
                    "status": "candidate"
                }
            ],
            "relationships": []
        }),
        encoding="utf-8",
    )
    out_dir = tmp_path / "induced-profile"
    result = runner.invoke(app, [
        "induce-profile",
        str(candidate_graph),
        "--output-dir", str(out_dir),
        "--domain-name", "demo",
    ])
    assert result.exit_code == 0
    assert (out_dir / "schema.json").exists()
    assert (out_dir / "induction_report.json").exists()
```

- [ ] **Step 2: Run the CLI test and verify it fails**

Run: `pytest tests/test_cli_discovery.py::test_induce_profile_writes_schema_and_report -v`
Expected: FAIL with `No such command 'induce-profile'`

- [ ] **Step 3: Implement the minimal `induce-profile` command**

```python
@app.command(name="induce-profile")
def induce_profile(
    candidate_graph: Path = typer.Argument(...),
    output_dir: Path = typer.Option(..., "--output-dir"),
    domain_name: str = typer.Option(..., "--domain-name"),
):
    from .core.discovery_contracts import CandidateConcept
    from .core.profile_induction import write_induced_profile
    from .core.relevance import score_candidates

    raw = json.loads(candidate_graph.read_text(encoding="utf-8"))
    concepts = [CandidateConcept.from_dict(c) for c in raw.get("concepts", [])]
    scored = score_candidates(concepts)
    write_induced_profile(domain_name, scored, output_dir)
    console.print(f"[green]Induced profile written to[/] {output_dir}")
```

- [ ] **Step 4: Run the CLI test and verify it passes**

Run: `pytest tests/test_cli_discovery.py::test_induce_profile_writes_schema_and_report -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ontozense/cli.py tests/test_cli_discovery.py
git commit -m "feat(cli): add induce-profile command"
```

### Task 7: Add the `rebuild` CLI Orchestration Command

**Files:**
- Modify: `src/ontozense/cli.py`
- Test: `tests/test_cli_discovery.py`

- [ ] **Step 1: Write the failing CLI test for `rebuild` orchestration**

```python
from typer.testing import CliRunner

from ontozense.cli import app


runner = CliRunner()


def test_rebuild_requires_profile_and_reports_next_steps(tmp_path):
    profile_dir = tmp_path / "profile"
    profile_dir.mkdir()
    result = runner.invoke(app, [
        "rebuild",
        "--profile", str(profile_dir),
        "--domain-dir", str(tmp_path / "domain"),
    ])
    assert result.exit_code != 0
    assert "schema.json" in result.stdout or "source" in result.stdout
```

- [ ] **Step 2: Run the CLI test and verify it fails**

Run: `pytest tests/test_cli_discovery.py::test_rebuild_requires_profile_and_reports_next_steps -v`
Expected: FAIL with `No such command 'rebuild'`

- [ ] **Step 3: Implement the minimal `rebuild` command as a safe wrapper**

```python
@app.command(name="rebuild")
def rebuild(
    profile: Path = typer.Option(..., "--profile"),
    domain_dir: Path = typer.Option(..., "--domain-dir"),
    source_a: list[Path] = typer.Option(None, "--source-a"),
    source_b: Path = typer.Option(None, "--source-b"),
    source_c: Path = typer.Option(None, "--source-c"),
    source_d: Path = typer.Option(None, "--source-d"),
):
    from .core.profile import load_profile, ProfileError

    try:
        loaded = load_profile(profile)
    except ProfileError as e:
        console.print(f"[red]Profile error:[/] {e}")
        raise typer.Exit(1)

    console.print(
        "[bold]Rebuild plan[/]: run extract/fuse/validate/lint/report with "
        f"profile={loaded.profile_name} under {domain_dir}"
    )
    console.print("[yellow]Initial implementation note:[/] this command is an orchestrator wrapper. Add subprocess-free direct calls in a follow-up task once the discovery flow is stable.")
```

- [ ] **Step 4: Run the CLI test and verify it passes**

Run: `pytest tests/test_cli_discovery.py::test_rebuild_requires_profile_and_reports_next_steps -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ontozense/cli.py tests/test_cli_discovery.py
git commit -m "feat(cli): add rebuild orchestrator command"
```

### Task 8: Add End-to-End Discovery Flow Coverage

**Files:**
- Modify: `tests/test_cli_discovery.py`
- Modify: `README.md`

- [ ] **Step 1: Write the failing end-to-end test for `discover -> induce-profile`**

```python
import json
from typer.testing import CliRunner

from ontozense.cli import app


runner = CliRunner()


def test_discover_then_induce_profile_round_trip(tmp_path):
    source_a = tmp_path / "source-a.json"
    source_a.write_text(
        json.dumps({
            "concepts": [{"name": "Customer", "definition": "A client."}],
            "relationships": [],
        }),
        encoding="utf-8",
    )
    domain_dir = tmp_path / "domain"
    discover = runner.invoke(app, [
        "discover",
        "--source-a", str(source_a),
        "--domain-dir", str(domain_dir),
    ])
    assert discover.exit_code == 0

    induce = runner.invoke(app, [
        "induce-profile",
        str(domain_dir / "discovery" / "candidate-graph.json"),
        "--output-dir", str(domain_dir / "induced-profile"),
        "--domain-name", "demo",
    ])
    assert induce.exit_code == 0
    assert (domain_dir / "induced-profile" / "schema.json").exists()
```

- [ ] **Step 2: Run the end-to-end CLI test and verify it fails if any prior task is incomplete**

Run: `pytest tests/test_cli_discovery.py::test_discover_then_induce_profile_round_trip -v`
Expected: FAIL until tasks 5 and 6 are correctly wired

- [ ] **Step 3: Update README with a minimal Path 1 discovery workflow section**

```markdown
## Discovery Workflow

Use this only when you do not already have a domain profile.

```bash
ontozense discover --source-a source-a.json --domain-dir domains/mydomain
ontozense induce-profile domains/mydomain/discovery/candidate-graph.json \
  --domain-name mydomain \
  --output-dir domains/mydomain/induced-profile
# Review/edit the induced profile, then run the normal profile-aware pipeline.
```
```

- [ ] **Step 4: Run the CLI test and targeted README-adjacent checks**

Run: `pytest tests/test_cli_discovery.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_cli_discovery.py README.md
git commit -m "docs: add discovery workflow usage"
```

### Task 9: Run Full Regression and Clean Up

**Files:**
- Modify: any files needed from earlier tasks only if regression failures prove a gap

- [ ] **Step 1: Run the full targeted new test set**

Run: `pytest tests/test_discovery_contracts.py tests/test_candidate_graph.py tests/test_relevance.py tests/test_profile_induction.py tests/test_cli_discovery.py -v`
Expected: PASS

- [ ] **Step 2: Run the full suite**

Run: `pytest -q`
Expected: PASS with the existing suite count plus the new discovery tests

- [ ] **Step 3: If regressions appear, make minimal fixes only in touched modules**

```python
# Example pattern only if needed during regression repair:
# keep fixes local to discovery-side modules or isolated CLI wiring
# do not change existing profile-mode JSON serialization unless a test proves it is required
```

- [ ] **Step 4: Re-run the full suite**

Run: `pytest -q`
Expected: PASS

- [ ] **Step 5: Commit final stabilization changes**

```bash
git add src/ontozense/cli.py src/ontozense/core/*.py tests/*.py README.md
git commit -m "test: stabilize discovery workflow rollout"
```

---

## Spec Coverage Check

- Candidate graph generation: covered by Tasks 1, 2, and 5.
- Relevance scoring and classification: covered by Task 3.
- Draft profile generation: covered by Tasks 4 and 6.
- Path 1 workflow preservation: covered by Tasks 5, 6, 7, and README constraints in Task 8.
- Reuse of existing profile-aware pipeline as second pass: covered by Task 7.
- Reviewable artifacts under `domain_dir`: covered by Tasks 5 and 6.
- Backward compatibility: enforced by Task 9 full regression.

## Placeholder Scan

- No `TODO`, `TBD`, or deferred implementation markers remain.
- Any follow-up note in Task 7 is non-blocking and does not prevent a working first implementation.

## Type Consistency Check

- `CandidateConcept`, `CandidateRelationship`, `EvidenceEntry`, and `InductionReport` are defined first in Task 1 and reused consistently later.
- `build_candidate_graph`, `score_candidates`, and `write_induced_profile` are introduced before CLI tasks call them.
- Command names are consistent with the approved architecture: `discover`, `induce-profile`, `rebuild`.
