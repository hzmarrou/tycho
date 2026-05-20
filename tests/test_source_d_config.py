from pathlib import Path

from ontozense.core.ingest.base import ArtifactKind
from ontozense.core.ingest.source_d import run


def _write(tmp: Path, body: str) -> Path:
    p = tmp / "m.py"
    p.write_text(body, encoding="utf-8")
    return p


def test_rule_extractors_allowlist_restricts_families(tmp_path):
    p = _write(tmp_path,
        "class Loan:\n"
        "    amount: float\n"
        "def helper():\n"
        "    if 1 < 2: pass\n"
    )
    out = list(run(p, config={"rule_extractors": ["model"]}))
    kinds = {c.artifact_kind for c in out}
    assert ArtifactKind.ENTITY in kinds
    assert ArtifactKind.RULE not in kinds  # procedural skipped


def test_exclude_functions_skips_matching_functions(tmp_path):
    p = _write(tmp_path,
        "def validate_internal(x):\n"
        "    if x['a'] < 0: raise ValueError\n"
        "def validate_public(x):\n"
        "    if x['b'] < 0: raise ValueError\n"
    )
    out = list(run(p, config={"exclude_functions": ["*_internal"]}))
    rule_attrs = {c.rule_payload["subject_attribute"] for c in out if c.artifact_kind == ArtifactKind.RULE}
    assert "b" in rule_attrs
    assert "a" not in rule_attrs


def test_force_rule_marks_arbitrary_function(tmp_path):
    p = _write(tmp_path,
        "def compute_risk(x):\n"
        "    return x * 0.1\n"
    )
    out = list(run(p, config={"force_rule": ["compute_*"]}))
    # Anchor layer suppresses the weak fallback (subject_entity=None,
    # subject_attribute=None), but emit_candidates still yields it as
    # an audit-shell with suppressed=True. The test asserts the RULE
    # is present anywhere in the output (suppressed audit included).
    assert any(c.artifact_kind == ArtifactKind.RULE for c in out)


def test_force_rule_does_not_add_second_rule_when_structured_already_emitted(tmp_path):
    """force_rule is a FALLBACK enabler, not an override. If the
    function already yields structured rules, the weak fallback must
    NOT also fire."""
    p = _write(tmp_path,
        "def compute_risk(x):\n"
        "    if x['a'] <= 0:\n"
        "        raise ValueError('bad')\n"
        "    return x['a'] * 0.1\n"
    )
    out = list(run(p, config={"force_rule": ["compute_*"]}))
    rules = [c for c in out if c.artifact_kind == ArtifactKind.RULE]
    # Exactly one structured rule on 'a', no weak fallback.
    assert len(rules) == 1, f"expected exactly one rule, got: {[(r.label, r.suppressed) for r in rules]}"
    assert rules[0].rule_payload["subject_attribute"] == "a"
    assert rules[0].rule_payload["predicate"] in {"gt", "gte"}


def test_empty_or_absent_config_keys_are_noops(tmp_path):
    """Empty / absent exclude_functions / force_rule produce the same
    output as no config at all (no regression of the default extraction)."""
    p = _write(tmp_path,
        "def validate_amount(x):\n"
        "    if x['amount'] <= 0:\n"
        "        raise ValueError\n"
    )
    out_no_config = list(run(p, config=None))
    out_empty = list(run(p, config={"exclude_functions": [], "force_rule": []}))
    out_absent = list(run(p, config={}))
    # All three produce the same set of rule subject_attributes.
    def _subj_attrs(out):
        return {
            c.rule_payload["subject_attribute"]
            for c in out
            if c.artifact_kind == ArtifactKind.RULE and c.rule_payload
        }
    assert _subj_attrs(out_no_config) == _subj_attrs(out_empty) == _subj_attrs(out_absent)


def test_exclude_functions_takes_precedence_over_force_rule(tmp_path):
    """When a function matches BOTH exclude_functions and force_rule,
    exclude_functions wins (continue fires first, before the fallback
    is even evaluated)."""
    p = _write(tmp_path,
        "def compute_internal(x):\n"
        "    return x * 2\n"
    )
    out = list(run(p, config={
        "exclude_functions": ["*_internal"],
        "force_rule": ["compute_*"],
    }))
    # No rules at all — exclude_functions wins.
    rules = [c for c in out if c.artifact_kind == ArtifactKind.RULE]
    assert rules == [], f"exclude_functions must win over force_rule: {rules}"


def test_rule_extractors_empty_list_runs_no_families(tmp_path):
    """An explicitly empty rule_extractors list means 'run nothing',
    not 'run everything'. The allowlist contract is key-presence based:
    if the user sets the key, the filter applies — even if the list
    is empty (which is a sharp 'opt out of all extraction' signal)."""
    p = _write(tmp_path,
        "class Loan:\n"
        "    amount: float\n"
        "def validate_amount(x):\n"
        "    if x['amount'] <= 0:\n"
        "        raise ValueError\n"
    )
    out = list(run(p, config={"rule_extractors": []}))
    assert out == [], (
        f"empty rule_extractors must run no families; got {len(out)} candidates: "
        f"{[(c.label, c.artifact_kind) for c in out]}"
    )


def test_rule_extractors_none_value_runs_no_families(tmp_path):
    """rule_extractors: None is normalized to empty allowlist — same
    semantics as explicit empty list."""
    p = _write(tmp_path,
        "class Loan:\n"
        "    amount: float\n"
    )
    out = list(run(p, config={"rule_extractors": None}))
    assert out == []


def test_exclude_functions_case_insensitive(tmp_path):
    """glob_match is case-insensitive; exclude_functions: ["*_Internal"]
    must match validate_internal regardless of platform (was a Linux
    regression with raw fnmatch)."""
    p = _write(tmp_path,
        "def validate_internal(x):\n"
        "    if x['a'] <= 0:\n"
        "        raise ValueError\n"
        "def validate_public(x):\n"
        "    if x['b'] <= 0:\n"
        "        raise ValueError\n"
    )
    out = list(run(p, config={"exclude_functions": ["*_Internal"]}))
    rule_attrs = {
        c.rule_payload["subject_attribute"]
        for c in out
        if c.artifact_kind == ArtifactKind.RULE and c.rule_payload
    }
    assert "b" in rule_attrs
    assert "a" not in rule_attrs, "case-insensitive match must filter validate_internal"
