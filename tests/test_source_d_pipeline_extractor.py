from pathlib import Path

from ontozense.core.ingest.source_d.ir import AttributeFact, RuleFact
from ontozense.core.ingest.source_d.parse import parse_module
from ontozense.core.ingest.source_d.pipeline_extractor import extract_pipeline

FIXTURES = Path(__file__).parent / "fixtures" / "source_d"


def test_pipeline_boolean_mask_emits_validation_rule():
    pm = parse_module(FIXTURES / "pipeline_fixture.py")
    facts = list(extract_pipeline(pm))
    rules = [f for f in facts if isinstance(f, RuleFact)]
    assert any(
        r.subject_attribute == "amount" and r.predicate == "gt" and r.object_value == 0
        for r in rules
    ), f"got: {[(r.subject_attribute, r.predicate, r.object_value) for r in rules]}"


def test_pipeline_derived_column_emits_attribute_and_derivation():
    pm = parse_module(FIXTURES / "pipeline_fixture.py")
    facts = list(extract_pipeline(pm))
    attrs = [f for f in facts if isinstance(f, AttributeFact)]
    assert any(a.name == "risk_band" for a in attrs)
    rules = [f for f in facts if isinstance(f, RuleFact)]
    assert any(r.rule_kind == "derivation" and r.subject_attribute == "risk_band" for r in rules)


def test_pipeline_dropna_subset_emits_required_rule():
    pm = parse_module(FIXTURES / "pipeline_fixture.py")
    facts = list(extract_pipeline(pm))
    rules = [f for f in facts if isinstance(f, RuleFact)]
    assert any(
        r.subject_attribute == "borrower_id" and r.predicate == "required"
        for r in rules
    )
