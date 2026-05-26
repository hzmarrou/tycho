"""Tests for VR007 — Required attributes present (Phase C PR C2).

Covers the three acceptance fixtures specified in
``docs/PROPERTY_EXTRACTION_IMPLEMENTATION_PLAN.md`` §12.3 (PR C2):

  Fixture 1  required-missing fires
  Fixture 2  complete profile silent
  Fixture 3  no-profile-attrs regression (byte-identical to pre-PR-C2)

Plus the four extra contracts pinned in design §5 Phase C contracts
and §12.3 PR C2 test list:

  - pre-Phase-A fused reload (no ``attributes`` on the element) still
    fires VR007 when the profile declares required attributes (per
    PROFILE_SPEC.md r1 fix);
  - B-LLM-sourced attributes count toward presence identically to
    deterministic Source C/D/B attributes;
  - per-missing-attribute granularity (two missing names emit two
    findings, each carrying one name);
  - ordering inside ``validate()`` — every VR003 finding precedes
    every VR007 finding for the same element;
  - filter-mode parity — VR007 is annotate-only in both modes, never
    drops an element.

Validation rule modules pre-Phase-C have six rules (VR001-VR006).
PR C2 adds VR007 only — all six existing rule paths must remain
green; that part of the regression is covered by
``tests/test_phase4_validation.py``, which we leave untouched.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ontozense.core.attribute import Attribute, FieldProvenance
from ontozense.core.fusion import (
    FusedElement,
    FusedRelationship,
    FusionResult,
)
from ontozense.core.profile import load_profile
from ontozense.core.validation import (
    ValidationFinding,
    validate,
)


PHASE_C_PROFILE = (
    Path(__file__).parent
    / "fixtures"
    / "phase_c"
    / "profile_customer_required"
)

PRE_PHASE_C_MINIMAL = (
    Path(__file__).parent / "fixtures" / "profiles" / "minimal"
)


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _el(
    name: str,
    *,
    eid: str = "",
    entity_type: str = "",
    attributes: list[Attribute] | None = None,
) -> FusedElement:
    """Construct a profile-mode ``FusedElement`` with typed attrs."""
    extra: dict = {}
    if eid:
        extra["id"] = eid
    if entity_type:
        extra["entity_type"] = entity_type
    return FusedElement(
        element_name=name,
        sources=["A"],
        confidence=0.9,
        extra_fields=extra,
        attributes=list(attributes or []),
    )


def _result(elements, relationships=None) -> FusionResult:
    return FusionResult(
        elements=list(elements),
        relationships=list(relationships or []),
        sources_used=["A"],
        fusion_timestamp="2026-05-26T00:00:00",
    )


def _attr(
    name: str,
    *,
    xsd_type: str = "xsd:string",
    source: str = "C",
    confidence: float = 1.0,
) -> Attribute:
    return Attribute(
        name=name,
        xsd_type=xsd_type,
        field_provenance=[
            FieldProvenance(source=source, confidence=confidence)
        ],
        confidence=confidence,
    )


# ─── Fixture 1 — required missing fires ──────────────────────────────────────


class TestFixtureOneRequiredMissingFires:
    def test_single_missing_required_attribute_fires_one_finding(self):
        profile = load_profile(PHASE_C_PROFILE)
        # Customer entity present, carries only `email` — missing `customerId`
        el = _el(
            "Acme Corp",
            eid="customer_acmecorp_abc123",
            entity_type="Customer",
            attributes=[_attr("email")],
        )
        result = validate(_result([el]), profile)

        vr007 = result.by_rule("VR007")
        assert len(vr007) == 1
        finding = vr007[0]
        assert finding.severity == "warning"
        assert finding.target_kind == "entity"
        assert finding.target_id == "customer_acmecorp_abc123"
        assert finding.details["entity_type"] == "Customer"
        assert finding.details["missing_required_attributes"] == ["customerId"]
        assert "customerId" in finding.message
        assert "Acme Corp" in finding.message

    def test_optional_attribute_absence_does_not_fire(self):
        profile = load_profile(PHASE_C_PROFILE)
        # Both required attributes present; the optional `createdAt` is absent.
        # No VR007 finding may fire for `createdAt`.
        el = _el(
            "Acme Corp",
            eid="customer_acmecorp_abc123",
            entity_type="Customer",
            attributes=[_attr("customerId"), _attr("email")],
        )
        result = validate(_result([el]), profile)
        assert result.by_rule("VR007") == []


# ─── Fixture 2 — complete profile silent ─────────────────────────────────────


class TestFixtureTwoCompleteSilent:
    def test_all_required_attributes_present_produces_no_findings(self):
        profile = load_profile(PHASE_C_PROFILE)
        el = _el(
            "Acme Corp",
            eid="customer_acmecorp_abc123",
            entity_type="Customer",
            attributes=[
                _attr("customerId"),
                _attr("email"),
            ],
        )
        result = validate(_result([el]), profile)
        assert result.by_rule("VR007") == []

    def test_case_insensitive_name_match_satisfies_presence(self):
        profile = load_profile(PHASE_C_PROFILE)
        # Extracted attribute name differs only in case from the
        # profile-declared name. Presence definition is case-insensitive
        # (design §5 Phase C contracts — "Present" definition).
        el = _el(
            "Acme Corp",
            eid="customer_acmecorp_abc123",
            entity_type="Customer",
            attributes=[
                _attr("CUSTOMERID"),
                _attr("  Email  "),
            ],
        )
        result = validate(_result([el]), profile)
        assert result.by_rule("VR007") == []

    def test_empty_name_attribute_never_satisfies(self):
        """An ``Attribute`` with ``name == ""`` must not count as
        present for any required name (design §5 "Present" definition)."""
        profile = load_profile(PHASE_C_PROFILE)
        el = _el(
            "Acme Corp",
            eid="customer_acmecorp_abc123",
            entity_type="Customer",
            attributes=[_attr(""), _attr("email")],
        )
        vr007 = validate(_result([el]), profile).by_rule("VR007")
        assert len(vr007) == 1
        assert vr007[0].details["missing_required_attributes"] == ["customerId"]


# ─── Fixture 3 — no-profile-attrs regression ─────────────────────────────────


class TestFixtureThreeNoAttrsRegression:
    """Phase C gate 4 + spec §11 C12 — when the profile declares no
    ``attributes`` on any entity type, VR007 produces zero findings
    regardless of what the fused result carries.

    Validation output must be byte-identical (modulo the new
    summary key not appearing) to a pre-Phase-C run on the same
    inputs.
    """

    def test_no_vr007_findings_when_profile_lacks_attribute_specs(self):
        profile = load_profile(PRE_PHASE_C_MINIMAL)
        # Concept-typed element with extracted attributes the profile
        # doesn't know about. Pre-Phase-C profile means VR007 is a no-op.
        el = _el(
            "Definition",
            eid="concept_definition_xyz",
            entity_type="Concept",
            attributes=[_attr("anything"), _attr("else")],
        )
        result = validate(_result([el]), profile)
        assert result.by_rule("VR007") == []

    def test_summary_contains_no_vr007_key_when_no_findings(self):
        profile = load_profile(PRE_PHASE_C_MINIMAL)
        el = _el(
            "Definition",
            eid="concept_definition_xyz",
            entity_type="Concept",
            attributes=[_attr("anything")],
        )
        result = validate(_result([el]), profile)
        # ValidationResult.summary only carries keys for fired rules.
        # VR007 absent means the no-op contract held.
        assert "VR007" not in result.summary

    def test_existing_six_rule_findings_unchanged(self):
        """The other six rules continue to operate as before. Concept
        without its required ``definition`` field must still produce a
        VR003 warning, and only VR003."""
        profile = load_profile(PRE_PHASE_C_MINIMAL)
        el = _el(
            "Lonely",
            eid="concept_lonely_aaa",
            entity_type="Concept",
        )
        # Concept's required_fields per fixture: ["definition"]
        result = validate(_result([el]), profile)
        rule_ids = {f.rule_id for f in result.findings}
        assert "VR003" in rule_ids
        assert "VR007" not in rule_ids


# ─── Pre-Phase-A fused reload (PROFILE_SPEC.md r1 fix) ───────────────────────


class TestPrePhaseAFusedReload:
    """When a fused result predates Phase A and carries no
    ``attributes[]`` on any element, the element-level field defaults
    to ``[]`` on reload. Against a Phase-C profile that declares
    ``required: true`` attributes for that element's type, VR007
    **fires** — same shape, same severity, same granularity as for
    any other empty attribute list.

    This is the contract pinned in PROFILE_SPEC.md r1 after the
    Codex round-1 spec review.
    """

    def test_pre_phase_a_fused_fires_vr007_for_each_required(self):
        profile = load_profile(PHASE_C_PROFILE)
        # Construct an element with the default empty attributes list
        # — same shape as a pre-Phase-A fused.json reload would yield
        # because ``FusedElement.attributes`` defaults to [].
        el = FusedElement(
            element_name="Acme Corp",
            sources=["A"],
            confidence=0.9,
            extra_fields={
                "id": "customer_acmecorp_abc123",
                "entity_type": "Customer",
            },
        )
        result = validate(_result([el]), profile)
        vr007 = result.by_rule("VR007")
        # Two required attributes on Customer (customerId, email) →
        # two findings, per-missing-attribute granularity.
        assert len(vr007) == 2
        missing = sorted(
            f.details["missing_required_attributes"][0] for f in vr007
        )
        assert missing == ["customerId", "email"]


# ─── B-LLM presence test ─────────────────────────────────────────────────────


class TestBLLMPresence:
    """A B-LLM-sourced attribute counts toward VR007 presence
    identically to a deterministic one (design §5 Phase C
    contracts — "B-LLM attribute handling"). Structural rule, not a
    confidence rule.
    """

    def test_b_llm_attribute_satisfies_presence(self):
        profile = load_profile(PHASE_C_PROFILE)
        el = _el(
            "Acme Corp",
            eid="customer_acmecorp_abc123",
            entity_type="Customer",
            attributes=[
                _attr("customerId", source="B-LLM", confidence=0.5),
                _attr("email", source="B-LLM", confidence=0.5),
            ],
        )
        result = validate(_result([el]), profile)
        # Zero findings — B-LLM source code should NOT downgrade the
        # presence check. The confidence remains visible on the
        # field_provenance; VR007 ignores it by design.
        assert result.by_rule("VR007") == []

    def test_b_llm_attribute_for_only_one_required_still_fires_for_other(self):
        profile = load_profile(PHASE_C_PROFILE)
        el = _el(
            "Acme Corp",
            eid="customer_acmecorp_abc123",
            entity_type="Customer",
            attributes=[
                _attr("customerId", source="B-LLM", confidence=0.5),
                # `email` deliberately absent — VR007 fires for it.
            ],
        )
        vr007 = validate(_result([el]), profile).by_rule("VR007")
        assert len(vr007) == 1
        assert vr007[0].details["missing_required_attributes"] == ["email"]


# ─── Per-attribute granularity ───────────────────────────────────────────────


class TestPerAttributeGranularity:
    def test_two_missing_required_emits_two_findings(self):
        profile = load_profile(PHASE_C_PROFILE)
        el = _el(
            "Acme Corp",
            eid="customer_acmecorp_abc123",
            entity_type="Customer",
        )
        vr007 = validate(_result([el]), profile).by_rule("VR007")
        assert len(vr007) == 2
        # Each finding carries exactly one name in its details list
        # (per-missing-attribute granularity per design §5 Phase C
        # contracts).
        for finding in vr007:
            assert len(finding.details["missing_required_attributes"]) == 1
        missing = sorted(
            f.details["missing_required_attributes"][0] for f in vr007
        )
        assert missing == ["customerId", "email"]

    def test_one_finding_per_element_per_missing_attribute_across_elements(self):
        profile = load_profile(PHASE_C_PROFILE)
        a = _el(
            "Acme",
            eid="customer_acme_aaa",
            entity_type="Customer",
            attributes=[_attr("email")],
        )
        b = _el(
            "Beta",
            eid="customer_beta_bbb",
            entity_type="Customer",
            attributes=[_attr("customerId")],
        )
        vr007 = validate(_result([a, b]), profile).by_rule("VR007")
        # One finding per element per missing name.
        assert len(vr007) == 2
        ids = sorted(f.target_id for f in vr007)
        assert ids == ["customer_acme_aaa", "customer_beta_bbb"]


# ─── Ordering: VR003 before VR007 for the same element ───────────────────────


class TestOrdering:
    def test_vr003_findings_precede_vr007_findings_for_same_element(
        self,
    ):
        """``validate()`` calls VR003 before VR007 (design §5 Phase C
        contracts — "When VR007 runs"). For an element that triggers
        both rules, every VR003 finding for that element must appear
        in ``result.findings`` before every VR007 finding for it.
        """
        # Build a profile where Customer has BOTH a required field
        # (VR003 surface) AND a required typed attribute (VR007 surface).
        # We need to author a custom profile dir for this case rather
        # than reuse the canonical one.
        import json
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            schema = {
                "profile_name": "phase_c_combo",
                "profile_version": "1.0.0",
                "entity_types": {
                    "Customer": {
                        "required": ["definition"],
                        "attributes": [
                            {
                                "name": "customerId",
                                "xsd_type": "xsd:string",
                                "required": True,
                            }
                        ],
                    }
                },
                "predicates": {},
            }
            Path(td, "schema.json").write_text(json.dumps(schema))
            profile = load_profile(td)

        el = _el(
            "Acme Corp",
            eid="customer_acme_aaa",
            entity_type="Customer",
            # definition deliberately missing → VR003 fires
            # customerId deliberately missing → VR007 fires
        )
        result = validate(_result([el]), profile)

        # Both fire
        assert result.by_rule("VR003")
        assert result.by_rule("VR007")

        # Compute the index of each rule's first finding for this
        # element in the overall findings list. VR003 must precede VR007.
        vr003_idx = next(
            i for i, f in enumerate(result.findings)
            if f.rule_id == "VR003" and f.target_id == "customer_acme_aaa"
        )
        vr007_idx = next(
            i for i, f in enumerate(result.findings)
            if f.rule_id == "VR007" and f.target_id == "customer_acme_aaa"
        )
        assert vr003_idx < vr007_idx


# ─── Filter-mode parity: VR007 is annotate-only ──────────────────────────────


class TestFilterModeParity:
    def test_filter_mode_does_not_drop_vr007_offending_element(self):
        profile = load_profile(PHASE_C_PROFILE)
        el = _el(
            "Acme Corp",
            eid="customer_acmecorp_abc123",
            entity_type="Customer",
            # Both required attrs absent → VR007 fires twice
        )
        result = validate(_result([el]), profile, mode="filter")
        # Finding still emitted
        assert result.by_rule("VR007")
        # Element NOT dropped — VR007 annotate-only in both modes
        # (design §5 Phase C contracts — "When VR007 runs").
        assert len(result.elements) == 1
        assert result.elements[0].element_name == "Acme Corp"
        # Cascade-filter accounting must not credit VR007 with a drop
        # either (it didn't drop anything).
        assert result.cascade_filtered_entities == 0


# ─── Unknown entity type / typed element with no attributes spec ─────────────


class TestEdgeCases:
    def test_element_with_unknown_entity_type_does_not_fire_vr007(self):
        profile = load_profile(PHASE_C_PROFILE)
        el = _el(
            "Mystery",
            eid="unknown_mystery_zzz",
            entity_type="NotInProfile",
        )
        # VR002 will flag the unknown type; VR007 must not fire because
        # the type lookup fails — there is no attribute spec to consult.
        result = validate(_result([el]), profile)
        assert result.by_rule("VR007") == []

    def test_element_with_no_entity_type_does_not_fire_vr007(self):
        profile = load_profile(PHASE_C_PROFILE)
        el = _el(
            "Anonymous",
            eid="customer_anonymous_aaa",
            # entity_type deliberately omitted
        )
        # VR002 handled the missing type; VR007 has nothing to compare.
        result = validate(_result([el]), profile)
        assert result.by_rule("VR007") == []

    def test_known_type_with_no_attribute_spec_does_not_fire(self):
        profile = load_profile(PHASE_C_PROFILE)
        # `Note` entity type exists in the fixture but declares no
        # `attributes` block. VR007 must be silent for it.
        el = _el(
            "Memo",
            eid="note_memo_aaa",
            entity_type="Note",
        )
        result = validate(_result([el]), profile)
        assert result.by_rule("VR007") == []

    def test_only_optional_attributes_with_no_required_does_not_fire(self):
        """When every declared ``attributes[*]`` carries
        ``required=false``, VR007 produces zero findings (the rule's
        second no-op condition in PROFILE_SPEC.md §4)."""
        import json
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            schema = {
                "profile_name": "phase_c_optional_only",
                "profile_version": "1.0.0",
                "entity_types": {
                    "Customer": {
                        "attributes": [
                            {"name": "email", "xsd_type": "xsd:string"},
                            {"name": "phone", "xsd_type": "xsd:string"},
                        ]
                    }
                },
                "predicates": {},
            }
            Path(td, "schema.json").write_text(json.dumps(schema))
            profile = load_profile(td)

        el = _el(
            "Acme",
            eid="customer_acme_aaa",
            entity_type="Customer",
        )
        result = validate(_result([el]), profile)
        assert result.by_rule("VR007") == []


# ─── Finding shape sanity ────────────────────────────────────────────────────


class TestFindingShape:
    def test_finding_carries_expected_keys(self):
        profile = load_profile(PHASE_C_PROFILE)
        el = _el(
            "Acme Corp",
            eid="customer_acmecorp_abc123",
            entity_type="Customer",
            attributes=[_attr("email")],
        )
        finding = validate(_result([el]), profile).by_rule("VR007")[0]
        assert isinstance(finding, ValidationFinding)
        assert finding.rule_id == "VR007"
        assert finding.severity == "warning"
        assert finding.target_kind == "entity"
        assert set(finding.details.keys()) >= {
            "element_name",
            "entity_type",
            "missing_required_attributes",
        }
        assert finding.details["element_name"] == "Acme Corp"
        assert finding.details["entity_type"] == "Customer"

    def test_target_id_falls_back_to_element_name_when_no_id(self):
        """Same fallback policy as VR003 — when the element carries no
        deterministic ID (``extra_fields["id"]`` empty), VR007 reports
        the element_name as ``target_id``."""
        profile = load_profile(PHASE_C_PROFILE)
        el = _el(
            "Nameless Co",
            entity_type="Customer",
            attributes=[_attr("email")],
        )
        finding = validate(_result([el]), profile).by_rule("VR007")[0]
        # Either the element_name itself or its normalised form is
        # accepted — both are stable, deterministic surrogates and
        # match the VR003 fallback chain used elsewhere in this module.
        assert finding.target_id in {
            "Nameless Co",
            "nameless co",
            "nameless_co",
        }
