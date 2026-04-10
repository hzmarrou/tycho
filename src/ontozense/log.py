"""Per-domain append-only log for the living knowledge base.

Each domain has its own ``log.md`` at ``<domain_dir>/log.md`` that records
every operation touching that domain's knowledge. The format is dictated
by ``docs/PLAYBOOK.md`` §10:

    ## [YYYY-MM-DD] <op> | key=val | key=val | ...

The log is append-only, grep-parseable, diff-able in git, and the audit
trail of the living knowledge base. It is the cheapest possible "did this
extraction actually happen, against what input, with what result" record.

Why a flat markdown file:
    - No database, no schema, no migrations
    - Diffable per commit in git
    - Greppable: ``grep "^## " <domain>/log.md | tail -10`` works
    - Human-readable when something looks wrong
    - Trivially portable (copy the directory, take the audit trail with you)

Pattern stolen from Karpathy's "LLM Wiki" gist.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any

LOG_FILENAME = "log.md"


def append_log(
    domain_dir: str | Path,
    op: str,
    *,
    timestamp: date | datetime | str | None = None,
    **fields: Any,
) -> Path:
    """Append a single grep-parseable entry to ``<domain_dir>/log.md``.

    Args:
        domain_dir: Per-domain knowledge base directory. Created if missing.
        op: Operation name (e.g. ``"extract-a"``, ``"fuse"``, ``"lint"``,
            ``"ingest"``). Should be short and stable across runs so the log
            is greppable.
        timestamp: Optional timestamp override. Accepts ``date``,
            ``datetime``, or a pre-formatted string. Default: today's date.
        **fields: Key/value pairs to record. Values are stringified; any
            newlines are flattened to spaces and any pipe characters are
            replaced with ``/`` so they don't break the field separator.

    Returns:
        The path to the log file that was appended to.

    Example:
        >>> append_log(
        ...     "output/some_domain",
        ...     "extract-a",
        ...     source="standard-doc.pdf",
        ...     concepts=47,
        ...     relationships=23,
        ... )
        # appends:
        # ## [2026-04-10] extract-a | source=standard-doc.pdf | concepts=47 | relationships=23
    """
    domain_path = Path(domain_dir)
    domain_path.mkdir(parents=True, exist_ok=True)
    log_path = domain_path / LOG_FILENAME

    # Format the timestamp
    if timestamp is None:
        ts_str = date.today().isoformat()
    elif isinstance(timestamp, datetime):
        ts_str = timestamp.date().isoformat()
    elif isinstance(timestamp, date):
        ts_str = timestamp.isoformat()
    else:
        ts_str = str(timestamp)

    # Format the line
    parts = [f"## [{ts_str}] {op}"]
    for key, val in fields.items():
        parts.append(f"{key}={_sanitize_value(val)}")
    line = " | ".join(parts) + "\n"

    # Append. POSIX append is atomic for writes under PIPE_BUF (~4KB);
    # Windows append is also generally atomic for small writes. Our lines
    # are well under that threshold, so this is process-safe enough for
    # the single-user CLI case. If we ever go SaaS / multi-process, this
    # is the spot to add a file lock.
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(line)

    return log_path


def _sanitize_value(val: Any) -> str:
    """Make a value safe to put in a pipe-separated single-line log entry.

    - Newlines collapse to spaces (entries must be one line)
    - Pipe characters become ``/`` (pipe is the field separator)
    - Multiple spaces collapse to single space
    """
    s = str(val)
    s = s.replace("\n", " ").replace("\r", " ").replace("|", "/")
    # Collapse runs of whitespace
    s = " ".join(s.split())
    return s
