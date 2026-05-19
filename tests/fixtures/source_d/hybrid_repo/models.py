from dataclasses import dataclass
from enum import Enum

from pydantic import BaseModel, field_validator


class LoanStatus(Enum):
    PERFORMING = "performing"
    NON_PERFORMING = "non_performing"


@dataclass
class Borrower:
    id: str
    name: str


class Loan(BaseModel):
    amount: float
    status: LoanStatus

    @field_validator("amount")
    def positive(cls, v):
        if v <= 0:
            raise ValueError("amount must be positive")
        return v
