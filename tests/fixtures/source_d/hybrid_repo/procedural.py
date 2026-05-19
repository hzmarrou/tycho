def validate_payment(payment):
    if payment["amount"] <= 0:
        raise ValueError("amount must be positive")
    if payment.get("currency") is None:
        payment["currency"] = "EUR"
    return payment
