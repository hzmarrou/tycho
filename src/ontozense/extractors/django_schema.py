"""Django model schema parser.

Parses Django model .py files to extract database schema information
without importing Django or requiring a running database.
Uses AST parsing to read model definitions statically.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ─── Django field type → Playground property type mapping ─────────────────────

DJANGO_TYPE_MAP = {
    "TextField": "string",
    "CharField": "string",
    "SlugField": "string",
    "EmailField": "string",
    "URLField": "string",
    "UUIDField": "string",
    "FilePathField": "string",
    "IntegerField": "integer",
    "SmallIntegerField": "integer",
    "BigIntegerField": "integer",
    "PositiveIntegerField": "integer",
    "PositiveSmallIntegerField": "integer",
    "AutoField": "integer",
    "BigAutoField": "integer",
    "FloatField": "double",
    "DecimalField": "decimal",
    "BooleanField": "boolean",
    "NullBooleanField": "boolean",
    "DateField": "date",
    "DateTimeField": "datetime",
    "TimeField": "string",
    "DurationField": "string",
    "BinaryField": "string",
    "JSONField": "string",
}


@dataclass
class SchemaField:
    """A parsed Django model field.

    The ``id`` and ``entity_type`` fields are populated only when a
    profile is loaded by the parser (constrained mode). Empty in
    unconstrained mode.
    """
    name: str
    field_type: str  # Django field type (e.g. "TextField", "IntegerField")
    playground_type: str  # Mapped Playground type
    is_primary_key: bool = False
    is_nullable: bool = False
    help_text: str = ""
    choices_var: str = ""  # Name of the choices variable (e.g. "ASSET_CLASS_CHOICES")
    choices_values: list[str] = field(default_factory=list)  # Resolved choice labels
    max_length: int | None = None
    # Profile-mode fields (empty in unconstrained mode):
    id: str = ""
    entity_type: str = ""


@dataclass
class SchemaRelationship:
    """A parsed Django ForeignKey / relationship."""
    field_name: str
    from_model: str
    to_model: str
    on_delete: str = "CASCADE"
    is_nullable: bool = False
    help_text: str = ""


@dataclass
class SchemaModel:
    """A parsed Django model (= database table).

    The ``id`` and ``entity_type`` fields are populated only when a
    profile is loaded by the parser (constrained mode). Empty in
    unconstrained mode.
    """
    name: str
    doc: str = ""
    fields: list[SchemaField] = field(default_factory=list)
    relationships: list[SchemaRelationship] = field(default_factory=list)
    source_file: str = ""
    # Profile-mode fields (empty in unconstrained mode):
    id: str = ""
    entity_type: str = ""


@dataclass
class SchemaResult:
    """Complete schema extraction result."""
    models: list[SchemaModel] = field(default_factory=list)
    source_dir: str = ""

    def get_model(self, name: str) -> SchemaModel | None:
        for m in self.models:
            if m.name.lower() == name.lower():
                return m
        return None


class DjangoSchemaParser:
    """Parses Django model files using AST to extract schema information.

    When a ``profile`` is provided (Phase 3 constrained mode), each
    parsed model and field gets:

      * a deterministic ``id`` via :func:`ontozense.core.identity.compute_id`
      * an ``entity_type`` resolved against the profile's declared types

    The model name is the primary signal for the entity_type. If the
    model name (after alias resolution) matches a profile entity type,
    that's used. Otherwise the entity_type stays empty for Phase 4
    validation to flag.

    When ``profile`` is None (default), behaviour is byte-identical to
    pre-Phase-3 commits.
    """

    def __init__(self, models_dir: str | Path, profile=None):
        """Initialize with path to Django app directory containing model files.

        Args:
            models_dir: Path to the Django app directory.
            profile: Optional Profile from ontozense.core.profile. When
                provided, parsed models and fields get deterministic IDs
                and entity_type resolution.
        """
        self.models_dir = Path(models_dir)
        self.profile = profile
        self._choices_cache: dict[str, list[str]] = {}

    def parse(self) -> SchemaResult:
        """Parse all model and choices files in the directory."""
        result = SchemaResult(source_dir=str(self.models_dir))

        # Skip files that are never models
        skip_files = {"__init__.py", "admin.py", "apps.py", "urls.py", "views.py", "tests.py"}

        # First pass: parse all choices files
        for choices_file in sorted(self.models_dir.glob("*_choices.py")):
            self._parse_choices_file(choices_file)

        # Second pass: parse all .py files for Django Model subclasses
        seen_names: set[str] = set()
        for py_file in sorted(self.models_dir.glob("*.py")):
            if py_file.name in skip_files or py_file.name.endswith("_choices.py"):
                continue
            models = self._parse_model_file(py_file)
            for m in models:
                if m.name not in seen_names:
                    result.models.append(m)
                    seen_names.add(m.name)

        # Profile-aware post-processing: applied only when a profile
        # is set. In unconstrained mode this branch is skipped and
        # the result is byte-identical to pre-Phase-3 output.
        if self.profile is not None:
            self._apply_profile(result)

        return result

    def _apply_profile(self, result: SchemaResult) -> None:
        """Resolve aliases, compute deterministic IDs for models + fields.

        Heuristic for entity_type resolution:
          * Take the model name, resolve through profile.alias_map
          * If the canonical name matches a profile entity_type, use it
          * Otherwise leave entity_type="" for Phase 4 validation

        Fields inherit their parent model's entity_type — they're
        properties of that entity, not entities in their own right.
        """
        from ..core.identity import compute_id

        for model in result.models:
            canonical_name = self.profile.resolve_alias(model.name)
            model.name = canonical_name

            # Map model name to entity_type via the profile
            if self.profile.is_known_type(canonical_name):
                model.entity_type = canonical_name

            # Compute model ID — even with unknown entity_type, we use
            # the model name itself as the ID type prefix, so cross-
            # source consolidation can still link it.
            id_type = model.entity_type or canonical_name
            try:
                model.id = compute_id(
                    id_type,
                    canonical_name,
                    hash_length=self.profile.id_format.hash_length,
                )
            except ValueError:
                model.id = ""

            # Fields inherit the parent's entity_type (they're properties
            # of that entity). Each field gets its own deterministic ID
            # using "<model_id>.<field_name>" semantics — keeps fields
            # uniquely identified across the whole schema.
            for f in model.fields:
                f.entity_type = model.entity_type
                # Field ID combines model + field via colon to avoid
                # collisions with same-named fields on different models
                try:
                    f.id = compute_id(
                        id_type,
                        f"{canonical_name}:{f.name}",
                        hash_length=self.profile.id_format.hash_length,
                    )
                except ValueError:
                    f.id = ""

    def _parse_choices_file(self, filepath: Path) -> None:
        """Parse a *_choices.py file to extract choice tuples."""
        try:
            source = filepath.read_text(encoding="utf-8")
            tree = ast.parse(source)
        except (SyntaxError, UnicodeDecodeError):
            return

        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id.endswith("_CHOICES"):
                        values = self._extract_choice_labels(node.value)
                        if values:
                            self._choices_cache[target.id] = values

    def _extract_choice_labels(self, node: ast.expr) -> list[str]:
        """Extract human-readable labels from a choices list like [(0, 'Label'), ...]."""
        labels = []
        if isinstance(node, ast.List):
            for elt in node.elts:
                if isinstance(elt, ast.Tuple) and len(elt.elts) >= 2:
                    label_node = elt.elts[1]
                    if isinstance(label_node, ast.Constant) and isinstance(label_node.value, str):
                        # Clean up labels: remove "(a) ", "(b) " prefixes
                        label = re.sub(r"^\([a-z]\)\s*", "", label_node.value).strip()
                        labels.append(label)
        return labels

    def _parse_model_file(self, filepath: Path) -> list[SchemaModel]:
        """Parse a Django model .py file and extract model definitions."""
        try:
            source = filepath.read_text(encoding="utf-8")
            tree = ast.parse(source)
        except (SyntaxError, UnicodeDecodeError):
            return []

        models = []
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.ClassDef):
                # Check if it's a Django Model subclass
                is_model = any(
                    (isinstance(base, ast.Attribute) and base.attr == "Model")
                    or (isinstance(base, ast.Name) and base.id == "Model")
                    for base in node.bases
                )
                if is_model:
                    model = self._parse_class(node, filepath)
                    if model:
                        models.append(model)

        return models

    def _parse_class(self, node: ast.ClassDef, filepath: Path) -> SchemaModel | None:
        """Parse a single Django Model class definition."""
        model = SchemaModel(
            name=node.name,
            doc=ast.get_docstring(node) or "",
            source_file=str(filepath.name),
        )

        for item in node.body:
            if isinstance(item, ast.Assign):
                for target in item.targets:
                    if isinstance(target, ast.Name):
                        field_info = self._parse_field_assignment(target.id, item.value, node.name)
                        if field_info:
                            if isinstance(field_info, SchemaField):
                                model.fields.append(field_info)
                            elif isinstance(field_info, SchemaRelationship):
                                model.relationships.append(field_info)

        return model

    def _parse_field_assignment(
        self, field_name: str, value: ast.expr, model_name: str
    ) -> SchemaField | SchemaRelationship | None:
        """Parse a field assignment like `name = models.CharField(...)`."""
        if not isinstance(value, ast.Call):
            return None

        # Get the field type name
        field_type = self._get_field_type(value.func)
        if not field_type:
            return None

        # Parse keyword arguments
        kwargs = self._parse_kwargs(value)

        # ForeignKey → relationship
        if field_type == "ForeignKey":
            to_model = self._get_first_arg(value)
            if to_model:
                return SchemaRelationship(
                    field_name=field_name,
                    from_model=model_name,
                    to_model=to_model,
                    on_delete=kwargs.get("on_delete", "CASCADE"),
                    is_nullable=kwargs.get("null") == "True",
                    help_text=kwargs.get("help_text", ""),
                )
            return None

        # OneToOneField → relationship
        if field_type == "OneToOneField":
            to_model = self._get_first_arg(value)
            if to_model:
                return SchemaRelationship(
                    field_name=field_name,
                    from_model=model_name,
                    to_model=to_model,
                    on_delete=kwargs.get("on_delete", "CASCADE"),
                    is_nullable=kwargs.get("null") == "True",
                    help_text=kwargs.get("help_text", ""),
                )
            return None

        # ManyToManyField → relationship
        if field_type == "ManyToManyField":
            to_model = self._get_first_arg(value)
            if to_model:
                return SchemaRelationship(
                    field_name=field_name,
                    from_model=model_name,
                    to_model=to_model,
                    is_nullable=True,
                    help_text=kwargs.get("help_text", ""),
                )
            return None

        # Regular data field
        playground_type = DJANGO_TYPE_MAP.get(field_type, "string")

        # Check for choices → enum
        choices_var = kwargs.get("choices", "")
        choices_values: list[str] = []
        if choices_var and choices_var in self._choices_cache:
            choices_values = self._choices_cache[choices_var]
            playground_type = "enum"

        # Check for primary_key
        is_pk = kwargs.get("primary_key") == "True"

        # Clean help_text (strip HTML)
        help_text = kwargs.get("help_text", "")
        help_text = re.sub(r"<[^>]+>", "", help_text).strip()

        return SchemaField(
            name=field_name,
            field_type=field_type,
            playground_type=playground_type,
            is_primary_key=is_pk,
            is_nullable=kwargs.get("null") == "True" or kwargs.get("blank") == "True",
            help_text=help_text,
            choices_var=choices_var,
            choices_values=choices_values,
            max_length=int(kwargs["max_length"]) if "max_length" in kwargs else None,
        )

    def _get_field_type(self, func: ast.expr) -> str | None:
        """Extract field type name from models.CharField etc."""
        if isinstance(func, ast.Attribute):
            return func.attr
        if isinstance(func, ast.Name):
            return func.id
        return None

    def _get_first_arg(self, call: ast.Call) -> str | None:
        """Get the first positional argument (e.g., the target model in ForeignKey)."""
        if call.args:
            arg = call.args[0]
            if isinstance(arg, ast.Name):
                return arg.id
            if isinstance(arg, ast.Constant):
                return str(arg.value)
        return None

    def _parse_kwargs(self, call: ast.Call) -> dict[str, str]:
        """Parse keyword arguments from a function call."""
        kwargs: dict[str, str] = {}
        for kw in call.keywords:
            if kw.arg is None:
                continue
            if isinstance(kw.value, ast.Constant):
                kwargs[kw.arg] = str(kw.value.value)
            elif isinstance(kw.value, ast.Name):
                kwargs[kw.arg] = kw.value.id
            elif isinstance(kw.value, ast.Attribute):
                kwargs[kw.arg] = kw.value.attr
        return kwargs


def parse_django_app(models_dir: str | Path) -> SchemaResult:
    """Convenience function to parse a Django app's models directory.

    Args:
        models_dir: Path to a Django app directory containing model files
            (one model class per .py file or a single models.py).
    """
    parser = DjangoSchemaParser(models_dir)
    return parser.parse()
