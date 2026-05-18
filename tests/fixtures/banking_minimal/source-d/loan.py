from dataclasses import dataclass

@dataclass
class Loan:
    amount: float
    term_months: int
    customer_id: int


def validate_amount(amount: float) -> bool:
    return amount > 0
