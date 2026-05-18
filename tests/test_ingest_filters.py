"""Tests for shared filter primitives: glob matching + YAML config loader."""

import pytest
from pathlib import Path


def test_glob_match_basic():
    from ontozense.core.ingest.filters import glob_match

    assert glob_match("created_at", ["*_at"])
    assert glob_match("updated_at", ["*_at"])
    assert not glob_match("birth_date", ["*_at"])
    assert glob_match("customer_audit", ["*_audit"])
    assert glob_match("tmp_loans", ["tmp_*"])


def test_glob_match_case_insensitive():
    from ontozense.core.ingest.filters import glob_match

    assert glob_match("Created_At", ["*_at"])
    assert glob_match("CUSTOMER_AUDIT", ["*_audit"])


def test_glob_match_empty_patterns():
    from ontozense.core.ingest.filters import glob_match

    assert not glob_match("anything", [])


def test_default_source_c_table_patterns_drop_audit_tables():
    from ontozense.core.ingest.filters import DEFAULT_SOURCE_C_TABLE_SUPPRESSIONS

    assert "*_audit" in DEFAULT_SOURCE_C_TABLE_SUPPRESSIONS
    assert "*_history" in DEFAULT_SOURCE_C_TABLE_SUPPRESSIONS
    assert "tmp_*" in DEFAULT_SOURCE_C_TABLE_SUPPRESSIONS


def test_default_source_c_column_patterns_drop_audit_columns():
    from ontozense.core.ingest.filters import DEFAULT_SOURCE_C_COLUMN_SUPPRESSIONS

    assert "created_at" in DEFAULT_SOURCE_C_COLUMN_SUPPRESSIONS
    assert "*_at" in DEFAULT_SOURCE_C_COLUMN_SUPPRESSIONS
    assert "created_by" in DEFAULT_SOURCE_C_COLUMN_SUPPRESSIONS


def test_default_source_c_column_domain_bearing_overrides():
    """birth_date / expiry_date should NOT be suppressed by the
    timestamp default — they have domain-bearing prefixes."""
    from ontozense.core.ingest.filters import column_is_suppressed

    assert column_is_suppressed("created_at", [], [])
    assert column_is_suppressed("updated_at", [], [])
    assert not column_is_suppressed("birth_date", [], [])
    assert not column_is_suppressed("expiry_date", [], [])
    assert not column_is_suppressed("valuation_date", [], [])


def test_default_source_d_path_patterns():
    from ontozense.core.ingest.filters import DEFAULT_SOURCE_D_PATH_SUPPRESSIONS

    assert "tests/**" in DEFAULT_SOURCE_D_PATH_SUPPRESSIONS
    assert "**/test_*.py" in DEFAULT_SOURCE_D_PATH_SUPPRESSIONS
    assert "**/conftest.py" in DEFAULT_SOURCE_D_PATH_SUPPRESSIONS


def test_load_source_config_returns_empty_when_missing(tmp_path):
    from ontozense.core.ingest.filters import load_source_config

    cfg = load_source_config(tmp_path / "source-c.yaml")
    assert cfg == {}


def test_load_source_config_parses_yaml(tmp_path):
    from ontozense.core.ingest.filters import load_source_config

    path = tmp_path / "source-c.yaml"
    path.write_text(
        """
source_c:
  exclude_tables:
    - legacy_*
    - regional_*_archive
  include_tables:
    - audit_loan_status
  force_vocabulary:
    - country_lookup
""".strip(),
        encoding="utf-8",
    )
    cfg = load_source_config(path)
    assert cfg["exclude_tables"] == ["legacy_*", "regional_*_archive"]
    assert cfg["include_tables"] == ["audit_loan_status"]
    assert cfg["force_vocabulary"] == ["country_lookup"]


def test_load_source_config_rejects_invalid_keys(tmp_path):
    from ontozense.core.ingest.filters import load_source_config, ConfigError

    path = tmp_path / "source-c.yaml"
    path.write_text(
        "source_c:\n  exclude_tables: [x]\n  bogus_key: [y]\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError) as exc_info:
        load_source_config(path)
    assert "bogus_key" in str(exc_info.value)
