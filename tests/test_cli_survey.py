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
        assert result.exit_code == 0, result.output
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
        assert result.exit_code == 0, result.output
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


class TestSurveyUniformInputShapes:
    """Spec §5.4: every --source-* flag accepts file, glob, OR
    directory uniformly. Codex round-1 review on Task 5 caught that
    glob expansion wasn't implemented and that Source C/D bypassed
    the expansion entirely. These tests pin both behaviours."""

    def test_survey_source_a_glob_pattern_expands(self, tmp_path: Path):
        """A quoted glob like 'docs/*.json' must be expanded internally
        by the CLI (the shell may not pre-expand it, especially on
        PowerShell). Each match should flow through to Source A."""
        sa_dir = tmp_path / "docs"
        sa_dir.mkdir()
        _write_source_a_json(
            sa_dir / "doc1.json",
            [{"name": "Borrower", "definition": "B"}],
        )
        _write_source_a_json(
            sa_dir / "doc2.json",
            [{"name": "Loan", "definition": "L"}],
        )
        # Pass a literal glob string (Path("docs/*.json") would not
        # exist as a file but the CLI should expand it).
        glob_pattern = str(sa_dir / "*.json")
        domain_dir = tmp_path / "domain"
        result = runner.invoke(app, [
            "survey",
            "--source-a", glob_pattern,
            "--domain-dir", str(domain_dir),
        ])
        assert result.exit_code == 0, result.output
        g = json.loads(
            (domain_dir / "discovery" / "candidate-graph.json")
            .read_text(encoding="utf-8")
        )
        labels = {c["label"] for c in g["concepts"]}
        assert {"Borrower", "Loan"}.issubset(labels)

    def test_survey_source_c_directory_expands(self, tmp_path: Path):
        """--source-c accepts a directory and walks for .json files."""
        sa = tmp_path / "source-a.json"
        _write_source_a_json(sa, [{"name": "Borrower", "definition": "B"}])
        c_dir = tmp_path / "schemas"
        c_dir.mkdir()
        # _load_source_passthrough expects JSON object payloads.
        (c_dir / "schema1.json").write_text(
            json.dumps({"opaque_payload": []}),
            encoding="utf-8",
        )
        domain_dir = tmp_path / "domain"
        result = runner.invoke(app, [
            "survey",
            "--source-a", str(sa),
            "--source-c", str(c_dir),
            "--domain-dir", str(domain_dir),
        ])
        # The command must succeed — Source C contents are accepted
        # without affecting candidate generation (forward-compat).
        assert result.exit_code == 0, result.output

    def test_survey_source_d_accepts_code_files(self, tmp_path: Path):
        """Spec §5.4: --source-d recognises .py / .sql / .js / .ts
        code files under the uniform file/glob/directory rule.

        Codex round-2 review on Task 5 caught that an earlier round
        narrowed Source D to .json only, which silently dropped
        actual code directories. This pins the broader extension
        set so a regression to .json-only is caught."""
        sa = tmp_path / "source-a.json"
        _write_source_a_json(sa, [{"name": "Borrower", "definition": "B"}])
        d_dir = tmp_path / "code"
        d_dir.mkdir()
        # A mix of supported Source D extensions.
        (d_dir / "classifier.py").write_text(
            "def classify(loan):\n    pass\n", encoding="utf-8",
        )
        (d_dir / "forbearance.sql").write_text(
            "SELECT * FROM loans WHERE status = 'forborne';\n",
            encoding="utf-8",
        )
        (d_dir / "rules.js").write_text(
            "function applyRule(loan) {}\n", encoding="utf-8",
        )
        domain_dir = tmp_path / "domain"
        result = runner.invoke(app, [
            "survey",
            "--source-a", str(sa),
            "--source-d", str(d_dir),
            "--domain-dir", str(domain_dir),
        ])
        # Survey must succeed — the contents are accepted without
        # affecting candidate generation (forward-compat).
        assert result.exit_code == 0, result.output
        # Source A's "Borrower" still surfaces normally.
        g = json.loads(
            (domain_dir / "discovery" / "candidate-graph.json")
            .read_text(encoding="utf-8")
        )
        labels = {c["label"] for c in g["concepts"]}
        assert "Borrower" in labels
