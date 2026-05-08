"""Tests for Phase 3: profile-aware Sources B, C, D.

Same pattern as Phase 2's test_extract_a_constrained.py:
  * Tests focus on the profile-aware paths in each extractor.
  * Backward compat is enforced by re-running the full suite —
    every test in test_governance_extractor.py / test_code_extractor.py
    must still pass byte-identical when profile=None.
  * Phase 1's minimal test fixture is reused.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ontozense.core.profile import load_profile
from ontozense.extractors.code_extractor import (
    CodeExtractor,
    CodeProvenance,
    CodeRule,
)
from ontozense.core.source_c import (
    SchemaField,
    SchemaModel,
    SchemaResult,
)
# DjangoSchemaParser tests live in adapters/django/tests/ — see
# adapters/django/tests/test_django_source_c_profile.py for the
# end-to-end profile-aware tests that used to be ``TestSourceCProfileAware``
# in this file. Profile-application logic itself is tested via
# ``ontozense.core.source_c.apply_profile_to_schema``.
from ontozense.extractors.governance_extractor import (
    GovernanceExtractor,
    GovernanceRecord,
)


MINIMAL_PROFILE_DIR = (
    Path(__file__).parent / "fixtures" / "profiles" / "minimal"
)


# ─── Source B (governance) profile awareness ────────────────────────────────


class TestSourceBProfileAware:
    """GovernanceExtractor accepts ``profile=`` and gives records IDs."""

    def test_no_profile_records_have_empty_profile_fields(self, tmp_path):
        """AC1 backward compat: without profile, records have empty
        id and entity_type."""
        f = tmp_path / "gov.json"
        f.write_text(
            json.dumps([
                {"element_name": "Concept One", "definition": "A test."},
            ]),
            encoding="utf-8",
        )
        result = GovernanceExtractor().extract_from_file(f)
        assert len(result.records) == 1
        r = result.records[0]
        assert r.id == ""
        assert r.entity_type == ""

    def test_profile_resolves_alias_on_element_name(self, tmp_path):
        """The minimal profile maps 'co1' -> 'Concept One'. Source B
        should canonicalise the element_name on load."""
        f = tmp_path / "gov.json"
        f.write_text(
            json.dumps([
                {
                    "element_name": "co1",
                    "entity_type": "Concept",
                    "definition": "via alias",
                },
            ]),
            encoding="utf-8",
        )
        profile = load_profile(MINIMAL_PROFILE_DIR)
        result = GovernanceExtractor(profile=profile).extract_from_file(f)
        assert len(result.records) == 1
        assert result.records[0].element_name == "Concept One"

    def test_profile_computes_deterministic_id(self, tmp_path):
        f = tmp_path / "gov.json"
        f.write_text(
            json.dumps([
                {
                    "element_name": "Concept One",
                    "entity_type": "Concept",
                    "definition": "A canonical concept.",
                },
            ]),
            encoding="utf-8",
        )
        profile = load_profile(MINIMAL_PROFILE_DIR)
        result = GovernanceExtractor(profile=profile).extract_from_file(f)
        r = result.records[0]
        assert r.id, "Profile mode must produce a deterministic ID"
        assert r.id.startswith("concept_")
        # Hash suffix length matches profile.id_format.hash_length=6
        assert len(r.id.rsplit("_", 1)[-1]) == 6

    def test_profile_id_aligns_with_phase2_source_a(self, tmp_path):
        """The whole point of cross-source consolidation: a Source B
        record and a Source A concept with the same canonical name +
        type produce the same ID."""
        from ontozense.core.identity import compute_id

        f = tmp_path / "gov.json"
        f.write_text(
            json.dumps([
                {"element_name": "Concept One", "entity_type": "Concept"},
            ]),
            encoding="utf-8",
        )
        profile = load_profile(MINIMAL_PROFILE_DIR)
        result = GovernanceExtractor(profile=profile).extract_from_file(f)

        expected = compute_id("Concept", "Concept One", hash_length=6)
        assert result.records[0].id == expected, (
            "Source B's deterministic ID must equal compute_id() output "
            "so Source A and Source B can dedupe in fusion (Phase 5)"
        )

    def test_profile_unknown_entity_type_records_warning(self, tmp_path):
        """Quarantine, don't drop. Unknown types get a profile_warning
        in extra_fields and a result-level warning, but the record
        still appears so Phase 4 can decide."""
        f = tmp_path / "gov.json"
        f.write_text(
            json.dumps([
                {
                    "element_name": "Mystery",
                    "entity_type": "Unknown",
                    "definition": "Type not in profile.",
                },
            ]),
            encoding="utf-8",
        )
        profile = load_profile(MINIMAL_PROFILE_DIR)
        result = GovernanceExtractor(profile=profile).extract_from_file(f)

        # Record kept (not dropped)
        assert len(result.records) == 1
        r = result.records[0]
        assert r.element_name == "Mystery"
        assert r.entity_type == "Unknown"

        # Warning recorded at both record level and result level
        assert "profile_warning" in r.extra_fields
        assert "Unknown" in r.extra_fields["profile_warning"]
        assert any("Unknown" in w for w in result.warnings)

    def test_profile_no_entity_type_in_record_leaves_id_empty(self, tmp_path):
        """If the user's JSON omits entity_type, we don't make one up.
        Phase 4 will flag the missing type."""
        f = tmp_path / "gov.json"
        f.write_text(
            json.dumps([
                {"element_name": "Untyped", "definition": "No type given."},
            ]),
            encoding="utf-8",
        )
        profile = load_profile(MINIMAL_PROFILE_DIR)
        result = GovernanceExtractor(profile=profile).extract_from_file(f)
        r = result.records[0]
        assert r.entity_type == ""
        assert r.id == ""


# Source C (Django schema) profile-aware tests moved to
# adapters/django/tests/test_django_source_c_profile.py when the
# parser was extracted to adapters/. Core profile-application logic
# is tested in tests/test_phase3_core_source_c_profile.py via
# ``apply_profile_to_schema`` directly.


# ─── Source D (code) profile awareness ──────────────────────────────────────


class TestSourceDProfileAware:
    """CodeExtractor accepts ``profile=`` and attaches rules to entities."""

    def _write_minimal_python(self, tmp_path: Path, content: str) -> Path:
        f = tmp_path / "rules.py"
        f.write_text(content, encoding="utf-8")
        return tmp_path

    def test_no_profile_rules_have_empty_profile_fields(self, tmp_path):
        """Backward compat: no profile = empty attached_to_entity_*."""
        d = self._write_minimal_python(
            tmp_path,
            "THRESHOLD = 90\n"
            "def validate(record):\n"
            "    if record.amount > THRESHOLD:\n"
            "        return False\n"
            "    return True\n",
        )
        result = CodeExtractor().extract_from_directory(d)
        assert len(result.rules) > 0
        for r in result.rules:
            assert r.attached_to_entity_id == ""
            assert r.attached_to_entity_type == ""

    def test_profile_attaches_rule_via_referenced_symbols(self, tmp_path):
        """When a rule references 'concept.foo' and Concept is a known
        type, the rule gets attached_to_entity_type='Concept'."""
        d = self._write_minimal_python(
            tmp_path,
            "def check_concept(concept):\n"
            "    \"\"\"Validate a concept.\"\"\"\n"
            "    if concept.value < 10:\n"
            "        return False\n"
            "    return True\n",
        )
        profile = load_profile(MINIMAL_PROFILE_DIR)
        result = CodeExtractor(profile=profile).extract_from_directory(d)

        # Find the function rule that references 'concept'
        attached = [
            r for r in result.rules
            if r.attached_to_entity_type == "Concept"
        ]
        assert len(attached) >= 1, (
            "At least one rule should be attached to Concept via "
            "referenced_symbols matching"
        )
        # IDs are deterministic
        for r in attached:
            assert r.attached_to_entity_id.startswith("concept_")

    def test_profile_attaches_rule_via_constant_name_prefix(self, tmp_path):
        """A constant like CONCEPT_THRESHOLD should be attached to
        entity_type=Concept via the name-prefix heuristic."""
        d = self._write_minimal_python(
            tmp_path,
            "CONCEPT_THRESHOLD = 100\n",
        )
        profile = load_profile(MINIMAL_PROFILE_DIR)
        result = CodeExtractor(profile=profile).extract_from_directory(d)

        const_rules = [r for r in result.rules if r.rule_type == "constant"]
        assert len(const_rules) >= 1
        c = const_rules[0]
        assert c.attached_to_entity_type == "Concept", (
            f"Expected name-prefix match: CONCEPT_THRESHOLD -> Concept, "
            f"got entity_type={c.attached_to_entity_type!r}"
        )
        assert c.attached_to_entity_id.startswith("concept_")

    def test_profile_unknown_anchor_leaves_attachment_empty(self, tmp_path):
        """A rule whose name and symbols don't match any known type
        gets empty profile fields (Phase 4 will flag)."""
        d = self._write_minimal_python(
            tmp_path,
            "MYSTERIOUS_TIMEOUT = 30\n",
        )
        profile = load_profile(MINIMAL_PROFILE_DIR)
        result = CodeExtractor(profile=profile).extract_from_directory(d)

        const_rules = [r for r in result.rules if r.rule_type == "constant"]
        assert len(const_rules) >= 1
        # No 'mysterious' in the minimal profile; nothing attaches
        assert const_rules[0].attached_to_entity_type == ""
        assert const_rules[0].attached_to_entity_id == ""


class TestSourceDProfileMultiWordTypes:
    """Review finding #1 (blocker): the type-inference heuristic must
    match multi-word PascalCase types (e.g. ``CustomerIdentifier``)
    against snake_case constant prefixes (``CUSTOMER_IDENTIFIER_THRESHOLD``).
    The fix: compact-form normalisation that strips separators on both
    sides before comparison."""

    def _write_python(self, tmp_path: Path, content: str) -> Path:
        f = tmp_path / "rules.py"
        f.write_text(content, encoding="utf-8")
        return tmp_path

    def _profile_with_multiword_type(self, tmp_path: Path):
        """Build a profile with a multi-word type like CustomerIdentifier."""
        profile_dir = tmp_path / "multiword_profile"
        profile_dir.mkdir()
        (profile_dir / "schema.json").write_text(
            json.dumps({
                "profile_name": "multiword",
                "profile_version": "1.0.0",
                "entity_types": {
                    "CustomerIdentifier": {"required": []},
                    "ReportingFramework": {"required": []},
                    "Concept": {"required": []},
                },
                "predicates": {},
            }),
            encoding="utf-8",
        )
        return load_profile(profile_dir)

    def test_constant_screaming_snake_matches_pascal_type(self, tmp_path):
        """A constant CUSTOMER_IDENTIFIER_THRESHOLD must attach to
        the profile's CustomerIdentifier type via the name-prefix
        heuristic."""
        # Write code FIRST in a sub-dir so it doesn't interfere with
        # profile dir tooling
        code_dir = tmp_path / "code"
        code_dir.mkdir()
        self._write_python(
            code_dir,
            "CUSTOMER_IDENTIFIER_THRESHOLD = 100\n",
        )
        profile = self._profile_with_multiword_type(tmp_path)
        result = CodeExtractor(profile=profile).extract_from_directory(code_dir)

        const_rules = [r for r in result.rules if r.rule_type == "constant"]
        assert len(const_rules) >= 1
        c = const_rules[0]
        assert c.attached_to_entity_type == "CustomerIdentifier", (
            f"CUSTOMER_IDENTIFIER_THRESHOLD must attach to "
            f"CustomerIdentifier (compact-form match), got "
            f"entity_type={c.attached_to_entity_type!r}"
        )

    def test_constant_kebab_matches_pascal_type(self, tmp_path):
        """Equivalent test with another multi-word type spelling style.
        A function name reporting_framework_check should reference
        ReportingFramework via the name-prefix heuristic."""
        code_dir = tmp_path / "code"
        code_dir.mkdir()
        self._write_python(
            code_dir,
            "REPORTING_FRAMEWORK_VERSION = '1.0'\n",
        )
        profile = self._profile_with_multiword_type(tmp_path)
        result = CodeExtractor(profile=profile).extract_from_directory(code_dir)

        const_rules = [r for r in result.rules if r.rule_type == "constant"]
        assert len(const_rules) >= 1
        c = const_rules[0]
        assert c.attached_to_entity_type == "ReportingFramework"

    def test_single_word_type_still_works(self, tmp_path):
        """Regression: the compact-form fix must not break single-word
        type matching."""
        code_dir = tmp_path / "code"
        code_dir.mkdir()
        self._write_python(code_dir, "CONCEPT_THRESHOLD = 100\n")
        profile = self._profile_with_multiword_type(tmp_path)
        result = CodeExtractor(profile=profile).extract_from_directory(code_dir)

        const_rules = [r for r in result.rules if r.rule_type == "constant"]
        assert any(
            r.attached_to_entity_type == "Concept" for r in const_rules
        )


class TestSourceDProfileSqlPath:
    """Review finding #3 (minor): SQL extraction in profile mode wasn't
    tested. These tests cover CREATE VIEW / CREATE TABLE / CHECK
    constraints with profile awareness."""

    def _write_sql(self, tmp_path: Path, content: str) -> Path:
        f = tmp_path / "schema.sql"
        f.write_text(content, encoding="utf-8")
        return tmp_path

    def test_create_table_attaches_to_known_type_by_table_name(self, tmp_path):
        """A CREATE TABLE concept (...) should produce a sql_table
        rule whose name is 'concept' and which attaches to entity_type
        Concept via the compact-form name match."""
        d = self._write_sql(
            tmp_path,
            "CREATE TABLE concept (id INTEGER PRIMARY KEY, name TEXT);\n",
        )
        profile = load_profile(MINIMAL_PROFILE_DIR)
        result = CodeExtractor(profile=profile).extract_from_directory(d)

        sql_table_rules = [r for r in result.rules if r.rule_type == "sql_table"]
        assert len(sql_table_rules) >= 1
        # Table 'concept' should attach to type 'Concept' (case-insensitive)
        attached = [
            r for r in sql_table_rules
            if r.attached_to_entity_type == "Concept"
        ]
        assert len(attached) >= 1, (
            f"sql_table for table 'concept' should attach to "
            f"Concept, got {[r.attached_to_entity_type for r in sql_table_rules]}"
        )
        assert attached[0].attached_to_entity_id.startswith("concept_")

    def test_create_view_attaches_to_known_type_via_name_prefix(self, tmp_path):
        """A CREATE VIEW concept_summary should attach to Concept via
        the leading-token match in _infer_entity_type."""
        d = self._write_sql(
            tmp_path,
            "CREATE VIEW concept_summary AS SELECT * FROM concept;\n",
        )
        profile = load_profile(MINIMAL_PROFILE_DIR)
        result = CodeExtractor(profile=profile).extract_from_directory(d)

        sql_view_rules = [r for r in result.rules if r.rule_type == "sql_view"]
        assert len(sql_view_rules) >= 1
        v = sql_view_rules[0]
        # 'concept_summary' tokens: ['concept', 'summary']. Longest-
        # prefix-first tries 'conceptsummary', then 'concept'. 'concept'
        # matches profile type 'Concept'.
        assert v.attached_to_entity_type == "Concept", (
            f"sql_view 'concept_summary' should attach to Concept via "
            f"prefix 'concept', got {v.attached_to_entity_type!r}"
        )

    def test_unknown_sql_object_leaves_attachment_empty(self, tmp_path):
        """A SQL view whose name doesn't match any known type stays
        unattached for Phase 4 to flag."""
        d = self._write_sql(
            tmp_path,
            "CREATE VIEW mysterious_aggregate AS SELECT 1;\n",
        )
        profile = load_profile(MINIMAL_PROFILE_DIR)
        result = CodeExtractor(profile=profile).extract_from_directory(d)

        sql_view_rules = [r for r in result.rules if r.rule_type == "sql_view"]
        assert len(sql_view_rules) >= 1
        assert sql_view_rules[0].attached_to_entity_type == ""


class TestProfileLookupCaseInsensitive:
    """Review finding #2 (major): Profile.is_known_type() was case-
    sensitive while compute_id() is case-insensitive. A record
    declared with entity_type: 'concept' (lowercase) was flagged as
    unknown but still got an ID — inconsistent. Fix makes lookups
    case-insensitive."""

    def test_is_known_type_case_insensitive(self):
        profile = load_profile(MINIMAL_PROFILE_DIR)
        # Profile declares 'Concept' (capitalised)
        assert profile.is_known_type("Concept")
        assert profile.is_known_type("concept")  # was failing before fix
        assert profile.is_known_type("CONCEPT")
        assert profile.is_known_type("CoNcEpT")

    def test_get_entity_type_case_insensitive(self):
        profile = load_profile(MINIMAL_PROFILE_DIR)
        et = profile.get_entity_type("concept")  # lowercase input
        assert et is not None
        assert et.name == "Concept"  # canonical case preserved in output

    def test_is_known_predicate_case_insensitive(self):
        profile = load_profile(MINIMAL_PROFILE_DIR)
        assert profile.is_known_predicate("AppliesTo")
        assert profile.is_known_predicate("appliesto")
        assert profile.is_known_predicate("APPLIESTO")

    def test_governance_record_lowercase_type_no_false_warning(self, tmp_path):
        """End-to-end: a Source B record with entity_type='concept'
        (lowercase) must NOT generate a profile_warning, because the
        profile recognises it case-insensitively."""
        f = tmp_path / "gov.json"
        f.write_text(
            json.dumps([
                {"element_name": "Concept One", "entity_type": "concept"},
            ]),
            encoding="utf-8",
        )
        profile = load_profile(MINIMAL_PROFILE_DIR)
        result = GovernanceExtractor(profile=profile).extract_from_file(f)

        r = result.records[0]
        # No profile_warning should have been added — type is known
        assert "profile_warning" not in r.extra_fields, (
            f"Lowercase entity_type 'concept' should match profile "
            f"type 'Concept' case-insensitively, but got warning: "
            f"{r.extra_fields.get('profile_warning')!r}"
        )
        # And no result-level warning either
        assert not any("concept" in w.lower() for w in result.warnings), (
            f"Should not have warned about lowercase type, but warnings = "
            f"{result.warnings}"
        )
        # ID still computed
        assert r.id, "ID should be populated for known type (any case)"


# ─── Cross-source ID alignment (the consolidation contract) ─────────────────


class TestCrossSourceIdAlignment:
    """Phase 5's consolidation depends on Sources A/B/C/D producing the
    same deterministic ID for the same canonical (type, name). This test
    pins that contract so it doesn't drift."""

    def test_same_type_and_name_produces_same_id_across_sources(self, tmp_path):
        """A 'Concept One' Concept declared in Source B and the same
        thing as a Django model in Source C must produce the same ID."""
        from ontozense.core.identity import compute_id

        # Source B record
        f = tmp_path / "gov.json"
        f.write_text(
            json.dumps([
                {"element_name": "Concept One", "entity_type": "Concept"},
            ]),
            encoding="utf-8",
        )
        profile = load_profile(MINIMAL_PROFILE_DIR)
        b = GovernanceExtractor(profile=profile).extract_from_file(f)

        # Source A would call compute_id directly via _apply_profile;
        # we simulate by computing the same ID
        expected_id = compute_id("Concept", "Concept One", hash_length=6)

        assert b.records[0].id == expected_id, (
            "Source B (governance) and Source A (extract-a) must "
            "produce the same ID for the same (type, name) — that's "
            "the whole basis of Phase 5 consolidation"
        )

    def test_alias_collapsed_before_id_so_synonyms_match(self, tmp_path):
        """If Source A extracts 'co1' and Source B also has 'co1', both
        should resolve via alias to 'Concept One' and produce the same
        ID."""
        from ontozense.core.identity import compute_id

        f = tmp_path / "gov.json"
        f.write_text(
            json.dumps([
                {"element_name": "co1", "entity_type": "Concept"},
            ]),
            encoding="utf-8",
        )
        profile = load_profile(MINIMAL_PROFILE_DIR)
        b = GovernanceExtractor(profile=profile).extract_from_file(f)

        expected_id = compute_id("Concept", "Concept One", hash_length=6)
        assert b.records[0].id == expected_id, (
            "Alias 'co1' must canonicalise to 'Concept One' before ID "
            "computation, so synonymous records produce the same ID"
        )
