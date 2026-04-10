"""Tests for the per-domain append-only log."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pytest


class TestAppendLog:
    def test_creates_log_file(self, tmp_path):
        from ontozense.log import append_log

        domain = tmp_path / "npl"
        result = append_log(domain, "extract-a", source="basel.pdf", concepts=47)
        assert result.exists()
        assert result.name == "log.md"
        assert result.parent == domain

    def test_creates_domain_dir_if_missing(self, tmp_path):
        from ontozense.log import append_log

        domain = tmp_path / "new_domain"
        assert not domain.exists()
        append_log(domain, "init")
        assert domain.exists()

    def test_creates_nested_domain_dir(self, tmp_path):
        from ontozense.log import append_log

        domain = tmp_path / "kb" / "npl" / "v1"
        append_log(domain, "init")
        assert domain.exists()
        assert (domain / "log.md").exists()

    def test_format_grep_parseable(self, tmp_path):
        from ontozense.log import append_log

        domain = tmp_path / "npl"
        log_path = append_log(domain, "extract-a", source="basel.pdf", concepts=47)
        content = log_path.read_text(encoding="utf-8")
        # Must start with the prefix pattern
        assert content.startswith("## [")
        # Operation name present
        assert "extract-a" in content
        # Pipe-separated key=value fields
        assert "source=basel.pdf" in content
        assert "concepts=47" in content
        assert " | " in content
        # Single line ending with newline
        assert content.endswith("\n")
        # Exactly one line
        non_empty = [ln for ln in content.split("\n") if ln.strip()]
        assert len(non_empty) == 1

    def test_appends_multiple_entries(self, tmp_path):
        from ontozense.log import append_log

        domain = tmp_path / "npl"
        append_log(domain, "extract-a", source="doc1.pdf", concepts=10)
        append_log(domain, "extract-a", source="doc2.pdf", concepts=20)
        append_log(domain, "fuse", sources="A+B")

        content = (domain / "log.md").read_text(encoding="utf-8")
        lines = [ln for ln in content.split("\n") if ln.startswith("## ")]
        assert len(lines) == 3
        assert "doc1.pdf" in lines[0]
        assert "doc2.pdf" in lines[1]
        assert "fuse" in lines[2]

    def test_explicit_date_timestamp(self, tmp_path):
        from ontozense.log import append_log

        domain = tmp_path / "npl"
        log_path = append_log(domain, "extract-a", timestamp=date(2026, 4, 10))
        content = log_path.read_text(encoding="utf-8")
        assert "[2026-04-10]" in content

    def test_explicit_datetime_timestamp(self, tmp_path):
        from ontozense.log import append_log

        domain = tmp_path / "npl"
        log_path = append_log(
            domain, "extract-a", timestamp=datetime(2026, 4, 10, 15, 30)
        )
        content = log_path.read_text(encoding="utf-8")
        # Datetimes are formatted as date only (we want grep-friendly day-level grouping)
        assert "[2026-04-10]" in content
        assert "15:30" not in content

    def test_string_timestamp_passthrough(self, tmp_path):
        from ontozense.log import append_log

        domain = tmp_path / "npl"
        log_path = append_log(domain, "extract-a", timestamp="2026-Q2-W15")
        content = log_path.read_text(encoding="utf-8")
        assert "[2026-Q2-W15]" in content

    def test_default_timestamp_today(self, tmp_path):
        from ontozense.log import append_log

        domain = tmp_path / "npl"
        log_path = append_log(domain, "extract-a")
        content = log_path.read_text(encoding="utf-8")
        assert f"[{date.today().isoformat()}]" in content

    def test_no_fields_only_op(self, tmp_path):
        from ontozense.log import append_log

        domain = tmp_path / "npl"
        log_path = append_log(domain, "init")
        content = log_path.read_text(encoding="utf-8")
        # No pipes when there are no fields
        assert " | " not in content
        assert content.rstrip().endswith("init")

    def test_value_with_newline_sanitized(self, tmp_path):
        from ontozense.log import append_log

        domain = tmp_path / "npl"
        log_path = append_log(domain, "extract-a", error="line one\nline two")
        content = log_path.read_text(encoding="utf-8")
        # The entry must remain one line
        non_empty_lines = [ln for ln in content.split("\n") if ln.strip()]
        assert len(non_empty_lines) == 1
        assert "line one line two" in content

    def test_value_with_pipe_sanitized(self, tmp_path):
        from ontozense.log import append_log

        domain = tmp_path / "npl"
        log_path = append_log(domain, "extract-a", path="a|b|c")
        content = log_path.read_text(encoding="utf-8")
        # Value-internal pipes should NOT survive (they would break grep parsing)
        # but the field-separator pipes should still be there
        assert "path=a/b/c" in content

    def test_numeric_values_serialized(self, tmp_path):
        from ontozense.log import append_log

        domain = tmp_path / "npl"
        log_path = append_log(
            domain,
            "extract-a",
            count=42,
            confidence=0.732,
            ratio=1e-3,
        )
        content = log_path.read_text(encoding="utf-8")
        assert "count=42" in content
        assert "confidence=0.732" in content

    def test_boolean_values_serialized(self, tmp_path):
        from ontozense.log import append_log

        domain = tmp_path / "npl"
        log_path = append_log(domain, "lint", clean=True, fatal=False)
        content = log_path.read_text(encoding="utf-8")
        assert "clean=True" in content
        assert "fatal=False" in content

    def test_none_value_serialized(self, tmp_path):
        from ontozense.log import append_log

        domain = tmp_path / "npl"
        log_path = append_log(domain, "extract-a", note=None)
        content = log_path.read_text(encoding="utf-8")
        assert "note=None" in content

    def test_append_does_not_truncate_existing_log(self, tmp_path):
        from ontozense.log import append_log

        domain = tmp_path / "npl"
        domain.mkdir()
        log_path = domain / "log.md"
        log_path.write_text("## [2026-01-01] init\n", encoding="utf-8")

        append_log(domain, "extract-a", concepts=10)

        content = log_path.read_text(encoding="utf-8")
        assert "2026-01-01" in content
        assert "init" in content
        assert "extract-a" in content

    def test_grep_simulation_by_op(self, tmp_path):
        """Simulate ``grep "extract-a" log.md`` returning the right entries."""
        from ontozense.log import append_log

        domain = tmp_path / "npl"
        append_log(domain, "extract-a", source="doc1.pdf", conflicts=0)
        append_log(domain, "extract-a", source="doc2.pdf", conflicts=3)
        append_log(domain, "fuse", sources="A+B", conflicts=1)
        append_log(domain, "lint", orphans=2)

        content = (domain / "log.md").read_text(encoding="utf-8")
        extract_lines = [ln for ln in content.split("\n") if "extract-a" in ln]
        assert len(extract_lines) == 2

        fuse_lines = [ln for ln in content.split("\n") if " fuse " in ln]
        assert len(fuse_lines) == 1

        lint_lines = [ln for ln in content.split("\n") if " lint " in ln]
        assert len(lint_lines) == 1

    def test_grep_simulation_by_field_value(self, tmp_path):
        """Simulate ``grep "conflicts=[1-9]" log.md`` finding non-zero conflicts."""
        from ontozense.log import append_log

        domain = tmp_path / "npl"
        append_log(domain, "extract-a", source="doc1.pdf", conflicts=0)
        append_log(domain, "extract-a", source="doc2.pdf", conflicts=3)
        append_log(domain, "fuse", sources="A+B", conflicts=1)

        content = (domain / "log.md").read_text(encoding="utf-8")
        # Lines with conflicts > 0
        nonzero = [
            ln for ln in content.split("\n")
            if "conflicts=" in ln and "conflicts=0" not in ln
        ]
        assert len(nonzero) == 2

    def test_returned_path_is_writable(self, tmp_path):
        from ontozense.log import append_log

        domain = tmp_path / "npl"
        log_path = append_log(domain, "init")
        assert log_path.is_file()
        # We should be able to read it
        assert log_path.read_text(encoding="utf-8") != ""

    def test_field_order_preserved(self, tmp_path):
        """Field insertion order should be preserved in the output line."""
        from ontozense.log import append_log

        domain = tmp_path / "npl"
        log_path = append_log(
            domain,
            "extract-a",
            source="basel.pdf",
            concepts=47,
            relationships=23,
            confidence_avg=0.71,
        )
        content = log_path.read_text(encoding="utf-8")
        # source should come before concepts which should come before relationships
        i_source = content.index("source=")
        i_concepts = content.index("concepts=")
        i_rels = content.index("relationships=")
        i_conf = content.index("confidence_avg=")
        assert i_source < i_concepts < i_rels < i_conf
