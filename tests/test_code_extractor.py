"""Tests for Source D — the code extractor.

Pins down the deterministic parsing layer of the Source D pipeline
(AI-RBX step 1). The LLM labelling pass (step 2) and symbol-table
validator (step 3) are deferred; these tests lock the contract that
those future steps will consume.

Covered:
  - Python AST: constants, functions, conditionals, citation regex,
    symbol table (with dotted attributes), parse failure
  - SQL via sqlglot: CREATE TABLE + CHECK, CREATE VIEW, ALTER TABLE
    ADD CONSTRAINT CHECK, SELECT WHERE, -- comment citations
  - Provenance completeness: every rule has file_path + line + snippet
  - Domain neutrality: the citation regex matches generic legal/spec
    patterns, not banking vocabulary
  - Directory walking and language dispatch
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ontozense.extractors.code_extractor import (
    CodeExtractor,
    CodeProvenance,
    CodeRule,
    PythonCodeExtractor,
    SqlCodeExtractor,
    _CITATION_RE,
    _find_citations,
)


# ─── Python AST tests ────────────────────────────────────────────────────────


@pytest.fixture
def sample_python(tmp_path: Path) -> Path:
    """A small Python module with every structural pattern the extractor
    should recognise. Domain-neutral vocabulary only.
    """
    src = tmp_path / "sample_module.py"
    src.write_text(
        '''\
"""Sample module with constants, functions, conditionals, and citations.

Per Policy Document Section 5, this module demonstrates the structural
patterns the Source D extractor should recognise.
"""

# Per Regulation X Article 14, a threshold applies here
THRESHOLD_DAYS = 90
MAX_RETRIES = 3
DEFAULT_NAME = "placeholder"
STATUS_ACTIVE = "active"

# Non-literal RHS — should NOT be captured as a constant
COMPUTED = 1 + 2 * 3

# Not upper-case — should NOT be captured
lowercase_not_a_constant = 10


def process_item(item, threshold):
    """Process a single item against a threshold.

    Implements the rule from Policy Document §12.
    """
    if item.value > threshold:
        item.flagged = True
        return True
    if item.value < 0:
        return False
    return None


def classify(record):
    """Classify a record.

    See Policy Document Section 5.2 for the classification criteria.
    """
    if record.age_days > THRESHOLD_DAYS and record.amount > 100:
        return "overdue"
    return "current"


class NotExtracted:
    """Classes are not extracted by the deterministic pass (they need
    LLM labelling to produce meaningful rules)."""

    def method_not_extracted(self):
        pass
''',
        encoding="utf-8",
    )
    return src


class TestPythonConstants:
    """Module-level UPPER_SNAKE_CASE constants with literal RHS."""

    def test_extracts_integer_constant(self, sample_python):
        rules = PythonCodeExtractor().extract(sample_python)
        constants = [r for r in rules if r.rule_type == "constant"]
        names = {r.name: r for r in constants}
        assert "THRESHOLD_DAYS" in names
        assert names["THRESHOLD_DAYS"].value == 90

    def test_extracts_string_constant(self, sample_python):
        rules = PythonCodeExtractor().extract(sample_python)
        constants = {r.name: r for r in rules if r.rule_type == "constant"}
        assert "DEFAULT_NAME" in constants
        assert constants["DEFAULT_NAME"].value == "placeholder"
        assert constants["STATUS_ACTIVE"].value == "active"

    def test_ignores_non_literal_rhs(self, sample_python):
        rules = PythonCodeExtractor().extract(sample_python)
        names = [r.name for r in rules if r.rule_type == "constant"]
        # COMPUTED = 1 + 2 * 3 is not a literal, must be skipped
        assert "COMPUTED" not in names

    def test_ignores_lowercase_assignments(self, sample_python):
        rules = PythonCodeExtractor().extract(sample_python)
        names = [r.name for r in rules if r.rule_type == "constant"]
        # lowercase_not_a_constant is not UPPER_SNAKE_CASE, must be skipped
        assert "lowercase_not_a_constant" not in names

    def test_constant_carries_provenance(self, sample_python):
        rules = PythonCodeExtractor().extract(sample_python)
        thr = next(r for r in rules if r.name == "THRESHOLD_DAYS")
        assert thr.provenance is not None
        assert thr.provenance.file_path == str(sample_python)
        assert thr.provenance.line > 0
        assert thr.provenance.snippet  # non-empty


class TestPythonFunctions:
    """Function definitions with docstrings and symbol tables."""

    def test_extracts_function_definitions(self, sample_python):
        rules = PythonCodeExtractor().extract(sample_python)
        functions = [r for r in rules if r.rule_type == "function"]
        names = {r.name for r in functions}
        assert "process_item" in names
        assert "classify" in names

    def test_function_carries_docstring(self, sample_python):
        rules = PythonCodeExtractor().extract(sample_python)
        process = next(r for r in rules if r.name == "process_item")
        assert "Process a single item" in process.docstring

    def test_function_symbol_table_includes_arguments(self, sample_python):
        rules = PythonCodeExtractor().extract(sample_python)
        process = next(r for r in rules if r.name == "process_item")
        assert "item" in process.referenced_symbols
        assert "threshold" in process.referenced_symbols

    def test_function_symbol_table_includes_dotted_attributes(self, sample_python):
        rules = PythonCodeExtractor().extract(sample_python)
        process = next(r for r in rules if r.name == "process_item")
        # record.age_days and item.value should be captured as dotted names
        # so the downstream validator can match them to schema columns
        assert "item.value" in process.referenced_symbols

    def test_class_methods_not_extracted(self, sample_python):
        """Classes and methods are deliberately not extracted by the
        deterministic pass — the LLM labelling step handles them.
        """
        rules = PythonCodeExtractor().extract(sample_python)
        names = {r.name for r in rules}
        assert "method_not_extracted" not in names
        assert "NotExtracted" not in names


class TestPythonConditionals:
    """`if` statements inside function bodies become `conditional` rules."""

    def test_extracts_conditionals(self, sample_python):
        rules = PythonCodeExtractor().extract(sample_python)
        conditionals = [r for r in rules if r.rule_type == "conditional"]
        # process_item has 2 ifs, classify has 1 — total 3
        assert len(conditionals) >= 3

    def test_conditional_references_symbols_in_test(self, sample_python):
        rules = PythonCodeExtractor().extract(sample_python)
        conditionals = [r for r in rules if r.rule_type == "conditional"]
        # At least one conditional should reference item.value
        assert any(
            "item.value" in c.referenced_symbols for c in conditionals
        ), f"Expected item.value in at least one conditional's symbols: {[c.referenced_symbols for c in conditionals]}"

    def test_conditional_carries_provenance(self, sample_python):
        rules = PythonCodeExtractor().extract(sample_python)
        conditionals = [r for r in rules if r.rule_type == "conditional"]
        for c in conditionals:
            assert c.provenance is not None
            assert c.provenance.line > 0


class TestPythonCitations:
    """Inline citations in comments and docstrings."""

    def test_comment_citation_extracted(self, sample_python):
        rules = PythonCodeExtractor().extract(sample_python)
        comments = [r for r in rules if r.rule_type == "comment_citation"]
        assert comments, "Expected at least one comment citation"
        all_cites = [c for r in comments for c in r.citations]
        assert any("Article 14" in c for c in all_cites)

    def test_function_docstring_citation_extracted(self, sample_python):
        rules = PythonCodeExtractor().extract(sample_python)
        process = next(r for r in rules if r.name == "process_item")
        assert any("§12" in c for c in process.citations)
        classify = next(r for r in rules if r.name == "classify")
        assert any("Section 5.2" in c for c in classify.citations)


class TestPythonParseFailure:
    """Syntax errors and unreadable files should fail soft."""

    def test_syntax_error_returns_empty(self, tmp_path):
        bad = tmp_path / "bad.py"
        bad.write_text("def broken(\n", encoding="utf-8")  # unclosed paren
        rules = PythonCodeExtractor().extract(bad)
        assert rules == []

    def test_empty_file_returns_empty(self, tmp_path):
        empty = tmp_path / "empty.py"
        empty.write_text("", encoding="utf-8")
        rules = PythonCodeExtractor().extract(empty)
        assert rules == []


# ─── SQL tests ───────────────────────────────────────────────────────────────


@pytest.fixture
def sample_sql(tmp_path: Path) -> Path:
    """SQL with CREATE TABLE + CHECK, ALTER TABLE ADD CONSTRAINT,
    CREATE VIEW, SELECT WHERE, and -- comment citations. Domain-neutral.
    """
    src = tmp_path / "sample.sql"
    src.write_text(
        """\
-- Implements the business rule from Policy Document §7.
-- See also Regulation X Article 22 for the upstream source.

CREATE TABLE widgets (
    widget_id INTEGER PRIMARY KEY,
    quantity  INTEGER NOT NULL CHECK (quantity >= 0),
    price     NUMERIC CHECK (price > 0)
);

ALTER TABLE widgets
    ADD CONSTRAINT chk_widget_max_quantity CHECK (quantity <= 10000);

CREATE VIEW active_widgets AS
    SELECT widget_id, quantity, price
    FROM widgets
    WHERE quantity > 0 AND price > 0;

SELECT widget_id
FROM widgets
WHERE quantity > 100;
""",
        encoding="utf-8",
    )
    return src


class TestSqlExtraction:
    def test_extracts_create_table(self, sample_sql):
        rules = SqlCodeExtractor().extract(sample_sql)
        tables = [r for r in rules if r.rule_type == "sql_table"]
        assert any(t.name == "widgets" for t in tables)

    def test_extracts_create_view(self, sample_sql):
        rules = SqlCodeExtractor().extract(sample_sql)
        views = [r for r in rules if r.rule_type == "sql_view"]
        assert any(v.name == "active_widgets" for v in views)

    def test_extracts_table_column_checks(self, sample_sql):
        rules = SqlCodeExtractor().extract(sample_sql)
        checks = [r for r in rules if r.rule_type == "sql_check"]
        # quantity >= 0 and price > 0 should both be captured as column CHECKs
        check_exprs = " ".join(c.expression for c in checks)
        assert "quantity" in check_exprs
        assert "price" in check_exprs

    def test_extracts_alter_table_add_constraint(self, sample_sql):
        rules = SqlCodeExtractor().extract(sample_sql)
        checks = [r for r in rules if r.rule_type == "sql_check"]
        named = [c for c in checks if c.name == "chk_widget_max_quantity"]
        assert named, "ALTER TABLE ADD CONSTRAINT CHECK not captured"
        assert "quantity" in named[0].expression

    def test_extracts_where_clauses(self, sample_sql):
        rules = SqlCodeExtractor().extract(sample_sql)
        wheres = [r for r in rules if r.rule_type == "sql_where"]
        assert len(wheres) >= 1
        # At least one WHERE should reference the quantity column
        assert any("quantity" in w.expression for w in wheres)

    def test_where_clause_symbol_table(self, sample_sql):
        rules = SqlCodeExtractor().extract(sample_sql)
        wheres = [r for r in rules if r.rule_type == "sql_where"]
        # Symbol table should contain column references
        all_symbols = [s for w in wheres for s in w.referenced_symbols]
        assert "quantity" in all_symbols or any("quantity" in s for s in all_symbols)

    def test_sql_comment_citations(self, sample_sql):
        rules = SqlCodeExtractor().extract(sample_sql)
        comments = [r for r in rules if r.rule_type == "comment_citation"]
        assert comments
        all_cites = [c for r in comments for c in r.citations]
        assert any("§7" in c for c in all_cites)
        assert any("Article 22" in c for c in all_cites)

    def test_sql_provenance_populated(self, sample_sql):
        rules = SqlCodeExtractor().extract(sample_sql)
        for r in rules:
            assert r.provenance is not None
            assert r.provenance.file_path == str(sample_sql)


class TestSqlParseFailure:
    def test_invalid_sql_returns_citations_only(self, tmp_path):
        """If sqlglot can't parse the file, we still keep any citations
        found in -- comments."""
        bad = tmp_path / "bad.sql"
        bad.write_text(
            "-- See Policy Document §99\nTHIS IS NOT VALID SQL $$$\n",
            encoding="utf-8",
        )
        rules = SqlCodeExtractor().extract(bad)
        # Comment citation is still captured even if the SQL parse fails
        comments = [r for r in rules if r.rule_type == "comment_citation"]
        assert comments
        assert any("§99" in c for r in comments for c in r.citations)


# ─── Citation regex tests ────────────────────────────────────────────────────


class TestCitationRegex:
    """Generic legal/spec citation patterns. Must be domain-neutral."""

    @pytest.mark.parametrize(
        "text,expected",
        [
            ("Per Section 5.2 of the policy", "Section 5.2"),
            ("See Article 14", "Article 14"),
            ("as required by §31", "§31"),
            ("refer to Paragraph 4", "Paragraph 4"),
            ("Chapter 2 specifies", "Chapter 2"),
            ("per ITS 42", "ITS 42"),
            ("Directive 2013/36", "Directive 2013/36"),
        ],
    )
    def test_matches_generic_citation_patterns(self, text, expected):
        cites = _find_citations(text)
        assert any(expected.lower() in c.lower() for c in cites), (
            f"Expected {expected!r} in extracted citations from {text!r}, got {cites}"
        )

    def test_symbol_citation_works_despite_non_word_boundary(self):
        """§ is not a \\w character, so a naive \\b lookup would fail.
        We use a negative lookbehind (?<![A-Za-z]) to handle this.
        """
        cites = _find_citations("Per §14, the rule applies")
        assert any("§14" in c for c in cites)

    def test_does_not_match_false_positives(self):
        """The lookbehind (?<![A-Za-z]) ensures 'section' inside 'intersection'
        does not match.
        """
        cites = _find_citations("at the intersection14 of two lines")
        assert cites == [], f"Should not match inside a word: {cites}"

    def test_no_domain_specific_vocabulary_in_regex(self):
        """The regex must not contain banking/NPL terms. Domain neutrality
        is enforced by tests/test_domain_neutrality.py, but we double-check
        here at the specific regex level.
        """
        pattern = _CITATION_RE.pattern.lower()
        banking_terms = [
            "npl", "basel", "ifrs", "finrep", "borrower", "collateral",
            "forbearance", "counterparty", "loan",
        ]
        for term in banking_terms:
            assert term not in pattern, (
                f"Citation regex should not reference banking term {term!r}"
            )


# ─── Top-level CodeExtractor tests ───────────────────────────────────────────


class TestCodeExtractorDispatch:
    """The top-level CodeExtractor dispatches by file extension."""

    def test_dispatches_py_to_python_extractor(self, sample_python):
        rules = CodeExtractor().extract_from_file(sample_python)
        assert any(r.rule_type == "function" for r in rules)

    def test_dispatches_sql_to_sql_extractor(self, sample_sql):
        rules = CodeExtractor().extract_from_file(sample_sql)
        assert any(r.rule_type in ("sql_view", "sql_table", "sql_check") for r in rules)

    def test_unknown_extension_returns_empty(self, tmp_path):
        other = tmp_path / "data.csv"
        other.write_text("a,b,c\n1,2,3\n", encoding="utf-8")
        assert CodeExtractor().extract_from_file(other) == []

    def test_extract_from_directory_walks_recursively(
        self, sample_python, sample_sql, tmp_path
    ):
        # Add a nested file to check recursion
        nested = tmp_path / "sub"
        nested.mkdir()
        nested_py = nested / "nested.py"
        nested_py.write_text("NESTED_CONSTANT = 42\n", encoding="utf-8")

        result = CodeExtractor().extract_from_directory(tmp_path, recursive=True)
        assert len(result.files_scanned) >= 3
        assert any(r.name == "NESTED_CONSTANT" for r in result.rules)

    def test_extract_from_directory_respects_non_recursive(
        self, sample_python, tmp_path
    ):
        nested = tmp_path / "sub"
        nested.mkdir()
        nested_py = nested / "nested.py"
        nested_py.write_text("NESTED_CONSTANT = 42\n", encoding="utf-8")

        result = CodeExtractor().extract_from_directory(tmp_path, recursive=False)
        # Only top-level sample_python should be scanned, not nested.py
        assert not any(r.name == "NESTED_CONSTANT" for r in result.rules)

    def test_extract_from_directory_records_timestamp(self, tmp_path):
        result = CodeExtractor().extract_from_directory(tmp_path)
        assert result.extraction_timestamp

    def test_extract_from_directory_raises_on_file_path(self, sample_python):
        with pytest.raises(NotADirectoryError):
            CodeExtractor().extract_from_directory(sample_python)


# ─── Provenance completeness (contract for fusion layer) ────────────────────


class TestProvenanceCompleteness:
    """Every CodeRule the deterministic pass produces must carry full
    provenance. The fusion layer (Step 6) relies on this contract to
    trace every claim back to (file, line) in the source tree.
    """

    def test_every_python_rule_has_file_and_line(self, sample_python):
        rules = PythonCodeExtractor().extract(sample_python)
        assert rules
        for r in rules:
            assert r.provenance is not None, (
                f"Rule {r.rule_type}:{r.name} has no provenance"
            )
            assert r.provenance.file_path, f"{r.name}: empty file_path"
            assert r.provenance.line > 0, f"{r.name}: line == 0"

    def test_every_sql_rule_has_file_path(self, sample_sql):
        rules = SqlCodeExtractor().extract(sample_sql)
        assert rules
        for r in rules:
            assert r.provenance is not None
            assert r.provenance.file_path, f"{r.name}: empty file_path"

    def test_every_rule_has_confidence(self, sample_python, sample_sql):
        """Deterministic rules should carry confidence (default 0.95)
        so the fusion layer can score them consistently with Source A
        outputs.
        """
        rules = (
            PythonCodeExtractor().extract(sample_python)
            + SqlCodeExtractor().extract(sample_sql)
        )
        for r in rules:
            assert 0.0 <= r.confidence <= 1.0, (
                f"{r.name}: confidence {r.confidence} out of [0,1]"
            )
