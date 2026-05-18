from dataclasses import dataclass
from enum import Enum

@dataclass
class Customer:
    """A customer of the bank."""
    name: str
    email: str
    credit_score: int


class CustomerStatus(Enum):
    ACTIVE = "active"
    DORMANT = "dormant"
    CLOSED = "closed"
