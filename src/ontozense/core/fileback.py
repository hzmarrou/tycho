"""File-back — save derived artifacts into the knowledge base.

Per ``docs/PLAYBOOK.md`` §9 (Query operation): query results can be
**filed back** as new derived artifacts under
``<domain>/derived/analyses/``. Filed-back artifacts become part of the
knowledge base audit trail and — in future iterations — input to
subsequent fusion runs.

File-back is deliberately simple: copy/move the file to the right
location and append a log entry. The file itself is the artifact;
Ontozense doesn't parse or validate its contents (it might be a
markdown review, a CSV comparison, an Excel annotated by the expert).

This is the Karpathy "LLM Wiki" pattern: human-curated artifacts
are the durable layer. Everything else is regenerable from them.
"""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

from ..log import append_log


def file_back(
    source_path: str | Path,
    domain_dir: str | Path,
    category: str = "analysis",
) -> Path:
    """File a derived artifact back into the domain knowledge base.

    Args:
        source_path: The file to file back (markdown, CSV, Excel, ...).
        domain_dir: The per-domain knowledge base directory.
        category: Sub-directory under ``derived/`` (default: "analyses").

    Returns:
        The destination path where the file was saved.

    Raises:
        FileNotFoundError: if ``source_path`` does not exist.
    """
    source_path = Path(source_path)
    domain_dir = Path(domain_dir)

    if not source_path.exists():
        raise FileNotFoundError(f"Source file not found: {source_path}")

    # Target: <domain_dir>/derived/<category>/<filename>
    target_dir = domain_dir / "derived" / category
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / source_path.name

    # If a file with the same name already exists, add a timestamp
    # suffix to avoid overwriting prior versions.
    if target_path.exists():
        stem = source_path.stem
        suffix = source_path.suffix
        ts = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
        target_path = target_dir / f"{stem}_{ts}{suffix}"

    shutil.copy2(source_path, target_path)

    append_log(
        domain_dir,
        "file-back",
        source=source_path.name,
        destination=str(target_path.relative_to(domain_dir)),
        category=category,
    )

    return target_path
