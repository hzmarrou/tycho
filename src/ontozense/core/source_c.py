"""Source C — the typed schema-view contract.

Source C in Tycho's four-source pipeline is the **database schema
view**: which fields exist on which entities, what types they have,
which enum values they accept, what foreign-key relationships connect
them. Pre-1.0 (when this module was named ``django_schema``) the
parser was bundled with the Tycho package, hard-coupling Source C to
Django ORM users.

Tycho 1.0 splits cleanly:

  - **This module** owns the typed Source C contract — ``SchemaField``,
    ``SchemaModel``, ``SchemaRelationship``, ``SchemaResult`` — plus
    JSON serialise/deserialise helpers and an optional profile-
    application step.
  - **Adapters** (e.g. ``adapters/django/``) read whatever upstream
    schema format applies (Django models, dbt manifest, INFORMATION_SCHEMA
    dump, OpenAPI, Pydantic, etc.) and emit a ``SchemaResult`` JSON
    file that conforms to this contract.
  - **The fusion engine** consumes the JSON via
    ``load_source_c_json()``. It doesn't know or care which adapter
    produced it.

The contract is format-versioned via ``schema_version`` in the
top-level JSON dict so future shape changes don't silently break
older adapters.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# JSON schema version for the Source C contract. Bumped when the
# serialised shape changes in a non-backward-compatible way.
SCHEMA_VERSION = "1.0"


# ─── Typed contract ──────────────────────────────────────────────────────────


@dataclass
class SchemaField:
    """One field of a database-schema entity.

    ``id`` and ``entity_type`` are the profile-mode metadata
    populated by ``apply_profile_to_schema()`` — empty in the
    unconstrained case.
    """
    name: str
    field_type: str           # adapter-native type label (e.g. "TextField", "VARCHAR(20)", "string")
    playground_type: str      # mapped Tycho type ("string", "integer", "decimal", ...)
    is_primary_key: bool = False
    is_nullable: bool = False
    help_text: str = ""
    choices_var: str = ""     # adapter-defined choices reference
    choices_values: list[str] = field(default_factory=list)
    max_length: int | None = None
    # Profile-mode fields:
    id: str = ""
    entity_type: str = ""

    def to_json_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "name": self.name,
            "field_type": self.field_type,
            "playground_type": self.playground_type,
            "is_primary_key": self.is_primary_key,
            "is_nullable": self.is_nullable,
            "help_text": self.help_text,
            "choices_var": self.choices_var,
            "choices_values": list(self.choices_values),
            "max_length": self.max_length,
        }
        # Only emit profile-mode keys when set — keeps unconstrained
        # JSON byte-identical to a pre-profile shape.
        if self.id:
            out["id"] = self.id
        if self.entity_type:
            out["entity_type"] = self.entity_type
        return out

    @classmethod
    def from_json_dict(cls, raw: dict[str, Any]) -> SchemaField:
        return cls(
            name=raw.get("name", ""),
            field_type=raw.get("field_type", ""),
            playground_type=raw.get("playground_type", ""),
            is_primary_key=raw.get("is_primary_key", False),
            is_nullable=raw.get("is_nullable", False),
            help_text=raw.get("help_text", ""),
            choices_var=raw.get("choices_var", ""),
            choices_values=list(raw.get("choices_values") or []),
            max_length=raw.get("max_length"),
            id=raw.get("id", ""),
            entity_type=raw.get("entity_type", ""),
        )


@dataclass
class SchemaRelationship:
    """A foreign-key / relationship between two entities."""
    field_name: str
    from_model: str
    to_model: str
    on_delete: str = "CASCADE"
    is_nullable: bool = False
    help_text: str = ""

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "field_name": self.field_name,
            "from_model": self.from_model,
            "to_model": self.to_model,
            "on_delete": self.on_delete,
            "is_nullable": self.is_nullable,
            "help_text": self.help_text,
        }

    @classmethod
    def from_json_dict(cls, raw: dict[str, Any]) -> SchemaRelationship:
        return cls(
            field_name=raw.get("field_name", ""),
            from_model=raw.get("from_model", ""),
            to_model=raw.get("to_model", ""),
            on_delete=raw.get("on_delete", "CASCADE"),
            is_nullable=raw.get("is_nullable", False),
            help_text=raw.get("help_text", ""),
        )


@dataclass
class SchemaModel:
    """One database-schema entity (= one table)."""
    name: str
    doc: str = ""
    fields: list[SchemaField] = field(default_factory=list)
    relationships: list[SchemaRelationship] = field(default_factory=list)
    source_file: str = ""
    # Profile-mode fields:
    id: str = ""
    entity_type: str = ""

    def to_json_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "name": self.name,
            "doc": self.doc,
            "fields": [f.to_json_dict() for f in self.fields],
            "relationships": [r.to_json_dict() for r in self.relationships],
            "source_file": self.source_file,
        }
        if self.id:
            out["id"] = self.id
        if self.entity_type:
            out["entity_type"] = self.entity_type
        return out

    @classmethod
    def from_json_dict(cls, raw: dict[str, Any]) -> SchemaModel:
        return cls(
            name=raw.get("name", ""),
            doc=raw.get("doc", ""),
            fields=[SchemaField.from_json_dict(f) for f in raw.get("fields", [])],
            relationships=[
                SchemaRelationship.from_json_dict(r)
                for r in raw.get("relationships", [])
            ],
            source_file=raw.get("source_file", ""),
            id=raw.get("id", ""),
            entity_type=raw.get("entity_type", ""),
        )


@dataclass
class SchemaResult:
    """The complete Source C contract — what an adapter emits and what
    the Tycho fusion engine consumes."""
    models: list[SchemaModel] = field(default_factory=list)
    source_dir: str = ""

    def get_model(self, name: str) -> SchemaModel | None:
        for m in self.models:
            if m.name.lower() == name.lower():
                return m
        return None

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "source_dir": self.source_dir,
            "models": [m.to_json_dict() for m in self.models],
        }

    @classmethod
    def from_json_dict(cls, raw: dict[str, Any]) -> SchemaResult:
        return cls(
            models=[SchemaModel.from_json_dict(m) for m in raw.get("models", [])],
            source_dir=raw.get("source_dir", ""),
        )


# ─── JSON file helpers ───────────────────────────────────────────────────────


def dump_source_c_json(result: SchemaResult, path: Path) -> None:
    """Serialise a ``SchemaResult`` to JSON, emitting the
    ``schema_version`` so future shape changes don't silently
    break older adapters."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(result.to_json_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def load_source_c_json(path: Path) -> SchemaResult:
    """Read a Source C JSON file (output of any adapter) and
    reconstruct a typed ``SchemaResult``.

    Raises ``OSError`` if the file is unreadable, ``json.JSONDecodeError``
    if it's not valid JSON. Callers (CLI) wrap these in user-facing
    error messages. Older JSON files without ``schema_version`` are
    accepted with a default of ``"1.0"`` — the field is informational
    until a future breaking change exists.
    """
    raw = json.loads(path.read_text(encoding="utf-8"))
    return SchemaResult.from_json_dict(raw)


# ─── Profile application ─────────────────────────────────────────────────────


def apply_profile_to_schema(result: SchemaResult, profile: Any) -> SchemaResult:
    """Annotate a SchemaResult with profile-mode ``id`` and
    ``entity_type``. Mutates and returns the input in place.

    Heuristic (mirrors the pre-1.0 ``DjangoSchemaParser._apply_profile``
    so adapter behaviour is identical to the old in-package version):

      * Resolve each model name through ``profile.alias_map`` to its
        canonical form.
      * If the canonical name matches a declared entity_type, set
        ``model.entity_type`` to it.
      * Compute deterministic IDs for each model and field using
        ``compute_id(entity_type or canonical_name, label, hash_length)``.
      * Fields inherit the parent model's ``entity_type`` (they're
        properties of an entity, not entities in their own right).
      * Field IDs use the label ``"<canonical_name>:<field_name>"`` so
        same-named fields on different models stay distinct.

    Adapters call this *before* dumping JSON so the resulting Source C
    file already carries profile-mode metadata, ready for fusion's
    cross-source ID alignment.
    """
    from .identity import compute_id

    for model in result.models:
        canonical_name = profile.resolve_alias(model.name)
        model.name = canonical_name

        if profile.is_known_type(canonical_name):
            model.entity_type = canonical_name

        id_type = model.entity_type or canonical_name
        try:
            model.id = compute_id(
                id_type,
                canonical_name,
                hash_length=profile.id_format.hash_length,
            )
        except ValueError:
            model.id = ""

        for f in model.fields:
            f.entity_type = model.entity_type
            try:
                f.id = compute_id(
                    id_type,
                    f"{canonical_name}:{f.name}",
                    hash_length=profile.id_format.hash_length,
                )
            except ValueError:
                f.id = ""

    return result
