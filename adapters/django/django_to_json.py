"""CLI entry point: Django models → Source C JSON.

Run from the adapters/django directory:

    python -m django_to_json /path/to/django/app --output source-c.json

Or with a profile (Tycho profile mode — populates id and entity_type):

    python -m django_to_json /path/to/django/app \
        --profile /path/to/profile/dir \
        --output source-c.json

Then feed source-c.json to Tycho:

    ontozense fuse --source-c source-c.json …
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Make the parser module importable when this file is run as a script.
sys.path.insert(0, str(Path(__file__).parent))

from django_schema import DjangoSchemaParser  # noqa: E402

from ontozense.core.source_c import dump_source_c_json  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(
        description=(
            "Parse a Django models directory and emit a Source C "
            "SchemaResult JSON file consumable by Tycho's fuse "
            "command."
        ),
    )
    p.add_argument(
        "models_dir",
        help="Path to the Django app directory (containing models.py).",
    )
    p.add_argument(
        "--output", "-o",
        required=True,
        help="Path to write the Source C JSON output.",
    )
    p.add_argument(
        "--profile",
        default=None,
        help=(
            "Optional Tycho profile directory. When supplied, parsed "
            "models and fields get deterministic id + entity_type."
        ),
    )

    args = p.parse_args()

    profile = None
    if args.profile:
        from ontozense.core.profile import load_profile
        profile = load_profile(Path(args.profile))

    parser = DjangoSchemaParser(args.models_dir, profile=profile)
    result = parser.parse()

    out_path = Path(args.output)
    dump_source_c_json(result, out_path)

    print(
        f"[ok] {len(result.models)} models from {args.models_dir} "
        f"→ {out_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
