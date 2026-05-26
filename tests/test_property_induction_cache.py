"""PR B2 — cache matrix + regression coverage.

Phase B PR B2 introduces ``discovery/source-a-properties.json`` as
the durable record of LLM-induced attributes. The Phase B spec
(design §4 / §10 B11) constrains the cache contract:

  * Cache hit on rerun with ``--property-induction llm`` = skip the
    LLM call, re-merge the cached attributes onto the FusedElement.
  * ``--property-induction-refresh`` forces a cache miss for every
    eligible class.
  * **Cache is consulted and written ONLY when
    ``--property-induction llm`` is explicitly set on the rerun.**
    Default-flag runs of ``draft`` never read or write the cache,
    so the Phase A "default output unchanged" guarantee holds even
    when a cache file is present.
  * Budget-skipped classes are recorded in the cache so the
    curator sees what wasn't induced.

These tests pin every claim above. The LLM seam
(``ontozense.core.property_induction._call_llm``) is mocked end-to-
end — no live API calls.
"""

from __future__ import annotations

import json
from pathlib import Path

from rdflib import Graph
from typer.testing import CliRunner

from ontozense.cli import app
from ontozense.core import property_induction as pi
from ontozense.core.attribute import Attribute, FieldProvenance
from ontozense.core.fusion import (
    FieldAnchor,
    FieldProvenance as FusionFieldProvenance,
    FusedElement,
    FusionResult,
)
from ontozense.core.property_induction import (
    CACHE_FILE_NAME,
    Budget,
    PropertyInductionCache,
    induce_attributes,
)

runner = CliRunner()


# ─── Helpers ────────────────────────────────────────────────────────────────


def _element_with_source_a(name: str, snippet: str = "context") -> FusedElement:
    el = FusedElement(element_name=name)
    el.field_provenance["definition"] = FusionFieldProvenance(
        source="A", confidence=0.9, original_value="x",
        anchor=FieldAnchor(line=1, segment_id="doc.md", snippet=snippet),
    )
    return el


def _seed_workspace_doc_only(domain_dir: Path, concept_names: list[str]) -> None:
    """Lay out a post-survey workspace where every concept passes
    Phase B gate 1 (attributes empty + Source A present)."""
    discovery = domain_dir / "discovery"
    discovery.mkdir(parents=True, exist_ok=True)
    discovery.joinpath("candidate-graph.json").write_text(
        json.dumps({
            "concepts": [
                {
                    "candidate_id": f"cand_{name.lower()}",
                    "label": name,
                    "normalized_label": name.lower(),
                    "suggested_entity_type": "Concept",
                    "classification": "core_business",
                    "summary_definition": f"{name} description.",
                    "source_presence": {
                        "A": True, "B": False, "C": False, "D": False,
                    },
                    "source_counts": {"A": 1, "B": 0, "C": 0, "D": 0},
                    "schema_links": [], "code_links": [], "governance_links": [],
                    "authoritative_evidence_count": 1,
                    "graph_degree": 0,
                    "relevance_score": 0.9,
                    "relevance_breakdown": {"authoritative_frequency": 0.5},
                    "provenance": [],
                    "aliases": [],
                    "status": "candidate",
                }
                for name in concept_names
            ],
            "relationships": [],
        }),
        encoding="utf-8",
    )
    discovery.joinpath("source-a.json").write_text(
        json.dumps({
            "concepts": [
                {
                    "name": name,
                    "definition": f"{name} description from doc.",
                    "extraction_provenance": {
                        "page": 0, "char_offset": 0, "char_length": 0,
                        "line": 1, "end_line": 1, "column": 0,
                        "segment_id": "doc.md",
                        "snippet": f"{name} context snippet.",
                    },
                }
                for name in concept_names
            ],
            "relationships": [],
        }),
        encoding="utf-8",
    )


# ─── PropertyInductionCache — unit tests ──────────────────────────────────


def test_cache_load_empty_when_file_absent(tmp_path):
    cache = PropertyInductionCache(tmp_path)
    assert cache.load_per_class() == {}


def test_cache_load_returns_per_class_map(tmp_path):
    (tmp_path / CACHE_FILE_NAME).write_text(
        json.dumps({
            "schema_version": "1.0",
            "per_class": {
                "customer": {"attributes": [], "input_truncated": False, "skipped_reason": None},
                "loan": {"attributes": [], "input_truncated": False, "skipped_reason": None},
            },
        }),
        encoding="utf-8",
    )
    cache = PropertyInductionCache(tmp_path)
    out = cache.load_per_class()
    assert set(out.keys()) == {"customer", "loan"}


def test_cache_load_treats_malformed_file_as_empty(tmp_path, caplog):
    (tmp_path / CACHE_FILE_NAME).write_text("not valid json {{{", encoding="utf-8")
    cache = PropertyInductionCache(tmp_path)
    with caplog.at_level("WARNING"):
        assert cache.load_per_class() == {}
    assert "unreadable" in caplog.text


def test_cache_load_treats_wrong_shape_as_empty(tmp_path):
    (tmp_path / CACHE_FILE_NAME).write_text(
        json.dumps({"per_class": "not-a-dict"}),
        encoding="utf-8",
    )
    cache = PropertyInductionCache(tmp_path)
    assert cache.load_per_class() == {}


def test_cache_load_drops_non_dict_entries_per_class(tmp_path, caplog):
    """Codex r1 blocker on PR B2: a malformed per-class entry
    (string instead of dict) must NOT crash the cache-hit code
    path on ``.get("attributes", [])``. Drop with WARNING +
    treat as cache miss for that class."""
    (tmp_path / CACHE_FILE_NAME).write_text(
        json.dumps({
            "per_class": {
                "good_class": {
                    "attributes": [], "input_truncated": False,
                    "skipped_reason": None,
                },
                "bad_class_string": "not a dict",
                "bad_class_list": ["also not a dict"],
                "bad_class_number": 42,
            },
        }),
        encoding="utf-8",
    )
    cache = PropertyInductionCache(tmp_path)
    with caplog.at_level("WARNING"):
        loaded = cache.load_per_class()
    # Only the good entry survives.
    assert set(loaded.keys()) == {"good_class"}
    # WARNING logged for each dropped entry.
    assert "bad_class_string" in caplog.text
    assert "bad_class_list" in caplog.text
    assert "bad_class_number" in caplog.text


def test_induce_attributes_survives_malformed_cache_entry(tmp_path, monkeypatch):
    """End-to-end guard: with a malformed per-class entry on disk,
    the induce_attributes call must not raise. The bad entry is
    dropped + the class falls back to a cache miss + LLM call."""
    # Pre-seed a cache with a malformed entry for the class we'll induce.
    (tmp_path / CACHE_FILE_NAME).write_text(
        json.dumps({
            "schema_version": "1.0",
            "per_class": {
                "customer": "this should be a dict",
            },
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        pi, "_call_llm",
        lambda *, prompt, model: (
            "- email :: xsd:string :: Customer email.\n"
        ),
    )
    fused = FusionResult(elements=[_element_with_source_a("Customer")])
    plan = induce_attributes(fused, dry_run=False, discovery_dir=tmp_path)
    # Cache miss (bad entry dropped) → LLM called → attribute merged.
    assert plan.cache_misses == 1
    assert plan.cache_hits == 0
    assert {a.name for a in fused.elements[0].attributes} == {"email"}


# ─── induce_attributes(dry_run=False) — cache hit / miss matrix ───────────


def _attr(name: str, xsd: str = "xsd:string") -> Attribute:
    return Attribute(
        name=name,
        xsd_type=xsd,
        description=f"{name} description.",
        field_provenance=[FieldProvenance(
            source="B-LLM", artifact=f"discovery/{CACHE_FILE_NAME}",
            confidence=0.5, extractor="spires-pass2",
        )],
        confidence=0.5,
    )


def test_first_run_populates_cache(tmp_path, monkeypatch):
    """First run with the flag: cache empty, LLM called once per
    eligible concept, cache file written."""
    fused = FusionResult(elements=[
        _element_with_source_a("Customer"),
        _element_with_source_a("Order"),
    ])
    monkeypatch.setattr(
        pi, "_call_llm",
        lambda *, prompt, model: (
            "- id :: xsd:string :: Identifier.\n"
            "- created_at :: xsd:dateTime :: Creation timestamp.\n"
        ),
    )
    plan = induce_attributes(
        fused, dry_run=False, discovery_dir=tmp_path,
    )
    assert plan.cache_hits == 0
    assert plan.cache_misses == 2
    # Cache file written.
    cache_path = tmp_path / CACHE_FILE_NAME
    assert cache_path.exists()
    payload = json.loads(cache_path.read_text(encoding="utf-8"))
    assert set(payload["per_class"].keys()) == {"customer", "order"}
    for entry in payload["per_class"].values():
        assert len(entry["attributes"]) == 2
    # Attributes attached to fused elements.
    assert {a.name for a in fused.elements[0].attributes} == {"id", "created_at"}


def test_second_run_uses_cache_zero_llm_calls(tmp_path, monkeypatch):
    """First run populates; second run reads the cache and makes
    zero LLM calls. The mocked _call_llm asserts it isn't invoked
    via a side-effect counter."""
    fused1 = FusionResult(elements=[_element_with_source_a("Customer")])
    monkeypatch.setattr(
        pi, "_call_llm",
        lambda *, prompt, model: "- email :: xsd:string :: Login email.\n",
    )
    induce_attributes(fused1, dry_run=False, discovery_dir=tmp_path)

    # Second run: replace the mock with one that fails if called.
    calls: list = []

    def _trap(*, prompt, model):
        calls.append((prompt, model))
        return ""

    monkeypatch.setattr(pi, "_call_llm", _trap)
    fused2 = FusionResult(elements=[_element_with_source_a("Customer")])
    plan = induce_attributes(fused2, dry_run=False, discovery_dir=tmp_path)
    assert calls == []  # zero LLM calls on rerun
    assert plan.cache_hits == 1
    assert plan.cache_misses == 0
    assert {a.name for a in fused2.elements[0].attributes} == {"email"}


def test_refresh_forces_cache_miss(tmp_path, monkeypatch):
    """--property-induction-refresh equivalent (refresh=True) forces
    re-calling the LLM even when the cache already has the class."""
    fused1 = FusionResult(elements=[_element_with_source_a("Customer")])
    monkeypatch.setattr(
        pi, "_call_llm",
        lambda *, prompt, model: "- email :: xsd:string :: Login.\n",
    )
    induce_attributes(fused1, dry_run=False, discovery_dir=tmp_path)

    calls: list = []

    def _record(*, prompt, model):
        calls.append((prompt, model))
        return "- email :: xsd:string :: Refreshed.\n"

    monkeypatch.setattr(pi, "_call_llm", _record)
    fused2 = FusionResult(elements=[_element_with_source_a("Customer")])
    plan = induce_attributes(
        fused2, dry_run=False, discovery_dir=tmp_path, refresh=True,
    )
    assert len(calls) == 1  # LLM re-called despite cache hit
    assert plan.cache_misses == 1
    assert plan.cache_hits == 0
    # Refreshed description landed on the attribute.
    email = fused2.elements[0].attributes[0]
    assert email.description == "Refreshed."


def test_budget_overage_recorded_in_cache(tmp_path, monkeypatch):
    """Concepts skipped by max_concepts land in the cache's skipped
    section so the curator sees the budget gap."""
    fused = FusionResult(elements=[
        _element_with_source_a("A"),
        _element_with_source_a("B"),
        _element_with_source_a("C"),
    ])
    monkeypatch.setattr(
        pi, "_call_llm",
        lambda *, prompt, model: "- x :: xsd:string :: A field.\n",
    )
    induce_attributes(
        fused, dry_run=False, discovery_dir=tmp_path,
        budget=Budget(max_concepts=1),
    )
    payload = json.loads(
        (tmp_path / CACHE_FILE_NAME).read_text(encoding="utf-8"),
    )
    skipped_uris = {entry["class_uri"] for entry in payload["skipped"]}
    assert "b" in skipped_uris
    assert "c" in skipped_uris


def test_unknown_xsd_type_defaults_to_string(tmp_path, monkeypatch):
    """LLM returns a type Tycho doesn't recognise → fall back to
    xsd:string (per design Q12) + warning log. Attribute still
    materialises rather than being dropped."""
    monkeypatch.setattr(
        pi, "_call_llm",
        lambda *, prompt, model: "- weird :: xsd:fictional :: A field.\n",
    )
    fused = FusionResult(elements=[_element_with_source_a("X")])
    induce_attributes(fused, dry_run=False, discovery_dir=tmp_path)
    attr = fused.elements[0].attributes[0]
    assert attr.name == "weird"
    assert attr.xsd_type == "xsd:string"


def test_malformed_lines_skipped_not_aborted(tmp_path, monkeypatch):
    """Lenient parser: malformed lines are skipped, the run does
    not abort, valid lines still materialise."""
    monkeypatch.setattr(
        pi, "_call_llm",
        lambda *, prompt, model: (
            "garbage line without dashes\n"
            "- only_one_token\n"
            "- valid :: xsd:string :: Good attribute.\n"
        ),
    )
    fused = FusionResult(elements=[_element_with_source_a("X")])
    induce_attributes(fused, dry_run=False, discovery_dir=tmp_path)
    attrs = fused.elements[0].attributes
    assert {a.name for a in attrs} == {"valid"}


def test_gate_1_merge_skip_when_attributes_already_present(
    tmp_path, monkeypatch,
):
    """Defensive belt-and-braces: even if the LLM is asked about an
    already-attributed element, _merge_into_fused refuses to
    overwrite. (Eligibility filter prevents this from happening in
    practice, but the merge guard makes the invariant
    self-defending against future code paths.)"""
    el = _element_with_source_a("X")
    el.attributes = [Attribute(name="existing", xsd_type="xsd:string")]
    fused = FusionResult(elements=[el])
    # Eligibility filter would skip this element entirely, so the
    # merge guard is never exercised via the public entry point.
    # Test the merge helper directly.
    pi._merge_into_fused(
        fused,
        pi.EligibleConcept(
            element_name="X", class_uri="x",
            confidence=0.9, snippet_chars=10, snippet="x",
        ),
        [_attr("new_one")],
    )
    # Existing attribute preserved; new not appended.
    assert {a.name for a in fused.elements[0].attributes} == {"existing"}


# ─── Regression guard — cache exists but no-flag run ignores it ───────────


def test_default_flag_run_ignores_existing_cache(
    tmp_path, monkeypatch,
):
    """Critical Phase B contract: a cache file on disk must not
    leak into a default ``draft`` run. The "default output
    unchanged" guarantee for Phase A holds even after Phase B has
    been used at least once.

    Verifies via two independent assertions:
      1. The cache file written by run 1 is byte-identical after
         run 2 — default-flag run never WRITES the cache.
      2. The OWL output of run 2 contains zero B-LLM provenance
         markers (no ``ontozense:`` attributes from Phase B that
         the cache held) — default-flag run never READS the cache.
    """
    domain_dir = tmp_path / "domain"
    _seed_workspace_doc_only(domain_dir, ["Customer"])

    monkeypatch.setattr(
        pi, "_call_llm",
        lambda *, prompt, model: (
            "- email :: xsd:string :: Customer email.\n"
        ),
    )

    # Run 1: --property-induction llm → writes cache + induces
    # attributes onto draft.owl.
    out_with_b = tmp_path / "draft_with_b.owl"
    result_with_b = runner.invoke(app, [
        "draft",
        "--domain-dir", str(domain_dir),
        "--output", str(out_with_b),
        "--property-induction", "llm",
    ])
    assert result_with_b.exit_code == 0, result_with_b.output
    cache_path = domain_dir / "discovery" / CACHE_FILE_NAME
    assert cache_path.exists()
    cache_payload_before = cache_path.read_text(encoding="utf-8")
    # Sanity check: cache stored the Phase B email attribute.
    assert '"name": "email"' in cache_payload_before

    # Run 2: default flag (no --property-induction). Same workspace,
    # cache file still on disk. Output must not pick up the cached
    # attributes — the cache is opt-in-only.
    out_default = tmp_path / "draft_default.owl"
    result_default = runner.invoke(app, [
        "draft",
        "--domain-dir", str(domain_dir),
        "--output", str(out_default),
    ])
    assert result_default.exit_code == 0, result_default.output

    # Assertion 1: cache file unchanged (default run didn't write).
    cache_payload_after = cache_path.read_text(encoding="utf-8")
    assert cache_payload_before == cache_payload_after, (
        "default-flag run mutated the cache file — opt-in contract "
        "broken"
    )

    # Assertion 2: OWL output of run 2 contains zero B-LLM
    # attribute markers. The Phase B "email" attribute that the
    # cache holds for Customer must not appear in the default-flag
    # OWL output.
    owl_text = out_default.read_text(encoding="utf-8")
    g = Graph()
    g.parse(data=owl_text, format="turtle")
    # No DatatypeProperty named "email" should appear on Customer's
    # class URI in the default-flag run, because Phase B never ran.
    from rdflib.namespace import OWL, RDF
    datatype_props = list(g.subjects(RDF.type, OWL.DatatypeProperty))
    for dp in datatype_props:
        assert "/customer/email" not in str(dp), (
            "default-flag run emitted a B-LLM-induced "
            "DatatypeProperty — cache leaked into default output"
        )
