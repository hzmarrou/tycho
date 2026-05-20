def validate_payment(payment):
    if payment["amount"] <= 0:
        raise ValueError("amount must be positive")
    if payment.get("currency") is None:
        payment["currency"] = "EUR"
    return payment


def is_eligible(borrower):
    """Eligibility: a borrower with credit_score >= 500 may apply."""
    return borrower["credit_score"] >= 500


def settle(payment, approved):
    """Transition: an approved payment moves to PAID status."""
    if approved:
        payment["status"] = "PAID"
    return payment
