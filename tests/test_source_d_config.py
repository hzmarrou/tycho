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
