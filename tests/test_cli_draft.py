"""Tests for the new `ontozense draft` command (Stage 2 orchestrator)."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from ontozense.cli import app


runner = CliRunner()


def _seed_workspace(domain_dir: Path) -> None:
    """Lay out a minimal post-survey workspace that the draft command
    can consume."""
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
                    "source_presence": {
                        "A": True, "B": True, "C": False, "D": False,
                    },
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
    discovery.joinpath("source-a.json").write_text(
        json.dumps({
            "concepts": [{"name": "Borrower", "definition": "A party."}],
            "relationships": [],
        }),
        encoding="utf-8",
    )


def _minimal_profile_dir(profile_dir: Path) -> None:
    profile_dir.mkdir(parents=True, exist_ok=True)
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
        _minimal_profile_dir(profile_dir)
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
        # JSON-LD content must parse as JSON.
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


class TestDraftErrors:
    def test_missing_candidate_graph_fails_cleanly(self, tmp_path: Path):
        domain_dir = tmp_path / "domain"
        # Note: no _seed_workspace() — discovery/ directory absent.
        out = tmp_path / "draft.owl"
        result = runner.invoke(app, [
            "draft",
            "--domain-dir", str(domain_dir),
            "--output", str(out),
        ])
        assert result.exit_code != 0
        assert "survey" in result.output.lower()  # hint to run survey first


class TestRebuildDeprecation:
    def test_rebuild_prints_deprecation_note(self, tmp_path: Path):
        profile = tmp_path / "profile"
        _minimal_profile_dir(profile)
        result = runner.invoke(app, [
            "rebuild",
            "--profile", str(profile),
            "--domain-dir", str(tmp_path / "domain"),
        ])
        assert "deprecated" in result.output.lower()
        # Should point at the replacement.
        assert "draft" in result.output
