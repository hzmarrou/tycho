from pathlib import Path

from ontozense.core.ingest.source_d.dispatch import select_families
from ontozense.core.ingest.source_d.parse import parse_module

FIXTURES = Path(__file__).parent / "fixtures" / "source_d"


def test_model_fixture_selects_model_family():
    pm = parse_module(FIXTURES / "model_fixture.py")
    fams = select_families(pm)
    assert "model" in fams


def test_pipeline_fixture_selects_pipeline_family():
    pm = parse_module(FIXTURES / "pipeline_fixture.py")
    fams = select_families(pm)
    assert "pipeline" in fams


def test_procedural_fixture_selects_procedural_family():
    pm = parse_module(FIXTURES / "procedural_fixture.py")
    fams = select_families(pm)
    assert "procedural" in fams


def test_module_with_class_and_pandas_selects_both(tmp_path):
    f = tmp_path / "hybrid.py"
    f.write_text(
        "import pandas as pd\n"
        "class Loan:\n"
        "    pass\n"
        "def step(df):\n"
        "    return df[df['x'] > 0]\n"
    )
    pm = parse_module(f)
    fams = select_families(pm)
    assert set(fams) >= {"model", "pipeline", "procedural"}


def test_sql_string_literal_selects_pipeline(tmp_path):
    """A module with embedded SQL but no pandas-like import must
    still trigger the pipeline family per spec §6.2."""
    f = tmp_path / "sql_only.py"
    f.write_text(
        "def load_loans(con):\n"
        "    return con.execute('SELECT * FROM loan WHERE amount > 0')\n"
    )
    pm = parse_module(f)
    fams = select_families(pm)
    assert "pipeline" in fams


def test_non_sql_string_does_not_trigger_pipeline(tmp_path):
    """Plain string literals must not false-positive into pipeline."""
    f = tmp_path / "plain.py"
    f.write_text(
        "def greet():\n"
        "    return 'hello world'\n"
    )
    pm = parse_module(f)
    fams = select_families(pm)
    assert "pipeline" not in fams
