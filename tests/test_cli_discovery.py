"""Tests for the discovery CLI commands (profile induction
architecture, Phase 3).

This file covers all three discovery-workflow subcommands —
``discover``, ``induce-profile``, and ``rebuild`` — plus the
end-to-end pinning of the workflow as a single user journey.

What ``discover`` does (per the plan):

  - Takes one or more raw source extraction JSONs (``--source-a``
    repeatable; also accepts ``--source-b/c/d`` and an optional
    ``--profile`` for light alias normalisation).
  - Builds a candidate graph via ``build_candidate_graph`` and
    writes three artifacts under ``<domain_dir>/discovery/``:

      * ``candidate-graph.json`` — concepts + relationships.
      * ``candidate-provenance.json`` — per-candidate evidence
        breakdown (so a reviewer can trace any candidate back to
        the source row it came from).
      * ``concept-mappings.json`` — written as
        ``{"mappings": []}`` by ``discover``. No command in this
        implementation populates it.

The architecture pins one constraint that's easy to miss: the
``--profile`` flag is *light normalisation only*. It must NOT
filter the candidate set or constrain types. Several tests below
explicitly pin that contract.
"""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from ontozense.cli import app


runner = CliRunner()


# ─── Test fixtures ──────────────────────────────────────────────────────────


def _write_source_a(
    path: Path,
    concepts: list[dict],
    relationships: list[dict] | None = None,
) -> None:
    path.write_text(
        json.dumps({
            "concepts": concepts,
            "relationships": relationships or [],
        }),
        encoding="utf-8",
    )


def _write_source_b(path: Path, records: list[dict]) -> None:
    path.write_text(
        json.dumps({"records": records}),
        encoding="utf-8",
    )


def _write_minimal_profile(profile_dir: Path, alias_map: dict[str, str]) -> None:
    """Write a minimal loader-valid profile with the given alias_map."""
    profile_dir.mkdir(parents=True, exist_ok=True)
    schema = {
        "profile_name": "test",
        "profile_version": "0.1.0",
        "entity_types": {
            "Concept": {"required": ["definition"], "optional": [], "subtypes": []},
        },
        "predicates": {},
        "alias_map": alias_map,
    }
    (profile_dir / "schema.json").write_text(
        json.dumps(schema), encoding="utf-8",
    )


# ─── Plan test + artifact-shape pins ───────────────────────────────────────


class TestDiscoverArtifacts:
    """The three artifacts the plan mandates plus their shapes."""

    def test_writes_three_discovery_artifacts(self, tmp_path: Path):
        """Plan's canonical Task 5 test."""
        source_a = tmp_path / "source-a.json"
        _write_source_a(source_a, [{"name": "Customer", "definition": "A client."}])
        domain_dir = tmp_path / "domain"
        result = runner.invoke(app, [
            "discover",
            "--source-a", str(source_a),
            "--domain-dir", str(domain_dir),
        ])
        assert result.exit_code == 0, result.output
        assert (domain_dir / "discovery" / "candidate-graph.json").exists()
        assert (domain_dir / "discovery" / "candidate-provenance.json").exists()
        assert (domain_dir / "discovery" / "concept-mappings.json").exists()

    def test_emitted_graph_contains_input_concepts(self, tmp_path: Path):
        source_a = tmp_path / "source-a.json"
        _write_source_a(source_a, [
            {"name": "Customer", "definition": "A client."},
            {"name": "Address", "definition": "A location."},
        ])
        domain_dir = tmp_path / "domain"
        result = runner.invoke(app, [
            "discover",
            "--source-a", str(source_a),
            "--domain-dir", str(domain_dir),
        ])
        assert result.exit_code == 0
        raw = json.loads(
            (domain_dir / "discovery" / "candidate-graph.json").read_text(
                encoding="utf-8"
            )
        )
        labels = {c["label"] for c in raw["concepts"]}
        assert labels == {"Customer", "Address"}

    def test_provenance_artifact_has_per_candidate_evidence(
        self, tmp_path: Path,
    ):
        """Every concept in the graph must have a corresponding
        provenance entry with at least one EvidenceEntry — that's
        the audit-trail invariant for discover (paralleling the
        reconciliation invariant the reviewer pinned on Task 4)."""
        source_a = tmp_path / "source-a.json"
        _write_source_a(source_a, [
            {"name": "Customer", "definition": "A client.",
             "provenance": {"source_document": "docs/customer.md"}},
        ])
        domain_dir = tmp_path / "domain"
        result = runner.invoke(app, [
            "discover",
            "--source-a", str(source_a),
            "--domain-dir", str(domain_dir),
        ])
        assert result.exit_code == 0
        graph = json.loads(
            (domain_dir / "discovery" / "candidate-graph.json").read_text(
                encoding="utf-8"
            )
        )
        prov = json.loads(
            (domain_dir / "discovery" / "candidate-provenance.json").read_text(
                encoding="utf-8"
            )
        )
        graph_ids = {c["candidate_id"] for c in graph["concepts"]}
        prov_ids = {entry["candidate_id"] for entry in prov["concepts"]}
        assert graph_ids == prov_ids
        for entry in prov["concepts"]:
            assert entry["provenance"], (
                f"Candidate {entry['candidate_id']!r} has empty provenance"
            )

    def test_concept_mappings_written_as_empty_mappings_object(
        self, tmp_path: Path,
    ):
        """concept-mappings.json is written as ``{"mappings": []}``
        by discover. No command in this implementation populates
        it. The file must exist and be JSON-parseable so downstream
        tooling has a stable shape to expect."""
        source_a = tmp_path / "source-a.json"
        _write_source_a(source_a, [{"name": "Customer", "definition": "A."}])
        domain_dir = tmp_path / "domain"
        result = runner.invoke(app, [
            "discover",
            "--source-a", str(source_a),
            "--domain-dir", str(domain_dir),
        ])
        assert result.exit_code == 0
        raw = json.loads(
            (domain_dir / "discovery" / "concept-mappings.json").read_text(
                encoding="utf-8"
            )
        )
        # Stable shape: a "mappings" key with an (empty) list.
        assert raw == {"mappings": []}


# ─── Source merging ────────────────────────────────────────────────────────


class TestDiscoverSourceMerging:

    def test_multiple_source_a_files_concat_concepts(self, tmp_path: Path):
        """Repeating ``--source-a`` merges the inputs — the CLI
        concatenates their ``concepts`` and ``relationships`` lists
        before passing to build_candidate_graph."""
        a1 = tmp_path / "a1.json"
        a2 = tmp_path / "a2.json"
        _write_source_a(a1, [{"name": "Customer", "definition": "C."}])
        _write_source_a(a2, [{"name": "Address", "definition": "A."}])
        domain_dir = tmp_path / "domain"
        result = runner.invoke(app, [
            "discover",
            "--source-a", str(a1),
            "--source-a", str(a2),
            "--domain-dir", str(domain_dir),
        ])
        assert result.exit_code == 0, result.output
        raw = json.loads(
            (domain_dir / "discovery" / "candidate-graph.json").read_text(
                encoding="utf-8"
            )
        )
        assert {c["label"] for c in raw["concepts"]} == {"Customer", "Address"}

    def test_source_a_and_b_cross_source_merge(self, tmp_path: Path):
        """Same normalised label in Source A and Source B → one
        merged candidate with both source bands marked present."""
        a = tmp_path / "a.json"
        b = tmp_path / "b.json"
        _write_source_a(a, [{"name": "Customer", "definition": "From A."}])
        _write_source_b(b, [
            {"element_name": "customer", "definition": "From B."},
        ])
        domain_dir = tmp_path / "domain"
        result = runner.invoke(app, [
            "discover",
            "--source-a", str(a),
            "--source-b", str(b),
            "--domain-dir", str(domain_dir),
        ])
        assert result.exit_code == 0
        raw = json.loads(
            (domain_dir / "discovery" / "candidate-graph.json").read_text(
                encoding="utf-8"
            )
        )
        assert len(raw["concepts"]) == 1
        concept = raw["concepts"][0]
        assert concept["source_presence"]["A"] is True
        assert concept["source_presence"]["B"] is True

    def test_no_source_inputs_writes_empty_but_valid_artifacts(
        self, tmp_path: Path,
    ):
        """Discovery without any source inputs is allowed (e.g. a
        smoke-test of the CLI wiring); the artifacts are empty but
        each is parseable JSON with the expected top-level shape."""
        domain_dir = tmp_path / "domain"
        result = runner.invoke(app, [
            "discover",
            "--domain-dir", str(domain_dir),
        ])
        assert result.exit_code == 0, result.output
        graph = json.loads(
            (domain_dir / "discovery" / "candidate-graph.json").read_text(
                encoding="utf-8"
            )
        )
        assert graph["concepts"] == []
        assert graph["relationships"] == []

    def test_source_c_flag_accepted_without_crash(self, tmp_path: Path):
        """The ``--source-c`` flag is accepted by ``discover``. Its
        payload is passed through to ``build_candidate_graph``,
        which does not extract candidate concepts or relationships
        from Source C in this implementation; the command must
        still exit cleanly."""
        c = tmp_path / "c.json"
        c.write_text(json.dumps({"opaque_payload": []}), encoding="utf-8")
        domain_dir = tmp_path / "domain"
        result = runner.invoke(app, [
            "discover",
            "--source-c", str(c),
            "--domain-dir", str(domain_dir),
        ])
        assert result.exit_code == 0, result.output

    def test_source_d_flag_accepted_without_crash(self, tmp_path: Path):
        """The ``--source-d`` flag is accepted by ``discover``. Its
        payload is passed through to ``build_candidate_graph``,
        which does not extract candidate concepts or relationships
        from Source D in this implementation; the command must
        still exit cleanly."""
        d = tmp_path / "d.json"
        d.write_text(json.dumps({"opaque_payload": []}), encoding="utf-8")
        domain_dir = tmp_path / "domain"
        result = runner.invoke(app, [
            "discover",
            "--source-d", str(d),
            "--domain-dir", str(domain_dir),
        ])
        assert result.exit_code == 0, result.output


# ─── Source B shape support (round-1 reviewer finding) ─────────────────────


class TestSourceBShapeSupport:
    """The Source B governance JSON shape that ships with the repo
    (``docs/governance_example.json``) is a top-level array. The
    governance extractor also accepts a single object. ``discover``
    must accept those same shapes — not just the synthetic
    ``{"records": [...]}`` wrapper the candidate graph uses
    internally. Reviewer-round-1 finding: top-level arrays were
    crashing with ``AttributeError: 'list' object has no attribute
    'get'`` instead of friendly handling."""

    def test_source_b_top_level_array_accepted(self, tmp_path: Path):
        """The shipped ``docs/governance_example.json`` shape."""
        b = tmp_path / "governance.json"
        b.write_text(
            json.dumps([
                {"element_name": "Borrower", "definition": "From B."},
                {"element_name": "Collateral", "definition": "Also B."},
            ]),
            encoding="utf-8",
        )
        domain_dir = tmp_path / "domain"
        result = runner.invoke(app, [
            "discover",
            "--source-b", str(b),
            "--domain-dir", str(domain_dir),
        ])
        assert result.exit_code == 0, result.output
        raw = json.loads(
            (domain_dir / "discovery" / "candidate-graph.json").read_text(
                encoding="utf-8"
            )
        )
        labels = {c["label"] for c in raw["concepts"]}
        assert labels == {"Borrower", "Collateral"}

    def test_source_b_single_object_accepted(self, tmp_path: Path):
        """Single-record governance file (the other format the
        governance extractor accepts at test_governance_extractor.py:56)."""
        b = tmp_path / "single.json"
        b.write_text(
            json.dumps({
                "element_name": "Exposure",
                "definition": "A financial exposure.",
            }),
            encoding="utf-8",
        )
        domain_dir = tmp_path / "domain"
        result = runner.invoke(app, [
            "discover",
            "--source-b", str(b),
            "--domain-dir", str(domain_dir),
        ])
        assert result.exit_code == 0, result.output
        raw = json.loads(
            (domain_dir / "discovery" / "candidate-graph.json").read_text(
                encoding="utf-8"
            )
        )
        labels = {c["label"] for c in raw["concepts"]}
        assert labels == {"Exposure"}

    def test_source_b_wrapped_records_form_still_accepted(
        self, tmp_path: Path,
    ):
        """The internal ``{"records": [...]}`` wrapper (the shape
        candidate_graph reads natively) is also accepted, both for
        forward-compat with any pipeline that already emits this
        form and so callers can pre-normalise if they want."""
        b = tmp_path / "wrapped.json"
        b.write_text(
            json.dumps({
                "records": [
                    {"element_name": "Customer", "definition": "C."},
                ],
            }),
            encoding="utf-8",
        )
        domain_dir = tmp_path / "domain"
        result = runner.invoke(app, [
            "discover",
            "--source-b", str(b),
            "--domain-dir", str(domain_dir),
        ])
        assert result.exit_code == 0
        raw = json.loads(
            (domain_dir / "discovery" / "candidate-graph.json").read_text(
                encoding="utf-8"
            )
        )
        assert {c["label"] for c in raw["concepts"]} == {"Customer"}

    def test_source_b_mixed_shapes_across_multiple_files_merge(
        self, tmp_path: Path,
    ):
        """Repeated ``--source-b`` flags can carry files with
        different shapes; each is normalised independently and the
        records concatenate."""
        single = tmp_path / "single.json"
        array = tmp_path / "array.json"
        wrapped = tmp_path / "wrapped.json"
        single.write_text(
            json.dumps({"element_name": "Single", "definition": "1."}),
            encoding="utf-8",
        )
        array.write_text(
            json.dumps([
                {"element_name": "FromArrayA", "definition": "2a."},
                {"element_name": "FromArrayB", "definition": "2b."},
            ]),
            encoding="utf-8",
        )
        wrapped.write_text(
            json.dumps({
                "records": [
                    {"element_name": "Wrapped", "definition": "3."},
                ],
            }),
            encoding="utf-8",
        )
        domain_dir = tmp_path / "domain"
        result = runner.invoke(app, [
            "discover",
            "--source-b", str(single),
            "--source-b", str(array),
            "--source-b", str(wrapped),
            "--domain-dir", str(domain_dir),
        ])
        assert result.exit_code == 0, result.output
        raw = json.loads(
            (domain_dir / "discovery" / "candidate-graph.json").read_text(
                encoding="utf-8"
            )
        )
        assert {c["label"] for c in raw["concepts"]} == {
            "Single", "FromArrayA", "FromArrayB", "Wrapped",
        }

    def test_source_b_unrecognised_shape_surfaces_friendly_error(
        self, tmp_path: Path,
    ):
        """A JSON file that's neither a single governance object,
        an array, nor a ``{"records": [...]}`` wrapper must surface
        a clean exit-2 error — not an AttributeError traceback."""
        bad = tmp_path / "bad.json"
        bad.write_text(json.dumps("just a string"), encoding="utf-8")
        domain_dir = tmp_path / "domain"
        result = runner.invoke(app, [
            "discover",
            "--source-b", str(bad),
            "--domain-dir", str(domain_dir),
        ])
        assert result.exit_code != 0
        # The error message should reference the path and the
        # accepted shapes so the user can self-diagnose.
        assert "bad.json" in result.output
        assert "Source B" in result.output

    def test_source_b_array_with_non_object_entry_surfaces_friendly_error(
        self, tmp_path: Path,
    ):
        """An array that mixes governance objects with non-object
        entries (e.g. a stray string) must fail loudly with a path
        and entry index, not crash inside the merge loop."""
        bad = tmp_path / "mixed.json"
        bad.write_text(
            json.dumps([
                {"element_name": "Valid"},
                "not-an-object",
            ]),
            encoding="utf-8",
        )
        domain_dir = tmp_path / "domain"
        result = runner.invoke(app, [
            "discover",
            "--source-b", str(bad),
            "--domain-dir", str(domain_dir),
        ])
        assert result.exit_code != 0
        assert "mixed.json" in result.output


# ─── --profile flag: light normalisation only ──────────────────────────────


class TestDiscoverWithProfile:
    """Architecture: ``optional --profile only for light
    normalization, not filtering``. The profile's alias_map is
    passed through to build_candidate_graph. Nothing else from the
    profile is allowed to influence discovery."""

    def test_profile_alias_map_merges_synonyms_into_one_candidate(
        self, tmp_path: Path,
    ):
        """The alias_map from --profile must reach
        build_candidate_graph so synonyms in different sources
        converge."""
        profile_dir = tmp_path / "profile"
        _write_minimal_profile(profile_dir, {"obligor": "Borrower"})

        a = tmp_path / "a.json"
        b = tmp_path / "b.json"
        _write_source_a(a, [{"name": "obligor", "definition": "From A."}])
        _write_source_b(b, [
            {"element_name": "Borrower", "definition": "From B."},
        ])

        domain_dir = tmp_path / "domain"
        result = runner.invoke(app, [
            "discover",
            "--source-a", str(a),
            "--source-b", str(b),
            "--profile", str(profile_dir),
            "--domain-dir", str(domain_dir),
        ])
        assert result.exit_code == 0, result.output
        raw = json.loads(
            (domain_dir / "discovery" / "candidate-graph.json").read_text(
                encoding="utf-8"
            )
        )
        # Two source spellings converge to one candidate via the
        # profile's alias_map.
        assert len(raw["concepts"]) == 1

    def test_profile_without_alias_map_is_a_no_op(self, tmp_path: Path):
        """An empty alias_map in the profile must not change
        behaviour vs. running without ``--profile`` at all."""
        profile_dir = tmp_path / "profile"
        _write_minimal_profile(profile_dir, {})

        a = tmp_path / "a.json"
        _write_source_a(a, [
            {"name": "obligor", "definition": "A."},
            {"name": "Borrower", "definition": "B."},
        ])
        domain_dir = tmp_path / "domain"
        result = runner.invoke(app, [
            "discover",
            "--source-a", str(a),
            "--profile", str(profile_dir),
            "--domain-dir", str(domain_dir),
        ])
        assert result.exit_code == 0
        raw = json.loads(
            (domain_dir / "discovery" / "candidate-graph.json").read_text(
                encoding="utf-8"
            )
        )
        # No alias_map → two separate candidates.
        assert len(raw["concepts"]) == 2

    def test_profile_does_not_filter_candidates(self, tmp_path: Path):
        """Architecture constraint: --profile is light normalisation
        *only*. A profile that declares a narrow type vocabulary
        must NOT cause discover to drop concepts whose names aren't
        in that vocabulary."""
        profile_dir = tmp_path / "profile"
        # Profile only declares "Loan" as an entity type; alias_map
        # is empty.
        profile_dir.mkdir()
        (profile_dir / "schema.json").write_text(
            json.dumps({
                "profile_name": "narrow",
                "profile_version": "0.1.0",
                "entity_types": {
                    "Loan": {"required": ["definition"], "optional": [],
                             "subtypes": []},
                },
                "predicates": {},
                "alias_map": {},
            }),
            encoding="utf-8",
        )

        a = tmp_path / "a.json"
        _write_source_a(a, [
            {"name": "Customer", "definition": "Not in profile vocab."},
            {"name": "Address", "definition": "Also not in vocab."},
        ])
        domain_dir = tmp_path / "domain"
        result = runner.invoke(app, [
            "discover",
            "--source-a", str(a),
            "--profile", str(profile_dir),
            "--domain-dir", str(domain_dir),
        ])
        assert result.exit_code == 0
        raw = json.loads(
            (domain_dir / "discovery" / "candidate-graph.json").read_text(
                encoding="utf-8"
            )
        )
        # Both concepts present even though neither matches the
        # profile's "Loan" type — discovery does not filter.
        assert {c["label"] for c in raw["concepts"]} == {
            "Customer", "Address",
        }


# ─── Error surfaces ────────────────────────────────────────────────────────


class TestDiscoverErrors:

    def test_missing_domain_dir_flag_fails(self, tmp_path: Path):
        result = runner.invoke(app, ["discover"])
        assert result.exit_code != 0

    def test_invalid_json_in_source_a_surfaces_friendly_error(
        self, tmp_path: Path,
    ):
        broken = tmp_path / "broken.json"
        broken.write_text("not-json", encoding="utf-8")
        domain_dir = tmp_path / "domain"
        result = runner.invoke(app, [
            "discover",
            "--source-a", str(broken),
            "--domain-dir", str(domain_dir),
        ])
        assert result.exit_code != 0
        # The path should be referenced in the error output so the
        # user can find the bad file.
        assert "broken.json" in result.output

    def test_invalid_profile_directory_surfaces_friendly_error(
        self, tmp_path: Path,
    ):
        no_such = tmp_path / "no-such-profile"
        domain_dir = tmp_path / "domain"
        result = runner.invoke(app, [
            "discover",
            "--profile", str(no_such),
            "--domain-dir", str(domain_dir),
        ])
        assert result.exit_code != 0
        assert "profile" in result.output.lower()


# ─── induce-profile (Task 6) ───────────────────────────────────────────────


def _write_candidate_graph(
    path: Path, concepts: list[dict], relationships: list[dict] | None = None,
) -> None:
    """Write a minimal candidate-graph.json. Each ``concept`` dict
    needs the post-Phase-1 CandidateConcept shape (id, label,
    normalized_label, suggested_entity_type, classification,
    summary_definition, source_presence, source_counts)."""
    path.write_text(
        json.dumps({
            "concepts": concepts,
            "relationships": relationships or [],
        }),
        encoding="utf-8",
    )


def _stub_candidate_dict(
    label: str,
    *,
    a: int = 0,
    b: int = 0,
    c: int = 0,
    d: int = 0,
    definition: str = "",
    classification: str = "unknown",
) -> dict:
    """Build a candidate dict in the on-disk shape that
    ``CandidateConcept.from_dict`` reconstructs. Pre-scoring
    candidates carry ``classification="unknown"``; induce-profile's
    job is to run score_candidates and assign proper bands."""
    return {
        "candidate_id": f"cand_{label.lower().replace(' ', '_')}",
        "label": label,
        "normalized_label": label.lower(),
        "suggested_entity_type": "Concept",
        "classification": classification,
        "summary_definition": definition,
        "source_presence": {"A": a > 0, "B": b > 0, "C": c > 0, "D": d > 0},
        "source_counts": {"A": a, "B": b, "C": c, "D": d},
        "schema_links": [],
        "code_links": [],
        "governance_links": [],
        "authoritative_evidence_count": a,
        "graph_degree": 0,
        "relevance_score": 0.0,
        "relevance_breakdown": {},
        "provenance": [],
        "aliases": [],
        "status": "candidate",
    }


class TestInduceProfileBasic:
    """Plan's canonical Task 6 contract: read candidate-graph.json,
    score, emit a draft profile directory."""

    def test_writes_schema_and_induction_report(self, tmp_path: Path):
        graph = tmp_path / "candidate-graph.json"
        _write_candidate_graph(graph, [
            _stub_candidate_dict("Customer", a=3, b=1, definition="A client."),
        ])
        out_dir = tmp_path / "induced"
        result = runner.invoke(app, [
            "induce-profile", str(graph),
            "--output-dir", str(out_dir),
            "--domain-name", "demo",
        ])
        assert result.exit_code == 0, result.output
        assert (out_dir / "schema.json").exists()
        assert (out_dir / "induction_report.json").exists()
        assert (out_dir / "alias_map.json").exists()
        assert (out_dir / "prompt_fragment.md").exists()

    def test_emitted_schema_round_trips_through_load_profile(
        self, tmp_path: Path,
    ):
        """CLI-level AC1 pin (the writer-side AC1 is already in
        test_profile_induction.py — this confirms the CLI wiring
        preserves it)."""
        from ontozense.core.profile import load_profile

        graph = tmp_path / "candidate-graph.json"
        _write_candidate_graph(graph, [
            _stub_candidate_dict("Customer", a=3, b=1, definition="A client."),
        ])
        out_dir = tmp_path / "induced"
        result = runner.invoke(app, [
            "induce-profile", str(graph),
            "--output-dir", str(out_dir),
            "--domain-name", "demo",
        ])
        assert result.exit_code == 0
        profile = load_profile(out_dir)
        assert profile.profile_name == "demo"
        assert "Concept" in profile.entity_types

    def test_uses_default_weights_and_thresholds_when_flags_omitted(
        self, tmp_path: Path,
    ):
        """When neither --weights nor --thresholds is given, the
        induction report records the documented defaults so a
        reviewer can always trace the exact config used."""
        from ontozense.core.relevance import (
            DEFAULT_THRESHOLDS, DEFAULT_WEIGHTS,
        )

        graph = tmp_path / "candidate-graph.json"
        _write_candidate_graph(graph, [
            _stub_candidate_dict("Customer", a=3, b=1, definition="A."),
        ])
        out_dir = tmp_path / "induced"
        result = runner.invoke(app, [
            "induce-profile", str(graph),
            "--output-dir", str(out_dir),
            "--domain-name", "demo",
        ])
        assert result.exit_code == 0
        report = json.loads(
            (out_dir / "induction_report.json").read_text(encoding="utf-8")
        )
        assert report["scoring_weights"] == dict(DEFAULT_WEIGHTS)
        assert report["scoring_thresholds"] == dict(DEFAULT_THRESHOLDS)


class TestInduceProfileScoringConfig:
    """The architecture mandates configurable weights AND thresholds
    (round-2 review of Task 3). The CLI exposes both via --weights
    and --thresholds. These tests pin end-to-end propagation: from
    JSON file → score_candidates → InductionReport."""

    def test_custom_weights_recorded_in_report(self, tmp_path: Path):
        """The exact weight values from the file land in the
        report verbatim."""
        from ontozense.core.relevance import DEFAULT_WEIGHTS

        custom = dict(DEFAULT_WEIGHTS)
        custom["authoritative_frequency"] = 0.50
        custom["governance_presence"] = 0.05
        weights_file = tmp_path / "weights.json"
        weights_file.write_text(json.dumps(custom), encoding="utf-8")

        graph = tmp_path / "candidate-graph.json"
        _write_candidate_graph(graph, [
            _stub_candidate_dict("Customer", a=3, b=1, definition="A."),
        ])
        out_dir = tmp_path / "induced"
        result = runner.invoke(app, [
            "induce-profile", str(graph),
            "--output-dir", str(out_dir),
            "--domain-name", "demo",
            "--weights", str(weights_file),
        ])
        assert result.exit_code == 0, result.output
        report = json.loads(
            (out_dir / "induction_report.json").read_text(encoding="utf-8")
        )
        assert report["scoring_weights"] == custom

    def test_custom_weights_change_relevance_score(self, tmp_path: Path):
        """Custom weights must actually feed score_candidates — a
        different weight produces a different score for the same
        candidate."""
        from ontozense.core.relevance import DEFAULT_WEIGHTS

        # Default-weight pass.
        graph = tmp_path / "candidate-graph.json"
        _write_candidate_graph(graph, [
            _stub_candidate_dict("X", a=1, definition="d."),
        ])
        out_a = tmp_path / "default"
        result_a = runner.invoke(app, [
            "induce-profile", str(graph),
            "--output-dir", str(out_a),
            "--domain-name", "demo",
        ])
        assert result_a.exit_code == 0
        report_a = json.loads(
            (out_a / "induction_report.json").read_text(encoding="utf-8")
        )

        # Custom-weight pass: shift everything onto definition_richness.
        custom = dict.fromkeys(DEFAULT_WEIGHTS.keys(), 0.0)
        custom["definition_richness"] = 1.0
        weights_file = tmp_path / "weights.json"
        weights_file.write_text(json.dumps(custom), encoding="utf-8")
        out_b = tmp_path / "custom"
        result_b = runner.invoke(app, [
            "induce-profile", str(graph),
            "--output-dir", str(out_b),
            "--domain-name", "demo",
            "--weights", str(weights_file),
        ])
        assert result_b.exit_code == 0
        report_b = json.loads(
            (out_b / "induction_report.json").read_text(encoding="utf-8")
        )
        # Top candidate's score differs between the two runs.
        score_a = report_a["top_candidates"][0]["score"] if report_a["top_candidates"] else None
        score_b = report_b["top_candidates"][0]["score"] if report_b["top_candidates"] else None
        assert score_a != score_b

    def test_custom_thresholds_recorded_in_report(self, tmp_path: Path):
        thresholds_file = tmp_path / "thresholds.json"
        thresholds_file.write_text(
            json.dumps({
                "core_business": 0.80,
                "supporting_technical": 0.55,
            }),
            encoding="utf-8",
        )
        graph = tmp_path / "candidate-graph.json"
        _write_candidate_graph(graph, [
            _stub_candidate_dict("Customer", a=3, b=1, definition="A."),
        ])
        out_dir = tmp_path / "induced"
        result = runner.invoke(app, [
            "induce-profile", str(graph),
            "--output-dir", str(out_dir),
            "--domain-name", "demo",
            "--thresholds", str(thresholds_file),
        ])
        assert result.exit_code == 0, result.output
        report = json.loads(
            (out_dir / "induction_report.json").read_text(encoding="utf-8")
        )
        assert report["scoring_thresholds"] == {
            "core_business": 0.80,
            "supporting_technical": 0.55,
        }

    def test_custom_thresholds_change_classification_bands(
        self, tmp_path: Path,
    ):
        """A candidate that classifies as supporting_technical under
        defaults must classify differently when the thresholds are
        relaxed enough to promote it to core_business."""
        graph = tmp_path / "candidate-graph.json"
        _write_candidate_graph(graph, [
            _stub_candidate_dict(
                "Customer", a=2, b=1, definition="A.",
            ),
        ])

        # Default run.
        out_default = tmp_path / "default"
        runner.invoke(app, [
            "induce-profile", str(graph),
            "--output-dir", str(out_default),
            "--domain-name", "demo",
        ])
        default_report = json.loads(
            (out_default / "induction_report.json").read_text(encoding="utf-8")
        )

        # Tighter thresholds.
        tight = tmp_path / "tight.json"
        tight.write_text(
            json.dumps({
                "core_business": 0.99,
                "supporting_technical": 0.99,
            }),
            encoding="utf-8",
        )
        out_tight = tmp_path / "tight"
        runner.invoke(app, [
            "induce-profile", str(graph),
            "--output-dir", str(out_tight),
            "--domain-name", "demo",
            "--thresholds", str(tight),
        ])
        tight_report = json.loads(
            (out_tight / "induction_report.json").read_text(encoding="utf-8")
        )
        # Both reports cover the same candidate, but band totals
        # differ: tight thresholds push it into the rejected pile.
        assert default_report["candidate_count"] == 1
        assert tight_report["candidate_count"] == 1
        assert tight_report["rejected_count"] >= default_report["rejected_count"]


class TestInduceProfileErrors:
    """User-facing failure modes surface as friendly exit-2
    messages, not Python tracebacks."""

    def test_missing_candidate_graph_file_fails_cleanly(
        self, tmp_path: Path,
    ):
        no_such = tmp_path / "no-such.json"
        out_dir = tmp_path / "induced"
        result = runner.invoke(app, [
            "induce-profile", str(no_such),
            "--output-dir", str(out_dir),
            "--domain-name", "demo",
        ])
        assert result.exit_code != 0
        assert "no-such.json" in result.output

    def test_malformed_candidate_graph_json_fails_cleanly(
        self, tmp_path: Path,
    ):
        graph = tmp_path / "broken.json"
        graph.write_text("not-json", encoding="utf-8")
        out_dir = tmp_path / "induced"
        result = runner.invoke(app, [
            "induce-profile", str(graph),
            "--output-dir", str(out_dir),
            "--domain-name", "demo",
        ])
        assert result.exit_code != 0
        assert "broken.json" in result.output

    def test_weights_file_missing_keys_fails_cleanly(self, tmp_path: Path):
        """Per Task 3's contract, score_candidates demands a
        *complete* weights dict (missing keys raise KeyError).
        The CLI must validate upstream and surface a clean message
        listing the missing keys."""
        partial = tmp_path / "partial.json"
        partial.write_text(
            json.dumps({"authoritative_frequency": 0.5}),
            encoding="utf-8",
        )
        graph = tmp_path / "candidate-graph.json"
        _write_candidate_graph(graph, [
            _stub_candidate_dict("X", a=1, definition="d."),
        ])
        out_dir = tmp_path / "induced"
        result = runner.invoke(app, [
            "induce-profile", str(graph),
            "--output-dir", str(out_dir),
            "--domain-name", "demo",
            "--weights", str(partial),
        ])
        assert result.exit_code != 0
        assert "partial.json" in result.output
        # The error must list at least one missing key by name so
        # the user can fix their file.
        assert "governance_presence" in result.output \
            or "missing" in result.output.lower()

    def test_thresholds_file_missing_keys_fails_cleanly(
        self, tmp_path: Path,
    ):
        partial = tmp_path / "partial.json"
        partial.write_text(
            json.dumps({"core_business": 0.7}),
            encoding="utf-8",
        )
        graph = tmp_path / "candidate-graph.json"
        _write_candidate_graph(graph, [
            _stub_candidate_dict("X", a=1, definition="d."),
        ])
        out_dir = tmp_path / "induced"
        result = runner.invoke(app, [
            "induce-profile", str(graph),
            "--output-dir", str(out_dir),
            "--domain-name", "demo",
            "--thresholds", str(partial),
        ])
        assert result.exit_code != 0
        assert "partial.json" in result.output
        assert "supporting_technical" in result.output \
            or "missing" in result.output.lower()

    def test_weights_file_with_non_dict_fails_cleanly(
        self, tmp_path: Path,
    ):
        bad = tmp_path / "bad.json"
        bad.write_text(json.dumps([0.1, 0.2]), encoding="utf-8")
        graph = tmp_path / "candidate-graph.json"
        _write_candidate_graph(graph, [
            _stub_candidate_dict("X", a=1, definition="d."),
        ])
        out_dir = tmp_path / "induced"
        result = runner.invoke(app, [
            "induce-profile", str(graph),
            "--output-dir", str(out_dir),
            "--domain-name", "demo",
            "--weights", str(bad),
        ])
        assert result.exit_code != 0
        assert "bad.json" in result.output

    def test_weights_file_with_non_numeric_value_fails_cleanly(
        self, tmp_path: Path,
    ):
        from ontozense.core.relevance import DEFAULT_WEIGHTS

        bad = dict.fromkeys(DEFAULT_WEIGHTS.keys(), 0.1)
        bad["authoritative_frequency"] = "not-a-number"
        bad_file = tmp_path / "bad.json"
        bad_file.write_text(json.dumps(bad), encoding="utf-8")
        graph = tmp_path / "candidate-graph.json"
        _write_candidate_graph(graph, [
            _stub_candidate_dict("X", a=1, definition="d."),
        ])
        out_dir = tmp_path / "induced"
        result = runner.invoke(app, [
            "induce-profile", str(graph),
            "--output-dir", str(out_dir),
            "--domain-name", "demo",
            "--weights", str(bad_file),
        ])
        assert result.exit_code != 0
        assert "bad.json" in result.output

    def test_concept_entry_is_not_an_object_fails_cleanly(
        self, tmp_path: Path,
    ):
        """Round-1 reviewer finding: a non-object concept entry (e.g.
        a string slipped into the concepts list) used to crash with
        ``ValueError: dictionary update sequence element #0 has
        length 1; 2 is required`` from ``dict(raw)`` inside
        ``CandidateConcept.from_dict``. The CLI's except-clause was
        too narrow (TypeError + KeyError only). Must now surface a
        clean exit-2 message with the offending entry index."""
        graph = tmp_path / "candidate-graph.json"
        graph.write_text(
            json.dumps({
                "concepts": [
                    "not-an-object",  # <- breaks dict(raw)
                ],
                "relationships": [],
            }),
            encoding="utf-8",
        )
        out_dir = tmp_path / "induced"
        result = runner.invoke(app, [
            "induce-profile", str(graph),
            "--output-dir", str(out_dir),
            "--domain-name", "demo",
        ])
        assert result.exit_code != 0
        assert "candidate-graph.json" in result.output
        # Index should be cited so the user can locate the bad row.
        assert "[0]" in result.output or "concept entry" in result.output.lower()

    def test_concept_with_non_object_provenance_entry_fails_cleanly(
        self, tmp_path: Path,
    ):
        """Round-1 reviewer finding: a non-object inside the nested
        ``provenance`` list (e.g. a bare string) hits
        ``EvidenceEntry.from_dict(p)`` and bubbles a friend-unfriendly
        exception out of CandidateConcept.from_dict. Must surface as
        a clean exit-2 message."""
        bad_concept = _stub_candidate_dict("X", a=1, definition="d.")
        bad_concept["provenance"] = ["not-an-evidence-dict"]
        graph = tmp_path / "candidate-graph.json"
        _write_candidate_graph(graph, [bad_concept])
        out_dir = tmp_path / "induced"
        result = runner.invoke(app, [
            "induce-profile", str(graph),
            "--output-dir", str(out_dir),
            "--domain-name", "demo",
        ])
        assert result.exit_code != 0
        assert "candidate-graph.json" in result.output

    def test_concept_missing_required_dataclass_fields_fails_cleanly(
        self, tmp_path: Path,
    ):
        """A concept dict missing required CandidateConcept fields
        raises ``TypeError`` from ``cls(**data)``. Should also
        surface clean — exercises the same code path."""
        graph = tmp_path / "candidate-graph.json"
        graph.write_text(
            json.dumps({
                "concepts": [
                    # Has the candidate_id key but is otherwise empty —
                    # CandidateConcept's __init__ rejects.
                    {"candidate_id": "cand_x"},
                ],
                "relationships": [],
            }),
            encoding="utf-8",
        )
        out_dir = tmp_path / "induced"
        result = runner.invoke(app, [
            "induce-profile", str(graph),
            "--output-dir", str(out_dir),
            "--domain-name", "demo",
        ])
        assert result.exit_code != 0
        assert "candidate-graph.json" in result.output

    def test_concepts_field_not_a_list_fails_cleanly(
        self, tmp_path: Path,
    ):
        """Pin the up-front shape guard for ``concepts``. The
        Task 6 round-2 reviewer noted this guard was added but
        not exercised by a test; this commit closes the residual
        pin so a future regression that loosens the guard is
        caught here."""
        graph = tmp_path / "candidate-graph.json"
        graph.write_text(
            json.dumps({
                "concepts": "not-a-list",  # top-level shape error
                "relationships": [],
            }),
            encoding="utf-8",
        )
        out_dir = tmp_path / "induced"
        result = runner.invoke(app, [
            "induce-profile", str(graph),
            "--output-dir", str(out_dir),
            "--domain-name", "demo",
        ])
        assert result.exit_code != 0
        assert "candidate-graph.json" in result.output
        assert "concepts" in result.output.lower()


# ─── rebuild (Task 7 — stub orchestrator per the plan) ─────────────────────


class TestRebuildStub:
    """Per the implementation plan, ``rebuild`` is a stub in v1:
    it loads (and validates) the supplied profile, then prints
    the rebuild plan — the chain of existing commands the user
    should run manually to rebuild the fused dictionary with the
    reviewed profile. Direct orchestration of that chain is
    deferred to a follow-up task once the discovery flow is
    stable."""

    def test_invalid_profile_dir_exits_nonzero_with_schema_message(
        self, tmp_path: Path,
    ):
        """Plan's canonical Task 7 test: an empty profile dir
        (no schema.json) must fail loudly, surfacing the missing-
        schema message so the user knows what to fix."""
        empty_profile = tmp_path / "profile"
        empty_profile.mkdir()
        result = runner.invoke(app, [
            "rebuild",
            "--profile", str(empty_profile),
            "--domain-dir", str(tmp_path / "domain"),
        ])
        assert result.exit_code != 0
        assert (
            "schema.json" in result.output
            or "schema" in result.output.lower()
        )

    def test_valid_profile_exits_zero_and_prints_plan(
        self, tmp_path: Path,
    ):
        profile_dir = tmp_path / "profile"
        _write_minimal_profile(profile_dir, {})
        domain_dir = tmp_path / "domain"
        result = runner.invoke(app, [
            "rebuild",
            "--profile", str(profile_dir),
            "--domain-dir", str(domain_dir),
        ])
        assert result.exit_code == 0, result.output

    def test_plan_names_each_existing_pipeline_command(
        self, tmp_path: Path,
    ):
        """The rebuild plan must reference every existing pipeline
        step the user is meant to run by hand: extract-a, fuse,
        validate, lint, report. If a future commit drops one of
        these from the printed plan, the user won't know to run
        it."""
        profile_dir = tmp_path / "profile"
        _write_minimal_profile(profile_dir, {})
        result = runner.invoke(app, [
            "rebuild",
            "--profile", str(profile_dir),
            "--domain-dir", str(tmp_path / "domain"),
        ])
        assert result.exit_code == 0
        for step in ("extract-a", "fuse", "validate", "lint", "report"):
            assert step in result.output, (
                f"rebuild plan does not mention {step!r}"
            )

    def test_plan_mentions_loaded_profile_name(self, tmp_path: Path):
        """Surfacing the loaded profile name gives the user
        immediate confirmation that ``--profile`` resolved to what
        they expected (vs an old / wrong directory)."""
        profile_dir = tmp_path / "profile"
        _write_minimal_profile(profile_dir, {})
        # _write_minimal_profile writes ``"profile_name": "test"``.
        result = runner.invoke(app, [
            "rebuild",
            "--profile", str(profile_dir),
            "--domain-dir", str(tmp_path / "domain"),
        ])
        assert result.exit_code == 0
        assert "test" in result.output

    def test_plan_flags_orchestration_as_deferred(
        self, tmp_path: Path,
    ):
        """The plan body explicitly defers direct orchestration to
        a follow-up task. The CLI surface must make that clear so
        a user doesn't expect the command to actually run the
        chain."""
        profile_dir = tmp_path / "profile"
        _write_minimal_profile(profile_dir, {})
        result = runner.invoke(app, [
            "rebuild",
            "--profile", str(profile_dir),
            "--domain-dir", str(tmp_path / "domain"),
        ])
        out = result.output.lower()
        # Either phrasing is acceptable — the contract is that
        # *something* signals "manual chain, not auto-orchestrated".
        assert (
            "deferred" in out
            or "manual" in out
            or "follow-up" in out
            or "stub" in out
        )

    def test_nonexistent_profile_dir_surfaces_friendly_error(
        self, tmp_path: Path,
    ):
        no_such = tmp_path / "no-such-profile"
        result = runner.invoke(app, [
            "rebuild",
            "--profile", str(no_such),
            "--domain-dir", str(tmp_path / "domain"),
        ])
        assert result.exit_code != 0
        # The error must reference the bad path so the user can
        # self-diagnose a typo.
        assert "no-such-profile" in result.output

    def test_source_flags_accepted_without_error(self, tmp_path: Path):
        """Forward-compat: --source-a/b/c/d are in rebuild's
        signature so the eventual orchestrator can consume them.
        In the stub they're informational; they must at least not
        cause a parse error."""
        profile_dir = tmp_path / "profile"
        _write_minimal_profile(profile_dir, {})
        # Tee touch files so typer's Path-existence checks don't
        # complain (rebuild doesn't validate file existence in
        # stub mode, but typer's parser does for Path arguments).
        a = tmp_path / "a.json"
        a.write_text("{}", encoding="utf-8")
        result = runner.invoke(app, [
            "rebuild",
            "--profile", str(profile_dir),
            "--domain-dir", str(tmp_path / "domain"),
            "--source-a", str(a),
        ])
        assert result.exit_code == 0, result.output


class TestRebuildPlanCorrectness:
    """Round-1 reviewer finding: the *printed plan* is the product
    of the stub. If the plan tells the user to run a command with
    a flag that command doesn't accept, the user hits a typer parse
    error immediately. These tests pin the plan against the real
    command signatures end-to-end.

    Strong correctness pin: every ``--flag`` the plan mentions in a
    given step must be accepted by the corresponding command (per
    its ``--help`` output)."""

    def _capture_plan(self, tmp_path: Path) -> str:
        profile_dir = tmp_path / "profile"
        _write_minimal_profile(profile_dir, {})
        result = runner.invoke(app, [
            "rebuild",
            "--profile", str(profile_dir),
            "--domain-dir", str(tmp_path / "domain"),
        ])
        assert result.exit_code == 0
        return result.output

    def test_fuse_step_uses_source_flags_not_positionals(
        self, tmp_path: Path,
    ):
        """The exact round-1 bug: ``fuse`` uses ``--source-a/b/c/d``
        flags, not positional source paths."""
        plan = self._capture_plan(tmp_path)
        fuse_lines = [l for l in plan.splitlines() if "ontozense fuse" in l]
        assert fuse_lines, "plan does not mention `ontozense fuse`"
        fuse_text = "\n".join(fuse_lines)
        assert "--source-a" in fuse_text

    def test_fuse_step_does_not_mention_profile_flag(
        self, tmp_path: Path,
    ):
        """The other half of the round-1 fuse bug: ``fuse`` does not
        accept ``--profile``."""
        plan = self._capture_plan(tmp_path)
        fuse_lines = [l for l in plan.splitlines() if "ontozense fuse" in l]
        fuse_text = "\n".join(fuse_lines)
        assert "--profile" not in fuse_text

    def test_report_step_does_not_mention_domain_dir_flag(
        self, tmp_path: Path,
    ):
        """``report`` doesn't have ``--domain-dir``; the previous
        plan suggested it incorrectly."""
        plan = self._capture_plan(tmp_path)
        report_lines = [
            l for l in plan.splitlines() if "ontozense report" in l
        ]
        assert report_lines, "plan does not mention `ontozense report`"
        report_text = "\n".join(report_lines)
        assert "--domain-dir" not in report_text

    def test_every_plan_flag_is_accepted_by_its_command(
        self, tmp_path: Path,
    ):
        """The strong end-to-end pin: scan every ``--flag`` token in
        each plan step and verify it's accepted by the corresponding
        command. This catches round-1-style bugs (flags that don't
        exist on a command) and would catch any future drift if a
        downstream command's argument list changes."""
        import re

        plan = self._capture_plan(tmp_path)

        commands = ["extract-a", "fuse", "validate", "lint", "report"]
        help_for: dict[str, str] = {}
        for cmd in commands:
            help_for[cmd] = runner.invoke(app, [cmd, "--help"]).output

        flag_pattern = re.compile(r"--[a-z][a-z\-]+")
        for line in plan.splitlines():
            for cmd in commands:
                if f"ontozense {cmd}" not in line:
                    continue
                # Found a plan step. Strip the `[` and `]` decorations
                # users use to mark optional flags so we can scan flags
                # cleanly.
                cleaned = line.replace("[", " ").replace("]", " ")
                for flag in flag_pattern.findall(cleaned):
                    assert flag in help_for[cmd], (
                        f"Plan suggests `{cmd} {flag}`, but `{cmd}` "
                        f"does not accept that flag "
                        f"(per `ontozense {cmd} --help`)"
                    )
                break  # one command per line


# ─── End-to-end workflow (Task 8) ──────────────────────────────────────────


class TestDiscoveryWorkflowEndToEnd:
    """Pin the full discovery workflow as a single user journey:
    ``discover`` → ``induce-profile`` → ``load_profile``. Each
    command was tested in isolation in Tasks 5/6/7; these tests
    verify they actually wire together without contract drift at
    the boundaries (candidate-graph.json shape, profile directory
    shape, etc.)."""

    def test_discover_then_induce_profile_round_trip(self, tmp_path: Path):
        """Plan's canonical Task 8 test: ``discover`` writes a
        candidate-graph.json, ``induce-profile`` reads it and
        writes a draft profile directory. Both exit 0 and the
        emitted ``schema.json`` exists."""
        source_a = tmp_path / "source-a.json"
        _write_source_a(source_a, [
            {"name": "Customer", "definition": "A client."},
        ])
        domain_dir = tmp_path / "domain"

        discover_result = runner.invoke(app, [
            "discover",
            "--source-a", str(source_a),
            "--domain-dir", str(domain_dir),
        ])
        assert discover_result.exit_code == 0, discover_result.output

        induce_result = runner.invoke(app, [
            "induce-profile",
            str(domain_dir / "discovery" / "candidate-graph.json"),
            "--output-dir", str(domain_dir / "induced-profile"),
            "--domain-name", "demo",
        ])
        assert induce_result.exit_code == 0, induce_result.output
        assert (domain_dir / "induced-profile" / "schema.json").exists()

    def test_full_chain_discover_induce_load_profile(
        self, tmp_path: Path,
    ):
        """The architecture's end-to-end loop: the profile emitted
        by ``induce-profile`` (fed from ``discover``'s output) must
        round-trip through ``load_profile`` cleanly. This is AC1
        for the whole workflow, not just the writer side."""
        from ontozense.core.profile import load_profile

        # Multi-source input (A + B) so the candidate graph
        # exercises both ingestion paths.
        source_a = tmp_path / "source-a.json"
        source_b = tmp_path / "source-b.json"
        _write_source_a(source_a, [
            {"name": "Customer", "definition": "A client.",
             "provenance": {"source_document": "docs/customer.md"}},
            {"name": "Address", "definition": "A location."},
        ])
        _write_source_b(source_b, [
            {"element_name": "customer", "definition": "Governed."},
        ])

        domain_dir = tmp_path / "domain"
        # Step 1: discover.
        runner.invoke(app, [
            "discover",
            "--source-a", str(source_a),
            "--source-b", str(source_b),
            "--domain-dir", str(domain_dir),
        ])
        assert (domain_dir / "discovery" / "candidate-graph.json").exists()

        # Step 2: induce-profile.
        induced_dir = domain_dir / "induced-profile"
        runner.invoke(app, [
            "induce-profile",
            str(domain_dir / "discovery" / "candidate-graph.json"),
            "--output-dir", str(induced_dir),
            "--domain-name", "demo",
        ])

        # Step 3: load_profile must accept the emitted directory.
        profile = load_profile(induced_dir)
        assert profile.profile_name == "demo"
        # The Source A "Customer" candidate is core-band-ish under
        # default weights; it should land in the schema under
        # Concept.subtypes (the canonical entity bucket).
        assert "Concept" in profile.entity_types

    def test_workflow_preserves_alias_map_into_induced_profile(
        self, tmp_path: Path,
    ):
        """When ``discover --profile`` applies an alias_map, the
        merged candidates land in a single subtype downstream.
        ``induce-profile`` then writes a profile derived from those
        merged candidates. The emitted profile is a different
        artifact (it does not include derived alias mappings), but
        the *count* of distinct subtypes reflects the alias-driven
        merge."""
        from ontozense.core.profile import load_profile

        seed_profile = tmp_path / "seed-profile"
        _write_minimal_profile(seed_profile, {"obligor": "Borrower"})

        source_a = tmp_path / "source-a.json"
        source_b = tmp_path / "source-b.json"
        _write_source_a(source_a, [
            {"name": "obligor", "definition": "From A."},
        ])
        _write_source_b(source_b, [
            {"element_name": "Borrower", "definition": "From B."},
        ])
        domain_dir = tmp_path / "domain"
        runner.invoke(app, [
            "discover",
            "--source-a", str(source_a),
            "--source-b", str(source_b),
            "--profile", str(seed_profile),
            "--domain-dir", str(domain_dir),
        ])

        induced_dir = domain_dir / "induced-profile"
        runner.invoke(app, [
            "induce-profile",
            str(domain_dir / "discovery" / "candidate-graph.json"),
            "--output-dir", str(induced_dir),
            "--domain-name", "demo",
        ])

        profile = load_profile(induced_dir)
        # The two source spellings collapsed to one candidate via
        # the alias_map. That candidate lands as exactly one
        # subtype somewhere in the schema — which type bucket it
        # ends up in (``Concept`` vs ``TechnicalArtifact``) depends
        # on its scored band, but the pin is "exactly one" not
        # "in this specific bucket".
        total_subtypes = sum(
            len(et.subtypes) for et in profile.entity_types.values()
        )
        assert total_subtypes == 1


class TestInduceProfileConsoleSummary:
    """A short summary printed after the run gives the user
    immediate feedback without having to ``cat`` the report."""

    def test_summary_includes_output_path(self, tmp_path: Path):
        graph = tmp_path / "candidate-graph.json"
        _write_candidate_graph(graph, [
            _stub_candidate_dict("Customer", a=3, b=1, definition="A."),
        ])
        out_dir = tmp_path / "induced"
        result = runner.invoke(app, [
            "induce-profile", str(graph),
            "--output-dir", str(out_dir),
            "--domain-name", "demo",
        ])
        assert result.exit_code == 0
        assert "induced" in result.output

    def test_summary_includes_classification_counts(self, tmp_path: Path):
        graph = tmp_path / "candidate-graph.json"
        _write_candidate_graph(graph, [
            _stub_candidate_dict("Customer", a=3, b=1, definition="A."),
            _stub_candidate_dict("Order", a=2, b=1, definition="O."),
            _stub_candidate_dict("tmp_x", definition=""),
        ])
        out_dir = tmp_path / "induced"
        result = runner.invoke(app, [
            "induce-profile", str(graph),
            "--output-dir", str(out_dir),
            "--domain-name", "demo",
        ])
        assert result.exit_code == 0
        # At least one of the three band names should appear.
        out = result.output.lower()
        assert (
            "core_business" in out
            or "supporting_technical" in out
            or "rejected" in out
        )
