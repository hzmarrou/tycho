"""CLI integration tests for the `ingest` command.

Covers the two safety invariants that the review flagged:
  1. --auto only dispatches decisions with confidence > 0.9 (PLAYBOOK §5)
  2. Multi-source routing is dispatched per decision.sources, not just
     primary_source — so a markdown file routed to A+D is sent to both
     legs, not just to A.

The tests monkeypatch the Router and extract_a function so they run
without touching OntoGPT, Azure, or the filesystem-heavy content sniff.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from ontozense import cli
from ontozense.router import RoutingDecision, Source


runner = CliRunner()


def _make_decision(
    path: Path,
    sources: list[Source],
    confidence: float,
    layer: str = "extension",
    reasoning: str = "test fixture",
) -> RoutingDecision:
    return RoutingDecision(
        file_path=path,
        sources=sources,
        confidence=confidence,
        layer=layer,
        reasoning=reasoning,
    )


@pytest.fixture
def stub_files(tmp_path: Path) -> dict[str, Path]:
    """Create real files on disk so the CLI path-existence check passes.
    The router is mocked, so content doesn't matter — only that the files
    exist and can be iterated.
    """
    files = {
        "high_a": tmp_path / "high_a.md",
        "high_multi": tmp_path / "multi.md",
        "low": tmp_path / "low_confidence.md",
        "b": tmp_path / "governance.csv",
    }
    for p in files.values():
        p.write_text("content", encoding="utf-8")
    return files


@pytest.fixture
def extract_a_recorder(monkeypatch):
    """Replace cli.extract_a with a recorder that captures the documents
    arg, so we can assert which files were actually dispatched.
    """
    calls: list[list[Path]] = []

    def _recorder(documents, **kwargs):
        calls.append(list(documents))

    monkeypatch.setattr(cli, "extract_a", _recorder)
    return calls


def _patch_router(monkeypatch, decisions: list[RoutingDecision]) -> None:
    """Replace Router.route so it returns decisions from a preloaded list
    keyed by file path. route_directory is also patched for completeness.
    """
    by_path = {d.file_path: d for d in decisions}

    def _route(self, path):
        return by_path[Path(path)]

    def _route_directory(self, path, recursive=True):  # noqa: ARG001
        return [d for d in decisions if d.file_path.parent == Path(path)]

    from ontozense.router import Router
    monkeypatch.setattr(Router, "route", _route)
    monkeypatch.setattr(Router, "route_directory", _route_directory)


# ─── Tests for --auto confidence gate (PLAYBOOK §5) ──────────────────────────


class TestAutoConfidenceGate:
    """--auto must only dispatch decisions with confidence > threshold."""

    def test_high_confidence_single_a_is_dispatched(
        self, stub_files, extract_a_recorder, monkeypatch
    ):
        decisions = [
            _make_decision(stub_files["high_a"], [Source.A], confidence=0.95),
        ]
        _patch_router(monkeypatch, decisions)

        result = runner.invoke(
            cli.app, ["ingest", str(stub_files["high_a"]), "--auto"]
        )
        assert result.exit_code == 0, result.output
        assert len(extract_a_recorder) == 1
        assert extract_a_recorder[0] == [stub_files["high_a"]]

    def test_low_confidence_is_not_dispatched(
        self, stub_files, extract_a_recorder, monkeypatch
    ):
        # confidence 0.80 is below default threshold 0.90 — must be skipped
        decisions = [
            _make_decision(stub_files["low"], [Source.A], confidence=0.80),
        ]
        _patch_router(monkeypatch, decisions)

        result = runner.invoke(
            cli.app, ["ingest", str(stub_files["low"]), "--auto"]
        )
        assert result.exit_code == 0, result.output
        assert len(extract_a_recorder) == 0, (
            "Low-confidence decision must NOT be auto-dispatched "
            "per PLAYBOOK §5 (confidence > 0.9 gate)"
        )
        # The skip reason should be visible in the output
        assert "Skipped" in result.output or "skipped" in result.output
        assert "low_confidence.md" in result.output

    def test_auto_threshold_flag_overrides_default(
        self, stub_files, extract_a_recorder, monkeypatch
    ):
        # With --auto-threshold 0.5, a 0.80-confidence decision should dispatch
        decisions = [
            _make_decision(stub_files["low"], [Source.A], confidence=0.80),
        ]
        _patch_router(monkeypatch, decisions)

        result = runner.invoke(
            cli.app,
            ["ingest", str(stub_files["low"]), "--auto", "--auto-threshold", "0.5"],
        )
        assert result.exit_code == 0, result.output
        assert len(extract_a_recorder) == 1
        assert extract_a_recorder[0] == [stub_files["low"]]

    def test_mixed_batch_dispatches_only_high_confidence(
        self, stub_files, extract_a_recorder, monkeypatch
    ):
        decisions = [
            _make_decision(stub_files["high_a"], [Source.A], confidence=0.95),
            _make_decision(stub_files["low"], [Source.A], confidence=0.60),
        ]
        _patch_router(monkeypatch, decisions)

        result = runner.invoke(
            cli.app,
            [
                "ingest",
                str(stub_files["high_a"]),
                str(stub_files["low"]),
                "--auto",
            ],
        )
        assert result.exit_code == 0, result.output
        assert len(extract_a_recorder) == 1
        # Only the high-confidence file reached extract_a
        assert extract_a_recorder[0] == [stub_files["high_a"]]
        assert "low_confidence.md" in result.output  # listed as skipped


# ─── Tests for multi-source dispatch ─────────────────────────────────────────


class TestMultiSourceDispatch:
    """A decision with sources=[A, D] must dispatch to BOTH legs, not just A."""

    def test_multi_source_a_plus_d_dispatches_a_leg(
        self, stub_files, extract_a_recorder, monkeypatch
    ):
        decisions = [
            _make_decision(
                stub_files["high_multi"],
                sources=[Source.A, Source.D],
                confidence=0.92,
                layer="content_sniff",
                reasoning="markdown with prose and code blocks",
            ),
        ]
        _patch_router(monkeypatch, decisions)

        result = runner.invoke(
            cli.app, ["ingest", str(stub_files["high_multi"]), "--auto"]
        )
        assert result.exit_code == 0, result.output
        # A leg: must actually run
        assert len(extract_a_recorder) == 1
        assert extract_a_recorder[0] == [stub_files["high_multi"]]
        # D leg: not wired yet, but must be reported to the user so they
        # know a leg was skipped (the worst failure mode is silent drop)
        assert "Source D" in result.output
        assert "multi.md" in result.output

    def test_multi_source_b_only_reports_not_wired(
        self, stub_files, extract_a_recorder, monkeypatch
    ):
        # Pure Source B routing — extract_a must NOT be called
        decisions = [
            _make_decision(stub_files["b"], [Source.B], confidence=0.95),
        ]
        _patch_router(monkeypatch, decisions)

        result = runner.invoke(
            cli.app, ["ingest", str(stub_files["b"]), "--auto"]
        )
        assert result.exit_code == 0, result.output
        assert len(extract_a_recorder) == 0
        assert "Source B" in result.output
        assert "not yet implemented" in result.output


# ─── Tests for dry-run and no-auto paths (regression) ────────────────────────


class TestDryRunAndDefault:
    """Dry-run and no-auto must never call extract_a."""

    def test_dry_run_never_dispatches(
        self, stub_files, extract_a_recorder, monkeypatch
    ):
        decisions = [
            _make_decision(stub_files["high_a"], [Source.A], confidence=0.99),
        ]
        _patch_router(monkeypatch, decisions)

        result = runner.invoke(
            cli.app, ["ingest", str(stub_files["high_a"]), "--dry-run", "--auto"]
        )
        assert result.exit_code == 0, result.output
        assert len(extract_a_recorder) == 0

    def test_default_mode_never_dispatches(
        self, stub_files, extract_a_recorder, monkeypatch
    ):
        decisions = [
            _make_decision(stub_files["high_a"], [Source.A], confidence=0.99),
        ]
        _patch_router(monkeypatch, decisions)

        result = runner.invoke(
            cli.app, ["ingest", str(stub_files["high_a"])]  # no --auto
        )
        assert result.exit_code == 0, result.output
        assert len(extract_a_recorder) == 0
        assert "--auto" in result.output  # hint to the user
