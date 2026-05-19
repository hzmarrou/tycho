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


def test_pipeline_dropna_multi_column_emits_one_rule_per_column(tmp_path):
    """dropna(subset=[multiple]) must emit one required-rule per column."""
    f = tmp_path / "p.py"
    f.write_text(
        "import pandas as pd\n"
        "def clean(df):\n"
        "    return df.dropna(subset=['a', 'b', 'c'])\n"
    )
    pm = parse_module(f)
    facts = list(extract_pipeline(pm))
    rules = [r for r in facts if isinstance(r, RuleFact) and r.predicate == "required"]
    assert {r.subject_attribute for r in rules} == {"a", "b", "c"}, (
        f"expected one required rule per column, got: {[r.subject_attribute for r in rules]}"
    )


def test_pipeline_non_dataframe_assign_does_not_trigger_derived_column(tmp_path):
    """Plain Python assignments like `x = 5` must not be interpreted as
    derived-column patterns."""
    f = tmp_path / "p.py"
    f.write_text(
        "import pandas as pd\n"
        "def helper():\n"
        "    x = 5\n"
        "    counter = x + 1\n"
        "    return counter\n"
    )
    pm = parse_module(f)
    facts = list(extract_pipeline(pm))
    attrs = [f for f in facts if isinstance(f, AttributeFact)]
    rules = [r for r in facts if isinstance(r, RuleFact) and r.rule_kind == "derivation"]
    assert attrs == [], f"plain assign should not produce AttributeFact: {attrs}"
    assert rules == [], f"plain assign should not produce derivation rule: {rules}"


def test_pipeline_dropna_without_subset_produces_no_rules(tmp_path):
    """df.dropna() without an explicit subset= kwarg has no column-level
    semantic -- must produce no rules."""
    f = tmp_path / "p.py"
    f.write_text(
        "import pandas as pd\n"
        "def clean(df):\n"
        "    return df.dropna()\n"
    )
    pm = parse_module(f)
    facts = list(extract_pipeline(pm))
    rules = [r for r in facts if isinstance(r, RuleFact)]
    assert rules == [], f"dropna without subset must produce no rules: {rules}"


def test_pipeline_boolean_mask_uses_direct_op_mapping(tmp_path):
    """Confirm pipeline_extractor's _CMP is NOT inverted: a `<= 100`
    mask must produce predicate 'lte', not 'gt' (which is what the
    model/procedural inverted mapping would emit)."""
    f = tmp_path / "p.py"
    f.write_text(
        "import pandas as pd\n"
        "def cap(df):\n"
        "    return df[df['score'] <= 100]\n"
    )
    pm = parse_module(f)
    facts = list(extract_pipeline(pm))
    rules = [r for r in facts if isinstance(r, RuleFact)]
    assert any(
        r.subject_attribute == "score" and r.predicate == "lte" and r.object_value == 100
        for r in rules
    ), f"expected score lte 100, got: {[(r.subject_attribute, r.predicate, r.object_value) for r in rules]}"


def test_pipeline_embedded_sql_where_emits_rule(tmp_path):
    f = tmp_path / "sql_embed.py"
    f.write_text(
        "import pandas as pd\n"
        "def load(con):\n"
        "    return pd.read_sql('SELECT * FROM loan WHERE amount > 0', con)\n"
    )
    pm = parse_module(f)
    facts = list(extract_pipeline(pm))
    rules = [r for r in facts if isinstance(r, RuleFact)]
    assert any(
        r.subject_entity == "loan" and r.subject_attribute == "amount"
        and r.predicate == "gt" and r.object_value == 0
        for r in rules
    )


def test_pipeline_non_sql_string_produces_no_rule(tmp_path):
    """A plain string literal that doesn't look like SQL must be
    silently skipped by the heuristic before sqlglot is called."""
    f = tmp_path / "p.py"
    f.write_text(
        "def greet():\n"
        "    msg = 'hello world this is not sql'\n"
        "    return msg\n"
    )
    pm = parse_module(f)
    facts = list(extract_pipeline(pm))
    rules = [r for r in facts if isinstance(r, RuleFact)]
    assert rules == []


def test_pipeline_malformed_sql_produces_no_rule(tmp_path):
    """A string that passes the keyword heuristic but fails sqlglot
    parsing must be silently skipped via the try/except guard."""
    f = tmp_path / "p.py"
    f.write_text(
        "def broken(con):\n"
        "    return con.execute('SELECT garbage no really not valid')\n"
    )
    pm = parse_module(f)
    facts = list(extract_pipeline(pm))
    rules = [r for r in facts if isinstance(r, RuleFact)]
    # No rules — extractor silently skips, doesn't crash.
    assert all(r.code_context != "embedded SQL WHERE" for r in rules)


def test_pipeline_sql_without_where_produces_no_rule(tmp_path):
    """SELECT with no WHERE clause has no extractable predicates."""
    f = tmp_path / "p.py"
    f.write_text(
        "def load(con):\n"
        "    return con.execute('SELECT amount FROM loan')\n"
    )
    pm = parse_module(f)
    facts = list(extract_pipeline(pm))
    rules = [r for r in facts if isinstance(r, RuleFact)]
    assert rules == []


def test_pipeline_sql_with_non_column_lhs_is_skipped(tmp_path):
    """WHERE 1 = 1 has a Literal LHS, not a Column — must be skipped
    (not silently converted into a phantom rule on a numeric column)."""
    f = tmp_path / "p.py"
    f.write_text(
        "def load(con):\n"
        "    return con.execute('SELECT * FROM loan WHERE 1 = 1')\n"
    )
    pm = parse_module(f)
    facts = list(extract_pipeline(pm))
    rules = [r for r in facts if isinstance(r, RuleFact)]
    assert all(r.code_context != "embedded SQL WHERE" for r in rules)


def test_pipeline_sql_with_multiple_where_predicates_emits_one_rule_per_predicate(tmp_path):
    """A WHERE clause with multiple simple comparisons (joined by AND/OR)
    must emit one rule per comparison."""
    f = tmp_path / "p.py"
    f.write_text(
        "def load(con):\n"
        "    return con.execute("
        "        'SELECT * FROM loan WHERE amount > 0 AND amount < 1000000'"
        "    )\n"
    )
    pm = parse_module(f)
    facts = list(extract_pipeline(pm))
    rules = [
        r for r in facts
        if isinstance(r, RuleFact)
        and r.subject_entity == "loan"
        and r.subject_attribute == "amount"
    ]
    predicates = {(r.predicate, r.object_value) for r in rules}
    assert ("gt", 0) in predicates, f"expected amount > 0, got {predicates}"
    assert ("lt", 1000000) in predicates, f"expected amount < 1000000, got {predicates}"
