"""Tests for Django schema parser and schema-based ontology refinement."""

from __future__ import annotations

from pathlib import Path

import pytest

OPENNPL_DIR = Path(r"C:\Users\hzmarrou\OneDrive\python\projects\openNPL\npl_portfolio")


@pytest.fixture
def schema():
    from ontozense.extractors.django_schema import DjangoSchemaParser
    if not OPENNPL_DIR.exists():
        pytest.skip("OpenNPL not cloned")
    return DjangoSchemaParser(OPENNPL_DIR).parse()


@pytest.fixture
def extraction():
    from ontozense.extractors.ontogpt_extractor import load_existing_extraction
    path = Path(r"C:\Users\hzmarrou\OneDrive\python\learning\ontogpt\scenario\npl\d403-combined-extraction.json")
    if not path.exists():
        pytest.skip("Extraction JSON not found")
    return load_existing_extraction(path)


class TestDjangoSchemaParser:
    def test_parses_all_models(self, schema):
        model_names = {m.name for m in schema.models}
        expected = {"Loan", "Counterparty", "Forbearance", "Enforcement",
                    "PropertyCollateral", "NonPropertyCollateral", "ExternalCollection",
                    "CounterpartyGroup", "Portfolio", "PortfolioSnapshot"}
        assert expected.issubset(model_names)

    def test_loan_has_fields(self, schema):
        loan = schema.get_model("Loan")
        assert loan is not None
        assert len(loan.fields) > 50  # Loan has ~109 fields
        field_names = {f.name for f in loan.fields}
        assert "contract_identifier" in field_names
        assert "instrument_identifier" in field_names

    def test_loan_has_counterparty_fk(self, schema):
        loan = schema.get_model("Loan")
        assert loan is not None
        fk_targets = {r.to_model for r in loan.relationships}
        assert "Counterparty" in fk_targets

    def test_enum_choices_resolved(self, schema):
        loan = schema.get_model("Loan")
        assert loan is not None
        enum_fields = [f for f in loan.fields if f.playground_type == "enum"]
        assert len(enum_fields) > 5
        # Check one specific enum
        asset_class = next((f for f in enum_fields if f.name == "asset_class"), None)
        assert asset_class is not None
        assert "Resi" in asset_class.choices_values

    def test_field_types_mapped(self, schema):
        loan = schema.get_model("Loan")
        assert loan is not None
        types = {f.playground_type for f in loan.fields}
        assert "string" in types
        assert "integer" in types

    def test_forbearance_has_two_fks(self, schema):
        forbearance = schema.get_model("Forbearance")
        assert forbearance is not None
        fk_targets = {r.to_model for r in forbearance.relationships}
        assert "Loan" in fk_targets
        assert "Counterparty" in fk_targets


class TestSchemaRefiner:
    def test_refinement_produces_valid_playground_format(self, schema, extraction):
        from ontozense.core.schema_refiner import SchemaRefiner

        refiner = SchemaRefiner(schema, extraction)
        ontology, report = refiner.refine()

        ont = ontology["ontology"]
        assert len(ont["entityTypes"]) == 10  # All schema models become entities
        assert len(ont["relationships"]) == 13  # All FKs become relationships

        for et in ont["entityTypes"]:
            assert "id" in et
            assert "name" in et
            assert "properties" in et
            assert "icon" in et
            assert "color" in et
            assert len(et["properties"]) >= 1
            has_id = any(p.get("isIdentifier") for p in et["properties"])
            assert has_id, f"{et['name']} missing identifier"

    def test_matching_finds_key_entities(self, schema, extraction):
        from ontozense.core.schema_refiner import SchemaRefiner

        refiner = SchemaRefiner(schema, extraction)
        _, report = refiner.refine()

        matched_models = {m for _, m in report.matched_entities}
        assert "loan" in matched_models or "Loan" in matched_models
        assert "forbearance" in matched_models or "Forbearance" in matched_models

    def test_enums_populated(self, schema, extraction):
        from ontozense.core.schema_refiner import SchemaRefiner

        refiner = SchemaRefiner(schema, extraction)
        _, report = refiner.refine()

        assert report.enums_populated > 20  # Many choice fields across models

    def test_compared_to_unrefined(self, schema, extraction):
        """Refined ontology should be much smaller than raw extraction."""
        from ontozense.core.schema_refiner import SchemaRefiner
        from ontozense.extractors.ontogpt_extractor import OntoGPTExtractor
        from ontozense.exporters import PlaygroundExporter

        # Unrefined: raw extraction
        extractor = OntoGPTExtractor()
        mgr = extractor.to_manager(extraction)
        unrefined = PlaygroundExporter(mgr).export()

        # Refined: schema-grounded
        refiner = SchemaRefiner(schema, extraction)
        refined, _ = refiner.refine()

        unrefined_count = len(unrefined["ontology"]["entityTypes"])
        refined_count = len(refined["ontology"]["entityTypes"])

        # Refined should have far fewer entities (10 vs 114)
        assert refined_count < unrefined_count
        # But refined entities have real properties from schema
        refined_props = sum(len(et["properties"]) for et in refined["ontology"]["entityTypes"])
        assert refined_props > 300  # Schema has ~400 columns
