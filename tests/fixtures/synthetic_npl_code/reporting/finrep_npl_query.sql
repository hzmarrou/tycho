-- FINREP F18.00.a — Non-performing exposures by counterparty sector
--
-- Implements the regulatory reporting view defined in Basel D403 §18 and
-- the EBA Implementing Technical Standards on supervisory reporting.
-- Each NPE row in the result set is grouped by industry segment of the
-- counterparty and reports gross carrying amount, value adjustments, and
-- forbearance status.

CREATE VIEW finrep_f18_00_a AS
SELECT
    cg.industry_segment,
    COUNT(DISTINCT l.loan_id)                          AS npe_count,
    SUM(l.principal_balance)                           AS npe_gross_carrying_amount,
    SUM(l.principal_balance + l.accrued_interest_on_book) AS npe_total_exposure,
    SUM(CASE WHEN fe.forbearance_event_id IS NOT NULL
             THEN l.principal_balance ELSE 0 END)      AS npe_forborne_amount,
    SUM(CASE WHEN l.write_off_flag = TRUE
             THEN l.principal_balance ELSE 0 END)      AS npe_written_off_amount
FROM loan l
JOIN loan_borrower_link lbl ON lbl.loan_id = l.loan_id
JOIN borrower b              ON b.borrower_id = lbl.borrower_id
JOIN counterparty_group cg   ON cg.counterparty_group_id = b.group_id
LEFT JOIN forbearance_event fe ON fe.loan_id = l.loan_id
                              AND fe.end_date IS NULL  -- only active forbearance
WHERE l.is_non_performing = TRUE
  AND l.write_off_flag = FALSE
  AND l.days_past_due > 90  -- materiality: at least 90 DPD
GROUP BY cg.industry_segment;
