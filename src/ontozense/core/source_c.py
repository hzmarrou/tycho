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
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_logger = logging.getLogger(__name__)


# JSON schema version for the Source C contract. Bumped when the
# serialised shape changes in a non-backward-compatible way. The
# major component (the part before the dot) defines compatibility:
# Tycho can read any minor version under a major it knows about.
SCHEMA_VERSION = "1.0"
SUPPORTED_MAJOR_VERSIONS = {"1"}


class SourceCContractError(ValueError):
    """Raised when a Source C JSON file violates the contract.

    Distinct from ``json.JSONDecodeError`` (the file isn't valid JSON
    at all) and ``OSError`` (the file isn't readable). This means the
    JSON parsed but its shape is wrong: unsupported ``schema_version``,
    missing required keys, wrong type for ``models``, etc. The CLI
    catches this separately so it can point at the adapter docs and
    the version-compatibility rules.
    """


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

    Raises:
      - ``OSError`` if the file is unreadable.
      - ``json.JSONDecodeError`` if it isn't valid JSON.
      - ``SourceCContractError`` if it parsed but the shape is wrong
        (unsupported ``schema_version``, missing/wrong-typed
        ``models`` list, etc.). Callers — typically the CLI — catch
        this and print a user-facing message pointing at adapter
        docs.

    Older JSON files without ``schema_version`` are tolerated by
    assuming ``"1.0"`` (the initial release shape). Files declaring a
    major version this Tycho doesn't know about are rejected loudly —
    silently parsing as 0 models is exactly the bug Phase 7 review
    flagged.
    """
    raw = json.loads(path.read_text(encoding="utf-8"))

    if not isinstance(raw, dict):
        raise SourceCContractError(
            f"Source C JSON root must be an object, got "
            f"{type(raw).__name__}."
        )

    declared_version = raw.get("schema_version", SCHEMA_VERSION)
    if not isinstance(declared_version, str):
        raise SourceCContractError(
            f"schema_version must be a string, got "
            f"{type(declared_version).__name__}."
        )
    declared_major = declared_version.split(".", 1)[0]
    if declared_major not in SUPPORTED_MAJOR_VERSIONS:
        raise SourceCContractError(
            f"Unsupported Source C schema_version {declared_version!r}. "
            f"This Tycho understands major version(s): "
            f"{sorted(SUPPORTED_MAJOR_VERSIONS)}. The adapter that "
            f"produced this JSON may need updating."
        )

    if "models" not in raw:
        raise SourceCContractError(
            "Source C JSON missing required key 'models'. The adapter "
            "must emit at least an empty list — see "
            "adapters/README.md for the contract."
        )
    if not isinstance(raw["models"], list):
        raise SourceCContractError(
            f"Source C 'models' must be a list, got "
            f"{type(raw['models']).__name__}."
        )

    # Nested validation. The reconstruction in from_json_dict() does
    # ``.get(...)`` on each model / field / relationship; if any of
    # those is the wrong type (e.g. ``models=[123]`` or
    # ``fields=[null]``) it would crash with a raw AttributeError —
    # which the CLI then prints as a traceback. Validate the shape
    # here so failures are user-facing.
    for i, m in enumerate(raw["models"]):
        if not isinstance(m, dict):
            raise SourceCContractError(
                f"Source C models[{i}] must be an object, got "
                f"{type(m).__name__}."
            )
        for key, sub_kind in (("fields", "field"), ("relationships", "relationship")):
            sub = m.get(key)
            if sub is None:
                continue
            if not isinstance(sub, list):
                raise SourceCContractError(
                    f"Source C models[{i}].{key} must be a list, "
                    f"got {type(sub).__name__}."
                )
            for j, item in enumerate(sub):
                if not isinstance(item, dict):
                    raise SourceCContractError(
                        f"Source C models[{i}].{key}[{j}] must be an "
                        f"object, got {type(item).__name__}."
                    )

    try:
        return SchemaResult.from_json_dict(raw)
    except (AttributeError, TypeError) as e:
        # Belt-and-braces: any remaining shape error during
        # reconstruction surfaces as a clean contract error rather
        # than a raw traceback.
        raise SourceCContractError(
            f"Source C JSON has unexpected shape during reconstruction: "
            f"{type(e).__name__}: {e}"
        ) from e


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


# ─── SQL DDL → SchemaResult builder ──────────────────────────────────────────
#
# Property extraction Phase A (PR1b) needs to persist a typed
# SchemaResult to ``discovery/source-c.json`` so PR2's fusion engine
# can read it back. ``SourceCIngester`` already parses .sql files via
# sqlglot but only yields ``IntermediateCandidate`` — the per-field
# metadata (type, nullable, pk, fk) lives in its internal ``tables``
# dict and never escapes. Rather than expose that internal state (or
# refactor the ingester in PR1b), this builder runs an independent
# sqlglot pass and produces a typed ``SchemaResult`` directly. The
# two passes parse the same files redundantly; the cost is acceptable
# for Phase A and a single-pass refactor can land later without
# changing this contract.


def build_schema_from_sql_files(
    file_paths: list[Path] | tuple[Path, ...],
    source_dir: str = "",
    config: dict[str, Any] | None = None,
) -> SchemaResult:
    """Parse a list of ``.sql`` DDL files and return a typed ``SchemaResult``.

    Recognised constructs (per CREATE TABLE):
      - column name + native SQL type → ``SchemaField.field_type`` +
        ``SchemaField.playground_type`` via ``xsd_type_for_sql()``.
      - PRIMARY KEY constraint (inline or table-level) → ``is_primary_key``.
      - NOT NULL constraint → ``is_nullable = False``.
      - VARCHAR(n) / CHAR(n) → ``max_length = n``.
      - CHECK (col IN ('a', 'b')) → ``choices_values`` populated.
      - FOREIGN KEY → ``SchemaModel.relationships`` entry pointing at
        the referenced table.

    **Suppression parity (PR1b r1 — Codex blocker 1):** when ``config``
    is supplied (typically loaded from
    ``<domain-dir>/source-c.yaml``), the builder mirrors the filtering
    semantics of :class:`ontozense.core.ingest.ingest_c.SourceCIngester`
    so the persisted ``discovery/source-c.json`` cannot resurrect
    tables / columns the survey orchestrator intentionally suppresses:

      - ``config["exclude_tables"]`` — user-suppressed table name globs.
      - ``config["include_tables"]`` — overrides default suppression.
      - ``config["exclude_columns"]`` — user-suppressed column globs.
      - :data:`DEFAULT_SOURCE_C_TABLE_SUPPRESSIONS` — default table noise
        patterns (``*_audit``, ``*_history``, ``tmp_*``, ...) unless
        the table is in ``include_tables``.
      - :data:`column_is_suppressed` — default column noise patterns
        (``created_at``, ``updated_at``, ``etag``, ...) with
        domain-bearing-prefix exemption (``birth_date`` survives).

    Non-``.sql`` files are silently skipped. Files that fail to parse
    are skipped with a WARNING log entry, matching the tolerance of
    :class:`ontozense.core.ingest.ingest_c.SourceCIngester`.

    ``source_dir`` populates ``SchemaResult.source_dir`` for downstream
    provenance.
    """
    import sqlglot
    from sqlglot import expressions as exp

    from .attribute import xsd_type_for_sql
    from .ingest.filters import (
        DEFAULT_SOURCE_C_TABLE_SUPPRESSIONS,
        column_is_suppressed,
        glob_match,
    )

    config = config or {}
    user_exclude_tables: list[str] = list(config.get("exclude_tables", []) or [])
    user_include_tables: list[str] = list(config.get("include_tables", []) or [])
    user_exclude_columns: list[str] = list(config.get("exclude_columns", []) or [])

    def _xsd_to_playground(xsd: str) -> str:
        """Project an XSD URI back to the legacy Tycho ``playground_type``
        label used by ``SchemaField``. The set of labels here mirrors
        the in-tree values produced by the Django adapter."""
        return {
            "xsd:string": "string",
            "xsd:integer": "integer",
            "xsd:decimal": "decimal",
            "xsd:double": "decimal",
            "xsd:date": "date",
            "xsd:time": "time",
            "xsd:dateTime": "datetime",
            "xsd:dateTimeStamp": "datetime",
            "xsd:duration": "string",
            "xsd:boolean": "boolean",
            "xsd:base64Binary": "string",
        }.get(xsd, "string")

    models: list[SchemaModel] = []

    for path in file_paths:
        if path.suffix.lower() != ".sql":
            continue
        try:
            statements = sqlglot.parse(
                path.read_text(encoding="utf-8", errors="replace")
            )
        except Exception as exc:  # sqlglot.errors.ParseError is too narrow
            # Match SourceCIngester tolerance: log at WARNING and skip.
            # PR1b r1 (Codex nit): code/doc parity — previously silent.
            _logger.warning(
                "Source C persistence: could not parse %s (%s); skipping.",
                path, exc,
            )
            continue

        for stmt in statements or []:
            if not isinstance(stmt, exp.Create):
                continue
            if (stmt.args.get("kind") or "").upper() != "TABLE":
                continue
            table = stmt.this
            if isinstance(table, exp.Schema):
                # CREATE TABLE name (cols, constraints) — table is a Schema
                table_name_node = table.this
            else:
                table_name_node = table
            if isinstance(table_name_node, exp.Table):
                table_name = table_name_node.name
            else:
                table_name = str(table_name_node)
            if not table_name:
                continue

            # ── Table-level suppression (PR1b r1) ─────────────────────
            # Mirror SourceCIngester semantics: user exclude wins,
            # user include overrides defaults, defaults catch noise.
            if glob_match(table_name, user_exclude_tables):
                continue
            if (
                not glob_match(table_name, user_include_tables)
                and glob_match(table_name, DEFAULT_SOURCE_C_TABLE_SUPPRESSIONS)
            ):
                continue

            fields: list[SchemaField] = []
            relationships: list[SchemaRelationship] = []

            # Pull every column + constraint expression from the schema.
            schema = table if isinstance(table, exp.Schema) else None
            if schema is None:
                models.append(SchemaModel(
                    name=table_name,
                    source_file=str(path),
                ))
                continue

            pk_columns: set[str] = set()
            check_choices: dict[str, list[str]] = {}
            seen_columns: list[str] = []

            for expr in schema.expressions:
                if isinstance(expr, exp.ColumnDef):
                    col_name = expr.this.name
                    if not col_name:
                        continue
                    # ── Column-level suppression (PR1b r1) ────────────
                    # column_is_suppressed enforces user exclude_columns
                    # AND default noise patterns (created_at, etag, ...)
                    # with domain-bearing-prefix exemption.
                    if column_is_suppressed(
                        col_name,
                        user_exclude=user_exclude_columns,
                        user_include=[],
                    ):
                        continue
                    seen_columns.append(col_name)
                    raw_type = expr.args.get("kind")
                    raw_type_str = raw_type.sql() if raw_type is not None else ""
                    xsd = xsd_type_for_sql(raw_type_str)

                    # Inline constraints (NOT NULL, PRIMARY KEY, CHECK).
                    constraints = expr.args.get("constraints") or []
                    is_pk = False
                    is_nullable = True
                    max_length: int | None = None

                    # Strip max length from VARCHAR(n) / CHAR(n).
                    if raw_type is not None:
                        params = raw_type.args.get("expressions") or []
                        if params and isinstance(params[0], exp.DataTypeParam):
                            inner = params[0].this
                            if isinstance(inner, exp.Literal) and inner.is_int:
                                try:
                                    max_length = int(inner.this)
                                except (TypeError, ValueError):
                                    max_length = None

                    for con in constraints:
                        kind = con.kind if hasattr(con, "kind") else None
                        if isinstance(kind, exp.PrimaryKeyColumnConstraint):
                            is_pk = True
                        elif isinstance(kind, exp.NotNullColumnConstraint):
                            is_nullable = False
                        elif isinstance(kind, exp.CheckColumnConstraint):
                            this = kind.this
                            # IN (...) → choices
                            if isinstance(this, exp.In):
                                values: list[str] = []
                                for v in this.args.get("expressions") or []:
                                    if isinstance(v, exp.Literal):
                                        values.append(str(v.this))
                                if values:
                                    check_choices[col_name] = values

                    fields.append(SchemaField(
                        name=col_name,
                        field_type=raw_type_str,
                        playground_type=_xsd_to_playground(xsd),
                        is_primary_key=is_pk,
                        is_nullable=is_nullable,
                        max_length=max_length,
                    ))

                elif isinstance(expr, exp.PrimaryKey):
                    # Table-level PRIMARY KEY (col1, col2, ...).
                    for col in expr.args.get("expressions") or []:
                        if isinstance(col, exp.Column):
                            pk_columns.add(col.name)
                        elif isinstance(col, exp.Identifier):
                            pk_columns.add(col.name)

                elif isinstance(expr, exp.ForeignKey):
                    # FK column on this table → referenced table.
                    cols = [
                        c.name if isinstance(c, exp.Identifier) else getattr(c, "name", "")
                        for c in expr.args.get("expressions") or []
                    ]
                    ref = expr.args.get("reference")
                    ref_table = ""
                    if ref is not None:
                        ref_inner = ref.this
                        if isinstance(ref_inner, exp.Schema):
                            ref_table_node = ref_inner.this
                        else:
                            ref_table_node = ref_inner
                        if isinstance(ref_table_node, exp.Table):
                            ref_table = ref_table_node.name
                        else:
                            ref_table = str(ref_table_node) if ref_table_node else ""
                    for col_name in cols:
                        if not col_name:
                            continue
                        relationships.append(SchemaRelationship(
                            field_name=col_name,
                            from_model=table_name,
                            to_model=ref_table,
                        ))

                elif isinstance(expr, exp.Constraint):
                    # CHECK named at table level; rare in tutorial-grade
                    # DDL — column-level CHECK above is the common form.
                    pass

            # Apply table-level PK to the relevant SchemaFields.
            if pk_columns:
                for f in fields:
                    if f.name in pk_columns:
                        f.is_primary_key = True

            # Apply CHECK IN (...) choices to the relevant SchemaFields.
            for f in fields:
                if f.name in check_choices:
                    f.choices_values = list(check_choices[f.name])

            models.append(SchemaModel(
                name=table_name,
                fields=fields,
                relationships=relationships,
                source_file=str(path),
            ))

    return SchemaResult(models=models, source_dir=source_dir)
