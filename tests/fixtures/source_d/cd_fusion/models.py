"""Source D twin of the schema.sql constraints — same canonical rule shape."""
from pydantic import BaseModel, field_validator


class loan(BaseModel):
    amount: float

    @field_validator("amount")
    def positive(cls, v):
        if v <= 0:
            raise ValueError("amount must be positive")
        return v
