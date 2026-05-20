"""Non-Performing Exposure classification rules.

Implements the categorisation criteria from Basel D403 Section 3.1.
This is a synthetic test fixture for Source D code extraction — it
embeds realistic threshold constants, conditional logic, and explicit
regulatory citations so the extractor has ground truth to validate
against.
"""

# Basel D403 §14: An exposure is non-performing if it is past due more than
# 90 days, regardless of jurisdiction. Retail exposures may use 180 DPD.
NPE_DPD_THRESHOLD = 90
NPE_DPD_THRESHOLD_RETAIL = 180

# Basel D403 §3.1: Materiality threshold below which past-due amounts are
# disregarded for NPE recognition.
MATERIALITY_THRESHOLD_EUR = 100
MATERIALITY_THRESHOLD_RELATIVE_PCT = 0.01

# IFRS 9 stages used to indicate impairment status. Stage 3 = credit-impaired.
IFRS_STAGE_PERFORMING = "ifrs_stage_1"
IFRS_STAGE_INCREASED_RISK = "ifrs_stage_2"
IFRS_STAGE_IMPAIRED = "ifrs_stage_3_impaired"


def classify_loan_as_npe(loan, exposure_amount: float, asset_class: str) -> bool:
    """Classify a loan as Non-Performing Exposure per Basel D403 §3.1.

    A loan is non-performing if any of the following criteria are met:
      - past due more than 90 days (180 for retail)  [Basel D403 §14]
      - credit-impaired under the accounting framework  [Basel D403 §16]
      - defaulted under the Basel framework  [Basel D403 §15]
    """
    is_retail = asset_class in ("retail", "consumer", "auto")
    threshold = NPE_DPD_THRESHOLD_RETAIL if is_retail else NPE_DPD_THRESHOLD

    # Past-due criterion
    if loan.days_past_due > threshold:
        return True

    # Credit-impaired criterion (IFRS 9 Stage 3)
    if loan.ifrs_stage == IFRS_STAGE_IMPAIRED:
        return True

    # Defaulted criterion (Basel framework Article 178)
    if loan.is_defaulted:
        return True

    # Unlikely-to-pay criterion (Basel D403 §17): subjective assessment
    # of whether full repayment is likely without realising collateral.
    if loan.unlikeliness_to_pay_flag:
        return True

    return False


def is_material_past_due(past_due_amount: float, total_exposure: float) -> bool:
    """Determine if a past-due amount crosses the materiality threshold.

    Per Basel D403 §3.1, materiality is the maximum of:
      - an absolute floor (default EUR 100)
      - a relative floor (default 1% of total counterparty exposure)
    """
    absolute_threshold = MATERIALITY_THRESHOLD_EUR
    relative_threshold = total_exposure * MATERIALITY_THRESHOLD_RELATIVE_PCT
    materiality = max(absolute_threshold, relative_threshold)
    return past_due_amount > materiality
