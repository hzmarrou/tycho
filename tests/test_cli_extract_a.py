"""CLI integration tests for the `extract-a` command's failure-mode gates.

Covers the two PLAYBOOK §8 gates:
  - Exit code 2: zero elements extracted (refuses to write output)
  - Exit code 3: all elements have confidence < 0.5 (writes output anyway
    so the human can inspect it, but signals untrustworthiness)

The review flagged that the earlier gate checked concepts only, missing
the edge case where relationships exist but are all low-confidence (or
vice versa). The gate now covers the union of concepts + relationships.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from ontozense import cli
from ontozense.extractors.domain_doc_extractor import (
    Concept,
    DomainDocumentExtractionResult,
    FieldConfidence,
    Provenance,
    Relationship,
)


runner = CliRunner()


def _make_concept(name: str, confidence: float) -> Concept:
    c = Concept(name=name, definition=f"definition of {name}")
    c.confidence.append(FieldConfidence("name", confidence, "test"))
    c.confidence.append(FieldConfidence("definition", confidence, "test"))
    c.provenance = Provenance(
        source_document="test.md",
        source_section="",
        source_text_snippet="",
        extraction_timestamp="2026-04-10T00:00:00",
    )
    return c


def _make_relationship(
    subject: str, predicate: str, obj: str, confidence: float
) -> Relationship:
    r = Relationship(subject=subject, predicate=predicate, object=obj)
    r.confidence.append(FieldConfidence("triple", confidence, "test"))
    r.provenance = Provenance(
        source_document="test.md",
        source_section="",
        source_text_snippet="",
        extraction_timestamp="2026-04-10T00:00:00",
    )
    return r


@pytest.fixture
def source_doc(tmp_path: Path) -> Path:
    p = tmp_path / "source.md"
    p.write_text("# Source\n\nSome content.\n", encoding="utf-8")
    return p


def _patch_extractor(monkeypatch, result: DomainDocumentExtractionResult):
    """Replace DomainDocumentExtractor.extract_from_file with a stub that
    returns the given result, so the test doesn't invoke OntoGPT.
    """
    from ontozense.extractors import domain_doc_extractor as dde

    def _stub_extract(self, path):
        result.source_documents = [str(path)]
        return result

    monkeypatch.setattr(
        dde.DomainDocumentExtractor, "extract_from_file", _stub_extract
    )

    # Also short-circuit _enrich_with_definitions so the definitions
    # regex pass (which reads the actual file) doesn't interfere.
    def _no_enrich(result, doc):  # noqa: ARG001
        return 0, 0, 0

    monkeypatch.setattr(cli, "_enrich_with_definitions", _no_enrich)


class TestExitCode2ZeroElements:
    """PLAYBOOK §8: zero elements → exit code 2, no output written."""

    def test_zero_concepts_and_zero_relationships_exits_2(
        self, source_doc, tmp_path, monkeypatch
    ):
        result = DomainDocumentExtractionResult(
            domain_name="Test Domain",
            concepts=[],
            relationships=[],
        )
        _patch_extractor(monkeypatch, result)

        out_xlsx = tmp_path / "out.xlsx"
        r = runner.invoke(
            cli.app,
            [
                "extract-a",
                str(source_doc),
                "--output", str(out_xlsx),
                "--skip-definitions-pass",
            ],
        )
        assert r.exit_code == 2, r.output
        flat = " ".join(r.output.split())
        assert "0 concepts and 0 relationships" in flat
        # No output file should be written
        assert not out_xlsx.exists()


class TestExitCode3AllLowConfidence:
    """PLAYBOOK §8: all elements low confidence → exit code 3, write anyway."""

    def test_all_low_concepts_no_relationships_exits_3(
        self, source_doc, tmp_path, monkeypatch
    ):
        result = DomainDocumentExtractionResult(
            domain_name="Test Domain",
            concepts=[
                _make_concept("foo", confidence=0.3),
                _make_concept("bar", confidence=0.3),
            ],
            relationships=[],
        )
        _patch_extractor(monkeypatch, result)

        out_xlsx = tmp_path / "out.xlsx"
        r = runner.invoke(
            cli.app,
            [
                "extract-a",
                str(source_doc),
                "--output", str(out_xlsx),
                "--skip-definitions-pass",
            ],
        )
        assert r.exit_code == 3, r.output
        # Rich console wraps lines, so normalise whitespace before matching
        flat = " ".join(r.output.split())
        assert "confidence < 50%" in flat
        # Output IS written (for human inspection)
        assert out_xlsx.exists()

    def test_all_low_relationships_no_concepts_exits_3(
        self, source_doc, tmp_path, monkeypatch
    ):
        """Gate must cover relationships. Previously it checked concepts
        only and would have failed to exit 3 in this case.
        """
        result = DomainDocumentExtractionResult(
            domain_name="Test Domain",
            concepts=[],
            relationships=[
                _make_relationship("a", "rel", "b", confidence=0.30),
                _make_relationship("c", "rel", "d", confidence=0.30),
            ],
        )
        _patch_extractor(monkeypatch, result)

        out_xlsx = tmp_path / "out.xlsx"
        r = runner.invoke(
            cli.app,
            [
                "extract-a",
                str(source_doc),
                "--output", str(out_xlsx),
                "--skip-definitions-pass",
            ],
        )
        assert r.exit_code == 3, r.output
        # Rich console wraps lines, so normalise whitespace before matching
        flat = " ".join(r.output.split())
        assert "confidence < 50%" in flat
        assert out_xlsx.exists()

    def test_all_low_mix_concepts_and_relationships_exits_3(
        self, source_doc, tmp_path, monkeypatch
    ):
        result = DomainDocumentExtractionResult(
            domain_name="Test Domain",
            concepts=[_make_concept("foo", confidence=0.3)],
            relationships=[_make_relationship("a", "rel", "b", confidence=0.3)],
        )
        _patch_extractor(monkeypatch, result)

        out_xlsx = tmp_path / "out.xlsx"
        r = runner.invoke(
            cli.app,
            [
                "extract-a",
                str(source_doc),
                "--output", str(out_xlsx),
                "--skip-definitions-pass",
            ],
        )
        assert r.exit_code == 3, r.output

    def test_any_high_confidence_element_prevents_exit_3(
        self, source_doc, tmp_path, monkeypatch
    ):
        """One high-confidence element (concept OR relationship) is enough
        to make the gate pass with exit 0.
        """
        result = DomainDocumentExtractionResult(
            domain_name="Test Domain",
            concepts=[_make_concept("foo", confidence=0.3)],
            relationships=[
                _make_relationship("customer identifier", "is", "unique id", confidence=0.95),
            ],
        )
        _patch_extractor(monkeypatch, result)

        out_xlsx = tmp_path / "out.xlsx"
        r = runner.invoke(
            cli.app,
            [
                "extract-a",
                str(source_doc),
                "--output", str(out_xlsx),
                "--skip-definitions-pass",
            ],
        )
        assert r.exit_code == 0, r.output
        assert out_xlsx.exists()


class TestExtractionFailureHandling:
    """Review 2026-04-15 #6: extract-a must surface clean errors, not
    raw tracebacks, when OntoGPT/Azure/template failures happen."""

    def test_auth_error_produces_clean_message(
        self, source_doc, tmp_path, monkeypatch,
    ):
        """Azure auth failure should show a friendly message pointing
        at the .env variables, not a raw traceback."""
        from ontozense.extractors import domain_doc_extractor as dde

        def _fail(self, path):
            raise RuntimeError(
                "Azure OpenAI API authentication failed: invalid api_key"
            )

        monkeypatch.setattr(
            dde.DomainDocumentExtractor, "extract_from_file", _fail
        )
        monkeypatch.setattr(cli, "_enrich_with_definitions", lambda r, d: (0, 0, 0))

        out_xlsx = tmp_path / "out.xlsx"
        r = runner.invoke(
            cli.app,
            [
                "extract-a", str(source_doc),
                "--output", str(out_xlsx),
                "--skip-definitions-pass",
            ],
        )
        assert r.exit_code == 1, r.output
        flat = " ".join(r.output.split())
        # User-facing error, not a stack trace
        assert "Extraction failed" in flat
        assert "AZURE_API_KEY" in flat
        # Must not leak a Python traceback to the user
        assert "Traceback" not in r.output

    def test_ontogpt_subprocess_error_produces_clean_message(
        self, source_doc, tmp_path, monkeypatch,
    ):
        from ontozense.extractors import domain_doc_extractor as dde

        def _fail(self, path):
            raise FileNotFoundError(
                "ontogpt executable not found on PATH"
            )

        monkeypatch.setattr(
            dde.DomainDocumentExtractor, "extract_from_file", _fail
        )
        monkeypatch.setattr(cli, "_enrich_with_definitions", lambda r, d: (0, 0, 0))

        out_xlsx = tmp_path / "out.xlsx"
        r = runner.invoke(
            cli.app,
            [
                "extract-a", str(source_doc),
                "--output", str(out_xlsx),
                "--skip-definitions-pass",
            ],
        )
        assert r.exit_code == 1, r.output
        flat = " ".join(r.output.split())
        assert "Extraction failed" in flat
        assert "ontogpt" in flat.lower()
        assert "Traceback" not in r.output

    def test_generic_error_still_surfaces_type_and_message(
        self, source_doc, tmp_path, monkeypatch,
    ):
        """Unknown error type should still produce a user-facing message
        with the exception type and message, no raw traceback."""
        from ontozense.extractors import domain_doc_extractor as dde

        def _fail(self, path):
            raise ValueError("some unexpected error")

        monkeypatch.setattr(
            dde.DomainDocumentExtractor, "extract_from_file", _fail
        )
        monkeypatch.setattr(cli, "_enrich_with_definitions", lambda r, d: (0, 0, 0))

        out_xlsx = tmp_path / "out.xlsx"
        r = runner.invoke(
            cli.app,
            [
                "extract-a", str(source_doc),
                "--output", str(out_xlsx),
                "--skip-definitions-pass",
            ],
        )
        assert r.exit_code == 1, r.output
        flat = " ".join(r.output.split())
        assert "Extraction failed" in flat
        assert "ValueError" in flat
        assert "some unexpected error" in flat
        assert "Traceback" not in r.output
