"""Tests for Source D ingestion (Python AST)."""

from pathlib import Path
import textwrap

import pytest

from ontozense.core.ingest.base import ArtifactKind, Strength
from ontozense.core.ingest.ingest_d import SourceDIngester


def _write(tmp_path: Path, name: str, src: str) -> Path:
    path = tmp_path / name
    path.write_text(textwrap.dedent(src), encoding="utf-8")
    return path


def test_class_with_fields_is_entity(tmp_path):
    src = """
        class Customer:
            name: str
            email: str
            def __init__(self, name: str, email: str):
                self.name = name
                self.email = email
    """
    f = _write(tmp_path, "models.py", src)
    cands = list(SourceDIngester().ingest({"files": [str(f)]}))
    entities = [c for c in cands if c.artifact_kind == ArtifactKind.ENTITY]
    assert any(c.label == "Customer" for c in entities)

    customer = next(c for c in entities if c.label == "Customer")
    assert customer.source_type == "D"
    assert customer.strength == Strength.STRONG
    assert customer.raw_type == "class"


def test_dataclass_is_entity(tmp_path):
    src = """
        from dataclasses import dataclass

        @dataclass
        class Loan:
            amount: float
            term_months: int
    """
    f = _write(tmp_path, "models.py", src)
    cands = list(SourceDIngester().ingest({"files": [str(f)]}))
    entities = [c for c in cands if c.artifact_kind == ArtifactKind.ENTITY]
    assert any(c.label == "Loan" and c.raw_type == "dataclass"
               for c in entities)


def test_pydantic_basemodel_is_entity(tmp_path):
    src = """
        from pydantic import BaseModel

        class CustomerProfile(BaseModel):
            name: str
            email: str
    """
    f = _write(tmp_path, "models.py", src)
    cands = list(SourceDIngester().ingest({"files": [str(f)]}))
    entities = [c for c in cands if c.artifact_kind == ArtifactKind.ENTITY]
    by_label = {c.label: c for c in entities}
    assert "CustomerProfile" in by_label
    # Pin the raw_type per the four-shape classifier contract. The class
    # name does NOT end in a DTO-suffix, so raw_type stays 'pydantic_model'.
    assert by_label["CustomerProfile"].raw_type == "pydantic_model"


def test_no_files_yields_nothing():
    assert list(SourceDIngester().ingest({"files": []})) == []
    assert list(SourceDIngester().ingest({})) == []


def test_handles_non_dict_input_safely():
    """Non-dict raw_input is treated as empty — no exception."""
    ingester = SourceDIngester()
    assert list(ingester.ingest(None)) == []
    assert list(ingester.ingest([])) == []
    assert list(ingester.ingest("not a dict")) == []


def test_private_class_skipped_by_default(tmp_path):
    src = """
        class _InternalHelper:
            x: int
    """
    f = _write(tmp_path, "models.py", src)
    cands = list(SourceDIngester().ingest({"files": [str(f)]}))
    labels = {c.label for c in cands}
    assert "_InternalHelper" not in labels


def test_unparseable_python_skipped(tmp_path):
    f = _write(tmp_path, "broken.py", "def : not valid python at all")
    cands = list(SourceDIngester().ingest({"files": [str(f)]}))
    assert cands == []


def test_sqlalchemy_model_is_entity(tmp_path):
    """A class inheriting from SQLAlchemy's Base (or a recognised
    entity base like Document) emits as entity with
    raw_type='sqlalchemy_model'."""
    src = """
        class Loan(Base):
            id: int
            amount: float
            term_months: int
    """
    f = _write(tmp_path, "models.py", src)
    cands = list(SourceDIngester().ingest({"files": [str(f)]}))
    entities = [c for c in cands if c.artifact_kind == ArtifactKind.ENTITY]
    by_label = {c.label: c for c in entities}
    assert "Loan" in by_label
    assert by_label["Loan"].raw_type == "sqlalchemy_model"
    assert by_label["Loan"].strength == Strength.STRONG


def test_class_fields_yield_attribute_candidates(tmp_path):
    src = """
        class Customer:
            name: str
            email: str
            credit_score: int
    """
    f = _write(tmp_path, "models.py", src)
    cands = list(SourceDIngester().ingest({"files": [str(f)]}))
    attrs = [c for c in cands if c.artifact_kind == ArtifactKind.ATTRIBUTE]
    labels = sorted(c.label for c in attrs)
    assert labels == ["credit_score", "email", "name"]

    for a in attrs:
        assert a.source_type == "D"
        # raw_type carries the Python type annotation
        assert a.raw_type in ("str", "int")


def test_dataclass_fields_yield_attribute_candidates(tmp_path):
    src = """
        from dataclasses import dataclass

        @dataclass
        class Loan:
            amount: float
            term_months: int
    """
    f = _write(tmp_path, "models.py", src)
    cands = list(SourceDIngester().ingest({"files": [str(f)]}))
    attrs = [c for c in cands if c.artifact_kind == ArtifactKind.ATTRIBUTE]
    labels = sorted(c.label for c in attrs)
    assert labels == ["amount", "term_months"]


def test_enum_subclass_is_vocabulary(tmp_path):
    src = """
        from enum import Enum

        class LoanStatus(Enum):
            ACTIVE = "active"
            CLOSED = "closed"
            DELINQUENT = "delinquent"
    """
    f = _write(tmp_path, "models.py", src)
    cands = list(SourceDIngester().ingest({"files": [str(f)]}))
    by_label = {c.label: c for c in cands if c.artifact_kind in
                (ArtifactKind.VOCABULARY, ArtifactKind.ENTITY)}

    assert "LoanStatus" in by_label
    assert by_label["LoanStatus"].artifact_kind == ArtifactKind.VOCABULARY
    assert by_label["LoanStatus"].strength == Strength.MEDIUM
    assert by_label["LoanStatus"].raw_type == "enum"


def test_method_without_two_class_endpoints_is_behavior(tmp_path):
    src = """
        class Customer:
            name: str
            def compute_score(self) -> int:
                return 42
    """
    f = _write(tmp_path, "models.py", src)
    cands = list(SourceDIngester().ingest({"files": [str(f)]}))
    behaviors = [c for c in cands if c.artifact_kind == ArtifactKind.BEHAVIOR]
    assert any(c.label.endswith("compute_score") for c in behaviors)

    b = next(c for c in behaviors if c.label.endswith("compute_score"))
    assert b.strength == Strength.WEAK
    assert b.raw_type == "method"


def test_validation_function_is_rule(tmp_path):
    src = """
        def validate_amount(amount: float) -> bool:
            return amount > 0

        def check_credit_score(score: int) -> bool:
            return 300 <= score <= 850
    """
    f = _write(tmp_path, "rules.py", src)
    cands = list(SourceDIngester().ingest({"files": [str(f)]}))
    rules = [c for c in cands if c.artifact_kind == ArtifactKind.RULE]
    rule_labels = {c.label for c in rules}
    assert "validate_amount" in rule_labels
    assert "check_credit_score" in rule_labels

    for r in rules:
        assert r.strength == Strength.WEAK
        assert r.raw_type == "validation_function"


def test_dto_classes_flagged_with_raw_type(tmp_path):
    src = """
        from pydantic import BaseModel

        class LoanRequest(BaseModel):
            amount: float
    """
    f = _write(tmp_path, "schemas.py", src)
    cands = list(SourceDIngester().ingest({"files": [str(f)]}))
    cls = next(c for c in cands if c.label == "LoanRequest"
               and c.artifact_kind == ArtifactKind.ENTITY)
    assert cls.raw_type == "dto_candidate"


def test_test_directory_files_suppressed(tmp_path):
    test_dir = tmp_path / "tests"
    test_dir.mkdir()
    src = """
        class FakeCustomer:
            name: str
    """
    f = test_dir / "test_things.py"
    f.write_text(textwrap.dedent(src), encoding="utf-8")

    cands = list(SourceDIngester().ingest({"files": [str(f)]}))
    # FakeCustomer should NOT appear as a non-suppressed entity
    labels = {c.label for c in cands if not c.suppressed}
    assert "FakeCustomer" not in labels


def test_generated_code_marker_suppresses(tmp_path):
    src = """
        # AUTOGENERATED — DO NOT EDIT
        class GeneratedModel:
            field: str
    """
    f = _write(tmp_path, "generated_models.py", src)
    cands = list(SourceDIngester().ingest({"files": [str(f)]}))
    labels = {c.label for c in cands if not c.suppressed}
    assert "GeneratedModel" not in labels


def test_user_exclude_classes_suppresses(tmp_path):
    src = """
        class Customer:
            name: str
        class CustomerFactory:
            def create(self): pass
    """
    f = _write(tmp_path, "models.py", src)
    cfg = {"exclude_classes": ["*Factory"]}
    cands = list(SourceDIngester(config=cfg).ingest({"files": [str(f)]}))
    by_label = {
        c.label: c for c in cands
        if c.artifact_kind == ArtifactKind.ENTITY
    }
    assert by_label["Customer"].suppressed is False
    assert by_label["CustomerFactory"].suppressed is True


def test_user_include_classes_unsuppresses_dto(tmp_path):
    """A class that DTO-flags can be force-promoted to a real entity
    by include_classes — raw_type goes back to pydantic_model."""
    src = """
        from pydantic import BaseModel
        class LoanRequest(BaseModel):
            amount: float
    """
    f = _write(tmp_path, "schemas.py", src)
    cfg = {"include_classes": ["LoanRequest"]}
    cands = list(SourceDIngester(config=cfg).ingest({"files": [str(f)]}))
    cls = next(c for c in cands if c.label == "LoanRequest"
               and c.artifact_kind == ArtifactKind.ENTITY)
    assert cls.raw_type == "pydantic_model"


def test_user_include_classes_glob_unsuppresses_dto(tmp_path):
    """include_classes: ['*Request'] (glob) restores raw_type=pydantic_model
    on LoanRequest, mirroring exclude_classes' glob semantics."""
    src = """
        from pydantic import BaseModel
        class LoanRequest(BaseModel):
            amount: float
    """
    f = _write(tmp_path, "schemas.py", src)
    cfg = {"include_classes": ["*Request"]}
    cands = list(SourceDIngester(config=cfg).ingest({"files": [str(f)]}))
    cls = next(c for c in cands if c.label == "LoanRequest"
               and c.artifact_kind == ArtifactKind.ENTITY)
    assert cls.raw_type == "pydantic_model"


def test_user_include_classes_is_case_insensitive(tmp_path):
    """include_classes: ['loanrequest'] (lower-case) restores
    raw_type=pydantic_model on the upper-case LoanRequest class —
    matching is case-insensitive per spec §7.4."""
    src = """
        from pydantic import BaseModel
        class LoanRequest(BaseModel):
            amount: float
    """
    f = _write(tmp_path, "schemas.py", src)
    cfg = {"include_classes": ["loanrequest"]}
    cands = list(SourceDIngester(config=cfg).ingest({"files": [str(f)]}))
    cls = next(c for c in cands if c.label == "LoanRequest"
               and c.artifact_kind == ArtifactKind.ENTITY)
    assert cls.raw_type == "pydantic_model"


def test_path_suppression_is_case_insensitive(tmp_path):
    """Tests/test_models.py (capitalised dir) is suppressed by the
    default tests/** pattern — matching is case-insensitive per
    spec §7.4."""
    test_dir = tmp_path / "Tests"  # capital T
    test_dir.mkdir()
    src = """
        class FakeCustomer:
            name: str
    """
    f = test_dir / "test_models.py"
    f.write_text(textwrap.dedent(src), encoding="utf-8")

    cands = list(SourceDIngester().ingest({"files": [str(f)]}))
    labels = {c.label for c in cands if not c.suppressed}
    assert "FakeCustomer" not in labels


def test_path_suppression_config_pattern_is_case_insensitive(tmp_path):
    """A user exclude_paths pattern in different case still matches
    a lower-case file path."""
    code_dir = tmp_path / "legacy_engine"
    code_dir.mkdir()
    src = """
        class LegacyThing:
            x: int
    """
    f = code_dir / "models.py"
    f.write_text(textwrap.dedent(src), encoding="utf-8")

    cfg = {"exclude_paths": ["LEGACY_*/**"]}    # upper-case pattern
    cands = list(SourceDIngester(config=cfg).ingest({"files": [str(f)]}))
    labels = {c.label for c in cands if not c.suppressed}
    assert "LegacyThing" not in labels


def test_user_force_vocabulary_supports_glob(tmp_path):
    """force_vocabulary: ['*Status'] reclassifies a class named
    CustomerStatusInfo from ENTITY to VOCABULARY at MEDIUM strength,
    matching Source C's force_vocabulary contract (per spec §7.4)."""
    src = """
        class CustomerStatusInfo:
            code: str
            description: str
    """
    f = _write(tmp_path, "models.py", src)
    cfg = {"force_vocabulary": ["*Status*"]}
    cands = list(SourceDIngester(config=cfg).ingest({"files": [str(f)]}))
    by_label = {c.label: c for c in cands}
    assert "CustomerStatusInfo" in by_label
    assert by_label["CustomerStatusInfo"].artifact_kind == ArtifactKind.VOCABULARY
    assert by_label["CustomerStatusInfo"].strength == Strength.MEDIUM
