from pathlib import Path

from ontozense.core.ingest.source_d.parse import parse_module

FIXTURES = Path(__file__).parent / "fixtures" / "source_d"


def test_parse_module_returns_ast_and_path():
    pm = parse_module(FIXTURES / "model_fixture.py")
    assert pm.path == FIXTURES / "model_fixture.py"
    assert pm.tree is not None


def test_parse_module_collects_top_level_classes():
    pm = parse_module(FIXTURES / "model_fixture.py")
    assert {"LoanStatus", "Borrower", "Loan"} <= set(pm.classes.keys())


def test_parse_module_collects_top_level_functions():
    pm = parse_module(FIXTURES / "procedural_fixture.py")
    assert {"validate_payment", "is_eligible"} <= set(pm.functions.keys())


def test_parse_module_records_imports():
    pm = parse_module(FIXTURES / "pipeline_fixture.py")
    assert "pandas" in pm.imports
