#!/usr/bin/env python3
"""Export a clean public Tycho distribution from this repo.

Assembles a curated subset of the repo — runtime code, the bundled NPL
example, and the user-facing tutorial — into ``dist/tycho-public/`` (or
a path supplied via ``--output``).

The export is deterministic: re-running on the same commit produces an
identical directory tree. The output is not committed to git (``dist/``
is already gitignored) — it is regenerated on demand.

Usage:

    python scripts/export_tycho_public.py
    python scripts/export_tycho_public.py --output build/tycho-public

The exported layout the consumer sees:

    dist/tycho-public/
    ├── README.md
    ├── pyproject.toml
    ├── src/ontozense/...
    ├── docs/
    │   └── ontozense-npl-tutorial.md
    └── domains/
        └── npl/
            └── sources/
                ├── npl-basel-guidelines.md   (Source A)
                ├── governance.json            (Source B)
                ├── npl-schema.sql             (Source C)
                └── npl-code/                  (Source D)

The four NPL sources are pulled from their canonical repo locations and
re-rooted under ``domains/npl/sources/`` so the bundle is self-contained
and the tutorial paths resolve against the bundled layout.
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Source → destination mapping. Sources are relative to the repo root.
# Destinations are relative to the export root (the output directory).
# Each tuple is (source_path, dest_path, kind) where ``kind`` is
# ``"file"`` or ``"tree"``.
MANIFEST: list[tuple[str, str, str]] = [
    # Runtime package.
    ("src/ontozense", "src/ontozense", "tree"),
    # Project metadata + entry doc.
    ("pyproject.toml", "pyproject.toml", "file"),
    ("README.md", "README.md", "file"),
    # README references this single image; ship it so the public README
    # renders correctly on GitHub. Other images under images/ are dev-only.
    ("images/tycho.png", "images/tycho.png", "file"),
    # User-facing tutorial.
    (
        "docs/ontozense-npl-tutorial.md",
        "docs/ontozense-npl-tutorial.md",
        "file",
    ),
    # NPL example — the four canonical sources, re-rooted under
    # domains/npl/sources/ for the bundled layout.
    (
        "tests/fixtures/npl-basel-guidelines.md",
        "domains/npl/sources/npl-basel-guidelines.md",
        "file",
    ),
    (
        "docs/governance_example.json",
        "domains/npl/sources/governance.json",
        "file",
    ),
    (
        "tests/fixtures/npl-schema.sql",
        "domains/npl/sources/npl-schema.sql",
        "file",
    ),
    (
        "tests/fixtures/synthetic_npl_code",
        "domains/npl/sources/npl-code",
        "tree",
    ),
]

# Patterns to drop when copying ``src/ontozense`` — keeps the runtime
# tree free of caches and editor artifacts.
EXCLUDE_PATTERNS = (
    "__pycache__",
    "*.pyc",
    "*.pyo",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
)


def _ignore(_dir: str, names: list[str]) -> set[str]:
    """``shutil.copytree`` ignore callable that strips cache/artifact dirs."""
    out: set[str] = set()
    for name in names:
        for pat in EXCLUDE_PATTERNS:
            if pat.startswith("*"):
                if name.endswith(pat[1:]):
                    out.add(name)
                    break
            elif name == pat:
                out.add(name)
                break
    return out


def export(output: Path) -> list[Path]:
    """Assemble the public distribution at ``output`` and return the
    list of top-level paths written, for verification.

    Wipes ``output`` first if it exists, so each run is deterministic.
    """
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)

    written: list[Path] = []
    for src_rel, dest_rel, kind in MANIFEST:
        src = REPO_ROOT / src_rel
        dest = output / dest_rel
        if not src.exists():
            raise FileNotFoundError(
                f"Missing canonical source: {src} (manifest entry "
                f"{src_rel!r} → {dest_rel!r}). Add the file to the repo "
                "or update the manifest."
            )
        dest.parent.mkdir(parents=True, exist_ok=True)
        if kind == "tree":
            shutil.copytree(src, dest, ignore=_ignore)
        elif kind == "file":
            shutil.copyfile(src, dest)
        else:
            raise ValueError(f"Unknown manifest kind: {kind!r}")
        written.append(dest)
    return written


def _print_tree(root: Path, max_depth: int = 3) -> None:
    """Print a directory tree rooted at ``root``, capped at ``max_depth``."""
    root = root.resolve()
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if len(rel.parts) > max_depth:
            continue
        if path.is_dir():
            print(f"  {rel}/")
        else:
            print(f"  {rel}")


def _verify_tutorial_paths(output: Path) -> list[str]:
    """Confirm every path the tutorial relies on exists in the bundle.

    Returns a list of missing paths (empty if all OK).
    """
    expected = [
        "docs/ontozense-npl-tutorial.md",
        "domains/npl/sources/npl-basel-guidelines.md",
        "domains/npl/sources/governance.json",
        "domains/npl/sources/npl-schema.sql",
        "domains/npl/sources/npl-code/classification/npe_classifier.py",
        "domains/npl/sources/npl-code/forbearance/forbearance_validator.py",
        "domains/npl/sources/npl-code/transitions/upgrade_rules.py",
        "domains/npl/sources/npl-code/reporting/finrep_npl_query.sql",
        "domains/npl/sources/npl-code/reporting/loan_constraints.sql",
        "src/ontozense/__init__.py",
        "pyproject.toml",
        "README.md",
        "images/tycho.png",
    ]
    return [p for p in expected if not (output / p).exists()]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO_ROOT / "dist" / "tycho-public",
        help="Where to write the exported distribution "
        "(default: dist/tycho-public/).",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Skip the export; only verify a pre-existing output.",
    )
    args = parser.parse_args()
    output: Path = args.output.resolve()

    if not args.verify_only:
        print(f"Exporting Tycho public distribution to {output}")
        export(output)
        print(f"Wrote {sum(1 for _ in output.rglob('*'))} entries.")

    missing = _verify_tutorial_paths(output)
    if missing:
        print("VERIFICATION FAILED — missing paths:", file=sys.stderr)
        for p in missing:
            print(f"  - {p}", file=sys.stderr)
        return 1

    print("\nVerification: OK (all required paths present).")
    print("\nTop-level layout:")
    _print_tree(output, max_depth=2)
    print(
        f"\nNext: `cd {output}` and follow docs/ontozense-npl-tutorial.md."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
