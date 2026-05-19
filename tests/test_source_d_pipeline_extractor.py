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
