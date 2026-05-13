"""Tests for the discovery CLI commands (profile induction
architecture, Phase 3 / Task 5+).

Task 5 covers the ``discover`` subcommand. Tasks 6+7 add the
``induce-profile`` and ``rebuild`` commands; their tests will land
alongside those tasks but in this same file for symmetry.

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
      * ``concept-mappings.json`` — placeholder for the induced
        alias / merge mappings; populated by ``induce-profile``
        in Task 6.

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

    def test_concept_mappings_initially_empty_placeholder(
        self, tmp_path: Path,
    ):
        """concept-mappings.json is written empty in discover —
        induce-profile (Task 6) populates it. The file must exist
        and be JSON-parseable so downstream tooling has a stable
        shape to expect."""
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
        """Forward-compat: build_candidate_graph's Source C hook is
        still a placeholder, but the CLI surface must already
        accept the flag so it doesn't break when ingestion lands."""
        c = tmp_path / "c.json"
        c.write_text(json.dumps({"some_future_shape": []}), encoding="utf-8")
        domain_dir = tmp_path / "domain"
        result = runner.invoke(app, [
            "discover",
            "--source-c", str(c),
            "--domain-dir", str(domain_dir),
        ])
        assert result.exit_code == 0, result.output

    def test_source_d_flag_accepted_without_crash(self, tmp_path: Path):
        """Same forward-compat as --source-c."""
        d = tmp_path / "d.json"
        d.write_text(json.dumps({"some_future_shape": []}), encoding="utf-8")
        domain_dir = tmp_path / "domain"
        result = runner.invoke(app, [
            "discover",
            "--source-d", str(d),
            "--domain-dir", str(domain_dir),
        ])
        assert result.exit_code == 0, result.output


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
