"""File router for the living knowledge base.

Classifies an incoming file by which Source should handle it (A, B, C, D,
or skip). The router sits in front of the four extractors and dispatches
each file to the right one. It is the routing layer that makes the
"drop a file in the knowledge base, automatic dispatch" workflow work.

Two layers (per ``docs/PLAYBOOK.md`` §5):

  Layer 1 — Deterministic file-extension rules (~70% of cases)
    Fast, no I/O beyond the path itself. Maps known extensions to sources.

  Layer 2 — Content sniffing for ambiguous cases (~25% more)
    For files where extension alone is ambiguous (e.g. ``.xlsx`` could be
    governance dictionary or schema export), reads a small prefix of the
    file and applies heuristics: column header patterns, markdown
    structure, code-block density.

Layer 3 (LLM classifier) is documented in PLAYBOOK §5 but not implemented
yet. The deterministic layers cover the cases we care about today; we'll
add the LLM fallback when real uploads expose cases the heuristics can't
handle.

Multi-source routing is supported: a file can match more than one source
(e.g. a markdown developer guide with both prose AND code blocks). The
router returns ALL matching sources ordered by confidence; the caller
decides whether to dispatch to all or pick one.

Domain-agnostic: zero hardcoded vocabulary. Routing decisions are based
purely on file structure, never on file content semantics.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class Source(str, Enum):
    """The four extraction sources, plus a skip sentinel."""
    A = "A"  # Authoritative domain documents (prose: PDF, MD, DOCX, ...)
    B = "B"  # Governance / policy data dictionaries (Excel, CSV, ...)
    C = "C"  # Database schemas (DDL, Django, SQLAlchemy, JSON Schema, ...)
    D = "D"  # Production code (Python, SQL, ...)
    SKIP = "skip"  # README, LICENSE, marketing, irrelevant


@dataclass
class RoutingDecision:
    """Outcome of routing a single file.

    A single file may match multiple sources (the canonical case is a
    markdown file with code blocks — Source A AND Source D). The
    ``sources`` list is ordered from highest confidence to lowest. The
    caller decides whether to dispatch to all or pick the top one.

    A skip decision is a normal outcome, not an error. It means the file
    is not useful for ontology extraction (README, license, marketing,
    irrelevant binary, etc.).
    """
    file_path: Path
    sources: list[Source]
    confidence: float                # 0.0 - 1.0; confidence of the top match
    layer: str                       # "extension", "content_sniff", "llm" (future)
    reasoning: str                   # human-readable explanation

    @property
    def primary_source(self) -> Source:
        """The single most-likely source. Convenience for single-dispatch."""
        return self.sources[0] if self.sources else Source.SKIP

    @property
    def is_skip(self) -> bool:
        return self.primary_source == Source.SKIP

    @property
    def is_multi_source(self) -> bool:
        return len([s for s in self.sources if s != Source.SKIP]) > 1


# ─── Layer 1 — Extension rules ───────────────────────────────────────────────


# Map file extensions to their primary source.
# Some extensions are ambiguous and trigger content sniffing in Layer 2.
_EXTENSION_RULES: dict[str, Source] = {
    # Source D — code (unambiguous)
    ".py": Source.D,
    ".dbt": Source.D,
    ".r": Source.D,
    ".scala": Source.D,
    ".java": Source.D,
    ".sas": Source.D,
    ".rb": Source.D,
    ".go": Source.D,
    ".ts": Source.D,
    ".js": Source.D,

    # Source A — prose-shaped authoritative domain documents
    ".md": Source.A,
    ".markdown": Source.A,
    ".txt": Source.A,
    ".rst": Source.A,
    ".pdf": Source.A,
    ".docx": Source.A,
    ".doc": Source.A,
    ".html": Source.A,
    ".htm": Source.A,

    # Ambiguous — refined by Layer 2 content sniffing
    ".sql": Source.D,           # may be DDL (C) or procedural (D); default D
    ".ddl": Source.C,           # explicitly DDL
    ".csv": Source.B,           # may be governance (B) or schema export (C); default B
    ".tsv": Source.B,
    ".xlsx": Source.B,           # may be governance (B), schema export (C), or data (skip)
    ".xls": Source.B,
    ".ods": Source.B,
    ".json": Source.C,           # may be schema (C) or data (skip); default C
    ".yaml": Source.C,           # may be schema (C) or config (skip); default C
    ".yml": Source.C,
    ".avsc": Source.C,           # Avro schema
    ".proto": Source.C,           # protobuf
}


# Filenames that should always be skipped, regardless of extension.
_SKIP_FILENAMES = {
    "readme",
    "readme.md",
    "readme.txt",
    "readme.rst",
    "license",
    "license.md",
    "license.txt",
    "licence",
    "licence.md",
    "licence.txt",
    "copying",
    "authors",
    "authors.md",
    "contributors",
    "contributors.md",
    "changelog",
    "changelog.md",
    "changelog.rst",
    "changes",
    "changes.md",
    "history",
    "history.md",
    "code_of_conduct",
    "code_of_conduct.md",
    "contributing",
    "contributing.md",
    ".gitignore",
    ".gitattributes",
    ".dockerignore",
    "dockerfile",
    "makefile",
}


# Extensions that should be skipped (binaries, build artifacts).
_SKIP_EXTENSIONS = {
    ".pyc", ".pyo", ".pyd",
    ".so", ".dll", ".dylib",
    ".exe", ".bin",
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".ico", ".svg",
    ".mp3", ".mp4", ".wav", ".avi", ".mov",
    ".zip", ".tar", ".gz", ".bz2", ".xz", ".7z", ".rar",
    ".log", ".tmp", ".bak", ".swp",
    ".lock",
    ".egg-info",
    ".class", ".jar",
}


# ─── Layer 2 — Content sniffing patterns ─────────────────────────────────────


# Header keywords typical of governance / data quality dictionaries.
# Used for Excel/CSV content sniffing. Domain-agnostic.
_GOVERNANCE_HEADER_KEYWORDS = {
    "definition", "data element", "data_element", "element name",
    "critical", "cde", "critical data",
    "mandatory", "optional", "m/o",
    "completeness", "accuracy", "uniqueness", "timeliness",
    "consistency", "validity",
    "data quality", "dq",
    "term definition", "regulation", "regulatory reference",
    "source reference", "citation",
}


# Header keywords typical of schema exports / DDL listings.
_SCHEMA_HEADER_KEYWORDS = {
    "table", "table name", "table_name",
    "column", "column name", "column_name",
    "data type", "data_type", "datatype",
    "primary key", "primary_key", "pk",
    "foreign key", "foreign_key", "fk",
    "nullable", "is_nullable",
    "constraint", "default value",
    "max length", "max_length", "char length",
}


# Patterns indicating SQL DDL vs procedural SQL
_SQL_DDL_PATTERN = re.compile(
    r"\b(create\s+(table|view|index|schema|sequence|materialized\s+view))\b",
    re.IGNORECASE,
)
_SQL_PROCEDURAL_PATTERN = re.compile(
    r"\b(create\s+(function|procedure|trigger)|begin\s+|declare\s+|loop\s+)\b",
    re.IGNORECASE,
)


# Markdown code-block detection
_MARKDOWN_CODE_FENCE = re.compile(r"^```", re.MULTILINE)


# ─── Router ──────────────────────────────────────────────────────────────────


class Router:
    """Classifies a file path into a routing decision."""

    def __init__(self, *, content_sniff_byte_limit: int = 8192):
        """
        Args:
            content_sniff_byte_limit: How many bytes to read from the head of
                a file when content sniffing. Default 8KB — enough to see
                Excel headers and markdown structure, small enough to be
                fast even for large files.
        """
        self.sniff_limit = content_sniff_byte_limit

    def route(self, file_path: str | Path) -> RoutingDecision:
        """Classify a single file.

        Args:
            file_path: Path to the file (need not exist for extension-only
                routing, but content sniffing will be skipped if it doesn't).

        Returns:
            A ``RoutingDecision``.
        """
        file_path = Path(file_path)

        # Step 1: skip-list check (filename or extension)
        skip_decision = self._check_skip(file_path)
        if skip_decision is not None:
            return skip_decision

        # Step 2: extension rules
        ext = file_path.suffix.lower()
        if ext not in _EXTENSION_RULES:
            return RoutingDecision(
                file_path=file_path,
                sources=[Source.SKIP],
                confidence=0.95,
                layer="extension",
                reasoning=f"Unknown file extension '{ext}'",
            )

        primary = _EXTENSION_RULES[ext]

        # Step 3: content sniffing for ambiguous extensions
        if file_path.exists() and file_path.is_file():
            sniff = self._content_sniff(file_path, ext, primary)
            if sniff is not None:
                return sniff

        # Default: extension rule wins, high confidence
        return RoutingDecision(
            file_path=file_path,
            sources=[primary],
            confidence=0.95,
            layer="extension",
            reasoning=f"File extension '{ext}' maps to Source {primary.value}",
        )

    def route_directory(
        self,
        directory: str | Path,
        recursive: bool = True,
    ) -> list[RoutingDecision]:
        """Route every file in a directory."""
        directory = Path(directory)
        if not directory.is_dir():
            raise NotADirectoryError(f"Not a directory: {directory}")

        decisions: list[RoutingDecision] = []
        iterator = directory.rglob("*") if recursive else directory.iterdir()
        for path in iterator:
            if path.is_file():
                decisions.append(self.route(path))
        return decisions

    # ─── Skip-list check ──────────────────────────────────────────────────

    def _check_skip(self, file_path: Path) -> RoutingDecision | None:
        """Return a skip decision if the file matches any skip rule, else None."""
        name_lower = file_path.name.lower()
        ext_lower = file_path.suffix.lower()

        if name_lower in _SKIP_FILENAMES:
            return RoutingDecision(
                file_path=file_path,
                sources=[Source.SKIP],
                confidence=0.99,
                layer="extension",
                reasoning=f"Filename '{file_path.name}' is in the skip list",
            )

        if ext_lower in _SKIP_EXTENSIONS:
            return RoutingDecision(
                file_path=file_path,
                sources=[Source.SKIP],
                confidence=0.99,
                layer="extension",
                reasoning=f"Extension '{ext_lower}' is a binary or build artifact",
            )

        return None

    # ─── Content sniffing ─────────────────────────────────────────────────

    def _content_sniff(
        self,
        file_path: Path,
        ext: str,
        extension_default: Source,
    ) -> RoutingDecision | None:
        """Refine the extension-based routing using content heuristics.

        Returns a more specific decision if the content sniff produces
        useful signal, or None to fall back to the extension rule.
        """
        if ext in {".sql"}:
            return self._sniff_sql(file_path)
        if ext in {".csv", ".tsv"}:
            return self._sniff_delimited(file_path, ext)
        if ext in {".xlsx", ".xls", ".ods"}:
            return self._sniff_excel(file_path)
        if ext in {".md", ".markdown", ".rst"}:
            return self._sniff_markdown(file_path, extension_default)
        if ext == ".json":
            return self._sniff_json(file_path)
        return None

    def _read_head(self, file_path: Path) -> str:
        """Read the first ``sniff_limit`` bytes of a file as text. Errors → ''."""
        try:
            with open(file_path, "rb") as f:
                raw = f.read(self.sniff_limit)
            return raw.decode("utf-8", errors="ignore")
        except OSError:
            return ""

    def _sniff_sql(self, file_path: Path) -> RoutingDecision:
        """SQL: distinguish DDL (Source C) from procedural SQL (Source D)."""
        text = self._read_head(file_path)
        if not text:
            return RoutingDecision(
                file_path=file_path,
                sources=[Source.D],
                confidence=0.7,
                layer="extension",
                reasoning="SQL file but content unreadable; defaulting to Source D",
            )

        ddl_hits = len(_SQL_DDL_PATTERN.findall(text))
        proc_hits = len(_SQL_PROCEDURAL_PATTERN.findall(text))

        if ddl_hits > proc_hits and ddl_hits >= 1:
            return RoutingDecision(
                file_path=file_path,
                sources=[Source.C],
                confidence=0.9,
                layer="content_sniff",
                reasoning=f"SQL file with {ddl_hits} DDL statements (CREATE TABLE/VIEW/...)",
            )
        if proc_hits > 0:
            return RoutingDecision(
                file_path=file_path,
                sources=[Source.D],
                confidence=0.85,
                layer="content_sniff",
                reasoning=f"SQL file with {proc_hits} procedural constructs (FUNCTION/PROCEDURE/...)",
            )
        # Default
        return RoutingDecision(
            file_path=file_path,
            sources=[Source.D],
            confidence=0.6,
            layer="content_sniff",
            reasoning="SQL file with no clear DDL or procedural pattern; defaulting to Source D",
        )

    def _sniff_delimited(self, file_path: Path, ext: str) -> RoutingDecision:
        """CSV/TSV: distinguish governance dictionary (B) from schema export (C)."""
        text = self._read_head(file_path)
        if not text:
            return RoutingDecision(
                file_path=file_path,
                sources=[Source.B],
                confidence=0.7,
                layer="extension",
                reasoning=f"{ext} file but content unreadable; defaulting to Source B",
            )

        # Read just the first line as the header row
        first_line = text.split("\n", 1)[0].lower() if text else ""
        delim = "\t" if ext == ".tsv" else ","
        headers = {h.strip().strip('"') for h in first_line.split(delim)}

        gov_hits = sum(
            1 for kw in _GOVERNANCE_HEADER_KEYWORDS
            if any(kw in h for h in headers)
        )
        schema_hits = sum(
            1 for kw in _SCHEMA_HEADER_KEYWORDS
            if any(kw in h for h in headers)
        )

        if gov_hits >= schema_hits and gov_hits >= 1:
            return RoutingDecision(
                file_path=file_path,
                sources=[Source.B],
                confidence=0.9,
                layer="content_sniff",
                reasoning=f"{ext} headers match {gov_hits} governance keywords",
            )
        if schema_hits >= 1:
            return RoutingDecision(
                file_path=file_path,
                sources=[Source.C],
                confidence=0.9,
                layer="content_sniff",
                reasoning=f"{ext} headers match {schema_hits} schema keywords",
            )
        return RoutingDecision(
            file_path=file_path,
            sources=[Source.B],
            confidence=0.6,
            layer="content_sniff",
            reasoning=f"{ext} headers don't match known governance/schema patterns; defaulting to Source B",
        )

    def _sniff_excel(self, file_path: Path) -> RoutingDecision:
        """Excel: distinguish governance dictionary (B) from schema export (C)
        by looking at the first sheet's header row."""
        try:
            import openpyxl
        except ImportError:
            return RoutingDecision(
                file_path=file_path,
                sources=[Source.B],
                confidence=0.7,
                layer="extension",
                reasoning="openpyxl not available; defaulting to Source B",
            )

        try:
            wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
        except Exception as e:
            return RoutingDecision(
                file_path=file_path,
                sources=[Source.B],
                confidence=0.6,
                layer="content_sniff",
                reasoning=f"Excel file unreadable ({type(e).__name__}); defaulting to Source B",
            )

        # Inspect headers from each sheet, top 5 rows
        all_headers: set[str] = set()
        for ws in wb.worksheets[:3]:  # cap at first 3 sheets
            try:
                for row in ws.iter_rows(min_row=1, max_row=5, values_only=True):
                    for cell in row:
                        if isinstance(cell, str) and cell.strip():
                            all_headers.add(cell.strip().lower())
            except Exception:
                continue

        wb.close()

        gov_hits = sum(
            1 for kw in _GOVERNANCE_HEADER_KEYWORDS
            if any(kw in h for h in all_headers)
        )
        schema_hits = sum(
            1 for kw in _SCHEMA_HEADER_KEYWORDS
            if any(kw in h for h in all_headers)
        )

        if gov_hits >= schema_hits and gov_hits >= 2:
            return RoutingDecision(
                file_path=file_path,
                sources=[Source.B],
                confidence=0.92,
                layer="content_sniff",
                reasoning=f"Excel headers match {gov_hits} governance keywords",
            )
        if schema_hits >= 2:
            return RoutingDecision(
                file_path=file_path,
                sources=[Source.C],
                confidence=0.9,
                layer="content_sniff",
                reasoning=f"Excel headers match {schema_hits} schema keywords",
            )
        return RoutingDecision(
            file_path=file_path,
            sources=[Source.B],
            confidence=0.6,
            layer="content_sniff",
            reasoning="Excel headers don't match strong governance/schema patterns; defaulting to Source B",
        )

    def _sniff_json(self, file_path: Path) -> RoutingDecision:
        """JSON: distinguish governance reference (Source B) from
        schema/data files (Source C).

        Governance JSON files from ``docs/CANONICAL_GOVERNANCE_FORMAT.md``
        have ``element_name`` at the top level of each object.
        JSON Schema / OpenAPI / Avro files use ``$schema``, ``openapi``,
        or ``type`` / ``properties`` keys. Anything else falls back to
        the extension default (Source C).
        """
        import json

        text = self._read_head(file_path)
        if not text:
            return RoutingDecision(
                file_path=file_path,
                sources=[Source.C],
                confidence=0.6,
                layer="extension",
                reasoning="JSON file but content unreadable; defaulting to Source C",
            )

        try:
            # The sniff_limit head may truncate a large file mid-JSON —
            # try to parse, accept if we got enough to classify.
            parsed = json.loads(text)
        except json.JSONDecodeError:
            # Try parsing just the first complete JSON value if possible
            parsed = None

        if parsed is None:
            return RoutingDecision(
                file_path=file_path,
                sources=[Source.C],
                confidence=0.6,
                layer="content_sniff",
                reasoning="JSON file couldn't be parsed at sniff-limit; defaulting to Source C",
            )

        # Governance JSON: object or array of objects with element_name
        first_entry = None
        if isinstance(parsed, list) and parsed and isinstance(parsed[0], dict):
            first_entry = parsed[0]
        elif isinstance(parsed, dict):
            first_entry = parsed

        if first_entry is not None and "element_name" in first_entry:
            return RoutingDecision(
                file_path=file_path,
                sources=[Source.B],
                confidence=0.95,
                layer="content_sniff",
                reasoning=(
                    "JSON contains 'element_name' field — governance "
                    "reference format (Source B)"
                ),
            )

        # JSON Schema / OpenAPI / Avro — Source C
        if isinstance(parsed, dict):
            schema_keys = {"$schema", "openapi", "swagger"}
            if schema_keys & set(parsed.keys()):
                return RoutingDecision(
                    file_path=file_path,
                    sources=[Source.C],
                    confidence=0.95,
                    layer="content_sniff",
                    reasoning="JSON Schema / OpenAPI specification (Source C)",
                )
            # Avro schema: has 'type' and 'fields' at top level
            if "type" in parsed and "fields" in parsed:
                return RoutingDecision(
                    file_path=file_path,
                    sources=[Source.C],
                    confidence=0.9,
                    layer="content_sniff",
                    reasoning="Avro-style schema (Source C)",
                )

        # Fallback: treat as Source C but with lower confidence — the
        # human should review via --dry-run before --auto dispatch.
        return RoutingDecision(
            file_path=file_path,
            sources=[Source.C],
            confidence=0.5,
            layer="content_sniff",
            reasoning=(
                "JSON file without governance or schema markers; "
                "defaulting to Source C (review before --auto)"
            ),
        )

    def _sniff_markdown(
        self,
        file_path: Path,
        extension_default: Source,
    ) -> RoutingDecision:
        """Markdown: detect code-block density. A markdown file that's mostly
        code blocks (e.g. a developer guide or a runbook of SQL snippets)
        should also route to Source D in addition to Source A."""
        text = self._read_head(file_path)
        if not text:
            return RoutingDecision(
                file_path=file_path,
                sources=[extension_default],
                confidence=0.85,
                layer="extension",
                reasoning="Markdown file unreadable for sniffing",
            )

        code_fences = len(_MARKDOWN_CODE_FENCE.findall(text))
        # Each code block has an opening and closing fence → /2
        code_blocks = code_fences // 2

        if code_blocks >= 3:
            # Multi-source: this is a markdown doc with substantial code,
            # so it's both A (the prose) AND D (the code blocks).
            return RoutingDecision(
                file_path=file_path,
                sources=[Source.A, Source.D],
                confidence=0.85,
                layer="content_sniff",
                reasoning=(
                    f"Markdown with {code_blocks} code blocks; routes to "
                    f"Source A (prose) AND Source D (code)"
                ),
            )

        return RoutingDecision(
            file_path=file_path,
            sources=[Source.A],
            confidence=0.95,
            layer="extension",
            reasoning="Markdown file with no significant code blocks; Source A",
        )


# ─── Convenience ─────────────────────────────────────────────────────────────


def route_file(file_path: str | Path) -> RoutingDecision:
    """One-shot helper: route a single file with the default Router."""
    return Router().route(file_path)
