"""Forbearance validation rules.

Per Basel D403 Section 4 (Definition of forbearance), forbearance is a
concession granted to a counterparty experiencing financial difficulty
that the lender would not otherwise consider. Forbearance does not
upgrade NPE status (Basel D403 §53).
"""


def is_forbearance(loan_modification, counterparty_status) -> bool:
    """Determine if a loan modification qualifies as forbearance.

    Per Basel D403 §31, two conditions must hold simultaneously:
      - The counterparty is experiencing financial difficulty
      - The modification is a concession the lender would not normally make
    """
    if not counterparty_status.is_in_financial_difficulty:
        return False

    if not loan_modification.is_concessionary:
        return False

    return True


def validate_forbearance_event(forbearance_event, loan) -> list[str]:
    """Validate a forbearance event against Basel D403 §54 constraints.

    Returns a list of validation error strings (empty list = valid).
    """
    errors = []

    # Forbearance cannot predate the loan it concerns
    if forbearance_event.start_date < loan.origination_date:
        errors.append(
            "Forbearance start_date predates loan origination_date "
            "(violates causal ordering — see Basel D403 §54)"
        )

    # Forbearance end_date must be after start_date if set
    if forbearance_event.end_date is not None:
        if forbearance_event.end_date < forbearance_event.start_date:
            errors.append("Forbearance end_date is before start_date")

    # If the loan was already non-performing when forbearance was granted,
    # it cannot be marked as performing-forborne (Basel D403 §53)
    if loan.was_non_performing_at(forbearance_event.start_date):
        if forbearance_event.classification == "performing_forborne":
            errors.append(
                "Loan was non-performing when forbearance was granted; "
                "cannot be classified as performing_forborne — see Basel D403 §53"
            )

    return errors
