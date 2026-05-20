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


def test_parse_module_does_not_collect_nested_classes(tmp_path):
    """Top-level-only walk: a class nested inside another class is
    NOT in pm.classes. Extractor families (Task 8+) walk into class
    bodies themselves."""
    src = tmp_path / "nested.py"
    src.write_text(
        "class Outer:\n"
        "    class Inner:\n"
        "        pass\n"
    )
    pm = parse_module(src)
    assert "Outer" in pm.classes
    assert "Inner" not in pm.classes


def test_parse_module_handles_empty_file(tmp_path):
    """A file with only a module docstring must parse without crashing
    and produce an empty symbol map."""
    src = tmp_path / "empty.py"
    src.write_text('"""Just a docstring."""\n')
    pm = parse_module(src)
    assert pm.classes == {}
    assert pm.functions == {}
    assert pm.imports == set()


def test_parse_module_skips_relative_imports(tmp_path):
    """`from . import x` has node.module=None and is silently skipped.
    No `""` or None entries should leak into pm.imports."""
    src = tmp_path / "rel.py"
    src.write_text(
        "from . import sibling\n"
        "from .pkg import other\n"
        "import pandas as pd\n"
    )
    pm = parse_module(src)
    # The "from . import x" case has node.module=None and is skipped.
    # The "from .pkg import other" case records "pkg" because
    # split('.')[0] of ".pkg" is "" — let's confirm exact behavior.
    assert "pandas" in pm.imports
    assert "" not in pm.imports
    assert None not in pm.imports
