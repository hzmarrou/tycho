"""Acceptance regressions for Task 15 — production-path Source D pipeline."""
from pathlib import Path

from ontozense.core.ingest.ingest_d import SourceDIngester


def test_run_skips_non_utf8_python_file_without_raising(tmp_path: Path):
    """A single non-UTF-8 file in the manifest must not abort the
    whole Source D ingestion. v1.1 tolerated this; v1.2 must too.

    Bytes 0xff 0xfe are not a valid UTF-8 sequence; parse_module's
    strict utf-8 read raises UnicodeDecodeError, which run() must catch.
    """
    broken = tmp_path / "broken.py"
    broken.write_bytes(b"\xff\xfe # not utf-8\nclass Foo: pass\n")
    good = tmp_path / "good.py"
    good.write_text("class Bar:\n    name: str\n", encoding="utf-8")

    # Both files are passed in the same manifest. The broken file must
    # be skipped silently (with a log warning), and the good file must
    # still yield its candidates.
    cands = list(SourceDIngester().ingest({"files": [str(broken), str(good)]}))

    # The good file's class is still extracted.
    labels = {c.label for c in cands}
    assert "Bar" in labels, f"good file's class missing; got: {labels}"
    # The broken file produced nothing — no Foo.
    assert "Foo" not in labels


def test_run_skips_unparseable_python_without_raising(tmp_path: Path):
    """SyntaxError tolerance was already covered by test_unparseable_python_skipped
    in test_ingest_d.py, but pin it here too at the run() level so a
    future change to either path can't silently regress."""
    broken = tmp_path / "broken.py"
    broken.write_text("def def def syntax error\n", encoding="utf-8")
    good = tmp_path / "good.py"
    good.write_text("class Baz:\n    name: str\n", encoding="utf-8")

    cands = list(SourceDIngester().ingest({"files": [str(broken), str(good)]}))
    labels = {c.label for c in cands}
    assert "Baz" in labels


from ontozense.core.ingest.base import ArtifactKind


REPO = Path(__file__).parent / "fixtures" / "source_d" / "hybrid_repo"


def _run_hybrid():
    files = [str(p) for p in REPO.glob("*.py")]
    return list(SourceDIngester().ingest({"files": files}))


def test_ac2_each_family_contributes():
    """AC2 — Shape-adaptive extraction: a repo containing model + pipeline +
    procedural code must produce rules from every applicable family."""
    cands = _run_hybrid()
    families = {
        c.rule_payload.get("extractor_family") if c.rule_payload else None
        for c in cands
        if c.artifact_kind == ArtifactKind.RULE
    }
    assert "model" in families, f"missing model family rules; got: {families}"
    assert "pipeline" in families, f"missing pipeline family rules; got: {families}"
    assert "procedural" in families, f"missing procedural family rules; got: {families}"


def test_ac5_pipeline_entities_attributes_rules_without_classes():
    """AC5 — Pipeline support: pandas DataFrame code in pipeline.py (no
    classes) produces validation rules with the right subject_attribute."""
    cands = _run_hybrid()
    pipe_rules = [
        c for c in cands
        if c.artifact_kind == ArtifactKind.RULE
        and c.rule_payload and c.rule_payload["extractor_family"] == "pipeline"
    ]
    assert any(r.rule_payload["subject_attribute"] == "amount" for r in pipe_rules), (
        f"missing amount rule from boolean mask; got: {[r.rule_payload['subject_attribute'] for r in pipe_rules]}"
    )
    assert any(r.rule_payload["subject_attribute"] == "borrower_id" for r in pipe_rules), (
        f"missing borrower_id rule from dropna; got: {[r.rule_payload['subject_attribute'] for r in pipe_rules]}"
    )


def test_ac6_model_entities_attributes_vocab_behaviors_validations():
    """AC6 — Model parity: classes, attributes (entity-prefixed labels),
    enums (vocabulary), and inline validators (rules) all emitted from
    models.py."""
    cands = _run_hybrid()
    labels = {c.label for c in cands}
    # Entity
    assert "Loan" in labels, f"missing Loan entity; got labels: {sorted(labels)[:20]}..."
    # Vocabulary (Enum)
    assert "LoanStatus" in labels
    # Attribute (entity-prefixed per v1.2 wire format)
    assert any(
        c.artifact_kind == ArtifactKind.ATTRIBUTE and c.label == "Loan.amount"
        for c in cands
    ), f"missing Loan.amount attribute"
    # Inline validator rule
    assert any(
        c.artifact_kind == ArtifactKind.RULE
        and c.rule_payload and c.rule_payload["subject_entity"] == "Loan"
        and c.rule_payload["subject_attribute"] == "amount"
        for c in cands
    ), "missing inline validator rule on Loan.amount"


def test_ac7_procedural_rules_without_classes():
    """AC7 — Procedural support: validate_payment in procedural.py
    (no class context) produces both validation and defaulting rules."""
    cands = _run_hybrid()
    proc_rules = [
        c for c in cands
        if c.artifact_kind == ArtifactKind.RULE
        and c.rule_payload and c.rule_payload["extractor_family"] == "procedural"
    ]
    kinds = {r.rule_payload["rule_kind"] for r in proc_rules}
    assert "validation" in kinds, f"missing validation rule_kind; got: {kinds}"
    assert "defaulting" in kinds, f"missing defaulting rule_kind; got: {kinds}"
