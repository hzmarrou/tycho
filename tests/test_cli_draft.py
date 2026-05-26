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

    def test_owl_xml_format(self, tmp_path: Path):
        """Spec §5.2: the third --format option is owl-xml (not the
        rdflib-internal name 'xml')."""
        domain_dir = tmp_path / "domain"
        _seed_workspace(domain_dir)
        out = tmp_path / "draft.owl"
        result = runner.invoke(app, [
            "draft",
            "--domain-dir", str(domain_dir),
            "--output", str(out),
            "--format", "owl-xml",
        ])
        assert result.exit_code == 0, result.output
        text = out.read_text(encoding="utf-8")
        assert "<?xml" in text  # RDF/XML always starts with the XML prolog


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


class TestDraftMultiSource:
    """Spec §5.2 Stage 2 contract: draft must fuse the resolved
    profile with ALL source inputs, not just Source A. The round-1
    review caught that the original draft implementation ignored
    --source-b/-c/-d."""

    def test_draft_with_source_b_includes_governance(self, tmp_path: Path):
        """Source B governance contributions should appear in
        fused.json alongside Source A's content."""
        domain_dir = tmp_path / "domain"
        _seed_workspace(domain_dir)

        # Write a minimal governance JSON with one record.
        governance = tmp_path / "governance.json"
        governance.write_text(
            json.dumps([
                {
                    "element_name": "Borrower",
                    "definition": "Governance-side definition.",
                    "is_critical": True,
                },
            ]),
            encoding="utf-8",
        )

        out = tmp_path / "draft.owl"
        result = runner.invoke(app, [
            "draft",
            "--domain-dir", str(domain_dir),
            "--output", str(out),
            "--source-b", str(governance),
        ])
        assert result.exit_code == 0, result.output

        # fused.json should mark the Borrower element with Source B
        # provenance (the governance record contributed to it).
        fused_path = domain_dir / "fused.json"
        assert fused_path.exists()
        fused = json.loads(fused_path.read_text(encoding="utf-8"))

        # Find an element whose name matches "Borrower" (case-insensitive)
        # and confirm Source B is in its sources list.
        borrower_elements = [
            e for e in fused["elements"]
            if e["element_name"].lower() == "borrower"
        ]
        assert borrower_elements, (
            "Borrower element missing from fused output"
        )

        # The element's per-field provenance should reference Source B
        # somewhere. After asdict() each FieldProvenance is a dict with
        # a "source" key ("A", "B", "C", or "D").
        borrower = borrower_elements[0]
        sources_seen = set()
        for prov_entry in borrower.get("field_provenance", {}).values():
            if isinstance(prov_entry, dict) and "source" in prov_entry:
                sources_seen.add(prov_entry["source"])
        assert "B" in sources_seen, (
            f"Source B not contributing to Borrower; saw "
            f"sources: {sources_seen}"
        )


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


# ---------------------------------------------------------------------------
# Task #96 (v1.1.x → soft-deprecation refactor) – --source-c deprecation tests
# ---------------------------------------------------------------------------

def test_draft_source_c_sql_emits_deprecation_warning_and_succeeds(tmp_path: Path):
    """`draft --source-c file.sql` is deprecated and ignored.
    The command must exit 0 (success), print a deprecation warning,
    and NOT attempt to ingest the SQL or crash with a JSON parse error.
    Source C contributions come from candidate-graph.json (produced
    by `survey`), not from this flag."""
    domain_dir = tmp_path / "demo"
    discovery_dir = domain_dir / "discovery"
    discovery_dir.mkdir(parents=True)
    (discovery_dir / "candidate-graph.json").write_text(
        '{"concepts": [], "relationships": [], "audit": []}',
        encoding="utf-8",
    )
    (discovery_dir / "source-a.json").write_text(
        '{"concepts": [], "relationships": []}',
        encoding="utf-8",
    )
    sql_path = tmp_path / "schema.sql"
    sql_path.write_text("CREATE TABLE loan (id INT PRIMARY KEY);\n", encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "draft",
            "--domain-dir", str(domain_dir),
            "--output", str(tmp_path / "draft.owl"),
            "--source-c", str(sql_path),
        ],
    )
    # Success exit code — deprecation is a warning, not an error.
    assert result.exit_code == 0, (
        f"expected exit 0; got {result.exit_code}\nstdout: {result.stdout}"
    )
    # Deprecation warning present.
    out = result.stdout
    assert "--source-c on `draft` is deprecated and ignored" in out
    assert "ontozense survey" in out
    # Critically: no SQL/JSON parse traceback wording from the old code paths.
    assert "JSON parse error" not in out
    assert "Expecting value" not in out
    assert "Source C SQL is not accepted by" not in out  # the old fail-fast message


def test_draft_source_c_json_also_emits_deprecation_warning_and_succeeds(tmp_path: Path):
    """A legacy .json SchemaResult passed to draft is now also
    deprecated and ignored — same warning as the .sql case.
    The user should run an adapter through `survey` instead."""
    domain_dir = tmp_path / "demo"
    discovery_dir = domain_dir / "discovery"
    discovery_dir.mkdir(parents=True)
    (discovery_dir / "candidate-graph.json").write_text(
        '{"concepts": [], "relationships": [], "audit": []}',
        encoding="utf-8",
    )
    (discovery_dir / "source-a.json").write_text(
        '{"concepts": [], "relationships": []}',
        encoding="utf-8",
    )
    json_path = tmp_path / "schema.json"
    json_path.write_text(
        '{"schema_version": "1.0", "models": [], "source_dir": ""}',
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        [
            "draft",
            "--domain-dir", str(domain_dir),
            "--output", str(tmp_path / "draft.owl"),
            "--source-c", str(json_path),
        ],
    )
    assert result.exit_code == 0
    assert "--source-c on `draft` is deprecated and ignored" in result.stdout
    # Confirm we did NOT take the legacy SchemaResult load path.
    assert "schema models from" not in result.stdout


def test_draft_without_source_c_works_unchanged(tmp_path: Path):
    """`draft` without --source-c (the v1.1+ canonical usage)
    must NOT print any deprecation warning."""
    domain_dir = tmp_path / "demo"
    discovery_dir = domain_dir / "discovery"
    discovery_dir.mkdir(parents=True)
    (discovery_dir / "candidate-graph.json").write_text(
        '{"concepts": [], "relationships": [], "audit": []}',
        encoding="utf-8",
    )
    (discovery_dir / "source-a.json").write_text(
        '{"concepts": [], "relationships": []}',
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        [
            "draft",
            "--domain-dir", str(domain_dir),
            "--output", str(tmp_path / "draft.owl"),
        ],
    )
    assert result.exit_code == 0
    assert "--source-c on `draft` is deprecated" not in result.stdout


# ─── Phase D PR D1 — --emit-rules CLI contract ─────────────────────────────
#
# Pins the user-facing flag contract for the Phase D annotation
# emission. Default emits annotations; "none" suppresses; reserved
# Phase E values reject cleanly with "queued for Phase E"; bogus
# values reject with a clear "must be one of" list.


class TestDraftEmitRules:
    def test_default_emit_rules_is_annotations(self, tmp_path: Path):
        """No --emit-rules flag = annotations behaviour. We don't
        seed BusinessRules in this fixture (empty fused), so the
        assertion focuses on the exit code and absence of any
        Phase E rejection message."""
        domain_dir = tmp_path / "domain"
        _seed_workspace(domain_dir)
        out = tmp_path / "draft.owl"
        result = runner.invoke(app, [
            "draft",
            "--domain-dir", str(domain_dir),
            "--output", str(out),
        ])
        assert result.exit_code == 0, result.output
        assert "queued for Phase E" not in result.output

    def test_explicit_emit_rules_annotations_succeeds(self, tmp_path: Path):
        domain_dir = tmp_path / "domain"
        _seed_workspace(domain_dir)
        out = tmp_path / "draft.owl"
        result = runner.invoke(app, [
            "draft",
            "--domain-dir", str(domain_dir),
            "--output", str(out),
            "--emit-rules", "annotations",
        ])
        assert result.exit_code == 0, result.output

    def test_emit_rules_none_succeeds(self, tmp_path: Path):
        domain_dir = tmp_path / "domain"
        _seed_workspace(domain_dir)
        out = tmp_path / "draft.owl"
        result = runner.invoke(app, [
            "draft",
            "--domain-dir", str(domain_dir),
            "--output", str(out),
            "--emit-rules", "none",
        ])
        assert result.exit_code == 0, result.output

    def test_emit_rules_restrictions_rejected_queued_for_phase_e(
        self, tmp_path: Path,
    ):
        domain_dir = tmp_path / "domain"
        _seed_workspace(domain_dir)
        result = runner.invoke(app, [
            "draft",
            "--domain-dir", str(domain_dir),
            "--output", str(tmp_path / "draft.owl"),
            "--emit-rules", "restrictions",
        ])
        assert result.exit_code != 0
        assert "queued for Phase E" in result.output
        assert "restrictions" in result.output

    def test_emit_rules_swrl_rejected_queued_for_phase_e(
        self, tmp_path: Path,
    ):
        domain_dir = tmp_path / "domain"
        _seed_workspace(domain_dir)
        result = runner.invoke(app, [
            "draft",
            "--domain-dir", str(domain_dir),
            "--output", str(tmp_path / "draft.owl"),
            "--emit-rules", "swrl",
        ])
        assert result.exit_code != 0
        assert "queued for Phase E" in result.output

    def test_emit_rules_all_rejected_queued_for_phase_e(
        self, tmp_path: Path,
    ):
        domain_dir = tmp_path / "domain"
        _seed_workspace(domain_dir)
        result = runner.invoke(app, [
            "draft",
            "--domain-dir", str(domain_dir),
            "--output", str(tmp_path / "draft.owl"),
            "--emit-rules", "all",
        ])
        assert result.exit_code != 0
        assert "queued for Phase E" in result.output

    def test_emit_rules_invalid_value_rejected_with_choices_list(
        self, tmp_path: Path,
    ):
        """Bogus value (typo) rejected with a clear listing of the
        five recognised modes — gives the user something to fix."""
        domain_dir = tmp_path / "domain"
        _seed_workspace(domain_dir)
        result = runner.invoke(app, [
            "draft",
            "--domain-dir", str(domain_dir),
            "--output", str(tmp_path / "draft.owl"),
            "--emit-rules", "annotationz",  # deliberate typo
        ])
        assert result.exit_code != 0
        assert "annotationz" in result.output
        # Error message lists the five recognised values.
        for mode in ("annotations", "none", "restrictions", "swrl", "all"):
            assert mode in result.output
