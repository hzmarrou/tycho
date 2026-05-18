"""Shared filter primitives for per-source ingesters.

Provides:

- ``glob_match`` — case-insensitive glob matching over a list of patterns.
- Default heuristic pattern lists for Source C (tables, columns)
  and Source D (paths, class patterns).
- ``column_is_suppressed`` — applies the Source C column suppression
  rule including the domain-bearing-prefix exception.
- ``load_source_config`` — loads + schema-validates a per-domain
  ``source-c.yaml`` / ``source-d.yaml``.

Per the design spec (§6.3, §7.3): defaults are baked in here.
Per-domain YAML overrides are loaded by the orchestrator and passed
to each ingester via its ``config`` argument.
"""

from __future__ import annotations

import fnmatch
from pathlib import Path
from typing import Any

import yaml


# ─── Source C defaults ────────────────────────────────────────────────────────

DEFAULT_SOURCE_C_TABLE_SUPPRESSIONS: list[str] = [
    "*_audit", "*_history", "*_log", "*_journal",
    "tmp_*", "bkp_*", "bak_*",
    "vw_*_audit",
]

DEFAULT_SOURCE_C_COLUMN_SUPPRESSIONS: list[str] = [
    # Timestamps (with domain-bearing-prefix override applied separately)
    "created_at", "updated_at", "modified_at",
    "*_at", "*_ts", "*_timestamp",
    # System metadata
    "etag", "row_version", "version", "_partition_*",
    "sys_*",
    # Tenant / soft-delete
    "tenant_id", "is_deleted", "deleted_at",
    # User attribution
    "created_by", "updated_by", "modified_by",
]

# Tokens that mark a column as domain-bearing even when its suffix
# matches a default suppression pattern. Matched as a prefix on the
# column name.
DOMAIN_BEARING_PREFIXES: list[str] = [
    "birth", "expiry", "expiration", "valuation", "issue", "maturity",
    "settlement", "value", "as_of", "effective", "report",
]


SOURCE_C_VALID_CONFIG_KEYS: set[str] = {
    "exclude_tables", "include_tables",
    "exclude_columns",
    "force_vocabulary", "force_entity",
}


# ─── Source D defaults ────────────────────────────────────────────────────────

DEFAULT_SOURCE_D_PATH_SUPPRESSIONS: list[str] = [
    "tests/**", "test/**",
    "mocks/**", "fixtures/**",
    "migrations/**", "vendor/**",
    "examples/**",
    "**/__pycache__/**",
    "**/test_*.py", "**/*_test.py",
    "**/conftest.py",
]

DEFAULT_SOURCE_D_CLASS_SUPPRESSIONS: list[str] = [
    "_*",          # Private (Python convention)
    "Meta", "Config",
]

SOURCE_D_VALID_CONFIG_KEYS: set[str] = {
    "exclude_paths", "exclude_classes", "include_classes",
    "force_vocabulary",
}


# ─── Glob primitives ──────────────────────────────────────────────────────────


def glob_match(name: str, patterns: list[str]) -> bool:
    """Return True if ``name`` matches any pattern in ``patterns``
    (case-insensitive). Empty patterns list returns False."""
    if not patterns:
        return False
    lowered = name.lower()
    return any(fnmatch.fnmatchcase(lowered, p.lower()) for p in patterns)


def path_match(path_str: str, patterns: list[str]) -> bool:
    """Return True if ``path_str`` (a POSIX-style path) matches any
    pattern in ``patterns``. Uses :class:`pathlib.PurePosixPath.match`
    for proper gitignore-style ``**`` directory semantics, and is
    case-insensitive per spec §7.4. Empty patterns list returns False.

    Both the path and each pattern are lower-cased before matching;
    the path string is expected to already use forward slashes
    (the caller is responsible for the normalisation, e.g.
    ``str(path).replace("\\\\", "/")``).
    """
    from pathlib import PurePosixPath

    if not patterns:
        return False
    lowered = path_str.lower()
    for p in patterns:
        if PurePosixPath(lowered).match(p.lower()):
            return True
    return False


def column_is_suppressed(
    column_name: str,
    user_exclude: list[str],
    user_include: list[str],
) -> bool:
    """Apply Source C column suppression rules.

    Suppress if:
      - matches a default suppression pattern AND not in ``user_include``, OR
      - matches a ``user_exclude`` pattern.

    BUT keep if the column name starts with a domain-bearing prefix
    (birth_date, expiry_date, etc.) — the prefix overrides the
    timestamp / `_at` default. The user can still force-exclude via
    ``user_exclude``.
    """
    lowered = column_name.lower()

    # User exclude always wins.
    if glob_match(column_name, user_exclude):
        return True

    # User include exempts from defaults.
    if glob_match(column_name, user_include):
        return False

    # Domain-bearing prefix exempts from defaults.
    if any(lowered.startswith(p) for p in DOMAIN_BEARING_PREFIXES):
        return False

    # Default suppression patterns.
    return glob_match(column_name, DEFAULT_SOURCE_C_COLUMN_SUPPRESSIONS)


# ─── YAML config loader ──────────────────────────────────────────────────────


class ConfigError(ValueError):
    """Raised when a per-domain YAML config has invalid structure."""


def load_source_config(path: Path) -> dict[str, Any]:
    """Load and validate a per-domain ``source-c.yaml`` or
    ``source-d.yaml`` file.

    Returns the inner dict (the value under the top-level ``source_c``
    or ``source_d`` key). Returns ``{}`` if the file doesn't exist or
    is empty.

    Raises :class:`ConfigError` if:
      - the YAML top level is not a mapping
      - the top-level mapping is non-empty but contains neither
        ``source_c`` nor ``source_d`` (catches typos like ``sourcec:``)
      - the top-level mapping contains BOTH ``source_c`` and ``source_d``
        (one config file describes one source)
      - the inner mapping contains keys outside the per-source
        allowed set
    """
    if not path.exists():
        return {}

    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if raw is None:
        # Empty file or explicit YAML null — nothing to validate.
        return {}

    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: top-level YAML must be a mapping")

    has_c = "source_c" in raw and isinstance(raw["source_c"], dict)
    has_d = "source_d" in raw and isinstance(raw["source_d"], dict)

    if has_c and has_d:
        raise ConfigError(
            f"{path}: both 'source_c' and 'source_d' present at the "
            f"top level; one config file must describe exactly one "
            f"source — split into source-c.yaml and source-d.yaml."
        )

    if not has_c and not has_d:
        raise ConfigError(
            f"{path}: top-level mapping must contain exactly one of "
            f"'source_c' or 'source_d'; got keys {sorted(raw.keys())}. "
            f"(Did you mean 'source_c'? Note the underscore.)"
        )

    if has_c:
        inner = raw["source_c"]
        valid = SOURCE_C_VALID_CONFIG_KEYS
    else:
        inner = raw["source_d"]
        valid = SOURCE_D_VALID_CONFIG_KEYS

    invalid_keys = set(inner.keys()) - valid
    if invalid_keys:
        raise ConfigError(
            f"{path}: invalid config keys {sorted(invalid_keys)}; "
            f"valid keys are {sorted(valid)}"
        )

    return inner
