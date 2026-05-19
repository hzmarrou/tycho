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
