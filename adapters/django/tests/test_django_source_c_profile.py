"""Tests for the Django adapter's profile-aware behaviour.

Migrated from tests/test_phase3_sources_bcd_profile.py when the
Django parser moved out of the installed package into adapters/.
The core profile-application logic has its own tests against
``apply_profile_to_schema`` directly; these tests cover the adapter's
end-to-end behaviour (parse Django files → apply profile → check IDs).
"""

from __future__ import annotations

from pathlib import Path

import pytest

# Provided by adapters/django/tests/conftest.py
from django_schema import DjangoSchemaParser

from ontozense.core.profile import load_profile


MINIMAL_PROFILE_DIR = (
    Path(__file__).parent.parent.parent.parent
    / "tests" / "fixtures" / "profiles" / "minimal"
)


class TestDjangoSourceCProfile:
    """DjangoSchemaParser accepts ``profile=`` and gives models +
    fields IDs and entity_types."""

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
        models_dir = self._write_minimal_models_dir(tmp_path, "Concept")
        profile = load_profile(MINIMAL_PROFILE_DIR)
        result = DjangoSchemaParser(models_dir, profile=profile).parse()
        m = next(m for m in result.models if m.name == "Concept")
        assert m.entity_type == "Concept"
        assert m.id
        assert m.id.startswith("concept_")

    def test_profile_fields_inherit_parent_entity_type(self, tmp_path):
        models_dir = self._write_minimal_models_dir(tmp_path, "Concept")
        profile = load_profile(MINIMAL_PROFILE_DIR)
        result = DjangoSchemaParser(models_dir, profile=profile).parse()
        m = next(m for m in result.models if m.name == "Concept")
        assert len(m.fields) >= 2
        for f in m.fields:
            assert f.entity_type == "Concept"
            assert f.id
            assert f.id != m.id

        ids = [f.id for f in m.fields]
        assert len(set(ids)) == len(ids), "Field IDs must be unique"

    def test_profile_unknown_model_name_leaves_entity_type_empty(self, tmp_path):
        models_dir = self._write_minimal_models_dir(tmp_path, "Mystery")
        profile = load_profile(MINIMAL_PROFILE_DIR)
        result = DjangoSchemaParser(models_dir, profile=profile).parse()
        m = next(m for m in result.models if m.name == "Mystery")
        assert m.entity_type == ""
        assert m.id, "Even unknown-type models should get a deterministic ID"
