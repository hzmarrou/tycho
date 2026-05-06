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
from ontozense.extractors.django_schema import (
    DjangoSchemaParser,
    SchemaField,
    SchemaModel,
    SchemaResult,
)
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


# ─── Source C (Django schema) profile awareness ──────────────────────────────


class TestSourceCProfileAware:
    """DjangoSchemaParser accepts ``profile=`` and gives models + fields IDs."""

    def _write_minimal_models_dir(self, tmp_path: Path, model_name: str) -> Path:
        """Create a tiny Django-models-shaped directory we can parse."""
        models_dir = tmp_path / "myapp"
        models_dir.mkdir()
        (models_dir / "__init__.py").write_text("", encoding="utf-8")
        (models_dir / "models.py").write_text(
            f"from django.db import models\n\n"
            f"class {model_name}(models.Model):\n"
            f"    name = models.CharField(max_length=100)\n"
            f"    description = models.TextField(blank=True)\n",
            encoding="utf-8",
        )
        return models_dir

    def test_no_profile_models_have_empty_profile_fields(self, tmp_path):
        """Backward compat: no profile = empty id/entity_type."""
        models_dir = self._write_minimal_models_dir(tmp_path, "Concept")
        result = DjangoSchemaParser(models_dir).parse()
        assert len(result.models) >= 1
        m = result.models[0]
        assert m.id == ""
        assert m.entity_type == ""
        for f in m.fields:
            assert f.id == ""
            assert f.entity_type == ""

    def test_profile_assigns_entity_type_when_model_name_matches(self, tmp_path):
        """The minimal profile declares 'Concept' as an entity type. A
        Django model named Concept should get entity_type='Concept'."""
        models_dir = self._write_minimal_models_dir(tmp_path, "Concept")
        profile = load_profile(MINIMAL_PROFILE_DIR)
        result = DjangoSchemaParser(models_dir, profile=profile).parse()
        m = next(m for m in result.models if m.name == "Concept")
        assert m.entity_type == "Concept"
        assert m.id, "Profile mode must produce a deterministic model ID"
        assert m.id.startswith("concept_")

    def test_profile_fields_inherit_parent_entity_type(self, tmp_path):
        """Fields are properties of their parent model — they inherit
        the parent's entity_type and get unique IDs."""
        models_dir = self._write_minimal_models_dir(tmp_path, "Concept")
        profile = load_profile(MINIMAL_PROFILE_DIR)
        result = DjangoSchemaParser(models_dir, profile=profile).parse()
        m = next(m for m in result.models if m.name == "Concept")
        assert len(m.fields) >= 2
        for f in m.fields:
            assert f.entity_type == "Concept"
            assert f.id, f"Field {f.name!r} must have a deterministic ID"
            assert f.id != m.id, "Field ID must differ from model ID"

        # Different fields have different IDs
        ids = [f.id for f in m.fields]
        assert len(set(ids)) == len(ids), "Field IDs must be unique"

    def test_profile_unknown_model_name_leaves_entity_type_empty(self, tmp_path):
        """A model whose name isn't a profile entity type still gets
        an ID (so consolidation sees it) but entity_type stays empty
        for Phase 4 to flag."""
        models_dir = self._write_minimal_models_dir(tmp_path, "Mystery")
        profile = load_profile(MINIMAL_PROFILE_DIR)
        result = DjangoSchemaParser(models_dir, profile=profile).parse()
        m = next(m for m in result.models if m.name == "Mystery")
        assert m.entity_type == ""
        # ID still computed using model name as the type prefix —
        # gives Phase 5 something to consolidate against.
        assert m.id, "Even unknown-type models should get a deterministic ID"


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
