"""State transition rules for non-performing → performing recategorisation.

Per Basel D403 §3.2 (Recategorisation of non-performing exposures as
performing), a non-performing exposure can only be recategorised as
performing when several criteria are simultaneously met. Forbearance
itself does not upgrade NPE status.
"""

from datetime import date

# Basel D403 §22: minimum continuous repayment period before NPE → performing.
# The standard minimum is 3 months, but supervisors may set higher values.
PROBATION_PERIOD_DAYS = 90
PROBATION_PERIOD_MONTHS = 3

# Basel D403 §38: forbearance probation is at least 1 year regardless of
# the standard NPE probation.
FORBEARANCE_PROBATION_YEARS = 1


def can_upgrade_to_performing(
    loan,
    payment_history,
    has_active_forbearance: bool,
) -> bool:
    """Determine if a non-performing loan can be reclassified as performing.

    Per Basel D403 §3.2:
      - The exposure must currently be non-performing
      - There must be no active forbearance arrangement (forbearance does
        NOT upgrade — see Basel D403 §53)
      - The probation period must have elapsed
      - Repayment must have been continuous and timely during probation
      - Counterparty's likelihood of full repayment must have improved
    """
    if not loan.is_non_performing:
        return False

    # Forbearance cannot trigger an upgrade
    if has_active_forbearance:
        return False

    # Probation period elapsed
    days_since_default = (date.today() - loan.default_date).days
    if days_since_default < PROBATION_PERIOD_DAYS:
        return False

    # Continuous timely repayments
    if not payment_history.continuous_timely_repayments(months=PROBATION_PERIOD_MONTHS):
        return False

    # Improved likelihood of full repayment
    if not payment_history.improved_repayment_likelihood:
        return False

    return True


def can_exit_forborne_status(forbearance, payment_history) -> bool:
    """Determine if a forborne exposure can exit forborne status.

    Per Basel D403 §38:
      - At least 1 year must have elapsed since the forbearance was granted
      - No past-due amounts during that period
      - Counterparty financial difficulty has resolved
    """
    years_since = (date.today() - forbearance.granted_date).days / 365.25
    if years_since < FORBEARANCE_PROBATION_YEARS:
        return False

    if payment_history.had_past_due_during(forbearance.granted_date, date.today()):
        return False

    if forbearance.counterparty_still_in_difficulty:
        return False

    return True
