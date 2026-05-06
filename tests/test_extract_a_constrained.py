"""Tests for Phase 2: constrained Source A extraction with --profile.

These tests focus on the profile-aware paths in DomainDocumentExtractor.
They mock the OntoGPT subprocess output so they run without network /
LLM calls — same pattern as test_domain_doc_extractor.py.

Backward compat is enforced by re-running the full suite — every test
in test_domain_doc_extractor.py must still pass byte-identical when
profile=None.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from ontozense.core.profile import load_profile
from ontozense.extractors.domain_doc_extractor import (
    Concept,
    DomainDocumentExtractor,
    DomainDocumentExtractionResult,
)


MINIMAL_PROFILE_DIR = (
    Path(__file__).parent / "fixtures" / "profiles" / "minimal"
)

ESG_PROFILE_DIR = (
    Path(__file__).parent.parent / "docs" / "profile-examples" / "esg"
)


# ─── OntoGPT output fixtures (3-part format used in profile mode) ─────────────


def _profile_mode_ontogpt_output() -> str:
    """Realistic raw_completion_output for the minimal profile.

    Concepts use the 3-part `name :: TYPE :: definition` format that the
    profile-aware template asks for.
    """
    return (
        '{\n'
        '  "extracted_object": {\n'
        '    "domain_name": "Test Domain",\n'
        '    "concepts": [],\n'
        '    "relationships": []\n'
        '  },\n'
        '  "raw_completion_output": "domain_name: Test Domain\\n'
        'concepts:\\n'
        '  - Customer Identifier :: Concept :: A unique identifier for a customer.\\n'
        '  - Validation Rule :: Rule :: A rule that constrains data input.\\n'
        '  - co1 :: Concept :: Maps to canonical via alias_map.\\n'
        'relationships:\\n'
        '  - Validation Rule -> applies to -> Customer Identifier\\n'
        '  - Validation Rule -> governs -> Customer Identifier\\n"\n'
        '}'
    )


def _unconstrained_mode_ontogpt_output() -> str:
    """OntoGPT output that uses the 2-part format (no profile).

    Backward-compat sanity: the same parser must still accept this when
    profile=None.
    """
    return (
        '{\n'
        '  "extracted_object": {\n'
        '    "domain_name": "Test Domain",\n'
        '    "concepts": [],\n'
        '    "relationships": []\n'
        '  },\n'
        '  "raw_completion_output": "domain_name: Test Domain\\n'
        'concepts:\\n'
        '  - Customer Identifier :: A unique identifier for a customer.\\n'
        'relationships:\\n'
        '  - Customer Identifier -> identifies -> Customer Record\\n"\n'
        '}'
    )


@pytest.fixture
def source_doc(tmp_path: Path) -> Path:
    """A small markdown source document for snippet anchoring."""
    p = tmp_path / "source.md"
    p.write_text(
        "# Test domain\n\n"
        "## Customer\n"
        "Customer Identifier: A unique identifier for a customer.\n"
        "Validation Rule: A rule that constrains data input.\n",
        encoding="utf-8",
    )
    return p


# ─── Profile-aware constructor ───────────────────────────────────────────────


class TestExtractorConstruction:
    def test_no_profile_constructor_uses_default_template(self):
        """Without profile, extractor uses bundled template (unchanged)."""
        ext = DomainDocumentExtractor()
        assert ext.profile is None
        assert "domain_doc_extraction.yaml" in str(ext.template_path)

    def test_profile_constructor_generates_template(self):
        """With profile, extractor generates a temp template embedding the
        profile's prompt fragment + allowed types + allowed predicates."""
        profile = load_profile(MINIMAL_PROFILE_DIR)
        ext = DomainDocumentExtractor(profile=profile)
        assert ext.profile is not None
        assert ext.template_path.exists()
        # Generated template name reflects the profile
        assert "minimal" in ext.template_path.name.lower()

        # Generated template must mention the profile's entity types and
        # predicates so the LLM sees them in its prompt context.
        content = ext.template_path.read_text(encoding="utf-8")
        assert "Concept" in content
        assert "Rule" in content
        assert "AppliesTo" in content

    def test_profile_constructor_with_explicit_template_overrides(self, tmp_path):
        """If user passes both profile AND template_path, the explicit
        template wins. Useful for power users."""
        profile = load_profile(MINIMAL_PROFILE_DIR)
        custom = tmp_path / "custom.yaml"
        custom.write_text(
            "id: x\nname: x\nclasses: {}\n", encoding="utf-8"
        )
        ext = DomainDocumentExtractor(
            profile=profile, template_path=str(custom)
        )
        assert ext.template_path == custom


# ─── Constrained extraction end-to-end ──────────────────────────────────────


class TestConstrainedExtraction:
    def test_concepts_get_deterministic_ids(self, source_doc):
        profile = load_profile(MINIMAL_PROFILE_DIR)
        ext = DomainDocumentExtractor(profile=profile)
        with patch.object(
            ext._ontogpt, "_run_ontogpt",
            return_value=_profile_mode_ontogpt_output(),
        ):
            result = ext.extract_from_file(source_doc)

        assert len(result.concepts) >= 2
        for c in result.concepts:
            assert c.id, (
                f"Concept {c.name!r} must have a deterministic ID in "
                "profile mode (got empty)"
            )
            # IDs must follow the type_label_hash format
            assert c.id.startswith(c.entity_type.lower() + "_"), (
                f"ID {c.id!r} should start with type prefix"
            )

    def test_alias_map_resolves_concept_names(self, source_doc):
        """The minimal profile maps 'co1' -> 'Concept One'. After
        constrained extraction, the LLM-emitted 'co1' concept should
        appear with the canonical name 'Concept One'."""
        profile = load_profile(MINIMAL_PROFILE_DIR)
        ext = DomainDocumentExtractor(profile=profile)
        with patch.object(
            ext._ontogpt, "_run_ontogpt",
            return_value=_profile_mode_ontogpt_output(),
        ):
            result = ext.extract_from_file(source_doc)

        names = [c.name for c in result.concepts]
        assert "Concept One" in names, (
            f"Alias 'co1' should resolve to 'Concept One', got {names}"
        )
        assert "co1" not in names, (
            "Alias 'co1' should be replaced by the canonical name"
        )

    def test_canonical_verbs_canonicalise_predicates(self, source_doc):
        """The minimal profile maps 'applies to' and 'governs' to
        'AppliesTo'. After constrained extraction, both predicates should
        be canonicalised."""
        profile = load_profile(MINIMAL_PROFILE_DIR)
        ext = DomainDocumentExtractor(profile=profile)
        with patch.object(
            ext._ontogpt, "_run_ontogpt",
            return_value=_profile_mode_ontogpt_output(),
        ):
            result = ext.extract_from_file(source_doc)

        predicates = [r.predicate for r in result.relationships]
        # Both 'applies to' and 'governs' should canonicalise to 'AppliesTo'
        assert all(p == "AppliesTo" for p in predicates), (
            f"Expected all predicates canonicalised to 'AppliesTo', got {predicates}"
        )

    def test_extraction_metadata_populated(self, source_doc):
        """Result carries profile_name, profile_version, extraction_mode
        when profile is set."""
        profile = load_profile(MINIMAL_PROFILE_DIR)
        ext = DomainDocumentExtractor(profile=profile)
        with patch.object(
            ext._ontogpt, "_run_ontogpt",
            return_value=_profile_mode_ontogpt_output(),
        ):
            result = ext.extract_from_file(source_doc)

        assert result.extraction_mode == "constrained"
        assert result.profile_name == "minimal"
        assert result.profile_version == "1.0.0"

    def test_entity_type_parsed_from_3_part_format(self, source_doc):
        profile = load_profile(MINIMAL_PROFILE_DIR)
        ext = DomainDocumentExtractor(profile=profile)
        with patch.object(
            ext._ontogpt, "_run_ontogpt",
            return_value=_profile_mode_ontogpt_output(),
        ):
            result = ext.extract_from_file(source_doc)

        # We expect 'Customer Identifier' to be type Concept
        ci = result.get_concept("Customer Identifier")
        assert ci is not None
        assert ci.entity_type == "Concept"

        # And 'Validation Rule' to be type Rule
        vr = result.get_concept("Validation Rule")
        assert vr is not None
        assert vr.entity_type == "Rule"

    def test_get_concept_by_id_works(self, source_doc):
        profile = load_profile(MINIMAL_PROFILE_DIR)
        ext = DomainDocumentExtractor(profile=profile)
        with patch.object(
            ext._ontogpt, "_run_ontogpt",
            return_value=_profile_mode_ontogpt_output(),
        ):
            result = ext.extract_from_file(source_doc)

        first = result.concepts[0]
        looked_up = result.get_concept_by_id(first.id)
        assert looked_up is first


# ─── Backward compatibility (no profile = unchanged) ────────────────────────


class TestUnconstrainedUnchanged:
    """When profile=None, every output field that didn't exist in
    Phase 1 must still be empty (id, entity_type, extraction_mode,
    profile_name, profile_version). This ensures existing fusion / lint
    code that reads the result doesn't see surprising new state."""

    def test_no_profile_concepts_have_empty_id(self, source_doc):
        ext = DomainDocumentExtractor()  # no profile
        with patch.object(
            ext._ontogpt, "_run_ontogpt",
            return_value=_unconstrained_mode_ontogpt_output(),
        ):
            result = ext.extract_from_file(source_doc)

        for c in result.concepts:
            assert c.id == "", (
                f"Unconstrained mode must leave id empty (got {c.id!r})"
            )
            assert c.entity_type == "", (
                f"Unconstrained mode must leave entity_type empty "
                f"(got {c.entity_type!r})"
            )

    def test_no_profile_result_metadata_empty(self, source_doc):
        ext = DomainDocumentExtractor()
        with patch.object(
            ext._ontogpt, "_run_ontogpt",
            return_value=_unconstrained_mode_ontogpt_output(),
        ):
            result = ext.extract_from_file(source_doc)

        assert result.extraction_mode == ""
        assert result.profile_name == ""
        assert result.profile_version == ""

    def test_no_profile_predicates_unchanged(self, source_doc):
        """Predicates are NOT canonicalised in unconstrained mode."""
        ext = DomainDocumentExtractor()
        with patch.object(
            ext._ontogpt, "_run_ontogpt",
            return_value=_unconstrained_mode_ontogpt_output(),
        ):
            result = ext.extract_from_file(source_doc)

        # The original "identifies" predicate should remain unchanged
        predicates = [r.predicate for r in result.relationships]
        assert "identifies" in predicates


# ─── ESG reference profile sanity ──────────────────────────────────────────


class TestEsgProfile:
    """Smoke tests against the shipped ESG reference profile."""

    def test_esg_template_generation(self, source_doc):
        if not ESG_PROFILE_DIR.exists():
            pytest.skip("ESG reference profile not found")
        profile = load_profile(ESG_PROFILE_DIR)
        ext = DomainDocumentExtractor(profile=profile)

        content = ext.template_path.read_text(encoding="utf-8")
        # Must include all 5 ESG entity types in the prompt context
        for t in ["Industry", "ReportingFramework", "Category", "Metric", "Model"]:
            assert t in content
        # Must include all 5 ESG predicates
        for p in ["ReportUsing", "Include", "ConsistOf", "IsCalculatedBy", "RequiresInputFrom"]:
            assert p in content

    def test_esg_alias_resolution_at_extraction(self, source_doc):
        """The ESG profile maps 'carbon emissions' -> 'GHG Emissions'.
        Verify the canonical name flows through extraction."""
        if not ESG_PROFILE_DIR.exists():
            pytest.skip("ESG reference profile not found")
        profile = load_profile(ESG_PROFILE_DIR)
        ext = DomainDocumentExtractor(profile=profile)

        # Mock OntoGPT to emit a concept with an alias-mapped name
        mock_output = (
            '{\n'
            '  "extracted_object": {"domain_name": "ESG", "concepts": [], "relationships": []},\n'
            '  "raw_completion_output": "domain_name: ESG\\n'
            'concepts:\\n  - carbon emissions :: Metric :: Total GHG output.\\n"\n'
            '}'
        )
        with patch.object(
            ext._ontogpt, "_run_ontogpt", return_value=mock_output,
        ):
            result = ext.extract_from_file(source_doc)

        names = [c.name for c in result.concepts]
        assert "GHG Emissions" in names, (
            f"ESG profile should canonicalise 'carbon emissions' to "
            f"'GHG Emissions', got {names}"
        )


# ─── CLI integration ────────────────────────────────────────────────────────


class TestCliConstrainedFlow:
    """Smoke test the --profile flag end-to-end via Typer."""

    def test_invalid_profile_path_clean_error(self, tmp_path):
        from typer.testing import CliRunner
        from ontozense import cli

        runner = CliRunner()
        src = tmp_path / "doc.md"
        src.write_text("# Doc\n", encoding="utf-8")
        bogus = tmp_path / "nonexistent_profile"

        r = runner.invoke(
            cli.app,
            [
                "extract-a", str(src),
                "--profile", str(bogus),
                "--skip-definitions-pass",
            ],
        )
        # Clean user-facing error, no traceback
        assert r.exit_code == 1
        flat = " ".join(r.output.split())
        assert "Profile load failed" in flat
        assert "Traceback" not in r.output

    def test_no_profile_prints_unconstrained_mode(self, tmp_path, monkeypatch):
        """Without --profile, CLI prints 'Mode: unconstrained' and runs
        the legacy path. Mock the extractor so we don't hit OntoGPT."""
        from typer.testing import CliRunner
        from ontozense import cli
        from ontozense.extractors import domain_doc_extractor as dde

        runner = CliRunner()
        src = tmp_path / "doc.md"
        src.write_text("# Doc\n", encoding="utf-8")

        # Stub the extractor so the CLI completes. Concept needs a
        # populated confidence score above 0.5 to avoid the exit-3
        # all-low-confidence gate (PLAYBOOK §8).
        from ontozense.extractors.domain_doc_extractor import (
            FieldConfidence,
            Provenance,
        )

        def _stub(self, path):
            c = Concept(
                name="X",
                definition="A test concept.",
                confidence=[
                    FieldConfidence("name", 0.95, "verbatim"),
                    FieldConfidence("definition", 0.95, "verbatim"),
                ],
                provenance=Provenance(
                    source_document=str(path),
                    extraction_timestamp="2026-05-06T00:00:00",
                ),
            )
            r = DomainDocumentExtractionResult(
                domain_name="Test", concepts=[c],
            )
            r.source_documents = [str(path)]
            return r
        monkeypatch.setattr(dde.DomainDocumentExtractor, "extract_from_file", _stub)
        monkeypatch.setattr(cli, "_enrich_with_definitions", lambda r, d: (0, 0, 0))

        r = runner.invoke(
            cli.app,
            [
                "extract-a", str(src),
                "--output", str(tmp_path / "out.xlsx"),
                "--skip-definitions-pass",
            ],
        )
        assert r.exit_code == 0
        flat = " ".join(r.output.split())
        assert "Mode: unconstrained" in flat
