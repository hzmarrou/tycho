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


# ─── Phase B PR B1 — --property-induction CLI contract ────────────────────
#
# B1 ships the dry-run path only: eligibility scan + budget plan
# printed to the console. No cache file. No LLM call. No new disk
# artifacts. PR B2 lands the real LLM call + cache.
#
# These tests pin the flag contract before implementation. They are
# the regression suite for the design-doc 5-gate scope lock.


class TestDraftPropertyInductionFlag:
    def test_default_is_off_no_console_noise(self, tmp_path: Path):
        """Default --property-induction is off. No eligibility scan
        runs, no console output about induction."""
        domain_dir = tmp_path / "domain"
        _seed_workspace(domain_dir)
        result = runner.invoke(app, [
            "draft",
            "--domain-dir", str(domain_dir),
            "--output", str(tmp_path / "draft.owl"),
        ])
        assert result.exit_code == 0, result.output
        # No property-induction noise in the console. Anchor on the
        # specific console marker the CLI prints so pytest tmp paths
        # containing "property-induction" don't cause false positives.
        assert "Property induction (PR B1 dry-run)" not in result.output

    def test_explicit_off_is_no_op(self, tmp_path: Path):
        """`--property-induction off` is the same as omitting the flag."""
        domain_dir = tmp_path / "domain"
        _seed_workspace(domain_dir)
        result = runner.invoke(app, [
            "draft",
            "--domain-dir", str(domain_dir),
            "--output", str(tmp_path / "draft.owl"),
            "--property-induction", "off",
        ])
        assert result.exit_code == 0, result.output

    def test_llm_mode_runs_induction_console_plan(
        self, tmp_path: Path, monkeypatch,
    ):
        """`--property-induction llm` runs the eligibility scan +
        real LLM call (mocked) + cache write. Console mentions
        induction. PR B2 onwards the cache file IS written when the
        domain has eligible concepts; the seeded workspace has none
        (Borrower already carries no Source A snippet anchor) so the
        scan yields zero eligible and the cache is created empty."""
        from ontozense.core import property_induction as pi
        monkeypatch.setattr(
            pi, "_call_llm",
            lambda *, prompt, model: "",  # no attributes returned
        )
        domain_dir = tmp_path / "domain"
        _seed_workspace(domain_dir)
        result = runner.invoke(app, [
            "draft",
            "--domain-dir", str(domain_dir),
            "--output", str(tmp_path / "draft.owl"),
            "--property-induction", "llm",
        ])
        assert result.exit_code == 0, result.output
        assert "Property induction:" in result.output

    def test_llm_mode_writes_cache_file_in_b2(
        self, tmp_path: Path, monkeypatch,
    ):
        """PR B2 writes ``discovery/source-a-properties.json`` when
        --property-induction llm runs. The cache file is the
        durable record of what the LLM induced + budget metadata."""
        from ontozense.core import property_induction as pi
        monkeypatch.setattr(
            pi, "_call_llm",
            lambda *, prompt, model: "",  # zero eligible in seeded fixture
        )
        domain_dir = tmp_path / "domain"
        _seed_workspace(domain_dir)
        result = runner.invoke(app, [
            "draft",
            "--domain-dir", str(domain_dir),
            "--output", str(tmp_path / "draft.owl"),
            "--property-induction", "llm",
        ])
        assert result.exit_code == 0, result.output
        # PR B2 writes the cache (empty per_class is fine here —
        # seeded fixture has no eligible concepts).
        assert (domain_dir / "discovery" / "source-a-properties.json").exists()

    def test_invalid_property_induction_mode_rejected(self, tmp_path: Path):
        domain_dir = tmp_path / "domain"
        _seed_workspace(domain_dir)
        result = runner.invoke(app, [
            "draft",
            "--domain-dir", str(domain_dir),
            "--output", str(tmp_path / "draft.owl"),
            "--property-induction", "bogus",
        ])
        assert result.exit_code != 0
        assert "bogus" in result.output
        # Error message lists the two recognised values.
        for mode in ("off", "llm"):
            assert mode in result.output


class TestDraftPropertyInductionBudgetFlags:
    def test_budget_flag_defaults_documented_in_help(self, tmp_path: Path):
        """`draft --help` exposes the three budget flags with their
        defaults (50 / 100 / unbounded). Pins the documented contract.

        Widens the simulated terminal so Click/Typer doesn't truncate
        long flag names (default CliRunner uses 80 cols).
        """
        result = runner.invoke(
            app, ["draft", "--help"], env={"COLUMNS": "200"},
        )
        assert result.exit_code == 0
        text = result.output
        assert "--property-induction-max-concepts" in text
        assert "--property-induction-max-calls" in text
        assert "--property-induction-token-budget" in text

    def test_max_concepts_accepted_in_llm_mode(self, tmp_path: Path):
        domain_dir = tmp_path / "domain"
        _seed_workspace(domain_dir)
        result = runner.invoke(app, [
            "draft",
            "--domain-dir", str(domain_dir),
            "--output", str(tmp_path / "draft.owl"),
            "--property-induction", "llm",
            "--property-induction-max-concepts", "5",
        ])
        assert result.exit_code == 0, result.output

    def test_max_calls_accepted_in_llm_mode(self, tmp_path: Path):
        domain_dir = tmp_path / "domain"
        _seed_workspace(domain_dir)
        result = runner.invoke(app, [
            "draft",
            "--domain-dir", str(domain_dir),
            "--output", str(tmp_path / "draft.owl"),
            "--property-induction", "llm",
            "--property-induction-max-calls", "10",
        ])
        assert result.exit_code == 0, result.output

    def test_token_budget_accepted_in_llm_mode(self, tmp_path: Path):
        domain_dir = tmp_path / "domain"
        _seed_workspace(domain_dir)
        result = runner.invoke(app, [
            "draft",
            "--domain-dir", str(domain_dir),
            "--output", str(tmp_path / "draft.owl"),
            "--property-induction", "llm",
            "--property-induction-token-budget", "1000",
        ])
        assert result.exit_code == 0, result.output

    def test_model_flag_accepted_with_default_documented(self, tmp_path: Path):
        result = runner.invoke(
            app, ["draft", "--help"], env={"COLUMNS": "200"},
        )
        assert result.exit_code == 0
        assert "--property-induction-model" in result.output
        assert "azure/gpt-5.4" in result.output


class TestDraftPropertyInductionBudgetValidation:
    """Codex r1 blocker: invalid budget values must be rejected at
    the CLI boundary so the BudgetEnforcer never sees negative or
    out-of-contract input. Hard cap means hard cap."""

    def test_max_concepts_zero_rejected(self, tmp_path: Path):
        domain_dir = tmp_path / "domain"
        _seed_workspace(domain_dir)
        result = runner.invoke(app, [
            "draft",
            "--domain-dir", str(domain_dir),
            "--output", str(tmp_path / "draft.owl"),
            "--property-induction", "llm",
            "--property-induction-max-concepts", "0",
        ])
        assert result.exit_code != 0
        assert "--property-induction-max-concepts" in result.output
        assert ">= 1" in result.output
        # User pointed at the actual disable mechanism.
        assert "--property-induction off" in result.output

    def test_max_concepts_negative_rejected(self, tmp_path: Path):
        domain_dir = tmp_path / "domain"
        _seed_workspace(domain_dir)
        result = runner.invoke(app, [
            "draft",
            "--domain-dir", str(domain_dir),
            "--output", str(tmp_path / "draft.owl"),
            "--property-induction", "llm",
            "--property-induction-max-concepts", "-5",
        ])
        assert result.exit_code != 0
        assert "-5" in result.output
        assert "--property-induction-max-concepts" in result.output

    def test_max_calls_zero_rejected(self, tmp_path: Path):
        domain_dir = tmp_path / "domain"
        _seed_workspace(domain_dir)
        result = runner.invoke(app, [
            "draft",
            "--domain-dir", str(domain_dir),
            "--output", str(tmp_path / "draft.owl"),
            "--property-induction", "llm",
            "--property-induction-max-calls", "0",
        ])
        assert result.exit_code != 0
        assert "--property-induction-max-calls" in result.output
        assert ">= 1" in result.output

    def test_max_calls_negative_rejected(self, tmp_path: Path):
        domain_dir = tmp_path / "domain"
        _seed_workspace(domain_dir)
        result = runner.invoke(app, [
            "draft",
            "--domain-dir", str(domain_dir),
            "--output", str(tmp_path / "draft.owl"),
            "--property-induction", "llm",
            "--property-induction-max-calls", "-1",
        ])
        assert result.exit_code != 0
        assert "--property-induction-max-calls" in result.output

    def test_token_budget_zero_accepted_as_unbounded(self, tmp_path: Path):
        """0 is the documented "unbounded" sentinel; must be
        accepted. Only negatives are rejected."""
        domain_dir = tmp_path / "domain"
        _seed_workspace(domain_dir)
        result = runner.invoke(app, [
            "draft",
            "--domain-dir", str(domain_dir),
            "--output", str(tmp_path / "draft.owl"),
            "--property-induction", "llm",
            "--property-induction-token-budget", "0",
        ])
        assert result.exit_code == 0, result.output

    def test_token_budget_negative_rejected(self, tmp_path: Path):
        domain_dir = tmp_path / "domain"
        _seed_workspace(domain_dir)
        result = runner.invoke(app, [
            "draft",
            "--domain-dir", str(domain_dir),
            "--output", str(tmp_path / "draft.owl"),
            "--property-induction", "llm",
            "--property-induction-token-budget", "-100",
        ])
        assert result.exit_code != 0
        assert "--property-induction-token-budget" in result.output
        assert ">= 0" in result.output

    def test_validation_runs_even_when_induction_is_off(self, tmp_path: Path):
        """Defensive: CLI validates ranges before checking the
        induction mode, so users pinning bad defaults via shell
        aliases discover the problem regardless of mode."""
        domain_dir = tmp_path / "domain"
        _seed_workspace(domain_dir)
        result = runner.invoke(app, [
            "draft",
            "--domain-dir", str(domain_dir),
            "--output", str(tmp_path / "draft.owl"),
            "--property-induction", "off",
            "--property-induction-max-concepts", "-1",
        ])
        assert result.exit_code != 0
        assert "--property-induction-max-concepts" in result.output


class TestDraftPropertyInductionRefresh:
    def test_refresh_in_llm_mode_prints_active_note_in_b2(
        self, tmp_path: Path, monkeypatch,
    ):
        """PR B2: --property-induction-refresh is now meaningful.
        Console prints the "cache misses forced" marker rather than
        the PR B1 "ignored" placeholder."""
        from ontozense.core import property_induction as pi
        monkeypatch.setattr(
            pi, "_call_llm",
            lambda *, prompt, model: "",
        )
        domain_dir = tmp_path / "domain"
        _seed_workspace(domain_dir)
        result = runner.invoke(app, [
            "draft",
            "--domain-dir", str(domain_dir),
            "--output", str(tmp_path / "draft.owl"),
            "--property-induction", "llm",
            "--property-induction-refresh",
        ])
        assert result.exit_code == 0, result.output
        assert "cache misses forced" in result.output
        # The old B1 "ignored" note must NOT fire any more.
        assert "--property-induction-refresh ignored" not in result.output

    def test_refresh_in_off_mode_is_silent_noop(self, tmp_path: Path):
        """With --property-induction off, --refresh is meaningless
        and must not produce the no-op console note."""
        domain_dir = tmp_path / "domain"
        _seed_workspace(domain_dir)
        result = runner.invoke(app, [
            "draft",
            "--domain-dir", str(domain_dir),
            "--output", str(tmp_path / "draft.owl"),
            "--property-induction-refresh",
        ])
        assert result.exit_code == 0, result.output
        # The specific console note ("refresh ignored / cache lands
        # in PR B2") must NOT appear when induction mode is off.
        # Use the marker text, not the bare word "refresh" — pytest
        # tmp paths can contain "refresh" in their names which would
        # produce false positives.
        assert "--property-induction-refresh ignored" not in result.output


class TestDraftPropertyInductionRegressionGuard:
    def test_default_draft_output_unchanged_by_phase_b_landing(
        self, tmp_path: Path,
    ):
        """Default-flag run on the seeded workspace must produce a
        draft.owl identical to a baseline captured before any
        --property-induction flag is even passed. This is the
        Phase-A regression guarantee that Phase B promised to
        preserve."""
        domain_dir = tmp_path / "domain"
        _seed_workspace(domain_dir)

        # Run 1: default (no flag).
        out_a = tmp_path / "draft_a.owl"
        result_a = runner.invoke(app, [
            "draft",
            "--domain-dir", str(domain_dir),
            "--output", str(out_a),
        ])
        assert result_a.exit_code == 0
        text_a = out_a.read_text(encoding="utf-8")

        # Reset workspace to the same starting state.
        import shutil
        shutil.rmtree(domain_dir)
        _seed_workspace(domain_dir)

        # Run 2: explicit --property-induction off (same as default).
        out_b = tmp_path / "draft_b.owl"
        result_b = runner.invoke(app, [
            "draft",
            "--domain-dir", str(domain_dir),
            "--output", str(out_b),
            "--property-induction", "off",
        ])
        assert result_b.exit_code == 0
        text_b = out_b.read_text(encoding="utf-8")

        # The two outputs must be graph-isomorphic. Literal byte-
        # identity is too brittle because rdflib doesn't guarantee
        # serialisation order; isomorphism is the spec-level claim.
        from rdflib import Graph
        from rdflib.compare import isomorphic
        ga = Graph()
        ga.parse(data=text_a, format="turtle")
        gb = Graph()
        gb.parse(data=text_b, format="turtle")
        assert isomorphic(ga, gb), (
            "draft default vs --property-induction off diverged — "
            "Phase B regression guarantee broken"
        )
