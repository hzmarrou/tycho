"""End-to-end acceptance test for v1.2.1 rich extraction against the
NPL demo fixtures at domains/npl/sources/npl-code/.

Pins the per-function rule counts from the spec §8 ACs:
- AC-R1: is_forbearance -> 2 eligibility rules
- AC-R2: can_upgrade_to_performing -> 3 eligibility rules
- AC-R3: classify_loan_as_npe -> 3 eligibility rules (incl. Pattern D)
- AC-R4: validate_forbearance_event -> 0 rules (nested-under-guard)
- AC-R5: can_exit_forborne_status -> 1 eligibility rule
- AC-R6: is_material_past_due -> 0 rules (local-var RHS)
"""
from pathlib import Path

from ontozense.core.ingest.ingest_d import SourceDIngester
from ontozense.core.ingest.base import ArtifactKind


NPL_CODE = Path(__file__).parent / "fixtures" / "synthetic_npl_code"


def _run_one(filename: str) -> list:
    """Run SourceDIngester on a single NPL file and return its candidate list."""
    path = NPL_CODE / filename
    return list(SourceDIngester().ingest({"files": [str(path)]}))


def _rules_for_function(cands: list, func_name: str) -> list:
    """Filter to non-suppressed RULE candidates emitted from a specific function."""
    return [
        c for c in cands
        if c.artifact_kind == ArtifactKind.RULE
        and not c.suppressed
        and c.rule_payload
        and c.rule_payload.get("code_context") == f"def {func_name}"
    ]


def test_ac_r1_is_forbearance_emits_two_eligibility_rules():
    cands = _run_one("forbearance/forbearance_validator.py")
    rules = _rules_for_function(cands, "is_forbearance")
    assert len(rules) == 2, f"expected 2 rules; got {len(rules)}: {[r.label for r in rules]}"
    subjects = {r.rule_payload["subject_attribute"] for r in rules}
    assert subjects == {"is_in_financial_difficulty", "is_concessionary"}
    for r in rules:
        assert r.rule_payload["rule_kind"] == "eligibility"
        assert r.rule_payload["predicate"] == "required"
        assert r.rule_payload["object_value"] is True


def test_ac_r2_can_upgrade_to_performing_emits_three_eligibility_rules():
    cands = _run_one("transitions/upgrade_rules.py")
    rules = _rules_for_function(cands, "can_upgrade_to_performing")
    assert len(rules) == 3, f"expected 3 rules; got {len(rules)}: {[r.label for r in rules]}"
    subjects = {r.rule_payload["subject_attribute"] for r in rules}
    assert subjects == {
        "is_non_performing",
        "has_active_forbearance",
        "improved_repayment_likelihood",
    }
    # Polarities:
    pred_by_subj = {r.rule_payload["subject_attribute"]: r.rule_payload for r in rules}
    assert pred_by_subj["is_non_performing"]["object_value"] is True
    assert pred_by_subj["has_active_forbearance"]["object_value"] is False
    assert pred_by_subj["improved_repayment_likelihood"]["object_value"] is True


def test_ac_r3_classify_loan_as_npe_emits_three_rules_with_constant_resolution():
    cands = _run_one("classification/npe_classifier.py")
    rules = _rules_for_function(cands, "classify_loan_as_npe")
    assert len(rules) == 3, f"expected 3 rules; got {len(rules)}"
    by_subj = {r.rule_payload["subject_attribute"]: r.rule_payload for r in rules}

    # Pattern D — IFRS_STAGE_IMPAIRED constant resolved.
    assert by_subj["ifrs_stage"]["object_value"] == "ifrs_stage_3_impaired"
    assert by_subj["ifrs_stage"]["predicate"] == "eq"

    # Bare-param truthiness checks (sufficient triggers for Pattern B).
    assert by_subj["is_defaulted"]["object_value"] is True
    assert by_subj["is_defaulted"]["predicate"] == "required"
    assert by_subj["unlikeliness_to_pay_flag"]["object_value"] is True


def test_ac_r4_validate_forbearance_event_emits_zero_structured_rules():
    """Nested-under-guard validation is skipped to avoid false promotion."""
    cands = _run_one("forbearance/forbearance_validator.py")
    rules = _rules_for_function(cands, "validate_forbearance_event")
    # The function itself still emits the weak validate_* fallback for
    # the function name. We assert NO structured validation rules
    # (i.e. no rule with a non-None subject_attribute).
    structured = [r for r in rules if r.rule_payload.get("subject_attribute") is not None]
    assert structured == [], f"expected 0 structured rules; got {[r.label for r in structured]}"
    # Pin the fallback's presence too — guards against future over-suppression.
    # The weak fallback has subject_attribute=None so anchor.py suppresses it;
    # check suppressed candidates to verify it was still emitted by extract_procedural.
    suppressed_fallback = [
        c for c in cands
        if c.artifact_kind == ArtifactKind.RULE
        and c.suppressed
        and c.rule_payload
        and c.rule_payload.get("code_context") == "def validate_forbearance_event"
        and c.rule_payload.get("subject_attribute") is None
    ]
    assert len(suppressed_fallback) >= 1, "expected at least the weak validate_* fallback rule (suppressed)"


def test_ac_r5_can_exit_forborne_status_emits_one_eligibility_rule():
    cands = _run_one("transitions/upgrade_rules.py")
    rules = _rules_for_function(cands, "can_exit_forborne_status")
    assert len(rules) == 1, f"expected 1 rule; got {len(rules)}"
    r = rules[0]
    assert r.rule_payload["subject_attribute"] == "counterparty_still_in_difficulty"
    assert r.rule_payload["object_value"] is False  # `if X: return False` -> required not-X


def test_ac_r6_is_material_past_due_emits_zero_rules():
    """Single-return body but RHS is a local variable (dataflow OOS)."""
    cands = _run_one("classification/npe_classifier.py")
    rules = _rules_for_function(cands, "is_material_past_due")
    structured = [r for r in rules if r.rule_payload.get("subject_attribute") is not None]
    assert structured == []


def test_total_npl_rule_count_is_exactly_nine():
    """Aggregate AC: exactly 9 deterministic structured rules across the
    six NPL functions in v1.2.1. The sum of AC-R1..R5 (2+3+3+0+1+0=9).
    Locked at == 9 — when a future patch deliberately expands extraction
    coverage, raise this number explicitly along with the per-function
    ACs."""
    all_files = [
        "classification/npe_classifier.py",
        "forbearance/forbearance_validator.py",
        "transitions/upgrade_rules.py",
    ]
    total = 0
    for f in all_files:
        cands = _run_one(f)
        # Count non-suppressed RULE candidates with a structured subject.
        total += sum(
            1 for c in cands
            if c.artifact_kind == ArtifactKind.RULE
            and not c.suppressed
            and c.rule_payload
            and c.rule_payload.get("subject_attribute") is not None
        )
    assert total == 9, f"expected exactly 9 NPL rules across the three files; got {total}"
