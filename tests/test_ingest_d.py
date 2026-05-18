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

        class CustomerModel(BaseModel):
            name: str
            email: str
    """
    f = _write(tmp_path, "models.py", src)
    cands = list(SourceDIngester().ingest({"files": [str(f)]}))
    entities = [c for c in cands if c.artifact_kind == ArtifactKind.ENTITY]
    by_label = {c.label: c for c in entities}
    assert "CustomerModel" in by_label
    # Pin the raw_type per the four-shape classifier contract. DTO flag
    # (raw_type=dto_candidate) lands in Task 13; Task 10 scaffold emits
    # pydantic_model.
    assert by_label["CustomerModel"].raw_type == "pydantic_model"


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
