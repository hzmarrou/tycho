"""Acceptance regressions for Task 15 — production-path Source D pipeline."""
import re
from pathlib import Path

from ontozense.core.candidate_graph import build_candidate_graph
from ontozense.core.ingest.base import ArtifactKind
from ontozense.core.ingest.ingest_d import SourceDIngester
from ontozense.core.ingest.source_d.normalize import normalize_labels
from ontozense.core.ingest.source_d.rule_payload import canonical_rule_label, merge_key
from ontozense.core.ingest.source_d.rule_payload import merge_key as _mk

CD = Path(__file__).parent / "fixtures" / "source_d" / "cd_fusion"


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

    # AC5 also requires pipeline extractor to seed ATTRIBUTES.
    # `df["risk_band"] = df["score"]` is a derived-column assignment
    # that emits an AttributeFact for `risk_band`.
    pipe_attrs = [
        c for c in cands
        if c.artifact_kind == ArtifactKind.ATTRIBUTE
        and c.label == "risk_band"
    ]
    assert pipe_attrs, (
        "expected risk_band AttributeFact from pipeline derived-column "
        f"`df['risk_band'] = df['score']`; got attribute labels: "
        f"{[c.label for c in cands if c.artifact_kind == ArtifactKind.ATTRIBUTE]}"
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


# ---------------------------------------------------------------------------
# Task 19 — AC1a, AC10: C/D rule merge through structured identity
# ---------------------------------------------------------------------------

def test_ac1a_ac10_c_and_d_check_rules_merge_into_one_concept():
    """SQL `CHECK (amount > 0)` on table ``loan`` and Pydantic
    ``class Loan`` with ``if v <= 0: raise`` must produce a single
    CandidateConcept with both C and D attribution. merge_key
    normalizes the Python ``Loan`` to ``loan`` so they fuse despite
    the conventional naming split."""
    graph = build_candidate_graph(
        source_c={"files": [str(CD / "schema.sql")]},
        source_d={"files": [str(CD / "models.py")]},
    )

    target_payload = {
        "rule_kind": "validation",
        "subject_entity": "loan",
        "subject_attribute": "amount",
        "predicate": "gt",
        "object_value": 0,
        "condition": None,
    }
    target_label = canonical_rule_label(target_payload)
    target_key = merge_key(target_payload)

    matches = [
        c for c in graph.concepts
        if c.artifact_kind == "rule"
        and c.rule_payload
        and merge_key(c.rule_payload) == target_key
    ]
    assert len(matches) == 1, (
        f"expected exactly one merged rule for {target_label!r}; "
        f"got {len(matches)}: {[(c.label, c.rule_payload) for c in matches]}"
    )
    concept = matches[0]
    assert concept.source_presence["C"] is True
    assert concept.source_presence["D"] is True
    assert concept.source_counts["C"] >= 1
    assert concept.source_counts["D"] >= 1
    assert concept.rule_payload["predicate"] == "gt"


def test_ac1a_anchored_c_rule_does_not_swallow_unanchored_d_rule(tmp_path):
    """Anchoring is a fusion precondition. A C-derived NOT NULL rule
    (anchored to the `loan` table) must NOT silently fuse with a
    D-derived `required` rule from a procedural `dropna(subset=[...])`
    call that has no enclosing entity (subject_entity=None). Their
    merge_keys differ on subject_entity, so structured identity keeps
    them as two distinct concepts."""
    schema = tmp_path / "s.sql"
    schema.write_text(
        "CREATE TABLE loan (\n"
        "  loan_id VARCHAR(32) PRIMARY KEY,\n"
        "  borrower_id VARCHAR(32) NOT NULL\n"
        ");\n",
        encoding="utf-8",
    )
    code = tmp_path / "p.py"
    code.write_text(
        "import pandas as pd\n"
        "def clean(df):\n"
        "    return df.dropna(subset=['borrower_id'])\n",
        encoding="utf-8",
    )
    graph = build_candidate_graph(
        source_c={"files": [str(schema)]},
        source_d={"files": [str(code)]},
    )
    rule_concepts = [
        c for c in graph.concepts
        if c.artifact_kind == "rule"
        and c.rule_payload
        and c.rule_payload.get("subject_attribute") == "borrower_id"
        and c.rule_payload.get("predicate") == "required"
    ]
    by_entity = {c.rule_payload.get("subject_entity") for c in rule_concepts}
    assert "loan" in by_entity, "expected C-derived rule anchored to loan"
    assert None in by_entity, "expected D-derived unanchored rule preserved separately"


# ---------------------------------------------------------------------------
# Task 20 — AC4, AC8: Provenance and suppression audit
# ---------------------------------------------------------------------------

def test_ac4_unanchored_rules_go_to_audit_with_reason(tmp_path):
    """AC4: Rules with both subject_entity and subject_attribute = None
    are suppressed by the anchor layer with a 'unanchored:' reason."""
    f = tmp_path / "m.py"
    f.write_text(
        "def validate_thing():\n"
        "    return True\n",
        encoding="utf-8",
    )
    cands = list(SourceDIngester().ingest({"files": [str(f)]}))
    suppressed_rules = [c for c in cands if c.suppressed and c.artifact_kind == ArtifactKind.RULE]
    assert suppressed_rules, "expected at least one suppressed unanchored rule"
    assert suppressed_rules[0].suppression_reason
    assert "unanchored" in suppressed_rules[0].suppression_reason


def test_ac8_provenance_points_to_exact_line(tmp_path):
    """AC8: Rule candidates carry evidence_span with the exact line
    where the guard appears. The class body starts at line 1, the
    `if amount <= 0:` is at line 4."""
    f = tmp_path / "m.py"
    f.write_text(
        "class Loan:\n"
        "    amount: float\n"
        "    def __init__(self, amount):\n"
        "        if amount <= 0:\n"
        "            raise ValueError('positive')\n"
        "        self.amount = amount\n",
        encoding="utf-8",
    )
    cands = list(SourceDIngester().ingest({"files": [str(f)]}))
    rule = next(
        c for c in cands
        if c.artifact_kind == ArtifactKind.RULE
        and c.rule_payload and c.rule_payload["subject_attribute"] == "amount"
        and not c.suppressed
    )
    assert rule.source_artifact.endswith(":L4")
    assert rule.rule_payload["evidence_span"]["file"].endswith("m.py")
    assert rule.rule_payload["evidence_span"]["start_line"] == 4


# ---------------------------------------------------------------------------
# Task 21 — AC9: LLM-off behavior parity
# ---------------------------------------------------------------------------

class _NoopLLM:
    def rephrase(self, label, payload):
        return f"[REPHRASED] {label}"


def test_ac9_llm_off_preserves_rule_set():
    """AC9: Disabling the LLM normalize pass must leave the set of
    promoted (non-suppressed) rules unchanged. Identity is the
    structured merge_key, not the surface label."""
    cands_off = _run_hybrid()
    cands_on = list(normalize_labels(_run_hybrid(), llm=_NoopLLM()))

    def rule_keys(cands):
        return {
            _mk(c.rule_payload)
            for c in cands
            if c.artifact_kind == ArtifactKind.RULE and c.rule_payload and not c.suppressed
        }

    assert rule_keys(cands_off) == rule_keys(cands_on), (
        "LLM must not change merge identity — only labels"
    )
    on_labels = {c.label for c in cands_on if c.artifact_kind == ArtifactKind.RULE and not c.suppressed}
    assert any(l.startswith("[REPHRASED]") for l in on_labels), (
        "LLM was supposed to rephrase at least one label"
    )


# ---------------------------------------------------------------------------
# Task 22 — AC11: draft.owl emission untouched (structural pin)
# ---------------------------------------------------------------------------

def _resolve_owl_emitter_paths() -> list[Path]:
    """Return paths of modules in core/ that participate in OWL emission.

    Detected by an import or call referencing rdflib or the literal
    ``draft.owl``. The list is recomputed on each run so the test
    survives module moves.
    """
    core = Path(__file__).resolve().parents[1] / "src" / "ontozense" / "core"
    hits: list[Path] = []
    pat = re.compile(r"\bimport rdflib\b|\bfrom rdflib\b|draft\.owl")
    for p in core.rglob("*.py"):
        if pat.search(p.read_text(encoding="utf-8", errors="replace")):
            hits.append(p)
    assert hits, "expected at least one OWL emitter module under core/"
    return hits


def test_ac11_owl_emitter_modules_do_not_reference_rule_payload():
    """AC11: v1.2 must not extend draft.owl serialization. Any reference
    to rule_payload from an OWL-emitting module would mean the rule
    contract is leaking into ontology axioms, violating §11.2."""
    offenders: list[tuple[Path, int, str]] = []
    for p in _resolve_owl_emitter_paths():
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), start=1):
            stripped = line.strip()
            if stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("'''"):
                continue
            if "rule_payload" in stripped:
                offenders.append((p, i, stripped))
    assert not offenders, (
        "AC11 violation — rule_payload referenced in OWL emitter module(s):\n"
        + "\n".join(f"  {p}:L{ln}: {src}" for p, ln, src in offenders)
    )


def test_ac10_python_capitalized_class_fuses_with_sql_lowercase_table(tmp_path):
    """Real OO Python codebases use ``class Loan`` while SQL uses
    ``CREATE TABLE loan``. merge_key canonicalizes subject_entity so
    these still fuse into one CandidateConcept — without this
    normalization, every fusion across normal OO/SQL projects would
    silently produce duplicate rule concepts."""
    schema = tmp_path / "loans.sql"
    schema.write_text(
        "CREATE TABLE loan (\n"
        "  loan_id VARCHAR(32) PRIMARY KEY,\n"
        "  amount NUMERIC NOT NULL CHECK (amount > 0)\n"
        ");\n",
        encoding="utf-8",
    )
    code = tmp_path / "models.py"
    code.write_text(
        "from pydantic import BaseModel, field_validator\n"
        "\n"
        "class Loan(BaseModel):\n"
        "    amount: float\n"
        "\n"
        "    @field_validator('amount')\n"
        "    def positive(cls, v):\n"
        "        if v <= 0:\n"
        "            raise ValueError('amount must be positive')\n"
        "        return v\n",
        encoding="utf-8",
    )
    graph = build_candidate_graph(
        source_c={"files": [str(schema)]},
        source_d={"files": [str(code)]},
    )
    # Look for the rule by its merge_key — normalization makes
    # Python "Loan" match SQL "loan".
    target_key = merge_key({
        "rule_kind": "validation",
        "subject_entity": "loan",
        "subject_attribute": "amount",
        "predicate": "gt",
        "object_value": 0,
        "condition": None,
    })
    matches = [
        c for c in graph.concepts
        if c.artifact_kind == "rule"
        and c.rule_payload
        and merge_key(c.rule_payload) == target_key
    ]
    assert len(matches) == 1, (
        f"Loan/loan naming split must produce exactly ONE concept; "
        f"got {len(matches)}: {[(c.label, c.rule_payload.get('subject_entity')) for c in matches]}"
    )
    concept = matches[0]
    assert concept.source_presence["C"] is True, "C attribution missing"
    assert concept.source_presence["D"] is True, "D attribution missing"


def test_ac10_pluralized_sql_table_fuses_with_singular_python_class(tmp_path):
    """SQL conventions often pluralize table names (``loans``) while
    Python uses the singular (``Loan``). merge_key singularizes both
    so they fuse."""
    schema = tmp_path / "s.sql"
    schema.write_text(
        "CREATE TABLE loans (\n"
        "  loan_id VARCHAR(32) PRIMARY KEY,\n"
        "  amount NUMERIC NOT NULL CHECK (amount > 0)\n"
        ");\n",
        encoding="utf-8",
    )
    code = tmp_path / "m.py"
    code.write_text(
        "from pydantic import BaseModel, field_validator\n"
        "\n"
        "class Loan(BaseModel):\n"
        "    amount: float\n"
        "\n"
        "    @field_validator('amount')\n"
        "    def positive(cls, v):\n"
        "        if v <= 0:\n"
        "            raise ValueError\n"
        "        return v\n",
        encoding="utf-8",
    )
    graph = build_candidate_graph(
        source_c={"files": [str(schema)]},
        source_d={"files": [str(code)]},
    )
    target_key = merge_key({
        "rule_kind": "validation", "subject_entity": "loan",
        "subject_attribute": "amount", "predicate": "gt",
        "object_value": 0, "condition": None,
    })
    matches = [
        c for c in graph.concepts
        if c.artifact_kind == "rule"
        and c.rule_payload
        and merge_key(c.rule_payload) == target_key
    ]
    assert len(matches) == 1, (
        f"loans (plural)/Loan (singular) must fuse; got {len(matches)}: "
        f"{[(c.label, c.rule_payload.get('subject_entity')) for c in matches]}"
    )


def test_ac11_no_shacl_or_swrl_emitter_added():
    """AC11: v1.2 must not add a SHACL or SWRL emitter (§11.2)."""
    core = Path(__file__).resolve().parents[1] / "src" / "ontozense" / "core"
    banned = ("shacl", "swrl", "NodeShape", "PropertyShape", "swrl:Imp")
    offenders: list[tuple[Path, int, str]] = []
    for p in core.rglob("*.py"):
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), start=1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            for tok in banned:
                if tok in stripped:
                    offenders.append((p, i, stripped))
                    break
    assert not offenders, (
        "AC11 violation — SHACL/SWRL token introduced in core/:\n"
        + "\n".join(f"  {p}:L{ln}: {src}" for p, ln, src in offenders)
    )
