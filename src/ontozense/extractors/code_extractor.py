"""Code extractor — Source D of the four-source pipeline.

Extracts business rules from production code: thresholds, conditional
logic, state transitions, constraints, and citations to authoritative
documents. Handles Python (AST) and SQL (sqlglot).

Methodology: AI-BRX (``docs/AI-RBX.pdf``) — *Leveraging Generative AI for
Extracting Business Requirements*. The paper validates this approach at
3.4M LoC scale with 93% expert agreement and 70% effort reduction. The
core insight: **deterministic parsing first, LLM labeling second,
validator against the parsed symbol table.** The LLM never sees raw code
without the surrounding parsed context, and every claim it makes must
reference a real symbol from the deterministic pass.

Pipeline (per AI-BRX Figure 1):

  1. Deterministic parsing (Python ``ast`` / ``sqlglot``) — extracts
     structured candidates: constants, conditional expressions, function
     definitions, CHECK/WHERE clauses, comments referencing regulations
  2. (Future) LLM labeling — translates the parsed candidates into
     business-readable rules with structured output JSON schemas
  3. (Future) Symbol-table validator — every LLM-labelled rule must
     reference a real symbol from step 1
  4. Provenance — every extracted rule carries (file, line, column) so
     the human reviewer can jump to the source

This module ships with the deterministic parsing complete. The LLM
labeling and symbol-table validator land in a follow-up iteration; the
dataclasses and public API are designed to accommodate them.

Domain-agnostic: zero hardcoded vocabulary. The extractor recognises
**structural patterns** in code (constants, conditionals, functions,
CHECK constraints) — never domain content.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional


# ─── Dataclasses ─────────────────────────────────────────────────────────────


@dataclass
class CodeProvenance:
    """Where in the source a code candidate was found."""
    file_path: str
    line: int
    column: int = 0
    end_line: int = 0
    snippet: str = ""


@dataclass
class CodeRule:
    """One business rule candidate extracted from production code.

    A ``CodeRule`` is the deterministic-pass output: structured but
    unlabelled. The LLM labelling step (future) will fill in
    ``natural_language``, ``business_purpose``, and an ``applies_to``
    field referencing entities/properties from the schema or data
    dictionary.
    """
    rule_type: str
    # One of:
    #   "constant"          — a module-level constant (threshold/flag)
    #   "conditional"       — an if/elif test that mutates state or returns
    #   "function"          — a function definition with a docstring
    #   "sql_check"         — a SQL CHECK constraint
    #   "sql_where"         — a WHERE-clause filter in a query
    #   "sql_view"          — a CREATE VIEW statement
    #   "comment_citation"  — a comment referencing a regulation/section

    name: str                          # e.g. "NPE_DPD_THRESHOLD"
    expression: str                    # source-text expression
    value: Optional[object] = None     # parsed Python literal if applicable
    referenced_symbols: list[str] = field(default_factory=list)
    citations: list[str] = field(default_factory=list)
    docstring: str = ""
    confidence: float = 0.95           # deterministic parsing — high
    provenance: Optional[CodeProvenance] = None


@dataclass
class CodeExtractionResult:
    """Result of running the code extractor over one or more files."""
    rules: list[CodeRule] = field(default_factory=list)
    files_scanned: list[str] = field(default_factory=list)
    files_failed: list[tuple[str, str]] = field(default_factory=list)
    extraction_timestamp: str = ""

    def by_type(self, rule_type: str) -> list[CodeRule]:
        return [r for r in self.rules if r.rule_type == rule_type]

    def by_file(self, file_path: str) -> list[CodeRule]:
        return [
            r for r in self.rules
            if r.provenance and r.provenance.file_path == file_path
        ]


# ─── Citation regex ──────────────────────────────────────────────────────────
#
# Looks for inline references to authoritative documents in code comments
# and docstrings. Domain-agnostic — matches generic citation patterns
# (Section, §, Article, Para, Chapter, Annex, ITS, RTS, ...).
# A lookbehind for "not preceded by a letter" works for both word-shaped
# tokens (section, article, regulation) and the symbol § (which isn't a
# word character, so a plain \b would never match it).
_CITATION_RE = re.compile(
    r"(?<![A-Za-z])"
    r"(?:section|sec\.|paragraph|para\.|para|§|article|art\.|"
    r"chapter|ch\.|annex|appendix|table\s+\w+|figure\s+\w+|"
    r"its|rts|directive|regulation)"
    r"\s*[\dA-Z][\d.A-Z\-/]*",
    re.IGNORECASE,
)


def _find_citations(text: str) -> list[str]:
    """Find inline citations in a comment or docstring. Returns deduped list."""
    if not text:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for m in _CITATION_RE.finditer(text):
        cite = m.group(0).strip()
        key = cite.lower()
        if key not in seen:
            seen.add(key)
            out.append(cite)
    return out


# ─── Python extractor ────────────────────────────────────────────────────────


class PythonCodeExtractor:
    """Parses a single Python file and extracts CodeRule candidates."""

    def extract(self, file_path: str | Path) -> list[CodeRule]:
        file_path = Path(file_path)
        try:
            source = file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            source = file_path.read_text(encoding="utf-8", errors="ignore")

        try:
            tree = ast.parse(source, filename=str(file_path))
        except SyntaxError:
            return []

        rules: list[CodeRule] = []
        source_lines = source.splitlines()

        # Collect citations from comments at file level. ast doesn't track
        # comments so we walk the source manually.
        for line_idx, raw_line in enumerate(source_lines, start=1):
            stripped = raw_line.strip()
            if stripped.startswith("#"):
                cites = _find_citations(stripped)
                if cites:
                    rules.append(
                        CodeRule(
                            rule_type="comment_citation",
                            name=f"comment_at_line_{line_idx}",
                            expression=stripped,
                            citations=cites,
                            provenance=CodeProvenance(
                                file_path=str(file_path),
                                line=line_idx,
                                column=0,
                                snippet=stripped,
                            ),
                        )
                    )

        # Walk the AST for module-level constants and functions
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.Assign):
                rules.extend(self._extract_constant(node, source_lines, file_path))
            elif isinstance(node, ast.FunctionDef):
                rules.extend(self._extract_function(node, source_lines, file_path))

        return rules

    def _extract_constant(
        self,
        node: ast.Assign,
        source_lines: list[str],
        file_path: Path,
    ) -> list[CodeRule]:
        """Extract a module-level constant assignment as a threshold candidate.

        Only emits CodeRules for assignments where:
          - The target is a single ``Name`` (not a tuple unpacking)
          - The name is UPPER_SNAKE_CASE (the Python convention for module
            constants)
          - The RHS is a literal (number, string, bool, None) — we don't
            try to evaluate complex expressions
        """
        out: list[CodeRule] = []
        if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
            return out
        name = node.targets[0].id
        if not name.isupper() or not all(c.isalnum() or c == "_" for c in name):
            return out

        try:
            value = ast.literal_eval(node.value)
        except (ValueError, SyntaxError):
            return out

        snippet = self._snippet(source_lines, node.lineno, node.lineno)
        out.append(
            CodeRule(
                rule_type="constant",
                name=name,
                expression=snippet.strip(),
                value=value,
                provenance=CodeProvenance(
                    file_path=str(file_path),
                    line=node.lineno,
                    column=node.col_offset,
                    end_line=getattr(node, "end_lineno", node.lineno) or node.lineno,
                    snippet=snippet,
                ),
            )
        )
        return out

    def _extract_function(
        self,
        node: ast.FunctionDef,
        source_lines: list[str],
        file_path: Path,
    ) -> list[CodeRule]:
        """Extract a function definition. The function itself is one CodeRule
        (carrying the docstring and citation candidates); each top-level
        ``if`` / ``return`` inside the function body is another CodeRule of
        type ``conditional``.
        """
        out: list[CodeRule] = []
        docstring = ast.get_docstring(node) or ""
        cites = _find_citations(docstring)

        # Collect the names of arguments and any names referenced in the
        # function body — used as the symbol table for downstream
        # validation.
        arg_names = [a.arg for a in node.args.args]
        referenced: list[str] = list(arg_names)
        for sub in ast.walk(node):
            if isinstance(sub, ast.Attribute):
                # e.g. loan.days_past_due → "loan.days_past_due"
                full = self._dotted_name(sub)
                if full and full not in referenced:
                    referenced.append(full)
            elif isinstance(sub, ast.Name) and sub.id not in referenced:
                referenced.append(sub.id)

        end_line = getattr(node, "end_lineno", node.lineno) or node.lineno
        snippet = self._snippet(source_lines, node.lineno, min(node.lineno + 5, end_line))
        out.append(
            CodeRule(
                rule_type="function",
                name=node.name,
                expression=f"def {node.name}({', '.join(arg_names)})",
                docstring=docstring,
                referenced_symbols=referenced,
                citations=cites,
                provenance=CodeProvenance(
                    file_path=str(file_path),
                    line=node.lineno,
                    column=node.col_offset,
                    end_line=end_line,
                    snippet=snippet,
                ),
            )
        )

        # Walk the function body for conditional rules
        for sub in ast.walk(node):
            if isinstance(sub, ast.If):
                cond_text = self._safe_unparse(sub.test, source_lines, sub.lineno)
                cond_refs = self._symbols_in_expr(sub.test)
                cond_snippet = self._snippet(
                    source_lines, sub.lineno, getattr(sub, "end_lineno", sub.lineno) or sub.lineno
                )
                out.append(
                    CodeRule(
                        rule_type="conditional",
                        name=f"{node.name}::if_at_line_{sub.lineno}",
                        expression=f"if {cond_text}",
                        referenced_symbols=cond_refs,
                        provenance=CodeProvenance(
                            file_path=str(file_path),
                            line=sub.lineno,
                            column=sub.col_offset,
                            snippet=cond_snippet,
                        ),
                    )
                )
        return out

    @staticmethod
    def _snippet(source_lines: list[str], start: int, end: int) -> str:
        # ast lines are 1-indexed
        start_idx = max(0, start - 1)
        end_idx = min(len(source_lines), end)
        return "\n".join(source_lines[start_idx:end_idx])

    @staticmethod
    def _dotted_name(node: ast.AST) -> str:
        """Convert an Attribute chain to a dotted name string."""
        parts: list[str] = []
        cur = node
        while isinstance(cur, ast.Attribute):
            parts.insert(0, cur.attr)
            cur = cur.value
        if isinstance(cur, ast.Name):
            parts.insert(0, cur.id)
            return ".".join(parts)
        return ""

    def _symbols_in_expr(self, expr: ast.AST) -> list[str]:
        """Collect all dotted names referenced in an expression."""
        out: list[str] = []
        for sub in ast.walk(expr):
            if isinstance(sub, ast.Attribute):
                d = self._dotted_name(sub)
                if d and d not in out:
                    out.append(d)
            elif isinstance(sub, ast.Name) and sub.id not in out:
                out.append(sub.id)
        return out

    @staticmethod
    def _safe_unparse(node: ast.AST, source_lines: list[str], line: int) -> str:
        """Best-effort: ast.unparse the node, fall back to source line text."""
        try:
            return ast.unparse(node)
        except Exception:
            if 1 <= line <= len(source_lines):
                return source_lines[line - 1].strip()
            return "<unparseable>"


# ─── SQL extractor ───────────────────────────────────────────────────────────


class SqlCodeExtractor:
    """Parses a single SQL file and extracts CodeRule candidates."""

    def extract(self, file_path: str | Path) -> list[CodeRule]:
        try:
            import sqlglot
            from sqlglot import expressions as exp
        except ImportError:
            return []

        file_path = Path(file_path)
        try:
            source = file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            source = file_path.read_text(encoding="utf-8", errors="ignore")

        # Pull citations from -- and /* */ comments
        rules: list[CodeRule] = []
        for line_idx, line in enumerate(source.splitlines(), start=1):
            stripped = line.strip()
            if stripped.startswith("--"):
                cites = _find_citations(stripped)
                if cites:
                    rules.append(
                        CodeRule(
                            rule_type="comment_citation",
                            name=f"sql_comment_at_line_{line_idx}",
                            expression=stripped,
                            citations=cites,
                            provenance=CodeProvenance(
                                file_path=str(file_path),
                                line=line_idx,
                                snippet=stripped,
                            ),
                        )
                    )

        try:
            statements = sqlglot.parse(source, dialect="postgres")
        except Exception as e:
            return rules  # citations only; parser failed

        for stmt in statements:
            if stmt is None:
                continue
            # CREATE VIEW / TABLE / FUNCTION
            if isinstance(stmt, exp.Create):
                rules.extend(self._extract_create(stmt, file_path))
            # ALTER TABLE ... ADD CONSTRAINT (CHECK)
            if isinstance(stmt, exp.Alter):
                rules.extend(self._extract_alter(stmt, file_path))
            # SELECT — capture WHERE clauses as filters
            if isinstance(stmt, exp.Select):
                rules.extend(self._extract_select(stmt, file_path))

        return rules

    def _extract_create(self, stmt, file_path: Path) -> list[CodeRule]:
        from sqlglot import expressions as exp

        out: list[CodeRule] = []
        kind = (stmt.args.get("kind") or "").upper()
        if kind in ("VIEW", "TABLE"):
            # CREATE VIEW: stmt.this is a Table node with .name directly.
            # CREATE TABLE: stmt.this is a Schema node that wraps a Table
            # node (the column definitions live on the Schema). Unwrap
            # the Schema to get the real table name.
            target = stmt.this.this if isinstance(stmt.this, exp.Schema) else stmt.this
            name = target.name if hasattr(target, "name") else str(target)
            sql_text = stmt.sql(dialect="postgres")
            rule_type = "sql_view" if kind == "VIEW" else "sql_table"
            out.append(
                CodeRule(
                    rule_type=rule_type,
                    name=name,
                    expression=sql_text[:500],
                    provenance=CodeProvenance(
                        file_path=str(file_path),
                        line=1,  # sqlglot doesn't expose line numbers reliably
                        snippet=sql_text[:500],
                    ),
                )
            )
            # If a CREATE TABLE has CHECK constraints, capture each
            if kind == "TABLE" and isinstance(stmt.this, exp.Schema):
                for col_def in stmt.this.expressions:
                    if isinstance(col_def, exp.ColumnDef):
                        for constr in col_def.constraints or []:
                            if isinstance(constr.kind, exp.CheckColumnConstraint):
                                out.append(
                                    CodeRule(
                                        rule_type="sql_check",
                                        name=f"{name}.{col_def.name}_check",
                                        expression=constr.sql(dialect="postgres"),
                                        referenced_symbols=[col_def.name],
                                        provenance=CodeProvenance(
                                            file_path=str(file_path),
                                            line=1,
                                            snippet=constr.sql(dialect="postgres"),
                                        ),
                                    )
                                )
        return out

    def _extract_alter(self, stmt, file_path: Path) -> list[CodeRule]:
        from sqlglot import expressions as exp

        out: list[CodeRule] = []
        # ALTER TABLE ... ADD CONSTRAINT chk_xxx CHECK (...)
        for action in stmt.args.get("actions") or []:
            if isinstance(action, exp.AddConstraint):
                for c in action.expressions or []:
                    if isinstance(c, exp.Constraint):
                        # Find the CheckColumnConstraint inside
                        check_node = c.find(exp.CheckColumnConstraint)
                        if check_node is not None:
                            constr_name = c.this.name if c.this else "unnamed_constraint"
                            check_sql = check_node.sql(dialect="postgres")
                            out.append(
                                CodeRule(
                                    rule_type="sql_check",
                                    name=constr_name,
                                    expression=check_sql,
                                    referenced_symbols=self._symbols_in_sql(check_node),
                                    provenance=CodeProvenance(
                                        file_path=str(file_path),
                                        line=1,
                                        snippet=check_sql,
                                    ),
                                )
                            )
        return out

    def _extract_select(self, stmt, file_path: Path) -> list[CodeRule]:
        from sqlglot import expressions as exp

        out: list[CodeRule] = []
        where = stmt.args.get("where")
        if where is not None and isinstance(where, exp.Where):
            where_sql = where.this.sql(dialect="postgres")
            out.append(
                CodeRule(
                    rule_type="sql_where",
                    name=f"where_at_select",
                    expression=where_sql[:500],
                    referenced_symbols=self._symbols_in_sql(where),
                    provenance=CodeProvenance(
                        file_path=str(file_path),
                        line=1,
                        snippet=where_sql[:500],
                    ),
                )
            )
        return out

    @staticmethod
    def _symbols_in_sql(node) -> list[str]:
        """Collect column names referenced inside a SQL node."""
        from sqlglot import expressions as exp

        out: list[str] = []
        for col in node.find_all(exp.Column):
            name = col.name
            table = col.table
            full = f"{table}.{name}" if table else name
            if full not in out:
                out.append(full)
        return out


# ─── Top-level CodeExtractor ─────────────────────────────────────────────────


class CodeExtractor:
    """Walks a directory and runs language-specific extractors per file."""

    def __init__(self) -> None:
        self.python_extractor = PythonCodeExtractor()
        self.sql_extractor = SqlCodeExtractor()

    def extract_from_file(self, file_path: str | Path) -> list[CodeRule]:
        file_path = Path(file_path)
        suffix = file_path.suffix.lower()
        if suffix == ".py":
            return self.python_extractor.extract(file_path)
        if suffix == ".sql":
            return self.sql_extractor.extract(file_path)
        return []

    def extract_from_directory(
        self,
        directory: str | Path,
        recursive: bool = True,
    ) -> CodeExtractionResult:
        directory = Path(directory)
        if not directory.is_dir():
            raise NotADirectoryError(f"Not a directory: {directory}")

        result = CodeExtractionResult(
            extraction_timestamp=datetime.utcnow().isoformat(),
        )
        iterator = directory.rglob("*") if recursive else directory.iterdir()
        for path in iterator:
            if not path.is_file():
                continue
            if path.suffix.lower() not in (".py", ".sql"):
                continue
            try:
                rules = self.extract_from_file(path)
                result.rules.extend(rules)
                result.files_scanned.append(str(path))
            except Exception as e:
                result.files_failed.append((str(path), f"{type(e).__name__}: {e}"))
        return result
