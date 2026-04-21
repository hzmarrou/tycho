"""Windows encoding regression tests for the CLI.

The first reviewer-testability review (docs/REVIEW_2026-04-15.md)
flagged that several CLI commands emitted non-ASCII characters in
console output that crashed on Windows cp1252 terminals. These tests
exercise the affected paths in an environment that mimics the Windows
encoding issue so the failures would surface here, not in the tester's
terminal.

Strategy: wrap stdout/stderr in an encoder that matches cp1252 behaviour
(errors="strict" on a tight codec) and run CLI commands through it. If
any command emits a character that can't be encoded, the test fails.

This is a regression test — the fix commit replaces the problem
Unicode characters with ASCII equivalents (-> <-> v >= <= [!] [x] *)
and also calls sys.stdout.reconfigure(encoding="utf-8") at CLI entry
as a belt-and-suspenders defence.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from ontozense import cli
from ontozense.router import RoutingDecision, Source


runner = CliRunner()


def _has_dangerous_unicode(text: str) -> list[str]:
    """Return a list of characters in text that would crash cp1252."""
    dangerous = []
    for c in text:
        try:
            c.encode("cp1252")
        except UnicodeEncodeError:
            dangerous.append(c)
    return dangerous


class TestIngestOutputIsAscii:
    """`ingest --dry-run` must not emit chars that crash Windows cp1252."""

    def test_dry_run_output_is_cp1252_safe(self, tmp_path, monkeypatch):
        # Create a fake markdown file
        f = tmp_path / "doc.md"
        f.write_text("# Sample\n\nSome content.", encoding="utf-8")

        # Stub the router so the output comes from known fixtures
        decision = RoutingDecision(
            file_path=f,
            sources=[Source.A],
            confidence=0.95,
            layer="extension",
            reasoning="markdown extension",
        )

        from ontozense.router import Router
        monkeypatch.setattr(Router, "route", lambda self, p: decision)

        result = runner.invoke(cli.app, ["ingest", str(f), "--dry-run"])
        assert result.exit_code == 0, result.output

        dangerous = _has_dangerous_unicode(result.output)
        assert not dangerous, (
            f"ingest --dry-run output contains characters that crash "
            f"Windows cp1252: {set(dangerous)}. Output: {result.output!r}"
        )

    def test_skip_marker_is_ascii(self, tmp_path, monkeypatch):
        f = tmp_path / "readme.md"
        f.write_text("# README", encoding="utf-8")

        skip_decision = RoutingDecision(
            file_path=f,
            sources=[Source.SKIP],
            confidence=1.0,
            layer="extension",
            reasoning="readme filename",
        )

        from ontozense.router import Router
        monkeypatch.setattr(Router, "route", lambda self, p: skip_decision)

        result = runner.invoke(cli.app, ["ingest", str(f), "--dry-run"])
        assert result.exit_code == 0
        dangerous = _has_dangerous_unicode(result.output)
        assert not dangerous, (
            f"skip marker output has cp1252-unsafe chars: {set(dangerous)}"
        )


class TestIngestLowConfidenceMessageIsAscii:
    """The `--auto` low-confidence skip message must be cp1252-safe."""

    def test_low_conf_skip_message_is_ascii(self, tmp_path, monkeypatch):
        f = tmp_path / "low.md"
        f.write_text("# Content", encoding="utf-8")

        # Confidence below the default 0.9 threshold
        decision = RoutingDecision(
            file_path=f,
            sources=[Source.A],
            confidence=0.50,
            layer="extension",
            reasoning="uncertain",
        )

        from ontozense.router import Router
        monkeypatch.setattr(Router, "route", lambda self, p: decision)

        result = runner.invoke(cli.app, ["ingest", str(f), "--auto"])
        # Even though nothing dispatches, the output should render safely
        dangerous = _has_dangerous_unicode(result.output)
        assert not dangerous, (
            f"low-confidence skip output has cp1252-unsafe chars: {set(dangerous)}. "
            f"Output: {result.output!r}"
        )


class TestExtractAFailureMessagesAreAscii:
    """`extract-a` exit-code-2 and exit-code-3 messages must be cp1252-safe."""

    def _stub_extractor(self, monkeypatch, result):
        from ontozense.extractors import domain_doc_extractor as dde

        def _stub(self, path):
            result.source_documents = [str(path)]
            return result

        monkeypatch.setattr(dde.DomainDocumentExtractor, "extract_from_file", _stub)
        monkeypatch.setattr(cli, "_enrich_with_definitions", lambda r, d: (0, 0, 0))

    def test_zero_output_failure_message_ascii(self, tmp_path, monkeypatch):
        from ontozense.extractors.domain_doc_extractor import (
            DomainDocumentExtractionResult,
        )

        empty = DomainDocumentExtractionResult(domain_name="Test")
        self._stub_extractor(monkeypatch, empty)

        src = tmp_path / "source.md"
        src.write_text("# Source", encoding="utf-8")
        out_xlsx = tmp_path / "out.xlsx"

        result = runner.invoke(
            cli.app,
            [
                "extract-a", str(src),
                "--output", str(out_xlsx),
                "--skip-definitions-pass",
            ],
        )
        # Exit 2 = zero elements
        assert result.exit_code == 2, result.output
        dangerous = _has_dangerous_unicode(result.output)
        assert not dangerous, (
            f"exit-code-2 output has cp1252-unsafe chars: {set(dangerous)}. "
            f"Output: {result.output!r}"
        )

    def test_summary_high_mid_low_bands_ascii(self, tmp_path, monkeypatch):
        """The >=80% band label used to contain U+2265 which crashes cp1252."""
        from ontozense.extractors.domain_doc_extractor import (
            Concept,
            DomainDocumentExtractionResult,
            FieldConfidence,
            Provenance,
        )

        c = Concept(
            name="Test",
            definition="A definition.",
            confidence=[
                FieldConfidence("name", 0.95, "verbatim"),
                FieldConfidence("definition", 0.95, "verbatim"),
            ],
            provenance=Provenance(
                source_document="source.md",
                extraction_timestamp="2026-04-15T00:00:00",
            ),
        )
        r = DomainDocumentExtractionResult(domain_name="Test", concepts=[c])
        self._stub_extractor(monkeypatch, r)

        src = tmp_path / "source.md"
        src.write_text("# Source", encoding="utf-8")
        out_xlsx = tmp_path / "out.xlsx"

        result = runner.invoke(
            cli.app,
            [
                "extract-a", str(src),
                "--output", str(out_xlsx),
                "--skip-definitions-pass",
            ],
        )
        assert result.exit_code == 0, result.output
        dangerous = _has_dangerous_unicode(result.output)
        assert not dangerous, (
            f"summary output has cp1252-unsafe chars: {set(dangerous)}. "
            f"Output: {result.output!r}"
        )


class TestBridgingMarkdownIsAscii:
    """The suggest-bridges markdown output must be cp1252-safe."""

    def test_format_suggestions_markdown_is_ascii(self):
        from ontozense.core.bridging import (
            BridgeSuggestion,
            format_suggestions_markdown,
        )

        suggestions = [
            BridgeSuggestion(
                community_a=["A", "B"],
                community_b=["X", "Y"],
                suggested_concept="Bridge",
                suggested_relationships=["A -> Bridge"],
                rationale="Because.",
                raw_response="raw",
            ),
        ]
        md = format_suggestions_markdown(suggestions)
        dangerous = _has_dangerous_unicode(md)
        assert not dangerous, (
            f"format_suggestions_markdown emits cp1252-unsafe chars: "
            f"{set(dangerous)}. Markdown: {md!r}"
        )
