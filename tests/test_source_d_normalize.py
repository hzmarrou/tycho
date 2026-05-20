from ontozense.core.ingest.base import ArtifactKind, IntermediateCandidate, Strength
from ontozense.core.ingest.source_d.normalize import normalize_labels


class _FakeLLM:
    def __init__(self, mapping):
        self.mapping = mapping
        self.calls = 0

    def rephrase(self, label: str, payload: dict) -> str:
        self.calls += 1
        return self.mapping.get(label, label)


def _rule_candidate(label: str, payload: dict) -> IntermediateCandidate:
    return IntermediateCandidate(
        label=label,
        definition=payload["expression"],
        source_type="D",
        source_artifact="x.py:L1",
        raw_type="rule:validation",
        eid="",
        artifact_kind=ArtifactKind.RULE,
        strength=Strength.STRONG,
        promotion_reason="test",
        rule_payload=payload,
    )


def _payload():
    return {
        "rule_kind": "validation", "subject_entity": "Loan", "subject_attribute": "amount",
        "predicate": "gt", "object_value": 0, "condition": None, "depends_on": [],
        "expression": "amount > 0",
        "evidence_span": {"file": "x.py", "start_line": 1, "end_line": 1, "snippet": ""},
        "code_context": "", "confidence": 0.9, "extractor_family": "model",
        "normalization_status": "deterministic",
    }


def test_normalize_off_is_noop():
    p = _payload()
    cand = _rule_candidate("Loan.amount gt 0", p)
    out = list(normalize_labels([cand], llm=None))
    assert out[0].label == "Loan.amount gt 0"
    assert out[0].rule_payload["normalization_status"] == "deterministic"


def test_normalize_on_rewrites_label_and_marks_payload():
    p = _payload()
    cand = _rule_candidate("Loan.amount gt 0", p)
    llm = _FakeLLM({"Loan.amount gt 0": "Loan amount must be positive"})
    out = list(normalize_labels([cand], llm=llm))
    assert out[0].label == "Loan amount must be positive"
    assert out[0].rule_payload["normalization_status"] == "llm_rephrased"
    assert llm.calls == 1


def test_normalize_only_touches_rule_candidates():
    p = _payload()
    rule_cand = _rule_candidate("Loan.amount gt 0", p)
    entity_cand = IntermediateCandidate(
        label="Loan", definition="", source_type="D", source_artifact="x.py:L1",
        raw_type="class", eid="",
        artifact_kind=ArtifactKind.ENTITY, strength=Strength.STRONG,
        promotion_reason="test",
    )
    llm = _FakeLLM({"Loan": "Loan (capitalized!)"})
    out = list(normalize_labels([rule_cand, entity_cand], llm=llm))
    assert out[1].label == "Loan"  # entity untouched
    assert llm.calls == 1  # only the rule was rephrased


from ontozense.core.candidate_graph import build_candidate_graph


def test_build_candidate_graph_threads_llm_to_source_d(tmp_path):
    src = tmp_path / "m.py"
    src.write_text(
        "class Loan:\n"
        "    amount: float\n"
        "    def __init__(self, amount):\n"
        "        if amount <= 0:\n"
        "            raise ValueError('positive')\n"
        "        self.amount = amount\n",
        encoding="utf-8",
    )
    llm = _FakeLLM({"Loan.amount gt 0": "Loan amount must be positive"})
    graph = build_candidate_graph(
        source_d={"files": [str(src)]},
        source_d_llm=llm,
    )
    rule_concepts = [c for c in graph.concepts if c.artifact_kind == "rule"]
    assert any(c.label == "Loan amount must be positive" for c in rule_concepts), (
        f"expected rephrased label among rule concepts; got: {[c.label for c in rule_concepts]}"
    )
    assert llm.calls >= 1
