"""Regression test: ensure the core engine in src/ontozense/ remains
domain-agnostic and contains no banking/NPL/risk terms.

This test enforces the design principle that the engine works for any
business domain (healthcare, manufacturing, retail, regulatory compliance,
etc.) and that NPL/banking content lives only in tests/ and docs/.

If you legitimately need to add a banking-related term to a docstring or
comment, add it to ALLOWED_OCCURRENCES below with justification.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

SRC_ROOT = Path(__file__).parent.parent / "src" / "ontozense"

# Banned domain-specific terms that must not appear in src/ontozense/.
# Word-boundary regex matches to avoid false positives like "default value".
BANNED_TERMS = [
    "npl",
    "borrower",
    "collateral",
    "forbearance",
    "enforcement",
    "basel",
    "ifrs",
    "finrep",
    "eba",
    "counterparty",
    "nplonto",
    "opennpl",
    "obligor",
]

# Explicit allowlist for any legitimate matches (file_path, term, reason).
# Empty for now — should stay empty unless there's a strong reason.
ALLOWED_OCCURRENCES: set[tuple[str, str]] = set()


def _scan_file(path: Path) -> list[tuple[int, str, str]]:
    """Return list of (line_no, term, line_text) for any banned term hits."""
    hits = []
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return hits
    for line_no, line in enumerate(text.splitlines(), start=1):
        lower = line.lower()
        for term in BANNED_TERMS:
            # Word-boundary match to avoid false positives
            pattern = r"\b" + re.escape(term) + r"\b"
            if re.search(pattern, lower):
                hits.append((line_no, term, line.strip()))
    return hits


def test_no_banking_terms_in_src():
    """No banking/NPL terms should appear anywhere in src/ontozense/."""
    leaks: list[str] = []
    for py_file in SRC_ROOT.rglob("*.py"):
        relative = py_file.relative_to(SRC_ROOT.parent.parent)
        for line_no, term, line in _scan_file(py_file):
            key = (str(relative).replace("\\", "/"), term)
            if key in ALLOWED_OCCURRENCES:
                continue
            leaks.append(f"{relative}:{line_no}: '{term}' in: {line}")

    for yaml_file in SRC_ROOT.rglob("*.yaml"):
        relative = yaml_file.relative_to(SRC_ROOT.parent.parent)
        for line_no, term, line in _scan_file(yaml_file):
            key = (str(relative).replace("\\", "/"), term)
            if key in ALLOWED_OCCURRENCES:
                continue
            leaks.append(f"{relative}:{line_no}: '{term}' in: {line}")

    if leaks:
        msg = (
            "Found banking/NPL terms in core engine. The engine must be "
            "domain-agnostic. Move domain-specific content to tests/ or docs/.\n\n"
            + "\n".join(leaks)
        )
        pytest.fail(msg)
