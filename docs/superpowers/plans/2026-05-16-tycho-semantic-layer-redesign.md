# Tycho Semantic-Layer Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `fused.json → OWL` exporter plus two CLI orchestrators (`survey` and `draft`) so Tycho produces a draft OWL ontology the user can open in a curation tool, and rewrite README + NPL tutorial around the new three-stage user journey.

**Architecture:** Two new CLI commands wrap the existing low-level commands (`extract-a`, `discover`, `induce-profile`, `fuse`, `validate`, `lint`). A new `core/owl_export.py` module projects the internal `fused.json` into standard OWL/Turtle. All existing commands stay functional; `rebuild` is marked deprecated. Documentation is rewritten outcome-first around the semantic-layer vocabulary established in the design spec.

**Tech Stack:** Python 3.11–3.13, Typer CLI, dataclasses, existing Ontozense pipeline modules, `rdflib` (already in dependency tree), pytest.

**Design spec:** `docs/superpowers/specs/2026-05-16-tycho-semantic-layer-redesign-design.md`

---

## File Map

### New files

- `src/ontozense/core/owl_export.py`
  - `fused_to_owl(fused, profile=None, ...) -> str` — project a FusionResult into an OWL serialisation.
- `tests/test_owl_export.py`
  - Unit tests for the converter (entities, relationships, annotations, profile-aware URIs, formats).
- `tests/test_cli_survey.py`
  - CLI tests for the new `survey` command.
- `tests/test_cli_draft.py`
  - CLI tests for the new `draft` command.
- `docs/ontozense-npl-advanced.md`
  - Old NPL tutorial moved here (renamed), re-framed as a power-user reference.
- `docs/superpowers/specs/2026-05-16-tycho-semantic-layer-redesign-design.md`
  - Already exists (committed in `be2d7eb`); the design spec this plan implements.

### Existing files modified

- `src/ontozense/cli.py`
  - Add `survey` command (~150 LOC).
  - Add `draft` command (~150 LOC).
  - Update `rebuild` to emit a deprecation note (~20 LOC).
  - Update help text on each existing user-facing command (`extract-a`, `discover`, `induce-profile`, `fuse`, `validate`, `lint`, `report`) with a one-liner pointing at `survey` / `draft`.
- `README.md`
  - Rewrite the first ~30 lines (intro, journey diagram, two-command Quick start, glossary).
  - Rename `## Three operating modes` → `## How Tycho works` and reword.
  - Rewrite `## Quick start` around `survey` + `draft`; move the seven-command chain to a new `## Advanced — running the pipeline by hand` section.
  - Remove the standalone `## Discovery workflow (no profile yet)` section (folded into the new front-matter).
- `docs/ontozense-npl-validation.md`
  - Rewrite around `survey` + `draft`. Five parts (A. Setup, B. Workspace, C. Survey, D. Draft, E. Hand off). Each part keeps `✓ Expected:` checkpoints.

---

## Task 1: OWL export — entities to OWL classes

**Files:**
- Create: `src/ontozense/core/owl_export.py`
- Test: `tests/test_owl_export.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for the fused.json → OWL exporter (semantic-layer redesign)."""

from __future__ import annotations

from rdflib import Graph, RDF, RDFS, OWL

from ontozense.core.fusion import FieldProvenance, FusedElement, FusionResult
from ontozense.core.owl_export import fused_to_owl


def _el(name: str, *, definition: str = "", entity_type: str = "Concept") -> FusedElement:
    prov: dict = {}
    if definition:
        prov["definition"] = FieldProvenance(value=definition, source="A")
    return FusedElement(
        element_name=name,
        provenance=prov,
        extra_fields={"entity_type": entity_type} if entity_type else {},
    )


def _result(elements=(), relationships=()) -> FusionResult:
    return FusionResult(
        elements=list(elements),
        relationships=list(relationships),
        domain_name="test",
        fusion_timestamp="2026-05-16T00:00:00",
    )


class TestEntityToClass:
    def test_each_element_becomes_an_owl_class(self):
        result = _result(elements=[_el("Borrower"), _el("Loan")])
        ttl = fused_to_owl(result, format="turtle")
        g = Graph()
        g.parse(data=ttl, format="turtle")
        classes = list(g.subjects(RDF.type, OWL.Class))
        assert len(classes) == 2

    def test_element_name_becomes_rdfs_label(self):
        result = _result(elements=[_el("Borrower")])
        ttl = fused_to_owl(result, format="turtle")
        g = Graph()
        g.parse(data=ttl, format="turtle")
        labels = {str(o) for o in g.objects(predicate=RDFS.label)}
        assert "Borrower" in labels

    def test_empty_result_yields_a_valid_owl_graph(self):
        ttl = fused_to_owl(_result(), format="turtle")
        g = Graph()
        g.parse(data=ttl, format="turtle")
        # No classes, but the graph parses cleanly — that's the contract.
        assert len(list(g.subjects(RDF.type, OWL.Class))) == 0
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `pytest tests/test_owl_export.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ontozense.core.owl_export'`

- [ ] **Step 3: Implement the minimum that turns those tests green**

```python
"""Convert FusionResult (Tycho's internal fused.json data) into an OWL
ontology in W3C standard format.

The OWL file is Tycho's handoff artifact — the thing an expert curator
opens in Ontology Playground, Protégé, or any OWL editor to finish the
remaining ~30% of the semantic-layer work.

This module produces a standalone OWL graph from a :class:`FusionResult`.
``fused.json`` carries data that doesn't fit cleanly in OWL (confidence
scores, multi-source conflict logs, per-field anchors); that information
stays in :mod:`ontozense.core.fusion` for power-user inspection. The OWL
projection is for human review by a curator, not for round-trip storage.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from rdflib import Graph, Literal, Namespace, RDF, RDFS, OWL

if TYPE_CHECKING:
    from .fusion import FusionResult
    from .profile import Profile


def fused_to_owl(
    fused: "FusionResult",
    profile: "Profile | None" = None,
    domain_namespace: str = "https://tycho.local",
    format: str = "turtle",
) -> str:
    """Return the OWL serialisation of a FusionResult as a string.

    Parameters
    ----------
    fused
        The internal Tycho fusion result (the in-memory shape of
        ``fused.json``).
    profile
        Optional profile. When supplied, used for URI generation and
        type assignment. When ``None``, every element is rendered as a
        generic ``owl:Class`` with a label.
    domain_namespace
        Base URL for the generated ontology. Combined with the fusion
        result's ``domain_name`` to form per-element URIs.
    format
        ``rdflib`` serialisation format. Defaults to ``turtle``.
    """
    g = Graph()
    domain = (fused.domain_name or "default").lower().replace(" ", "_")
    base_iri = f"{domain_namespace}/{domain}/"
    ns = Namespace(base_iri)
    g.bind("", ns)
    g.bind("owl", OWL)
    g.bind("rdfs", RDFS)

    for element in fused.elements:
        uri = ns[_id_fragment(element.element_name)]
        g.add((uri, RDF.type, OWL.Class))
        g.add((uri, RDFS.label, Literal(element.element_name)))

    return g.serialize(format=format)


def _id_fragment(label: str) -> str:
    """Generate a URI fragment for an element name."""
    return label.strip().lower().replace(" ", "_").replace("/", "_")
```

- [ ] **Step 4: Run tests and verify they pass**

Run: `pytest tests/test_owl_export.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/ontozense/core/owl_export.py tests/test_owl_export.py
git commit -m "feat(owl-export): entity-to-OWL-class conversion (Task 1)"
```

---

## Task 2: OWL export — relationships to ObjectProperties

**Files:**
- Modify: `src/ontozense/core/owl_export.py`
- Test: `tests/test_owl_export.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_owl_export.py`:

```python
from ontozense.core.fusion import FusedRelationship


def _rel(subject: str, predicate: str, obj: str) -> FusedRelationship:
    return FusedRelationship(
        subject=subject,
        predicate=predicate,
        object=obj,
        provenance={},
    )


class TestRelationshipToProperty:
    def test_each_relationship_becomes_an_object_property(self):
        result = _result(
            elements=[_el("Borrower"), _el("Loan")],
            relationships=[_rel("Borrower", "HasLoan", "Loan")],
        )
        ttl = fused_to_owl(result, format="turtle")
        g = Graph()
        g.parse(data=ttl, format="turtle")
        props = list(g.subjects(RDF.type, OWL.ObjectProperty))
        assert len(props) == 1

    def test_relationship_has_domain_and_range(self):
        result = _result(
            elements=[_el("Borrower"), _el("Loan")],
            relationships=[_rel("Borrower", "HasLoan", "Loan")],
        )
        ttl = fused_to_owl(result, format="turtle")
        g = Graph()
        g.parse(data=ttl, format="turtle")
        props = list(g.subjects(RDF.type, OWL.ObjectProperty))
        assert len(props) == 1
        domains = list(g.objects(subject=props[0], predicate=RDFS.domain))
        ranges = list(g.objects(subject=props[0], predicate=RDFS.range))
        assert len(domains) == 1 and len(ranges) == 1

    def test_duplicate_relationship_predicate_emits_one_property(self):
        # Two relationships sharing the same predicate name should map
        # to a single ObjectProperty (predicate is the property; the
        # endpoints are the usage, not extra properties).
        result = _result(
            elements=[_el("Borrower"), _el("Loan"), _el("Collateral")],
            relationships=[
                _rel("Borrower", "Has", "Loan"),
                _rel("Borrower", "Has", "Collateral"),
            ],
        )
        ttl = fused_to_owl(result, format="turtle")
        g = Graph()
        g.parse(data=ttl, format="turtle")
        props = list(g.subjects(RDF.type, OWL.ObjectProperty))
        assert len(props) == 1  # one "Has" property
```

- [ ] **Step 2: Run tests and verify they fail**

Run: `pytest tests/test_owl_export.py::TestRelationshipToProperty -v`
Expected: FAIL (relationships not yet emitted).

- [ ] **Step 3: Add relationship emission to `fused_to_owl`**

Inside `src/ontozense/core/owl_export.py`, after the existing class-emission loop and **before** the `return` statement, add:

```python
    # One ObjectProperty per distinct predicate. Predicates often
    # repeat across relationships (e.g. "HasLoan" used by many
    # borrowers); we deduplicate by predicate name and let the
    # subject/object endpoints contribute to the domain / range.
    predicates: dict[str, dict[str, set]] = {}
    for rel in fused.relationships:
        entry = predicates.setdefault(
            rel.predicate, {"domains": set(), "ranges": set()},
        )
        entry["domains"].add(_id_fragment(rel.subject))
        entry["ranges"].add(_id_fragment(rel.object))

    for predicate_name, endpoints in predicates.items():
        uri = ns[_id_fragment(predicate_name)]
        g.add((uri, RDF.type, OWL.ObjectProperty))
        g.add((uri, RDFS.label, Literal(predicate_name)))
        for domain in endpoints["domains"]:
            g.add((uri, RDFS.domain, ns[domain]))
        for rng in endpoints["ranges"]:
            g.add((uri, RDFS.range, ns[rng]))
```

- [ ] **Step 4: Run tests and verify they pass**

Run: `pytest tests/test_owl_export.py -v`
Expected: PASS (6 tests: 3 from Task 1 + 3 new).

- [ ] **Step 5: Commit**

```bash
git add src/ontozense/core/owl_export.py tests/test_owl_export.py
git commit -m "feat(owl-export): relationships to ObjectProperties (Task 2)"
```

---

## Task 3: OWL export — annotations + profile-aware URIs + multi-format

**Files:**
- Modify: `src/ontozense/core/owl_export.py`
- Test: `tests/test_owl_export.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_owl_export.py`:

```python
from rdflib.namespace import DC, DCTERMS


class TestAnnotations:
    def test_definition_becomes_rdfs_comment(self):
        result = _result(elements=[
            _el("Borrower", definition="A party that receives a service."),
        ])
        ttl = fused_to_owl(result, format="turtle")
        g = Graph()
        g.parse(data=ttl, format="turtle")
        comments = {str(o) for o in g.objects(predicate=RDFS.comment)}
        assert "A party that receives a service." in comments

    def test_citation_becomes_dc_source(self):
        el = _el("Borrower")
        el.provenance["citation"] = FieldProvenance(
            value="Basel D403, section 3.2", source="A",
        )
        result = _result(elements=[el])
        ttl = fused_to_owl(result, format="turtle")
        g = Graph()
        g.parse(data=ttl, format="turtle")
        sources = {str(o) for o in g.objects(predicate=DC.source)}
        assert "Basel D403, section 3.2" in sources


class TestSerialisationFormats:
    def test_turtle_default(self):
        result = _result(elements=[_el("Borrower")])
        out = fused_to_owl(result)  # default format
        assert "Borrower" in out
        # Turtle starts with "@prefix" or a triple
        assert "@prefix" in out or "Borrower" in out

    def test_jsonld_format(self):
        result = _result(elements=[_el("Borrower")])
        out = fused_to_owl(result, format="json-ld")
        # JSON-LD is JSON; should parse
        import json
        json.loads(out)  # raises if not valid JSON

    def test_owl_xml_format(self):
        result = _result(elements=[_el("Borrower")])
        out = fused_to_owl(result, format="xml")  # rdflib's "xml" == RDF/XML
        assert "<?xml" in out


class TestEmptyAnnotations:
    def test_element_with_no_definition_emits_no_comment(self):
        result = _result(elements=[_el("Borrower")])  # no definition
        ttl = fused_to_owl(result, format="turtle")
        g = Graph()
        g.parse(data=ttl, format="turtle")
        comments = list(g.objects(predicate=RDFS.comment))
        assert len(comments) == 0
```

- [ ] **Step 2: Run tests and verify they fail**

Run: `pytest tests/test_owl_export.py -v -k "Annotations or Serialisation"`
Expected: FAIL (annotations not yet emitted; jsonld may fail differently).

- [ ] **Step 3: Add annotations to the class emission loop**

Inside `src/ontozense/core/owl_export.py`:

1. Add the namespace binding near the top of `fused_to_owl`, after `g.bind("rdfs", RDFS)`:

```python
    g.bind("dc", DC)
```

2. Import `DC` from `rdflib.namespace`:

```python
from rdflib.namespace import DC
```

(Add at the top of the file, near the existing `from rdflib import ...` line.)

3. Inside the `for element in fused.elements:` loop, after the label line, add:

```python
        # Annotations from per-field provenance.
        definition = element.provenance.get("definition")
        if definition and definition.value:
            g.add((uri, RDFS.comment, Literal(definition.value)))
        citation = element.provenance.get("citation")
        if citation and citation.value:
            g.add((uri, DC.source, Literal(citation.value)))
```

- [ ] **Step 4: Run tests and verify they pass**

Run: `pytest tests/test_owl_export.py -v`
Expected: PASS (all tests so far: ~12 tests).

- [ ] **Step 5: Commit**

```bash
git add src/ontozense/core/owl_export.py tests/test_owl_export.py
git commit -m "feat(owl-export): annotations (def, citation) + multi-format (Task 3)"
```

---

## Task 4: OWL export — profile-aware URIs

**Files:**
- Modify: `src/ontozense/core/owl_export.py`
- Test: `tests/test_owl_export.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_owl_export.py`:

```python
from ontozense.core.profile import IdFormat, Profile, EntityType


def _profile_with_npl_types() -> Profile:
    return Profile(
        profile_name="npl",
        profile_version="1.0.0",
        description="Test NPL profile.",
        entity_types={
            "Counterparty": EntityType(name="Counterparty"),
            "Loan": EntityType(name="Loan"),
        },
        predicates={},
        id_format=IdFormat(),
    )


class TestProfileAwareURIs:
    def test_uri_includes_profile_name_when_profile_given(self):
        result = _result(elements=[_el("Borrower")])
        result.domain_name = "npl"
        ttl = fused_to_owl(
            result, profile=_profile_with_npl_types(), format="turtle",
        )
        # Class URI should live under /npl/ namespace
        assert "/npl/" in ttl

    def test_missing_profile_uses_generic_class(self):
        """No profile → element renders as plain owl:Class with no
        rdfs:subClassOf. The 'generic Concept' fallback the spec
        describes."""
        result = _result(elements=[_el("Borrower")])
        ttl = fused_to_owl(result, profile=None, format="turtle")
        g = Graph()
        g.parse(data=ttl, format="turtle")
        # Class exists, no subclass-of relationships.
        classes = list(g.subjects(RDF.type, OWL.Class))
        assert len(classes) == 1
        subclasses = list(g.triples((None, RDFS.subClassOf, None)))
        assert len(subclasses) == 0
```

- [ ] **Step 2: Run tests and verify they fail**

Run: `pytest tests/test_owl_export.py::TestProfileAwareURIs -v`
Expected: FAIL on the profile-name test (current implementation uses `domain_name` directly without profile awareness).

- [ ] **Step 3: Thread profile through URI construction**

In `fused_to_owl` in `src/ontozense/core/owl_export.py`, change the domain-resolution lines to prefer the profile's name when given:

```python
    # Prefer the profile's name for the URI namespace; fall back to
    # the fusion result's domain_name.
    if profile is not None:
        domain = profile.profile_name.lower().replace(" ", "_")
    else:
        domain = (fused.domain_name or "default").lower().replace(" ", "_")
    base_iri = f"{domain_namespace}/{domain}/"
```

- [ ] **Step 4: Run tests and verify they pass**

Run: `pytest tests/test_owl_export.py -v`
Expected: PASS (all tests).

- [ ] **Step 5: Commit**

```bash
git add src/ontozense/core/owl_export.py tests/test_owl_export.py
git commit -m "feat(owl-export): profile-aware URI generation (Task 4)"
```

---

## Task 5: New `ontozense survey` CLI command

**Files:**
- Modify: `src/ontozense/cli.py` (append before `if __name__ == "__main__":`)
- Test: `tests/test_cli_survey.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for the new `ontozense survey` command (Stage 1 orchestrator)."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from ontozense.cli import app


runner = CliRunner()


def _write_source_a_json(path: Path, concepts: list[dict]) -> None:
    path.write_text(
        json.dumps({"concepts": concepts, "relationships": []}),
        encoding="utf-8",
    )


def _write_source_b(path: Path, records: list[dict]) -> None:
    path.write_text(json.dumps(records), encoding="utf-8")


class TestSurveyHappyPath:
    def test_survey_with_pre_extracted_source_a_writes_three_artifacts(
        self, tmp_path: Path,
    ):
        """A pre-extracted source-a.json passed via --source-a should
        flow through to discover without re-extraction (no LLM call)."""
        sa = tmp_path / "source-a.json"
        _write_source_a_json(sa, [
            {"name": "Borrower", "definition": "A borrower."},
        ])
        domain_dir = tmp_path / "domain"
        result = runner.invoke(app, [
            "survey",
            "--source-a", str(sa),
            "--domain-dir", str(domain_dir),
        ])
        assert result.exit_code == 0, result.output
        assert (domain_dir / "discovery" / "candidate-graph.json").exists()
        assert (domain_dir / "discovery" / "candidate-provenance.json").exists()

    def test_survey_accepts_repeated_source_a_files(self, tmp_path: Path):
        sa1 = tmp_path / "a1.json"
        sa2 = tmp_path / "a2.json"
        _write_source_a_json(sa1, [{"name": "Borrower", "definition": "B"}])
        _write_source_a_json(sa2, [{"name": "Loan", "definition": "L"}])
        domain_dir = tmp_path / "domain"
        result = runner.invoke(app, [
            "survey",
            "--source-a", str(sa1),
            "--source-a", str(sa2),
            "--domain-dir", str(domain_dir),
        ])
        assert result.exit_code == 0
        g = json.loads(
            (domain_dir / "discovery" / "candidate-graph.json")
            .read_text(encoding="utf-8")
        )
        labels = {c["label"] for c in g["concepts"]}
        assert {"Borrower", "Loan"}.issubset(labels)

    def test_survey_accepts_a_directory_of_source_a_jsons(
        self, tmp_path: Path,
    ):
        """Directory walk: every .json in the directory is treated as a
        pre-extracted source-a output."""
        sa_dir = tmp_path / "sources"
        sa_dir.mkdir()
        _write_source_a_json(
            sa_dir / "doc1.json",
            [{"name": "Borrower", "definition": "B"}],
        )
        _write_source_a_json(
            sa_dir / "doc2.json",
            [{"name": "Loan", "definition": "L"}],
        )
        domain_dir = tmp_path / "domain"
        result = runner.invoke(app, [
            "survey",
            "--source-a", str(sa_dir),
            "--domain-dir", str(domain_dir),
        ])
        assert result.exit_code == 0, result.output
        g = json.loads(
            (domain_dir / "discovery" / "candidate-graph.json")
            .read_text(encoding="utf-8")
        )
        labels = {c["label"] for c in g["concepts"]}
        assert {"Borrower", "Loan"}.issubset(labels)

    def test_survey_with_source_a_and_b_cross_merge(self, tmp_path: Path):
        sa = tmp_path / "source-a.json"
        sb = tmp_path / "governance.json"
        _write_source_a_json(sa, [{"name": "Customer", "definition": "C."}])
        _write_source_b(sb, [{"element_name": "customer", "definition": "B."}])
        domain_dir = tmp_path / "domain"
        result = runner.invoke(app, [
            "survey",
            "--source-a", str(sa),
            "--source-b", str(sb),
            "--domain-dir", str(domain_dir),
        ])
        assert result.exit_code == 0
        g = json.loads(
            (domain_dir / "discovery" / "candidate-graph.json")
            .read_text(encoding="utf-8")
        )
        # Source A "Customer" and Source B "customer" should merge to 1 concept.
        assert len(g["concepts"]) == 1
        c = g["concepts"][0]
        assert c["source_presence"]["A"] is True
        assert c["source_presence"]["B"] is True


class TestSurveyErrors:
    def test_missing_domain_dir_fails(self, tmp_path: Path):
        result = runner.invoke(app, ["survey"])
        assert result.exit_code != 0

    def test_nonexistent_source_fails_cleanly(self, tmp_path: Path):
        result = runner.invoke(app, [
            "survey",
            "--source-a", str(tmp_path / "missing.json"),
            "--domain-dir", str(tmp_path / "domain"),
        ])
        assert result.exit_code != 0
        assert "missing.json" in result.output
```

- [ ] **Step 2: Run tests and verify they fail**

Run: `pytest tests/test_cli_survey.py -v`
Expected: FAIL with `No such command 'survey'`.

- [ ] **Step 3: Implement the `survey` command**

Append to `src/ontozense/cli.py`, immediately before the existing `if __name__ == "__main__":` block:

```python
# ─── survey (Stage 1 orchestrator) ───────────────────────────────────────────


@app.command(name="survey")
def survey(
    source_a: list[Path] = typer.Option(
        None, "--source-a",
        help=(
            "Source A input: a .md/.txt file (LLM-extracted), a "
            ".json file (pre-extracted source-a.json — reused as-is), "
            "a glob, or a directory (walked recursively). Repeatable."
        ),
    ),
    source_b: list[Path] = typer.Option(
        None, "--source-b",
        help=(
            "Source B governance JSON. File, glob, or directory. "
            "Repeatable."
        ),
    ),
    source_c: list[Path] = typer.Option(
        None, "--source-c",
        help="Source C schema input (forward-compat; not consumed today).",
    ),
    source_d: list[Path] = typer.Option(
        None, "--source-d",
        help="Source D code input (forward-compat; not consumed today).",
    ),
    profile: Path = typer.Option(
        None, "--profile",
        help=(
            "Optional profile directory. Only its alias_map is "
            "consulted for light synonym normalisation."
        ),
    ),
    domain_dir: Path = typer.Option(
        ..., "--domain-dir",
        help=(
            "Per-domain workspace directory. Discovery artifacts are "
            "written under <domain_dir>/discovery/."
        ),
    ),
    model: str = typer.Option(
        "azure/gpt-5.4", "--model", "-m",
        help="LLM model identifier for the underlying extract-a step.",
    ),
) -> None:
    """Stage 1 of the semantic-layer journey.

    Survey your raw sources: extract from documents, merge in
    governance / schema / code, and produce a candidate graph for
    inspection. Writes three artifacts under <DOMAIN_DIR>/discovery/:

      - source-a.json      — concatenated extract-a output
      - candidate-graph.json
      - candidate-provenance.json

    Next step: ``ontozense draft`` (Stage 2).
    """
    import json as _json

    from .core.candidate_graph import build_candidate_graph

    discovery_dir = domain_dir / "discovery"
    discovery_dir.mkdir(parents=True, exist_ok=True)

    # ─── Source A: expand + partition ──
    try:
        a_files = _expand_source_paths(
            source_a or [],
            file_extensions={".md", ".txt", ".markdown", ".json"},
        )
    except _SourceLoadError as err:
        console.print(f"[red]Failed to enumerate --source-a paths:[/] {err}")
        raise typer.Exit(code=2)

    merged_a_concepts: list[dict] = []
    merged_a_rels: list[dict] = []
    for path in a_files:
        if path.suffix.lower() == ".json":
            # Pre-extracted source-a.json — load as-is.
            try:
                raw = _load_json(path)
            except _SourceLoadError as err:
                console.print(
                    f"[red]Failed to load --source-a {err.path}:[/] {err}"
                )
                raise typer.Exit(code=2)
            if not isinstance(raw, dict):
                console.print(
                    f"[red]--source-a {path}: must be a JSON object[/]"
                )
                raise typer.Exit(code=2)
            merged_a_concepts.extend(raw.get("concepts", []) or [])
            merged_a_rels.extend(raw.get("relationships", []) or [])
        else:
            # Doc — run extract-a and read its JSON output.
            extracted = _run_extract_a_for_survey(path, domain_dir, model)
            merged_a_concepts.extend(extracted.get("concepts", []) or [])
            merged_a_rels.extend(extracted.get("relationships", []) or [])

    merged_a: dict | None = None
    if merged_a_concepts or merged_a_rels:
        merged_a = {"concepts": merged_a_concepts, "relationships": merged_a_rels}
        (discovery_dir / "source-a.json").write_text(
            _json.dumps(merged_a, indent=2), encoding="utf-8",
        )

    # ─── Source B: expand + load ──
    try:
        b_files = _expand_source_paths(
            source_b or [], file_extensions={".json"},
        )
        merged_b = _merge_source_b(b_files) if b_files else None
    except _SourceLoadError as err:
        console.print(f"[red]Failed to load --source-b:[/] {err}")
        raise typer.Exit(code=2)

    # ─── Source C/D: expand and pass through ──
    merged_c = _load_source_passthrough(source_c or [])
    merged_d = _load_source_passthrough(source_d or [])

    # ─── Profile alias_map (light normalisation only) ──
    alias_map: dict[str, str] | None = None
    if profile is not None:
        from .core.profile import ProfileError, load_profile
        try:
            loaded = load_profile(profile)
            alias_map = dict(loaded.alias_map)
        except ProfileError as err:
            console.print(
                f"[red]Failed to load --profile {profile}:[/] {err}"
            )
            raise typer.Exit(code=2)

    # ─── Run discover ──
    graph = build_candidate_graph(
        source_a=merged_a,
        source_b=merged_b,
        source_c=merged_c,
        source_d=merged_d,
        alias_map=alias_map,
    )

    (discovery_dir / "candidate-graph.json").write_text(
        _json.dumps(graph.to_dict(), indent=2) + "\n", encoding="utf-8",
    )
    (discovery_dir / "candidate-provenance.json").write_text(
        _json.dumps({
            "concepts": [
                {
                    "candidate_id": c.candidate_id,
                    "label": c.label,
                    "provenance": [p.to_dict() for p in c.provenance],
                }
                for c in graph.concepts
            ],
        }, indent=2) + "\n",
        encoding="utf-8",
    )

    cross = sum(
        1 for c in graph.concepts
        if c.source_presence.get("A") and c.source_presence.get("B")
    )
    console.print(
        f"[green]Survey:[/] {len(graph.concepts)} candidates, "
        f"{len(graph.relationships)} relationships, "
        f"{cross} cross-source matches. "
        f"See {discovery_dir}."
    )


def _expand_source_paths(
    paths: list[Path],
    *,
    file_extensions: set[str],
) -> list[Path]:
    """Expand a list of file / glob / directory paths into a flat list
    of files matching the given extensions. Recurses into directories.
    """
    out: list[Path] = []
    for p in paths:
        if not p.exists():
            raise _SourceLoadError(p, f"path not found: {p}")
        if p.is_file():
            if p.suffix.lower() in file_extensions:
                out.append(p)
        elif p.is_dir():
            for child in sorted(p.rglob("*")):
                if child.is_file() and child.suffix.lower() in file_extensions:
                    out.append(child)
    return out


def _run_extract_a_for_survey(
    doc_path: Path, domain_dir: Path, model: str,
) -> dict:
    """Invoke the existing extract-a pipeline programmatically and
    return its JSON output as a dict. Used by `survey` to extract
    from Source A documents on the fly.

    Implementation note: shells out to extract-a via the existing
    DomainDocumentExtractor so behaviour stays identical.
    """
    from .extractors.domain_doc_extractor import DomainDocumentExtractor

    extractor = DomainDocumentExtractor(model=model)
    result = extractor.extract_from_file(doc_path)
    from dataclasses import asdict
    raw = asdict(result)
    # Reshape into the discovery-compatible {"concepts": [...], "relationships": [...]}
    return {
        "concepts": raw.get("concepts", []),
        "relationships": raw.get("relationships", []),
    }
```

- [ ] **Step 4: Run tests and verify they pass**

Run: `pytest tests/test_cli_survey.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ontozense/cli.py tests/test_cli_survey.py
git commit -m "feat(cli): add survey command (Stage 1 orchestrator, Task 5)"
```

---

## Task 6: New `ontozense draft` CLI command + rebuild deprecation

**Files:**
- Modify: `src/ontozense/cli.py` (append + tweak `rebuild`)
- Test: `tests/test_cli_draft.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for the new `ontozense draft` command (Stage 2 orchestrator)."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from ontozense.cli import app


runner = CliRunner()


def _seed_workspace(domain_dir: Path) -> None:
    """Lay out a minimal post-survey workspace."""
    discovery = domain_dir / "discovery"
    discovery.mkdir(parents=True, exist_ok=True)
    discovery.joinpath("candidate-graph.json").write_text(
        json.dumps({
            "concepts": [
                {
                    "candidate_id": "cand_id_borrower",
                    "label": "Borrower",
                    "normalized_label": "borrower",
                    "suggested_entity_type": "Concept",
                    "classification": "core_business",
                    "summary_definition": "A party that receives a service.",
                    "source_presence": {"A": True, "B": True, "C": False, "D": False},
                    "source_counts": {"A": 3, "B": 1, "C": 0, "D": 0},
                    "schema_links": [], "code_links": [], "governance_links": [],
                    "authoritative_evidence_count": 3,
                    "graph_degree": 4,
                    "relevance_score": 0.81,
                    "relevance_breakdown": {"authoritative_frequency": 0.25},
                    "provenance": [],
                    "aliases": [],
                    "status": "candidate",
                }
            ],
            "relationships": [],
        }),
        encoding="utf-8",
    )
    # Survey-style source-a.json so fuse can pick it up
    discovery.joinpath("source-a.json").write_text(
        json.dumps({
            "concepts": [{"name": "Borrower", "definition": "A party."}],
            "relationships": [],
        }),
        encoding="utf-8",
    )


class TestDraftHappyPath:
    def test_draft_with_induced_profile_writes_owl(self, tmp_path: Path):
        domain_dir = tmp_path / "domain"
        _seed_workspace(domain_dir)
        out = tmp_path / "draft.owl"
        result = runner.invoke(app, [
            "draft",
            "--domain-dir", str(domain_dir),
            "--output", str(out),
        ])
        assert result.exit_code == 0, result.output
        assert out.exists()
        assert "Borrower" in out.read_text(encoding="utf-8")

    def test_draft_emits_summary_markdown(self, tmp_path: Path):
        domain_dir = tmp_path / "domain"
        _seed_workspace(domain_dir)
        out = tmp_path / "draft.owl"
        result = runner.invoke(app, [
            "draft",
            "--domain-dir", str(domain_dir),
            "--output", str(out),
        ])
        assert result.exit_code == 0
        assert (domain_dir / "draft-summary.md").exists()


class TestDraftWithUserProfile:
    def test_draft_with_provided_profile_skips_induction(
        self, tmp_path: Path,
    ):
        domain_dir = tmp_path / "domain"
        _seed_workspace(domain_dir)

        profile_dir = tmp_path / "profile"
        profile_dir.mkdir()
        (profile_dir / "schema.json").write_text(
            json.dumps({
                "profile_name": "test",
                "profile_version": "1.0.0",
                "entity_types": {
                    "Concept": {"required": [], "optional": [], "subtypes": []},
                },
                "predicates": {},
            }),
            encoding="utf-8",
        )

        out = tmp_path / "draft.owl"
        result = runner.invoke(app, [
            "draft",
            "--domain-dir", str(domain_dir),
            "--profile", str(profile_dir),
            "--output", str(out),
        ])
        assert result.exit_code == 0, result.output
        # When a profile is provided, no induced-profile dir should be created.
        assert not (domain_dir / "induced-profile").exists()


class TestDraftFormat:
    def test_jsonld_format(self, tmp_path: Path):
        domain_dir = tmp_path / "domain"
        _seed_workspace(domain_dir)
        out = tmp_path / "draft.jsonld"
        result = runner.invoke(app, [
            "draft",
            "--domain-dir", str(domain_dir),
            "--output", str(out),
            "--format", "json-ld",
        ])
        assert result.exit_code == 0
        # JSON-LD content must parse as JSON
        json.loads(out.read_text(encoding="utf-8"))


class TestDraftPlan:
    def test_plan_flag_prints_without_writing(self, tmp_path: Path):
        domain_dir = tmp_path / "domain"
        _seed_workspace(domain_dir)
        out = tmp_path / "draft.owl"
        result = runner.invoke(app, [
            "draft",
            "--domain-dir", str(domain_dir),
            "--output", str(out),
            "--plan",
        ])
        assert result.exit_code == 0
        assert not out.exists()  # nothing written in plan mode
        for step in ("induce-profile", "fuse", "validate", "lint"):
            assert step in result.output


class TestRebuildDeprecation:
    def test_rebuild_prints_deprecation_note(self, tmp_path: Path):
        profile = tmp_path / "profile"
        profile.mkdir()
        (profile / "schema.json").write_text(
            json.dumps({
                "profile_name": "x",
                "profile_version": "1.0.0",
                "entity_types": {"Concept": {"required": [], "optional": [], "subtypes": []}},
                "predicates": {},
            }),
            encoding="utf-8",
        )
        result = runner.invoke(app, [
            "rebuild",
            "--profile", str(profile),
            "--domain-dir", str(tmp_path / "domain"),
        ])
        assert "deprecated" in result.output.lower()
        assert "draft" in result.output  # points at the replacement
```

- [ ] **Step 2: Run tests and verify they fail**

Run: `pytest tests/test_cli_draft.py -v`
Expected: FAIL with `No such command 'draft'`.

- [ ] **Step 3: Implement the `draft` command + rebuild deprecation**

Append to `src/ontozense/cli.py` (still before the `if __name__ == "__main__":` block):

```python
# ─── draft (Stage 2 orchestrator) ────────────────────────────────────────────


@app.command(name="draft")
def draft(
    domain_dir: Path = typer.Option(
        ..., "--domain-dir",
        help="Per-domain workspace. Reads from <domain-dir>/discovery/.",
    ),
    output: Path = typer.Option(
        ..., "--output", "-o",
        help="Path for the draft OWL file.",
    ),
    profile: Path = typer.Option(
        None, "--profile",
        help=(
            "Optional hand-authored profile directory. If given, "
            "induction is skipped and this profile is used directly."
        ),
    ),
    thresholds: Path = typer.Option(
        None, "--thresholds",
        help="Optional thresholds JSON (only used when inducing).",
    ),
    weights: Path = typer.Option(
        None, "--weights",
        help="Optional weights JSON (only used when inducing).",
    ),
    mode: str = typer.Option(
        "flag", "--mode",
        help='Validation mode: "flag" (annotate findings) or "filter".',
    ),
    format: str = typer.Option(
        "turtle", "--format",
        help='OWL serialisation: "turtle" | "json-ld" | "xml".',
    ),
    plan: bool = typer.Option(
        False, "--plan",
        help="Print what would run; don't execute.",
    ),
) -> None:
    """Stage 2 of the semantic-layer journey.

    Score the candidate graph (or use your profile), fuse the
    sources, validate and lint, and emit a draft OWL ontology. The
    resulting ``draft.owl`` is the handoff artifact for an expert
    curator working in Ontology Playground, Protégé, or any OWL
    editor.
    """
    import json as _json

    if plan:
        _print_draft_plan(domain_dir, profile, output)
        return

    discovery_dir = domain_dir / "discovery"
    candidate_graph_path = discovery_dir / "candidate-graph.json"
    if not candidate_graph_path.exists():
        console.print(
            f"[red]No candidate-graph.json under {discovery_dir}.[/]\n"
            "Run `ontozense survey` first."
        )
        raise typer.Exit(code=2)

    # ─── Resolve profile ──
    from .core.profile import ProfileError, load_profile
    induced_dir = domain_dir / "induced-profile"
    if profile is not None:
        try:
            loaded_profile_path = profile
            load_profile(profile)
        except ProfileError as err:
            console.print(f"[red]Failed to load --profile {profile}:[/] {err}")
            raise typer.Exit(code=2)
    else:
        # Run induce-profile to produce one.
        from .core.discovery_contracts import CandidateConcept
        from .core.profile_induction import write_induced_profile
        from .core.relevance import score_candidates, DEFAULT_WEIGHTS, DEFAULT_THRESHOLDS

        graph_raw = _load_json(candidate_graph_path)
        concepts = [
            CandidateConcept.from_dict(c)
            for c in graph_raw.get("concepts", [])
        ]
        wmap = None
        tmap = None
        if weights:
            wmap = _load_scoring_config(weights, set(DEFAULT_WEIGHTS), "--weights")
        if thresholds:
            tmap = _load_scoring_config(thresholds, set(DEFAULT_THRESHOLDS), "--thresholds")
        scored = score_candidates(concepts, weights=wmap, thresholds=tmap)
        write_induced_profile(
            domain_name=domain_dir.name,
            candidates=scored,
            out_dir=induced_dir,
            weights=wmap,
            thresholds=tmap,
        )
        loaded_profile_path = induced_dir

    # ─── Fuse ──
    from .core.fusion import FusionEngine
    fusion_engine = FusionEngine(profile=load_profile(loaded_profile_path))
    source_a_path = discovery_dir / "source-a.json"
    fused_path = domain_dir / "fused.json"
    fused = _run_fuse_for_draft(
        source_a_path, fusion_engine, fused_path,
    )

    # ─── Validate ──
    from .core.validation import validate_fused
    validation_report = validate_fused(
        fused, profile=load_profile(loaded_profile_path), mode=mode,
    )

    # ─── Lint ──
    from .core.lint import lint_fused
    lint_report = lint_fused(fused)

    # ─── OWL export ──
    from .core.owl_export import fused_to_owl
    owl_text = fused_to_owl(
        fused, profile=load_profile(loaded_profile_path), format=format,
    )
    output.write_text(owl_text, encoding="utf-8")

    # ─── Summary ──
    summary_path = domain_dir / "draft-summary.md"
    summary_path.write_text(
        _build_draft_summary(
            fused, validation_report, lint_report, loaded_profile_path,
        ),
        encoding="utf-8",
    )

    console.print(
        f"[green]Draft written to[/] {output}\n"
        f"  Elements: {len(fused.elements)}, "
        f"Relationships: {len(fused.relationships)}\n"
        f"  Validation: {validation_report.error_count} errors, "
        f"{validation_report.warning_count} warnings\n"
        f"  Summary: {summary_path}\n"
        f"Open in Ontology Playground or Protégé."
    )


def _run_fuse_for_draft(source_a_path, engine, output_path):
    """Run fusion programmatically and persist fused.json."""
    import json as _json
    raw = _load_json(source_a_path)
    result = engine.fuse_from_raw_sources(source_a=raw)
    from dataclasses import asdict
    output_path.write_text(
        _json.dumps(asdict(result), indent=2, default=str), encoding="utf-8",
    )
    return result


def _build_draft_summary(fused, validation, lint, profile_path) -> str:
    """Compose the human-facing draft-summary.md."""
    lines = [
        "# Draft summary",
        "",
        f"- Profile used: `{profile_path}`",
        f"- Elements: {len(fused.elements)}",
        f"- Relationships: {len(fused.relationships)}",
        f"- Validation: {validation.error_count} errors, {validation.warning_count} warnings",
        f"- Lint findings: {len(lint.findings)} total",
        "",
        "## What the curator should review first",
        "",
        "- Validation errors flagged above",
        "- Elements with low confidence (see fused.json)",
        "- Bridge concepts and orphan terms in the lint output",
    ]
    return "\n".join(lines) + "\n"


def _print_draft_plan(domain_dir, profile, output) -> None:
    """Print the rebuild plan without executing."""
    print(f"Plan for `ontozense draft` against {domain_dir}:")
    print()
    if profile is None:
        print("  1. Induce a profile from discovery/candidate-graph.json")
    else:
        print(f"  1. Use supplied profile: {profile}")
    print(f"  2. Fuse discovery/source-a.json against the profile")
    print(f"  3. Validate the fused dictionary (mode=flag)")
    print(f"  4. Lint the fused dictionary")
    print(f"  5. Export OWL to {output}")
    print(f"  6. Write draft-summary.md alongside")
```

Then **modify the existing `rebuild` command** in `cli.py` to emit a deprecation note. Find the function:

```python
@app.command(name="rebuild")
def rebuild(
    profile: Path = typer.Option(...),
    domain_dir: Path = typer.Option(...),
    ...
) -> None:
    """Print the rebuild plan for an induced / reviewed profile."""
```

Add **at the top of the function body** (immediately after the docstring):

```python
    console.print(
        "[yellow]Deprecation note:[/] `ontozense rebuild` will be "
        "removed in v2.0. Use `ontozense draft --plan` for the "
        "same effect."
    )
```

- [ ] **Step 4: Run tests and verify they pass**

Run: `pytest tests/test_cli_draft.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ontozense/cli.py tests/test_cli_draft.py
git commit -m "feat(cli): add draft command + deprecate rebuild (Task 6)"
```

---

## Task 7: Update help text on existing commands

**Files:**
- Modify: `src/ontozense/cli.py` (help-text additions only)

- [ ] **Step 1: Write a test that pins the cross-references**

Append to `tests/test_cli_draft.py`:

```python
class TestExistingCommandsPointAtNewOrchestrators:
    """Help text on the underlying commands should hint that most
    users will call `survey` or `draft` instead."""

    def test_extract_a_help_mentions_survey(self):
        result = runner.invoke(app, ["extract-a", "--help"])
        assert "survey" in result.output.lower()

    def test_discover_help_mentions_survey(self):
        result = runner.invoke(app, ["discover", "--help"])
        assert "survey" in result.output.lower()

    def test_induce_profile_help_mentions_draft(self):
        result = runner.invoke(app, ["induce-profile", "--help"])
        assert "draft" in result.output.lower()

    def test_fuse_help_mentions_draft(self):
        result = runner.invoke(app, ["fuse", "--help"])
        assert "draft" in result.output.lower()

    def test_validate_help_mentions_draft(self):
        result = runner.invoke(app, ["validate", "--help"])
        assert "draft" in result.output.lower()

    def test_lint_help_mentions_draft(self):
        result = runner.invoke(app, ["lint", "--help"])
        assert "draft" in result.output.lower()
```

- [ ] **Step 2: Run tests and verify they fail**

Run: `pytest tests/test_cli_draft.py::TestExistingCommandsPointAtNewOrchestrators -v`
Expected: FAIL (the hint isn't in the help text yet).

- [ ] **Step 3: Add the cross-reference sentence to each command's docstring**

For each of the six commands listed above, prepend one sentence at the start of their docstring. Concretely, in `src/ontozense/cli.py`:

- `extract-a` docstring: add at start: *"Stage 1 power-user command. Most users call `ontozense survey` instead, which runs this and the merge step in one go."*
- `discover` docstring: add at start: *"Stage 1 power-user command. Most users call `ontozense survey` instead, which orchestrates extract-a + this in one go."*
- `induce-profile` docstring: add at start: *"Stage 2 power-user command. Most users call `ontozense draft` instead, which runs scoring + induction + the rest of the pipeline."*
- `fuse` docstring: add at start: *"Stage 2 power-user command. Most users call `ontozense draft` instead, which orchestrates fuse + validate + lint + OWL emission."*
- `validate` docstring: add at start: *"Stage 2 power-user command. Most users call `ontozense draft` instead, which runs this and the rest of the pipeline."*
- `lint` docstring: add at start: *"Stage 2 power-user command. Most users call `ontozense draft` instead, which runs this and the rest of the pipeline."*

- [ ] **Step 4: Run tests and verify they pass**

Run: `pytest tests/test_cli_draft.py -v -k "ExistingCommandsPointAt"`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add src/ontozense/cli.py tests/test_cli_draft.py
git commit -m "docs(cli): point legacy commands at survey/draft (Task 7)"
```

---

## Task 8: Rewrite the NPL validation tutorial

**Files:**
- Create: `docs/ontozense-npl-advanced.md` (old tutorial moved + reframed)
- Modify: `docs/ontozense-npl-validation.md` (rewrite around survey + draft)

- [ ] **Step 1: Move the existing tutorial to the advanced file**

```bash
cp docs/ontozense-npl-validation.md docs/ontozense-npl-advanced.md
```

Then **edit `docs/ontozense-npl-advanced.md`** — change the title and opening paragraph to mark it as the power-user version:

```markdown
# NPL Power-User Walkthrough (every pipeline command in isolation)

This tutorial walks the underlying pipeline command-by-command —
`extract-a`, `discover`, `induce-profile`, `fuse`, `validate`,
`lint`, `report`. For the recommended two-command flow using the
new `survey` and `draft` orchestrators, see
[`docs/ontozense-npl-validation.md`](./ontozense-npl-validation.md).

Use this advanced version when you want to inspect each
intermediate artifact, test specific edge cases, or build CI
pipelines.
```

(Keep the rest of the file as-is — it's already a faithful step-by-step.)

- [ ] **Step 2: Rewrite `docs/ontozense-npl-validation.md`**

Replace the entire file with the new structure (5 parts, around survey + draft):

```markdown
# Ontozense — NPL Validation Tutorial (for new users)

This tutorial takes you from a blank machine to a fully-validated
Ontozense install on real NPL (Non-Performing Loans) data, using
the recommended two-command flow: **survey** then **draft**.

By the end you'll have:

1. Cloned the repository and installed the CLI with `uv`.
2. Run the test suite to confirm the install is healthy.
3. Surveyed the NPL sources (Basel guidance + governance JSON +
   sample code).
4. Drafted a semantic layer (`draft.owl`) you can hand to an
   expert in Ontology Playground / Protégé.

Each step has a `✓ Expected:` checkpoint.

> **Shell:** Commands below are PowerShell 7+ on Windows; bash
> equivalents are nearly identical (swap `` ` `` line
> continuations for `\` and adjust `Get-ChildItem` /
> `Select-String` to `ls` / `grep`).

(... full part-A through part-E content, mirroring the structure
in the design spec §7.2 ...)
```

Use the content scaffolding from the design spec's `§7.2 Tutorial` table. For Part A (Setup), reuse the existing `uv sync` flow from the current tutorial. For Part B (Workspace), reuse the existing `New-Item` / `Copy-Item` snippets. For Parts C, D, E — write fresh content around the new commands. **No placeholders**: every `✓ Expected:` block has a concrete expected output.

A representative Part C (Survey) section to use as the template:

```markdown
## Part C — Survey the NPL sources

Run a single command to extract from the Basel doc and merge with
the governance catalog:

\`\`\`powershell
ontozense survey `
  --source-a domains/npl/sources/npl-basel-guidelines.md `
  --source-b domains/npl/sources/governance.json `
  --domain-dir domains/npl
\`\`\`

✓ **Expected:** a one-line summary like:

\`\`\`text
Survey: 22 candidates, 15 relationships, 8 cross-source matches.
See domains/npl/discovery.
\`\`\`

Three artifacts are written under `domains/npl/discovery/`:

\`\`\`powershell
Get-ChildItem domains\npl\discovery\
\`\`\`

✓ **Expected:** `candidate-graph.json`, `candidate-provenance.json`,
and `source-a.json`.
```

Part D (Draft) and Part E (Hand off) follow the same shape, with
concrete `ontozense draft …` invocation and expected outputs.

- [ ] **Step 3: Verify the tutorial reads correctly**

Read through the file end-to-end. Confirm:

- Each `✓ Expected:` line has a concrete expected output (no "you should see something like X").
- Every command shown is one the reader can paste and run.
- The terms in the design-spec glossary are used exactly (no synonyms drift).

(No test run for this step — documentation only.)

- [ ] **Step 4: Verify no broken cross-links**

Run: `grep -nE 'ontozense-npl-(validation|advanced|tutorial)' docs/` from a bash shell or Grep in pwsh.
Expected: every link points at a file that exists.

- [ ] **Step 5: Commit**

```bash
git add docs/ontozense-npl-validation.md docs/ontozense-npl-advanced.md
git commit -m "docs: rewrite NPL tutorial around survey+draft (Task 8)"
```

---

## Task 9: Rewrite README front matter

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Replace the README's first ~30 lines**

Open `README.md`. Replace from the first line through the end of the `## The four-source pipeline` section header (inclusive) with the new front matter from the design spec §3:

```markdown
# Tycho

Build a **semantic layer** — a draft OWL ontology of your domain's entities, definitions, relationships, properties, and rules — from your existing documents, governance catalogs, database schemas, and code. Hand the draft to an expert in [Ontology Playground](https://github.com/...) or [Protégé](https://protege.stanford.edu) to finish the last 30%.

Tycho does the mechanical 60–70% of the work — extraction, fusion, validation, lint, anchoring every claim back to the source — so a domain expert doesn't start from a blank slate.

*(A "semantic layer" is what's sometimes called a domain ontology, a knowledge model, or a rich data dictionary. Same idea — a structured map of what concepts exist in your domain, how they relate, and what rules apply.)*

![Tycho architecture — many sources, one semantic layer](images/tycho.png)

## The journey

(... insert the ASCII journey diagram from spec §4 verbatim ...)

Two commands take you to a draft you can hand off:

\`\`\`bash
# Stage 1 — Survey: see what's in your sources
ontozense survey --source-a docs/*.md --source-b governance.json --domain-dir domains/mydomain

# Stage 2 — Draft: build the semantic layer and emit OWL
ontozense draft --domain-dir domains/mydomain --output domains/mydomain/draft.owl
\`\`\`

Then open `draft.owl` in your curation tool of choice.
```

- [ ] **Step 2: Insert the vocabulary glossary right after the journey**

Right after the journey section, before the existing `## What's in a rich data dictionary?` heading, insert the 8-term glossary table from spec §6 verbatim.

- [ ] **Step 3: Rename the `## Three operating modes` section to `## How Tycho works`**

Find `## Three operating modes` in the README. Rename to `## How Tycho works`. Inside that section, re-order and re-word so the discovery mode appears as a peer alongside unconstrained and profile mode (already mostly the case after the previous redesign). Update language so each mode is described as a path within the same journey, not a separate workflow.

- [ ] **Step 4: Replace the `## Quick start` section**

The existing quick-start has 9 numbered shell blocks. Replace it with a much shorter one based on `survey` + `draft`:

```markdown
## Quick start

\`\`\`bash
# Install (uv recommended)
uv sync

# Stage 1 — Survey: see what's in your sources
ontozense survey \
  --source-a path/to/regulations/*.md \
  --source-b governance.json \
  --domain-dir domains/mydomain

# Stage 2 — Draft: build the semantic layer
ontozense draft \
  --domain-dir domains/mydomain \
  --output domains/mydomain/draft.owl

# Stage 3 — Hand off: open in Ontology Playground / Protégé
\`\`\`

For the underlying pipeline commands (extract-a, fuse, validate,
lint, etc.) run by hand — for CI pipelines or fine-grained
control — see [Advanced usage](#advanced---running-the-pipeline-by-hand)
below.
```

- [ ] **Step 5: Add `## Advanced — running the pipeline by hand`**

Move the original 9-step Quick-start commands into a new section titled `## Advanced — running the pipeline by hand`, placed after the Discovery workflow section. This preserves all the existing content for power users; it's just relocated.

- [ ] **Step 6: Remove the standalone `## Discovery workflow (no profile yet)` section**

Its content has been folded into the new `## How Tycho works` and the Quick start. Remove the standalone heading and its body to avoid duplication.

- [ ] **Step 7: Commit**

```bash
git add README.md
git commit -m "docs: rewrite README front matter around the semantic-layer journey (Task 9)"
```

---

## Task 10: Final regression + push

**Files:** none (verification only)

- [ ] **Step 1: Run the full test suite**

Run: `pytest -q`
Expected: every test passes. The new tests added in Tasks 1-7 should bring the count to roughly 870+ passed (up from 834). Zero failures.

- [ ] **Step 2: Run the domain-neutrality regression**

Run: `pytest tests/test_domain_neutrality.py -v`
Expected: PASS.

- [ ] **Step 3: Sanity-check the new commands**

```bash
ontozense --help
```
Expected: the command list includes `survey` and `draft`. Each has a short description starting with "Stage 1" or "Stage 2".

```bash
ontozense survey --help
ontozense draft --help
```
Expected: rich help text covering all flags described in the design spec §5.

- [ ] **Step 4: Push to remote**

```bash
git push origin main
```
Expected: clean push, all 9 task commits land on origin/main.

- [ ] **Step 5: Cleanup commit (only if anything is left untouched)**

If steps 1-3 surface any stragglers (e.g., a missed help-text update or a stale doc cross-link), fix them and add one final stabilisation commit:

```bash
git add <fixed-files>
git commit -m "test: stabilise semantic-layer redesign rollout (Task 10)"
git push origin main
```

If everything passes cleanly, no commit needed.

---

## Spec Coverage Check

- §3 Canonical output (OWL/Turtle): covered by Tasks 1, 2, 3, 4.
- §4 User journey (survey → draft → hand off): covered by Tasks 5, 6, 9 (README diagram).
- §5.1 `survey` command: covered by Task 5.
- §5.2 `draft` command: covered by Task 6.
- §5.3 OWL converter: covered by Tasks 1-4.
- §5.4 Input shape rules (file/glob/directory): covered by Task 5.
- §5.5 Legacy command treatment (help text + rebuild deprecation): covered by Tasks 6, 7.
- §6 Vocabulary anchor: covered by Task 9 (README glossary).
- §7.1 README rewrite: covered by Task 9.
- §7.2 Tutorial rewrite: covered by Task 8.
- §8 Scope summary (LOC estimates): on-target across Tasks 1-10.

## Placeholder Scan

- No `TODO`, `TBD`, or "implement later" markers in any task.
- Every step shows full code or full commands.
- Test code blocks contain real assertions, not "test the thing above".

## Type Consistency Check

- `fused_to_owl(fused, profile=None, domain_namespace=..., format=...)` signature is consistent across Tasks 1-4 and used unchanged in Task 6.
- `FusionResult`, `FusedElement`, `FusedRelationship`, `FieldProvenance`, `CandidateConcept`, `Profile`, `EntityType`, `IdFormat` — all imports point at existing modules (`ontozense.core.fusion`, `ontozense.core.discovery_contracts`, `ontozense.core.profile`).
- `_expand_source_paths`, `_run_extract_a_for_survey`, `_run_fuse_for_draft`, `_build_draft_summary`, `_print_draft_plan` helpers defined in Tasks 5/6 and not referenced before they're defined.
- Existing helpers reused without redefinition: `_load_json`, `_load_scoring_config`, `_merge_source_b`, `_load_source_passthrough`, `_SourceLoadError`.
