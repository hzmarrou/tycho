"""Fixture for PR1a AttributeFact extended-metadata extraction.

Each class exercises a different combination of the new fields:
description, is_multivalued, default_factory, enum_values, is_pk,
is_nullable, raw_type. Used by tests/test_source_d_ir_extension.py.

This fixture is parsed via ``parse_module`` and walked by
``extract_model``; it is not imported as Python (no need to actually
install pydantic / sqlalchemy for the test).
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field
from sqlalchemy import Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Priority(Enum):
    LOW = "low"
    HIGH = "high"


class Account(BaseModel):
    account_id: str = Field(description="Unique account identifier")
    name: str
    tags: list[str] = Field(default_factory=list)
    nickname: Optional[str] = None
    status: Literal["open", "closed"] = "open"
    notes: str = ""  # Free-form notes


@dataclass
class Order:
    order_id: str = field(metadata={"description": "Order primary key"})
    items: list[str] = field(default_factory=list)
    note: str | None = None
    priority: Priority = Priority.LOW


class Base(DeclarativeBase):
    pass


class Customer(Base):
    __tablename__ = "customer"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, comment="PK")
    email: Mapped[str] = mapped_column(String(255), nullable=False, comment="Login email")
    nickname: Mapped[str | None] = mapped_column(String(80), nullable=True)
    # Note: legacy SQLAlchemy ``id = Column(...)`` plain Assign is out of
    # PR1a scope — the existing extract_model loop walks only ast.AnnAssign.
    # Mapped[...] columns above use AnnAssign so they are covered.


# ─── Wrapped-annotation cases (Codex r1) ────────────────────────────────────
#
# The recursive annotation walker must propagate enum_values,
# is_multivalued, and is_nullable signals through wrapper types
# (Mapped, Optional, |None, list/set/Sequence). Each field below
# exercises one wrapped form that the r0 walker silently missed.


class Wrapped(BaseModel):
    """Pydantic class with wrapped annotations."""

    opt_enum: Optional[Priority] = None
    pep604_enum: Priority | None = None
    list_enum: list[Priority] = Field(default_factory=list)
    list_literal: list[Literal["red", "green"]] = Field(default_factory=list)
    opt_list_str: Optional[list[str]] = None


class WrappedColumn(Base):
    """SQLAlchemy 2.0 Mapped[...] wrapped annotations."""

    __tablename__ = "wrapped"
    mid: Mapped[int] = mapped_column(Integer, primary_key=True)
    mapped_enum: Mapped[Priority] = mapped_column()
    mapped_literal: Mapped[Literal["open", "closed"]] = mapped_column()
    mapped_list_str: Mapped[list[str]] = mapped_column()
    mapped_opt_str: Mapped[Optional[str]] = mapped_column()
