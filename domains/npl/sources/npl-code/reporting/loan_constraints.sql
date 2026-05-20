-- Schema-level CHECK constraints for the loan table.
-- These encode business rules at the database level so the data layer
-- enforces them regardless of which application path writes a row.

ALTER TABLE loan
    ADD CONSTRAINT chk_loan_dpd_non_negative
        CHECK (days_past_due >= 0);

ALTER TABLE loan
    ADD CONSTRAINT chk_loan_default_after_origination
        CHECK (default_date IS NULL OR default_date >= origination_date);

ALTER TABLE loan
    ADD CONSTRAINT chk_loan_npe_requires_default_date
        -- A loan flagged as non-performing must have a default_date set.
        -- Implements the audit trail requirement from Basel D403 §19.
        CHECK (is_non_performing = FALSE OR default_date IS NOT NULL);

ALTER TABLE loan
    ADD CONSTRAINT chk_loan_principal_balance_non_negative
        CHECK (principal_balance >= 0);

-- Forbearance must be granted on or after the loan origination date.
ALTER TABLE forbearance_event
    ADD CONSTRAINT chk_forbearance_after_origination
        CHECK (
            start_date >= (
                SELECT origination_date FROM loan
                WHERE loan_id = forbearance_event.loan_id
            )
        );
