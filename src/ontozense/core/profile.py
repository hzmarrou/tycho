"""Profile loader for ontology-constrained extraction.

A **profile** is a per-domain artifact authored by the user that tells
Ontozense's extractors what entity types, predicates, required fields,
and verb canonicalisations apply to their domain. Profiles live OUTSIDE
the engine (typically under ``domains/<name>/profile/``) — Ontozense
ships only a loader and a spec.

This module is **Phase 1 foundation**. It loads and validates a
profile, but no existing extractor consumes it yet. Phase 2+ wires
the profile into Source A, then B/C/D.

Backward compatibility note: a profile is OPTIONAL. If no profile is
loaded, every extractor and the fusion layer behave exactly as today.
The presence of a profile only changes behaviour when explicitly
requested via the ``--profile`` CLI flag (added in Phase 2).

Profile directory layout (per ``docs/PROFILE_SPEC.md``)::

    profile/
    ├── schema.json          (REQUIRED — entities, predicates, IDs, aliases, verbs)
    ├── prompt_fragment.md   (Source A only — constrained extraction prompt)
    ├── alias_map.json       (OPTIONAL — overrides/extends schema.alias_map)
    └── validation_rules.json (OPTIONAL — custom rules beyond schema)

Only ``schema.json`` is required. Everything else is optional and
extends the schema's defaults.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ─── Dataclasses ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ProfileAttribute:
    """A typed property declaration on an entity type (Phase C).

    Mirrors the runtime ``Attribute`` dataclass produced by Phase A /
    Phase B extraction so a profile-declared attribute is structurally
    comparable to an extracted one. Validation rule VR007 (PR C2)
    consumes the ``required`` flag and the ``name`` field.
    """
    name: str
    xsd_type: str
    description: str = ""
    required: bool = False
    is_id: bool = False
    is_multivalued: bool = False
    enum_values: list[str] = field(default_factory=list)

    @property
    def name_key(self) -> str:
        """Lowercased + stripped name, used for case-insensitive lookup."""
        return self.name.strip().lower()


@dataclass(frozen=True)
class EntityType:
    """An entity type declared in a profile's schema.

    Attributes
    ----------
    name : str
        The canonical type name (e.g. "Metric", "Industry").
    required_fields : list[str]
        Fields that must be present on every instance of this type.
    optional_fields : list[str]
        Fields that may be present.
    subtypes : list[str]
        Sub-classifications (e.g. Metric has DirectMetric, CalculatedMetric,
        InputMetric). Empty for leaf types.
    attributes : list[ProfileAttribute]
        Typed property declarations introduced in Phase C. Defaults to
        an empty list so pre-Phase-C profiles parse unchanged.
    """
    name: str
    required_fields: list[str] = field(default_factory=list)
    optional_fields: list[str] = field(default_factory=list)
    subtypes: list[str] = field(default_factory=list)
    attributes: list[ProfileAttribute] = field(default_factory=list)

    @property
    def all_fields(self) -> list[str]:
        return list(self.required_fields) + list(self.optional_fields)


@dataclass(frozen=True)
class Predicate:
    """A relationship predicate declared in a profile's schema.

    Attributes
    ----------
    name : str
        Canonical predicate name (e.g. "ReportUsing", "IsCalculatedBy").
    subject_types : list[str]
        Entity types that may appear as subjects of this predicate.
    object_types : list[str]
        Entity types that may appear as objects.
    cardinality : str
        One of "1:1", "1:N", "N:1", "N:N".
    """
    name: str
    subject_types: list[str] = field(default_factory=list)
    object_types: list[str] = field(default_factory=list)
    cardinality: str = "N:N"


@dataclass(frozen=True)
class IdFormat:
    """ID generation strategy for a profile.

    Currently only ``"type_label_hash"`` is supported (see
    ``ontozense.core.identity.compute_id``). Future strategies are an
    extension point.
    """
    strategy: str = "type_label_hash"
    pattern: str = "{entity_type_lower}_{normalized_label}_{hash6}"
    hash_length: int = 6


@dataclass(frozen=True)
class Profile:
    """A loaded, validated profile.

    Loaded from ``profile/schema.json`` plus optional sidecar files.
    Frozen because profiles are configuration: passed around, never
    mutated.
    """
    profile_name: str
    profile_version: str
    description: str
    entity_types: dict[str, EntityType] = field(default_factory=dict)
    predicates: dict[str, Predicate] = field(default_factory=dict)
    id_format: IdFormat = field(default_factory=IdFormat)
    alias_map: dict[str, str] = field(default_factory=dict)
    canonical_verbs: dict[str, str] = field(default_factory=dict)
    prompt_fragment: str = ""

    # Where this was loaded from (for provenance / log entries).
    source_path: Path | None = None

    # ── Convenience lookups ──

    def get_entity_type(self, type_name: str) -> EntityType | None:
        """Return the EntityType for ``type_name``, accounting for subtypes.

        If ``type_name`` is a subtype (e.g. "DirectMetric"), returns the
        parent EntityType ("Metric"). Returns None if no match.

        Lookup is **case-insensitive** to align with
        :func:`ontozense.core.identity.compute_id` (which lowercases its
        type input). Without this, a record declared with
        ``entity_type: "concept"`` (lowercase) would be flagged as
        unknown by ``is_known_type`` while still getting a valid
        deterministic ID — an inconsistency.
        """
        target = type_name.strip().lower()
        for et in self.entity_types.values():
            if et.name.lower() == target:
                return et
            if any(sub.lower() == target for sub in et.subtypes):
                return et
        return None

    def is_known_type(self, type_name: str) -> bool:
        """Whether ``type_name`` is declared as an entity type or subtype.

        Case-insensitive — see ``get_entity_type``.
        """
        return self.get_entity_type(type_name) is not None

    def is_known_predicate(self, predicate_name: str) -> bool:
        """Whether ``predicate_name`` is in the canonical predicate set.

        Case-insensitive for parity with ``is_known_type``.
        """
        target = predicate_name.strip().lower()
        return any(p.lower() == target for p in self.predicates)

    def canonicalise_verb(self, verb: str) -> str:
        """Map a free-form verb phrase to a canonical predicate name.

        Returns the input unchanged if no mapping exists. Lookup is
        case-insensitive on the input verb.
        """
        return self.canonical_verbs.get(verb.strip().lower(), verb)

    def resolve_alias(self, label: str) -> str:
        """Map a label to its canonical form via the alias map.

        Returns the input unchanged if no mapping exists. Lookup is
        case-insensitive on the input label.
        """
        return self.alias_map.get(label.strip().lower(), label)


# ─── Loader ──────────────────────────────────────────────────────────────────


class ProfileError(Exception):
    """Raised when profile loading or validation fails.

    Distinct from ValueError so callers can catch profile-specific
    failures (and the CLI can surface a clean error) without masking
    other configuration bugs.
    """


# Required top-level keys in schema.json
_REQUIRED_SCHEMA_KEYS = {"profile_name", "profile_version", "entity_types", "predicates"}

# Supported id_format strategies
_SUPPORTED_ID_STRATEGIES = {"type_label_hash"}

# Accepted XSD identifiers on ``entity_types[*].attributes[*].xsd_type``.
# Aligned with the Phase A XSD mapping table in
# ``docs/PROPERTY_EXTRACTION_DESIGN.md`` §5 so a profile-declared type
# is always one an extractor can produce.
_ACCEPTED_XSD_TYPES = frozenset({
    "xsd:string",
    "xsd:integer",
    "xsd:decimal",
    "xsd:double",
    "xsd:date",
    "xsd:time",
    "xsd:dateTime",
    "xsd:dateTimeStamp",
    "xsd:duration",
    "xsd:boolean",
    "xsd:base64Binary",
    "xsd:anyURI",
})


def load_profile(profile_path: str | Path) -> Profile:
    """Load and validate a profile from a directory.

    Parameters
    ----------
    profile_path : str or Path
        Directory containing at minimum ``schema.json``. Optional sidecar
        files (``prompt_fragment.md``, ``alias_map.json``,
        ``validation_rules.json``) are loaded if present.

    Returns
    -------
    Profile
        Validated profile, frozen.

    Raises
    ------
    ProfileError
        If the directory doesn't exist, schema.json is missing or
        invalid, or validation fails.
    """
    profile_path = Path(profile_path)

    if not profile_path.exists():
        raise ProfileError(f"Profile directory not found: {profile_path}")
    if not profile_path.is_dir():
        raise ProfileError(
            f"Profile path is not a directory: {profile_path}"
        )

    schema_file = profile_path / "schema.json"
    if not schema_file.exists():
        raise ProfileError(
            f"Profile is missing required schema.json at {schema_file}"
        )

    try:
        raw = json.loads(schema_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ProfileError(f"schema.json is not valid JSON: {e}") from e

    _validate_schema_top_level(raw, schema_file)
    entity_types = _parse_entity_types(raw["entity_types"])
    predicates = _parse_predicates(raw["predicates"], entity_types)
    id_format = _parse_id_format(raw.get("id_format", {}))

    # Aliases and canonical verbs may also live in schema.json or in
    # sidecar files. Sidecar wins on conflict (lets users keep schema
    # generic and overlay deployment-specific aliases).
    alias_map = _normalise_lower_dict(raw.get("alias_map", {}))
    canonical_verbs = _normalise_lower_dict(raw.get("canonical_verbs", {}))

    sidecar_aliases = profile_path / "alias_map.json"
    if sidecar_aliases.exists():
        try:
            sidecar = json.loads(sidecar_aliases.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise ProfileError(
                f"alias_map.json is not valid JSON: {e}"
            ) from e
        alias_map.update(_normalise_lower_dict(sidecar))

    prompt_fragment = ""
    pf = profile_path / "prompt_fragment.md"
    if pf.exists():
        prompt_fragment = pf.read_text(encoding="utf-8")

    return Profile(
        profile_name=raw["profile_name"],
        profile_version=raw["profile_version"],
        description=raw.get("description", ""),
        entity_types=entity_types,
        predicates=predicates,
        id_format=id_format,
        alias_map=alias_map,
        canonical_verbs=canonical_verbs,
        prompt_fragment=prompt_fragment,
        source_path=profile_path,
    )


# ─── Validation helpers ──────────────────────────────────────────────────────


def _validate_schema_top_level(raw: Any, schema_file: Path) -> None:
    if not isinstance(raw, dict):
        raise ProfileError(
            f"schema.json must be a JSON object at the top level "
            f"(got {type(raw).__name__})"
        )
    missing = _REQUIRED_SCHEMA_KEYS - set(raw.keys())
    if missing:
        raise ProfileError(
            f"schema.json missing required keys: {sorted(missing)}"
        )
    if not raw["profile_name"] or not isinstance(raw["profile_name"], str):
        raise ProfileError("profile_name must be a non-empty string")
    if not raw["profile_version"] or not isinstance(raw["profile_version"], str):
        raise ProfileError("profile_version must be a non-empty string")


def _parse_entity_types(raw: Any) -> dict[str, EntityType]:
    if not isinstance(raw, dict) or not raw:
        raise ProfileError(
            "entity_types must be a non-empty object mapping type "
            "names to specs"
        )
    out: dict[str, EntityType] = {}
    for name, spec in raw.items():
        if not isinstance(spec, dict):
            raise ProfileError(
                f"entity_types[{name!r}] must be an object"
            )
        out[name] = EntityType(
            name=name,
            required_fields=_string_list(spec.get("required", []), f"entity_types[{name}].required"),
            optional_fields=_string_list(spec.get("optional", []), f"entity_types[{name}].optional"),
            subtypes=_string_list(spec.get("subtypes", []), f"entity_types[{name}].subtypes"),
            attributes=_parse_profile_attributes(name, spec.get("attributes", [])),
        )

    # Reject subtype/top-level name collisions. If "DirectMetric" is
    # both declared as a top-level entity_type and as a subtype of
    # another type (e.g. "Metric"), get_entity_type("DirectMetric")
    # would return whichever the dict-iteration-order surfaces first
    # — non-deterministic and a real correctness bug. Fail loudly at
    # load time so the author notices the conflict.
    top_level = set(out.keys())
    for et in out.values():
        for sub in et.subtypes:
            if sub in top_level and sub != et.name:
                raise ProfileError(
                    f"Subtype name collision: {sub!r} is declared as "
                    f"a subtype of {et.name!r} but is also a top-level "
                    f"entity type. Each name must appear in exactly "
                    f"one role — either top-level or subtype, not both."
                )
            # Also reject duplicate subtypes across different parents,
            # which would create the same ambiguity.
            for other_et in out.values():
                if other_et.name == et.name:
                    continue
                if sub in other_et.subtypes:
                    raise ProfileError(
                        f"Subtype name collision: {sub!r} is declared as "
                        f"a subtype of both {et.name!r} and "
                        f"{other_et.name!r}. Each subtype must belong "
                        f"to exactly one parent."
                    )

    return out


def _parse_predicates(
    raw: Any,
    entity_types: dict[str, EntityType],
) -> dict[str, Predicate]:
    if not isinstance(raw, dict):
        raise ProfileError("predicates must be an object")

    # Build set of valid type names (entity types + subtypes)
    valid_types = set(entity_types.keys())
    for et in entity_types.values():
        valid_types.update(et.subtypes)

    out: dict[str, Predicate] = {}
    for name, spec in raw.items():
        if not isinstance(spec, dict):
            raise ProfileError(f"predicates[{name!r}] must be an object")

        subject_types = _string_list(
            spec.get("subject_types", []),
            f"predicates[{name}].subject_types",
        )
        object_types = _string_list(
            spec.get("object_types", []),
            f"predicates[{name}].object_types",
        )

        # Cross-validate that referenced types are declared
        for t in subject_types + object_types:
            if t not in valid_types:
                raise ProfileError(
                    f"predicates[{name!r}] references undeclared entity "
                    f"type {t!r}. Declared types: {sorted(valid_types)}"
                )

        cardinality = spec.get("cardinality", "N:N")
        if cardinality not in {"1:1", "1:N", "N:1", "N:N"}:
            raise ProfileError(
                f"predicates[{name!r}].cardinality must be one of "
                f"1:1, 1:N, N:1, N:N (got {cardinality!r})"
            )

        out[name] = Predicate(
            name=name,
            subject_types=subject_types,
            object_types=object_types,
            cardinality=cardinality,
        )
    return out


def _parse_id_format(raw: Any) -> IdFormat:
    if not isinstance(raw, dict):
        raise ProfileError("id_format must be an object (or omitted)")

    strategy = raw.get("strategy", "type_label_hash")
    if strategy not in _SUPPORTED_ID_STRATEGIES:
        raise ProfileError(
            f"id_format.strategy {strategy!r} not supported. "
            f"Supported: {sorted(_SUPPORTED_ID_STRATEGIES)}"
        )

    pattern = raw.get("pattern", "{entity_type_lower}_{normalized_label}_{hash6}")
    hash_length = raw.get("hash_length", 6)

    if not isinstance(hash_length, int) or hash_length < 4:
        raise ProfileError(
            f"id_format.hash_length must be an integer >= 4 "
            f"(got {hash_length!r})"
        )

    return IdFormat(strategy=strategy, pattern=pattern, hash_length=hash_length)


def _string_list(value: Any, where: str) -> list[str]:
    if not isinstance(value, list):
        raise ProfileError(f"{where} must be a list of strings")
    out: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ProfileError(
                f"{where} contains invalid entry {item!r}; expected non-empty string"
            )
        out.append(item)
    return out


def _parse_profile_attributes(
    entity_type_name: str,
    raw: Any,
) -> list[ProfileAttribute]:
    """Parse ``entity_types[X].attributes`` into typed ``ProfileAttribute`` records.

    Phase C addition. Pre-Phase-C profiles omit the ``attributes`` key
    entirely; callers pass ``spec.get("attributes", [])`` so omission
    arrives here as an empty list and produces an empty result.

    Validation rules (see ``docs/PROPERTY_EXTRACTION_DESIGN.md`` §5
    Phase C contracts, "Loader validation rules added by Phase C"):

    * ``raw`` must be a list (omitted = empty list, which is valid).
    * Every entry must be an object.
    * ``name`` and ``xsd_type`` must be present and non-empty strings.
    * ``xsd_type`` must be in :data:`_ACCEPTED_XSD_TYPES`.
    * ``description`` (when present) must be a string.
    * ``required`` / ``is_id`` / ``is_multivalued`` (when present) must be bools.
    * ``enum_values`` (when present) must be a list of strings.
    * Within one entity type, attribute ``name`` values must be
      case-insensitively unique.
    * At most one entry per entity type may set ``is_id: true``.
    """
    where = f"entity_types[{entity_type_name!r}].attributes"
    if not isinstance(raw, list):
        raise ProfileError(f"{where} must be a list (or omitted)")

    out: list[ProfileAttribute] = []
    seen_keys: set[str] = set()
    id_attr_names: list[str] = []

    for index, entry in enumerate(raw):
        loc = f"{where}[{index}]"
        if not isinstance(entry, dict):
            raise ProfileError(
                f"{loc} must be an object (got {type(entry).__name__})"
            )

        # name (required, non-empty string)
        if "name" not in entry:
            raise ProfileError(f"{loc}.name is required")
        name = entry["name"]
        if not isinstance(name, str) or not name.strip():
            raise ProfileError(
                f"{loc}.name must be a non-empty string (got {name!r})"
            )

        # xsd_type (required, non-empty string, in accepted set)
        if "xsd_type" not in entry:
            raise ProfileError(f"{loc}.xsd_type is required")
        xsd_type = entry["xsd_type"]
        if not isinstance(xsd_type, str) or not xsd_type.strip():
            raise ProfileError(
                f"{loc}.xsd_type must be a non-empty string (got {xsd_type!r})"
            )
        if xsd_type not in _ACCEPTED_XSD_TYPES:
            accepted = ", ".join(sorted(_ACCEPTED_XSD_TYPES))
            raise ProfileError(
                f"{loc}.xsd_type {xsd_type!r} is not an accepted XSD type. "
                f"Accepted values: {accepted}."
            )

        # description (optional, string)
        description = entry.get("description", "")
        if not isinstance(description, str):
            raise ProfileError(
                f"{loc}.description must be a string (got {type(description).__name__})"
            )

        # required / is_id / is_multivalued (optional, bool)
        required = _bool_flag(entry, "required", loc)
        is_id = _bool_flag(entry, "is_id", loc)
        is_multivalued = _bool_flag(entry, "is_multivalued", loc)

        # enum_values (optional, list[str])
        enum_values = _string_list(
            entry.get("enum_values", []),
            f"{loc}.enum_values",
        )

        attr = ProfileAttribute(
            name=name,
            xsd_type=xsd_type,
            description=description,
            required=required,
            is_id=is_id,
            is_multivalued=is_multivalued,
            enum_values=enum_values,
        )

        # Case-insensitive duplicate-name check
        if attr.name_key in seen_keys:
            raise ProfileError(
                f"{loc}.name duplicates an earlier entry "
                f"(case-insensitive match on {attr.name_key!r}). "
                f"Each attribute name within one entity type must be unique."
            )
        seen_keys.add(attr.name_key)

        if is_id:
            id_attr_names.append(name)

        out.append(attr)

    if len(id_attr_names) > 1:
        raise ProfileError(
            f"{where} declares more than one attribute with "
            f"is_id=true: {id_attr_names}. At most one is_id "
            f"attribute is allowed per entity type."
        )

    return out


def _bool_flag(entry: dict, key: str, loc: str) -> bool:
    """Read an optional bool flag from a parsed attribute object."""
    if key not in entry:
        return False
    value = entry[key]
    if not isinstance(value, bool):
        raise ProfileError(
            f"{loc}.{key} must be a bool (got {type(value).__name__}: {value!r})"
        )
    return value


def _normalise_lower_dict(raw: Any) -> dict[str, str]:
    """Lowercase keys for case-insensitive lookup. Values are kept as-is."""
    if not isinstance(raw, dict):
        raise ProfileError(
            f"Expected an object (str → str), got {type(raw).__name__}"
        )
    out: dict[str, str] = {}
    for k, v in raw.items():
        if not isinstance(k, str) or not isinstance(v, str):
            raise ProfileError(
                f"alias / verb maps must be str → str (got {k!r}: {v!r})"
            )
        out[k.strip().lower()] = v
    return out
