"""Procedural-family fixture: module-level functions, guards, defaults."""

def validate_payment(payment):
    if payment["amount"] <= 0:
        raise ValueError("amount must be positive")
    if payment.get("currency") is None:
        payment["currency"] = "EUR"
    return payment


def is_eligible(borrower):
    return borrower["credit_score"] >= 500
