"""Source D twin of the schema.sql constraints — realistic capitalized class name.

The Python class is ``class Loan`` (PEP 8 convention) but the SQL table
is ``loan`` (SQL convention). merge_key normalizes both to ``loan``
internally, so the rule fuses into one CandidateConcept.
"""
from pydantic import BaseModel, field_validator


class Loan(BaseModel):
    amount: float

    @field_validator("amount")
    def positive(cls, v):
        if v <= 0:
            raise ValueError("amount must be positive")
        return v
