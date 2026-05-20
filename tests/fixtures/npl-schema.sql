SET search_path TO opennpl;

-- CounterpartyGroup: The CounterpartyGroup model holds Counterparty Group data conforming to the EBA 
CREATE TABLE IF NOT EXISTS counterpartygroup (
    id SERIAL PRIMARY KEY,
    counterparty_group_identifier TEXT,
    cross_collateralisation_in_counterparty_group TEXT,
    cross_default_in_counterparty_group TEXT,
    description_of_cross_collateralisation TEXT,
    description_of_cross_default TEXT,
    description_of_sponsor TEXT,
    industry_segment_of_counterparty_group TEXT,
    name_of_counterparty_group TEXT,
    name_of_sponsor TEXT,
    type_of_sponsor TEXT,
    creation_date TIMESTAMP,
    last_change_date TIMESTAMP
);

-- Portfolio: The portfolio data object is useful to aggregate datasets belonging to the same 
CREATE TABLE IF NOT EXISTS portfolio (
    id SERIAL PRIMARY KEY,
    name TEXT,
    description TEXT,
    creation_date TIMESTAMP,
    last_change_date TIMESTAMP
);

-- PortfolioSnapshot: The NPL Portfolio_Snapshot object groups NPL Portfolio generated portfolio data 
CREATE TABLE IF NOT EXISTS portfoliosnapshot (
    id SERIAL PRIMARY KEY,
    creation_date TIMESTAMP,
    last_change_date TIMESTAMP,
    cutoff_date TIMESTAMP,
    name TEXT
);

-- Counterparty: The Counterparty model holds Counterparty data conforming to the EBA NPL Templat
CREATE TABLE IF NOT EXISTS counterparty (
    id SERIAL PRIMARY KEY,
    counterparty_identifier TEXT,
    borrower_type TEXT,
    address_of_registered_location TEXT,
    annual_ebit BIGINT,
    annual_revenue BIGINT,
    basis_of_financial_statements TEXT,
    business_description TEXT,
    cash_and_cash_equivalent_items BIGINT,
    city_of_registered_location TEXT,
    comments_on_other_litigation_related_process TEXT,
    commencement_date_of_insolvency_or_restructuring_proceedings DATE,
    contingent_obligations TEXT,
    counterparty_role TEXT,
    country_of_registered_location TEXT,
    correspondence_address_of_appointed_insolvency_practitioner TEXT,
    insolvency_practitioner_reference TEXT,
    proof_of_claim_filed_by_the_seller BOOLEAN,
    distribution_made_to_the_seller BOOLEAN,
    notice_for_procedure_termination BOOLEAN,
    cross_collateralisation_for_counterparty TEXT,
    cross_default_for_counterparty TEXT,
    currency_of_deposit TEXT,
    currency_of_financial_statements TEXT,
    current_assets BIGINT,
    current_external_credit_rating TEXT,
    current_internal_credit_rating TEXT,
    date_of_appointment DATE,
    date_of_external_demand_issuance DATE,
    date_of_incorporation DATE,
    date_of_internal_demand_issuance DATE,
    date_of_last_contact DATE,
    date_of_latest_annual_financial_statements DATE,
    date_of_obtaining_order_for_possession DATE,
    date_when_reservation_of_rights_letter_was_issued DATE,
    deposit_balance_with_institution BIGINT,
    description_of_contingent_obligations TEXT,
    description_of_cross_collateralisation TEXT,
    description_of_cross_default TEXT,
    description_of_related_party TEXT,
    eligibility_for_deposit_to_offset TEXT,
    enterprise_size TEXT,
    eviction_date DATE,
    external_credit_rating_at_origination TEXT,
    financial_statements_type TEXT,
    financials_audited TEXT,
    fixed_assets BIGINT,
    geographic_region_classification TEXT,
    geographic_region_of_registered_location TEXT,
    indicator_of_counterparty_cooperation TEXT,
    industry_segment TEXT,
    insolvency_practitioner_appointed TEXT,
    internal_credit_rating_at_origination TEXT,
    jurisdiction_of_court TEXT,
    legal_entity_identifier TEXT,
    legal_fees_accrued BIGINT,
    legal_procedure_type TEXT,
    description_of_legal_procedure_type TEXT,
    legal_type_of_counterparty TEXT,
    market_capitalisation BIGINT,
    name_of_counterparty TEXT,
    name_of_insolvency_practitioner TEXT,
    name_of_insolvency_or_restructuring_proceedings TEXT,
    additional_name_of_insolvency_or_restructuring_proceedings TEXT,
    net_assets BIGINT,
    number_of_fte BIGINT,
    number_of_joint_counterparties BIGINT,
    occupation_type TEXT,
    occupation_description TEXT,
    other_products_with_institution TEXT,
    postcode_of_registered_location TEXT,
    registration_number TEXT,
    related_party TEXT,
    sheriff_or_bailiff_acquisition_date DATE,
    source_of_current_external_credit_rating TEXT,
    source_of_external_credit_rating_at_origination TEXT,
    stage_reached_in_insolvency_or_restructuring_procedure TEXT,
    additional_stage_reached_in_insolvency_procedure TEXT,
    total_assets BIGINT,
    total_debt BIGINT,
    total_liabilities BIGINT,
    creation_date TIMESTAMP,
    last_change_date TIMESTAMP,
    counterparty_group_identifier INTEGER REFERENCES counterpartygroup(id),
    portfolio_id INTEGER REFERENCES portfolio(id),
    snapshot_id INTEGER REFERENCES portfoliosnapshot(id)
);

-- Loan: The Loan model holds Loan Portfolio data conforming to the EBA NPL Template spec
CREATE TABLE IF NOT EXISTS loan (
    id SERIAL PRIMARY KEY,
    contract_identifier TEXT,
    instrument_identifier TEXT,
    accounting_stages_of_asset_quality TEXT,
    accrued_interest_balance_off_book BIGINT,
    accrued_interest_balance_on_book BIGINT,
    amortisation_type TEXT,
    asset_class TEXT,
    balance_at_default BIGINT,
    capitalised_pastdue_amount BIGINT,
    channel_of_origination TEXT,
    chargeoff_date DATE,
    code_of_conduct TEXT,
    comments_on_code_of_conduct TEXT,
    comments_on_covenant_waiver TEXT,
    country_of_origination TEXT,
    covenant_waiver TEXT,
    current_covenant_levels BIGINT,
    current_external_credit_rating TEXT,
    current_interest_base_rate DOUBLE PRECISION,
    current_interest_margin DOUBLE PRECISION,
    current_interest_rate DOUBLE PRECISION,
    current_interest_rate_reference TEXT,
    current_interest_rate_type TEXT,
    current_internal_credit_rating TEXT,
    current_maturity_date DATE,
    current_reversion_interest_rate DOUBLE PRECISION,
    date_of_default DATE,
    date_of_origination DATE,
    days_in_pastdue BIGINT,
    default_penalty_interest_margin DOUBLE PRECISION,
    description_of_bespoke_repayment TEXT,
    description_of_current_interest_rate_type TEXT,
    description_of_original_interest_rate_type TEXT,
    description_of_relevant_schemes TEXT,
    details_of_origination_channel TEXT,
    early_redemption_penalty DOUBLE PRECISION,
    end_date_of_current_fixed_interest_period DATE,
    end_date_of_interest_grace_period DATE,
    end_date_of_interest_only_period DATE,
    end_date_of_principal_grace_period DATE,
    end_date_of_subsidy DATE,
    external_credit_rating_at_origination TEXT,
    final_bullet_repayment BIGINT,
    governing_law_of_loan_agreement TEXT,
    interest_cap_rate DOUBLE PRECISION,
    interest_floor_rate DOUBLE PRECISION,
    interest_payment_frequency TEXT,
    interest_reset_interval BIGINT,
    internal_credit_rating_at_origination TEXT,
    last_covenant_test_date DATE,
    last_interest_reset_date DATE,
    last_payment_amount BIGINT,
    last_payment_date DATE,
    legal_balance BIGINT,
    legal_balance_at_chargeoff_date BIGINT,
    loan_commitment BIGINT,
    loan_covenants TEXT,
    loan_currency TEXT,
    loan_purpose TEXT,
    loan_status TEXT,
    marp_applicable BOOLEAN,
    marp_entry DATE,
    marp_status TEXT,
    next_interest_reset_date DATE,
    next_interest_scheduled_repayment_amount BIGINT,
    next_interest_scheduled_repayment_date DATE,
    next_principal_scheduled_repayment_amount BIGINT,
    next_principal_scheduled_repayment_date DATE,
    nonperforming_reason TEXT,
    number_of_pastdue_events BIGINT,
    original_interest_base_rate DOUBLE PRECISION,
    original_interest_margin DOUBLE PRECISION,
    original_interest_rate DOUBLE PRECISION,
    original_interest_rate_reference TEXT,
    original_interest_rate_type TEXT,
    original_maturity_date DATE,
    origination_amount BIGINT,
    other_balances BIGINT,
    other_pastdue_amounts BIGINT,
    other_syndicate_counterparties TEXT,
    pastdue_interest_amount BIGINT,
    pastdue_penalty_interest_margin DOUBLE PRECISION,
    pastdue_principal_amount BIGINT,
    principal_balance BIGINT,
    principal_payment_frequency TEXT,
    product_type TEXT,
    relevant_schemes TEXT,
    recourse_to_other_assets BOOLEAN,
    securitised TEXT,
    source_of_current_external_credit_rating TEXT,
    source_of_external_credit_rating_at_origination TEXT,
    specialised_product TEXT,
    start_date_of_current_fixed_interest_period DATE,
    start_date_of_interest_grace_period DATE,
    start_date_of_interest_only_period DATE,
    start_date_of_principal_grace_period DATE,
    start_date_of_subsidy DATE,
    subsidy TEXT,
    subsidy_amount BIGINT,
    subsidy_provider TEXT,
    syndicated_loan TEXT,
    syndicated_portion DOUBLE PRECISION,
    time_in_pastdue BIGINT,
    total_balance BIGINT,
    total_pastdue_amount BIGINT,
    trigger_levels_of_loan_covenants BIGINT,
    type_of_reversion_interest_rate TEXT,
    creation_date TIMESTAMP,
    last_change_date TIMESTAMP,
    counterparty_identifier INTEGER REFERENCES counterparty(id)
);

-- NonPropertyCollateral: The NonPropertyCollateral model holds Non-Property Collateral data conforming to
CREATE TABLE IF NOT EXISTS nonpropertycollateral (
    id SERIAL PRIMARY KEY,
    protection_identifier TEXT,
    activation_of_guarantee BOOLEAN,
    collateral_insurance BOOLEAN,
    collateral_insurance_coverage_amount DOUBLE PRECISION,
    collateral_insurance_provider TEXT,
    collateral_type TEXT,
    estimated_useful_life BIGINT,
    configuration TEXT,
    original_country_of_registration TEXT,
    current_country_of_registration TEXT,
    currency_of_collateral TEXT,
    current_opex_and_overheads DOUBLE PRECISION,
    date_of_initial_valuation DATE,
    date_of_latest_valuation DATE,
    description TEXT,
    enforcement_description TEXT,
    enforcement_status BOOLEAN,
    enforcement_status_third_parties BOOLEAN,
    engine_size DOUBLE PRECISION,
    guarantee_amount DOUBLE PRECISION,
    initial_valuation_amount DOUBLE PRECISION,
    initial_residual_value DOUBLE PRECISION,
    date_of_the_latest_residual_valuation DATE,
    initial_residual_valuation_date DATE,
    latest_residual_value DOUBLE PRECISION,
    latest_valuation_amount DOUBLE PRECISION,
    legal_owner TEXT,
    manufacturer_of_collateral TEXT,
    name_or_model_of_collateral TEXT,
    new_or_used TEXT,
    registration_number TEXT,
    type_of_initial_valuation TEXT,
    type_of_latest_valuation TEXT,
    type_of_legal_owner TEXT,
    asset_purchase_obligation BOOLEAN,
    option_to_buy_price DOUBLE PRECISION,
    year_of_manufacture DATE,
    year_of_registration DATE,
    creation_date TIMESTAMP,
    last_change_date TIMESTAMP,
    loan_identifier INTEGER REFERENCES loan(id)
);

-- PropertyCollateral: The PropertyCollateral model object holds Property Collateral data conforming to
CREATE TABLE IF NOT EXISTS propertycollateral (
    id SERIAL PRIMARY KEY,
    protection_identifier TEXT,
    address_of_property TEXT,
    amount_of_vat_payable DOUBLE PRECISION,
    area_type_of_property TEXT,
    building_area_m2 DOUBLE PRECISION,
    building_area_m2_lettable DOUBLE PRECISION,
    building_area_m2_occupied DOUBLE PRECISION,
    city_of_property TEXT,
    completion_of_property BOOLEAN,
    condition_of_property TEXT,
    currency_of_property TEXT,
    current_annual_passing_rent DOUBLE PRECISION,
    current_net_operating_income DOUBLE PRECISION,
    current_opex_and_overheads DOUBLE PRECISION,
    date_of_initial_valuation DATE,
    date_of_latest_valuation DATE,
    enforcement_description TEXT,
    enforcement_status BOOLEAN,
    enforcement_status_third_parties BOOLEAN,
    estimated_annual_void_cost DOUBLE PRECISION,
    estimated_rental_void DOUBLE PRECISION,
    geographic_region_classification TEXT,
    geographic_region_of_property TEXT,
    initial_estimated_rental_value DOUBLE PRECISION,
    initial_valuation_amount DOUBLE PRECISION,
    internal_or_external_initial_valuation TEXT,
    internal_or_external_latest_valuation TEXT,
    land_area_m2 DOUBLE PRECISION,
    latest_estimated_rental_value DOUBLE PRECISION,
    latest_valuation_amount DOUBLE PRECISION,
    legal_owner_of_the_property TEXT,
    number_of_bedrooms DOUBLE PRECISION,
    number_of_car_parking_spaces DOUBLE PRECISION,
    number_of_lettable_units DOUBLE PRECISION,
    number_of_rooms DOUBLE PRECISION,
    number_of_units_occupied DOUBLE PRECISION,
    number_of_units_vacant DOUBLE PRECISION,
    party_liable_for_vat TEXT,
    percentage_complete DOUBLE PRECISION,
    planned_capex_next_12m DOUBLE PRECISION,
    property_country TEXT,
    property_postcode TEXT,
    provider_of_energy_performance_certificate TEXT,
    provider_of_initial_valuation TEXT,
    provider_of_latest_valuation TEXT,
    purpose_of_property TEXT,
    register_of_deeds_number TEXT,
    remaining_term_of_leasehold DOUBLE PRECISION,
    sector_of_property TEXT,
    tenure TEXT,
    type_of_initial_valuation TEXT,
    type_of_latest_valuation TEXT,
    type_of_occupancy TEXT,
    type_of_property TEXT,
    value_of_energy_performance_certificate TEXT,
    vat_payable BOOLEAN,
    year_of_construction DATE,
    year_of_refurbishment DATE,
    creation_date TIMESTAMP,
    last_change_date TIMESTAMP,
    loan_identifier INTEGER REFERENCES loan(id)
);

-- Enforcement: The Enforcement model holds Enforcement data conforming to the EBA NPL Template 
CREATE TABLE IF NOT EXISTS enforcement (
    id SERIAL PRIMARY KEY,
    enforcement_identifier TEXT,
    protection_identifier TEXT,
    amount_of_outstanding_liabilities DOUBLE PRECISION,
    annual_insurance_payment DOUBLE PRECISION,
    contracted_date DATE,
    collateral_repossessed_date DATE,
    costs_accrued_to_buyer DOUBLE PRECISION,
    costs_at_end_of_sale DOUBLE PRECISION,
    court_appraisal_amount DOUBLE PRECISION,
    court_auction_identifier TEXT,
    court_auction_reserve_price_for_first_auction DOUBLE PRECISION,
    court_auction_reserve_price_for_last_auction DOUBLE PRECISION,
    court_auction_reserve_price_for_next_auction DOUBLE PRECISION,
    currency_of_enforcement TEXT,
    current_market_status TEXT,
    date_next_insurance_payment_is_due DATE,
    date_of_court_appraisal DATE,
    date_of_receiver_appointment DATE,
    enforcement_description TEXT,
    fees_of_receivership DOUBLE PRECISION,
    first_auction_date DATE,
    funds_remitted_full_date DATE,
    funds_remitted_partial_date DATE,
    gross_sale_proceeds DOUBLE PRECISION,
    indicator_of_enforcement BOOLEAN,
    indicator_of_receivership BOOLEAN,
    insurance BOOLEAN,
    insurance_coverage_amount DOUBLE PRECISION,
    insurance_provider TEXT,
    jurisdiction_of_court TEXT,
    last_auction_date DATE,
    name_of_legal_firm TEXT,
    name_of_receiver TEXT,
    net_sale_proceeds DOUBLE PRECISION,
    next_auction_date DATE,
    number_of_failed_auctions DOUBLE PRECISION,
    offer_price DOUBLE PRECISION,
    on_market_offer_date DATE,
    on_market_price DOUBLE PRECISION,
    other_ongoing_enforcement_proceedings TEXT,
    prepare_property_for_sale_date DATE,
    property_on_market_date DATE,
    sale_agreed_date DATE,
    sale_agreed_price DOUBLE PRECISION,
    sold_date DATE,
    creation_date TIMESTAMP,
    last_change_date TIMESTAMP,
    property_collateral_identifier INTEGER REFERENCES propertycollateral(id),
    non_property_collateral_identifier INTEGER REFERENCES nonpropertycollateral(id),
    counterparty_identifier INTEGER REFERENCES counterparty(id)
);

-- ExternalCollection: The ExternalCollection model holds External Collection data conforming to the EB
CREATE TABLE IF NOT EXISTS externalcollection (
    id SERIAL PRIMARY KEY,
    external_collection_identifier TEXT,
    institutions_internal_identifier_for_the_loan_or_counterparty TEXT,
    instrument_identifier TEXT,
    type_of_identifier TEXT,
    balance_amount_sent_to_agent DOUBLE PRECISION,
    cash_recoveries DOUBLE PRECISION,
    costs_accrued DOUBLE PRECISION,
    date_returned_from_agent DATE,
    date_sent_to_agent DATE,
    legal_entity_identifier TEXT,
    name_of_external_debt_collection_agent TEXT,
    principal_forgiveness DOUBLE PRECISION,
    quantity_returned_from_agent DOUBLE PRECISION,
    registration_number TEXT,
    repayment_plan BOOLEAN,
    repayment_plan_description TEXT,
    creation_date TIMESTAMP,
    last_change_date TIMESTAMP,
    loan_identifier INTEGER REFERENCES loan(id),
    counterparty_identifier INTEGER REFERENCES counterparty(id)
);

-- Forbearance: The Forbearance model holds Forbearance data conforming to the EBA NPL Template 
CREATE TABLE IF NOT EXISTS forbearance (
    id SERIAL PRIMARY KEY,
    forbearance_identifier TEXT,
    type_of_identifier TEXT,
    institutions_internal_identifier_for_the_loan_or_counterparty TEXT,
    instrument_identifier TEXT,
    amount_of_repayment_step_up DOUBLE PRECISION,
    clause_to_stop_forbearance BOOLEAN,
    date_of_first_forbearance DATE,
    date_of_principal_forgiveness DATE,
    date_of_repayment_step_up DATE,
    description_of_forbearance TEXT,
    description_of_the_forbearance_clause TEXT,
    end_date_of_forbearance DATE,
    interest_rate_under_forbearance DOUBLE PRECISION,
    number_of_historical_forbearance DOUBLE PRECISION,
    principal_forgiveness DOUBLE PRECISION,
    repayment_amount_under_forbearance DOUBLE PRECISION,
    repayment_frequency_under_forbearance TEXT,
    start_date_of_forbearance DATE,
    type_of_forbearance TEXT,
    creation_date TIMESTAMP,
    last_change_date TIMESTAMP,
    loan_identifier INTEGER REFERENCES loan(id),
    counterparty_identifier INTEGER REFERENCES counterparty(id)
);

COMMENT ON TABLE counterpartygroup IS 'The CounterpartyGroup model holds Counterparty Group data conforming to the EBA NPL Template specification';
COMMENT ON COLUMN counterpartygroup.cross_collateralisation_in_counterparty_group IS 'Indicator as to whether all / some of the loans in the Counterparty Group are secured by all / some of the collaterals within the Counterparty Group ("Full", "Partial", "none"). Documentation';
COMMENT ON COLUMN counterpartygroup.cross_default_in_counterparty_group IS 'The indicator as to whether Contractual breach of any loans in the Counterparty Group would trigger the contractual default event of the other loans. ("Full", "Partial", "none"). Documentation';
COMMENT ON COLUMN counterpartygroup.description_of_cross_collateralisation IS 'Description of cross collateralisation when "Partial" is selected in field "Cross Collateralisation in Borrower Group". Documentation';
COMMENT ON COLUMN counterpartygroup.description_of_cross_default IS 'Description of cross default when "Partial" is selected in field "Cross Default in Borrower Group". Documentation';
COMMENT ON COLUMN counterpartygroup.description_of_sponsor IS 'Description and related narrative on the Sponsor, e.g. the Sponsor is a high net worth individual and owns the Borrower via a fund. Documentation';
COMMENT ON COLUMN counterpartygroup.industry_segment_of_counterparty_group IS 'Industry in which the Counterparty Group mainly operates. Documentation';
COMMENT ON COLUMN counterpartygroup.name_of_counterparty_group IS 'Name used to refer to the Counterparty Group. Documentation';
COMMENT ON COLUMN counterpartygroup.name_of_sponsor IS 'Name used to refer to the main decision maker / key individual in relation to the Counterparty Group. Documentation';
COMMENT ON COLUMN counterpartygroup.type_of_sponsor IS 'Type of entity the sponsor is i.e. Listed Corporate, Unlisted Corporate, Listed Fund, Unlisted Fund and High Net Worth Individual. Documentation';
COMMENT ON TABLE portfolio IS 'The portfolio data object is useful to aggregate datasets belonging to the same actual credit portfolio. A portfolio may be optionally named to facilitate recognition and a longer description provides';
COMMENT ON COLUMN portfolio.description IS 'Description of the portfolio';
COMMENT ON TABLE portfoliosnapshot IS 'The NPL Portfolio_Snapshot object groups NPL Portfolio generated portfolio data for a given cutoff date. The Snapshot may be named to facilitate recognition.';
COMMENT ON COLUMN portfoliosnapshot.creation_date IS 'Date at which the snapshot has been created. Different from the cutoff date';
COMMENT ON COLUMN portfoliosnapshot.cutoff_date IS 'Portfolio Cutoff Date (If available). Different from the creation date';
COMMENT ON COLUMN portfoliosnapshot.name IS 'An assigned name to help identify the snapshot. By convention the name of the portfolio plus the cutoff date';
COMMENT ON TABLE counterparty IS 'The Counterparty model holds Counterparty data conforming to the EBA NPL Template specification';
COMMENT ON COLUMN counterparty.counterparty_identifier IS 'Unique internal identifier for the Counterparty. One or multiple Counterparties can be part of a Counterparty. Documentation';
COMMENT ON COLUMN counterparty.borrower_type IS 'The borrower type (individual or corporate';
COMMENT ON COLUMN counterparty.address_of_registered_location IS 'Address where the Corporate Counterparty is registered, including flat / house number. Documentation';
COMMENT ON COLUMN counterparty.annual_ebit IS 'Amount of annual EBIT held by the Corporate Counterparty as per the latest available financial statements. Documentation';
COMMENT ON COLUMN counterparty.annual_revenue IS 'Amount of annual revenue held by the Corporate Counterparty as per the latest available financial statements. Documentation';
COMMENT ON COLUMN counterparty.basis_of_financial_statements IS 'Financial reporting practice the Corporate Counterparty has adopted i.e. IFRS, National GAAP, Not Available. Documentation';
COMMENT ON COLUMN counterparty.business_description IS 'Description of the business operations of the Corporate Counterparty, providing more detail for field "Industry Segment". Documentation';
COMMENT ON COLUMN counterparty.cash_and_cash_equivalent_items IS 'Amount of cash and cash equivalent items held by the Corporate Counterparty as  per the latest available financial statements. Documentation';
COMMENT ON COLUMN counterparty.city_of_registered_location IS 'City where the Corporate Counterparty is registered. Documentation';
COMMENT ON COLUMN counterparty.comments_on_other_litigation_related_process IS 'Further comments / details if there is other litigation processes in place. Documentation';
COMMENT ON COLUMN counterparty.commencement_date_of_insolvency_or_restructuring_proceedings IS 'Date that the Counterparty commenced Insolvency / Restructuring Proceedings Documentation';
COMMENT ON COLUMN counterparty.contingent_obligations IS 'Indicator as to whether the Corporate Counterparty has contingent obligations which will be part of the sale, e.g. the Institution provided a guarantee to a real estate developer on their development.';
COMMENT ON COLUMN counterparty.counterparty_role IS 'Type of the Counterparty i.e. Guarantor, Borrower, Tenant. Documentation';
COMMENT ON COLUMN counterparty.country_of_registered_location IS 'Country where the Corporate Counterparty is registered. Documentation';
COMMENT ON COLUMN counterparty.correspondence_address_of_appointed_insolvency_practitioner IS 'https://www.openriskmanual.org/wiki/EBA_NPL.Counterparty.Correspondence_address_of_appointed_insolvency_practitioner. Documentation';
COMMENT ON COLUMN counterparty.insolvency_practitioner_reference IS 'Insolvency Practitioner Reference" href="https://www.openriskmanual.org/wiki/EBA_NPL.Counterparty.Insolvency_Practitioner_Reference">Documentation';
COMMENT ON COLUMN counterparty.proof_of_claim_filed_by_the_seller IS 'Proof of Claim Filed by the seller. Documentation';
COMMENT ON COLUMN counterparty.distribution_made_to_the_seller IS 'https://www.openriskmanual.org/wiki/EBA_NPL.Counterparty.Distribution_made_to_the_Seller. Documentation';
COMMENT ON COLUMN counterparty.notice_for_procedure_termination IS 'Indicator as to whether the notice of the end of the procedure has been given to the seller. Documentation';
COMMENT ON COLUMN counterparty.cross_collateralisation_for_counterparty IS 'Indicator as to whether all / some of the loans held by the Counterparty are secured by all / some of the collaterals held by the Counterparty. Documentation';
COMMENT ON COLUMN counterparty.cross_default_for_counterparty IS 'Indicator as to whether contractual breach of any loans held by the Counterparty would trigger the default event of any other loans. Documentation';
COMMENT ON COLUMN counterparty.currency_of_deposit IS 'Currency that the deposit held with the Institution is expressed in. Documentation';
COMMENT ON COLUMN counterparty.currency_of_financial_statements IS 'Currency that the latest available financial statements are expressed in. Documentation';
COMMENT ON COLUMN counterparty.current_assets IS 'Amount of current assets held by the Corporate Counterparty, excluding cash and cash equivalent items as per the latest available financial statements. Documentation';
COMMENT ON COLUMN counterparty.current_external_credit_rating IS 'External credit rating issued to the Corporate Counterparty at NPL Portfolio Cut-Off Date. Documentation';
COMMENT ON COLUMN counterparty.current_internal_credit_rating IS 'Internal credit rating issued to the Counterparty at the NPL Portfolio Cut-Off Date and please provide the internal methodology used to decide the rating as a part of the transaction documents. Docume';
COMMENT ON COLUMN counterparty.date_of_appointment IS 'Date that the insolvency practitioner was appointed. Documentation';
COMMENT ON COLUMN counterparty.date_of_external_demand_issuance IS 'Date that a demand notice was sent by solicitors who act on behalf of the Institution. Documentation';
COMMENT ON COLUMN counterparty.date_of_incorporation IS 'Date that the Corporate Counterparty was incorporated as a company, partnership or fund, and therefore became a separate legal entity from its owners, with its own rights and obligations. Documentatio';
COMMENT ON COLUMN counterparty.date_of_internal_demand_issuance IS 'Date that a demand notice was sent by the Institution itself. Documentation';
COMMENT ON COLUMN counterparty.date_of_last_contact IS 'Date of last direct contact with the Counterparty. Documentation';
COMMENT ON COLUMN counterparty.date_of_latest_annual_financial_statements IS 'Date of the latest available Financial Statements. Documentation';
COMMENT ON COLUMN counterparty.date_of_obtaining_order_for_possession IS 'Date that the Order for Possession is granted by the court. Documentation';
COMMENT ON COLUMN counterparty.date_when_reservation_of_rights_letter_was_issued IS 'Date that the Reservation of Rights Letter was issued by the Institution. Documentation';
COMMENT ON COLUMN counterparty.deposit_balance_with_institution IS 'Deposit amount the Counterparty holds with the Institution as defined by annex II, Part two of the ECB BSI Regulation. Documentation';
COMMENT ON COLUMN counterparty.description_of_contingent_obligations IS 'Description of contingent obligations when "Yes" is selected in field "Contingent Obligations". Documentation';
COMMENT ON COLUMN counterparty.description_of_cross_collateralisation IS 'Description of cross collateralisation when "Partial" is selected in field "Cross Collateralisation for Counterparty". Documentation';
COMMENT ON COLUMN counterparty.description_of_cross_default IS 'Description of cross default when "Partial" is selected in field "Cross Default for Counterparty". Documentation';
COMMENT ON COLUMN counterparty.description_of_related_party IS 'Further comments / details on the nature of the relation between the institution and the related party when "Yes" is selected in field "Related Party". Documentation';
COMMENT ON COLUMN counterparty.eligibility_for_deposit_to_offset IS 'Indicator as to whether the deposit held with the Institution can be used to pay down the loan. Documentation';
COMMENT ON COLUMN counterparty.enterprise_size IS 'Classification of enterprises by size for the Corporate Counterparty i.e. Microenterprise, Small enterprise, Medium enterprise and Large enterprise. Documentation';
COMMENT ON COLUMN counterparty.eviction_date IS 'Date that the Counterparty is evicted. Documentation';
COMMENT ON COLUMN counterparty.external_credit_rating_at_origination IS 'External credit rating issued to the Corporate Counterparty applicable at the point in time when the Counterparty became a customer and choose the lowest one if there are multiple ratings. In case sev';
COMMENT ON COLUMN counterparty.financial_statements_type IS 'Indicator as to whether the financial statements have been prepared at the Consolidated or at the Counterparty level. Documentation';
COMMENT ON COLUMN counterparty.financials_audited IS 'Indicator as to whether the financial statements have been audited or not by the Corporate Counterparty. Documentation';
COMMENT ON COLUMN counterparty.fixed_assets IS 'Amount of fixed assets held by the Corporate Counterparty as per the latest available financial statements. Documentation';
COMMENT ON COLUMN counterparty.geographic_region_classification IS 'NUTS3 classification used for the field "Geographic Region of Registered Location", i.e. NUTS3 2013 (1), NUTS3 2010 (2), NUTS3 2006 (3), NUTS3 2003 (4), Other (5). Documentation';
COMMENT ON COLUMN counterparty.geographic_region_of_registered_location IS 'Province or Region where the Corporate Counterparty is registered. Documentation';
COMMENT ON COLUMN counterparty.indicator_of_counterparty_cooperation IS 'Indicator as to whether the Corporate or Private Individual Counterparty is cooperative or not. Documentation';
COMMENT ON COLUMN counterparty.industry_segment IS 'Industry in which the Corporate Counterparty mainly operates. Documentation';
COMMENT ON COLUMN counterparty.insolvency_practitioner_appointed IS 'Indicator as to whether an insolvency practitioner has been appointed. Documentation';
COMMENT ON COLUMN counterparty.internal_credit_rating_at_origination IS 'Internal credit rating issued to the Counterparty applicable at the point in time when the Counterparty became a customer. Please provide the internal methodology used to decide the rating as a part o';
COMMENT ON COLUMN counterparty.jurisdiction_of_court IS 'Location of the court where the case is being heard. Documentation';
COMMENT ON COLUMN counterparty.legal_entity_identifier IS 'Global standard 20-character corporate identifier of the Corporate Counterparty. Documentation';
COMMENT ON COLUMN counterparty.legal_fees_accrued IS 'Total amount of legal fees accrued at the NPL Portfolio Cut-Off Date. Documentation';
COMMENT ON COLUMN counterparty.legal_procedure_type IS 'Type of the insolvency process the Counterparty is currently in. Choice fields are provided indicating per country the possible procedures. Documentation';
COMMENT ON COLUMN counterparty.description_of_legal_procedure_type IS 'Type of the insolvency process the Counterparty is currently in. Choice fields are provided indicating per country the possible procedures. Documentation';
COMMENT ON COLUMN counterparty.legal_type_of_counterparty IS 'Type of the Counterparty i.e. Private Individual, Listed Corporate, Unlisted Corporate and Partnership. Documentation';
COMMENT ON COLUMN counterparty.market_capitalisation IS 'Market capitalisation of a listed Corporate Counterparty. Documentation';
COMMENT ON COLUMN counterparty.name_of_counterparty IS 'Name used to refer to the Counterparty. Documentation';
COMMENT ON COLUMN counterparty.name_of_insolvency_practitioner IS 'Name of the insolvency practitioner. Documentation';
COMMENT ON COLUMN counterparty.name_of_insolvency_or_restructuring_proceedings IS 'Name of the insolvency or restructuring proceedings. Documentation';
COMMENT ON COLUMN counterparty.additional_name_of_insolvency_or_restructuring_proceedings IS 'Name of the insolvency or restructuring proceedings. Documentation';
COMMENT ON COLUMN counterparty.net_assets IS 'Amount of net assets held by the Corporate Counterparty as per the latest available financial statements. Documentation';
COMMENT ON COLUMN counterparty.number_of_fte IS 'Number of full-time employees (or equivalent) working for the Corporate Counterparty as at the last financial reporting date. Documentation';
COMMENT ON COLUMN counterparty.number_of_joint_counterparties IS 'Number of joint Counterparties who jointly own parts of the Loan.. Documentation';
COMMENT ON COLUMN counterparty.occupation_type IS 'Main occupation of the Private Individual Counterparty, where (a), (b), (c) or (d) is selected in the field Employment Status. Documentation';
COMMENT ON COLUMN counterparty.occupation_description IS 'Description of the occupation of the Private Individual Counterparty, providing more detail for field Occupation Type. Documentation';
COMMENT ON COLUMN counterparty.other_products_with_institution IS 'Other products that the Counterparty holds with the Institution that are not included in the NPL Portfolio. Documentation';
COMMENT ON COLUMN counterparty.postcode_of_registered_location IS 'Postcode where the Corporate Counterparty is registered. Documentation';
COMMENT ON COLUMN counterparty.registration_number IS 'Company registration number of the Corporate Counterparty according to the country specific registration office. Documentation';
COMMENT ON COLUMN counterparty.related_party IS 'Indicator as to whether the Counterparty is a related party to the Institution, e.g. Counterparty is an employee of the Institution. Documentation';
COMMENT ON COLUMN counterparty.sheriff_or_bailiff_acquisition_date IS 'Date that sheriff / bailiff is acquired by the court. Documentation';
COMMENT ON COLUMN counterparty.source_of_current_external_credit_rating IS 'Agency which provided the external credit rating at cut-off date. Documentation';
COMMENT ON COLUMN counterparty.source_of_external_credit_rating_at_origination IS 'From which agency the external credit rating at the point in time when the Counterparty became a customer. Documentation';
COMMENT ON COLUMN counterparty.stage_reached_in_insolvency_or_restructuring_procedure IS 'Stage Reached in Insolvency/Restructuring procedure  Documentation';
COMMENT ON COLUMN counterparty.additional_stage_reached_in_insolvency_procedure IS 'Additional indication of how advanced the relevant procedure has become as a result of various legal steps in the legal procedure having been completeted. Documentation';
COMMENT ON COLUMN counterparty.total_assets IS 'Amount of total assets held by the Corporate Counterparty as per the latest available financial statements. Documentation';
COMMENT ON COLUMN counterparty.total_debt IS 'Amount of total debt held by the Corporate Counterparty as per the latest available financial statements. Documentation';
COMMENT ON COLUMN counterparty.total_liabilities IS 'Amount of total liabilities held by the Corporate Counterparty on the balance sheet as defined by the applicable accounting standard as per the latest available financial statements. Documentation';
COMMENT ON TABLE loan IS 'The Loan model holds Loan Portfolio data conforming to the EBA NPL Template specification';
COMMENT ON COLUMN loan.instrument_identifier IS 'Institution internal identifier for the Loan part. Documentation';
COMMENT ON COLUMN loan.accounting_stages_of_asset_quality IS 'Accounting stages of asset quality, i.e. IFRS Stage 1, IFRS Stage 2, IFRS Stage 3 (impaired), Fair Value Through P&L, Other Accounting Standard - impaired asset, Other Accounting Standard - Not impair';
COMMENT ON COLUMN loan.accrued_interest_balance_off_book IS 'Amount of interest that has been accrued but not capitalised to the Loan,  as not recognised on the balance sheet. Documentation';
COMMENT ON COLUMN loan.accrued_interest_balance_on_book IS 'Current amount of outstanding interest as recognised on the balance sheet at the NPL Portfolio Cut-Off Date. Documentation';
COMMENT ON COLUMN loan.amortisation_type IS 'Description of the Amortisation type of the loan as per the latest Loan Agreement e.g. Full amortisation, part amortisation, final bullet, bespoke repayment. Documentation';
COMMENT ON COLUMN loan.asset_class IS 'Asset class of the Loan, i.e. Resi, CRE, SME/Corp, etc.. Documentation';
COMMENT ON COLUMN loan.balance_at_default IS 'Balance of the Loan when the Loan has defaulted (CRR Art.178). Documentation';
COMMENT ON COLUMN loan.capitalised_pastdue_amount IS 'Total capitalised past-due balance as recognised on balance sheet at NPL Portfolio Cut-Off Date i.e. Interest and Legal Fees. Documentation';
COMMENT ON COLUMN loan.channel_of_origination IS 'Channel through which the Loan was originated, i.e. Branch, Internet and Broker. Documentation';
COMMENT ON COLUMN loan.chargeoff_date IS 'Date when the Loan went into charge-off. A charge-off is the declaration by the Institution commonly on Unsecured Retail when the Borrower is severely delinquent, and the Institution starts the recove';
COMMENT ON COLUMN loan.code_of_conduct IS 'Indicator as to whether the Loan is subject to certain Code of Conduct. Documentation';
COMMENT ON COLUMN loan.comments_on_code_of_conduct IS 'Further comments / details on Code of Conduct. Documentation';
COMMENT ON COLUMN loan.comments_on_covenant_waiver IS 'Further comments / details on the covenant waiver if "Yes" is selected in field "Covenant Waiver". Documentation';
COMMENT ON COLUMN loan.country_of_origination IS 'Country where the Loan was originated. Documentation';
COMMENT ON COLUMN loan.covenant_waiver IS 'Indicator as to whether there has been a covenant waiver sent out for any breaches of the Loan Agreement. Documentation';
COMMENT ON COLUMN loan.current_covenant_levels IS 'Current levels of covenants as at NPL Portfolio Cut-Off date. Documentation';
COMMENT ON COLUMN loan.current_external_credit_rating IS 'External credit rating issued for the Loan at NPL Portfolio Cut-Off Date. In case several ratings are assigned, the approach described in Art. 138 of the CRR applies.. Documentation';
COMMENT ON COLUMN loan.current_interest_base_rate IS 'Current base rate of the Loan as at NPL Portfolio Cut-Off Date when "Variable" is selected in field "Current Interest Rate Type". Documentation';
COMMENT ON COLUMN loan.current_interest_margin IS 'is the current margin above the base rate as stated in the Loan Agreement and applicable at the NPL Portfolio Cut-Off Date. Documentation';
COMMENT ON COLUMN loan.current_interest_rate IS 'is the current total interest rate of the loan as stated in the Loan Agreement on and applicable at the NPL Portfolio Cut-Off Date.. Documentation';
COMMENT ON COLUMN loan.current_interest_rate_reference IS 'Current interest rate base or reference of the loan as stated in the Loan Agreement and applicable at the NPL Portfolio Cut-Off Date when Variable is selected in field Current Interest Rate Type. Docu';
COMMENT ON COLUMN loan.current_interest_rate_type IS 'is the current interest rate type as per Loan Agreement and applicable at the NPL Portfolio Cut-Off Date, i.e. Fixed / Variable / Mixed. Documentation';
COMMENT ON COLUMN loan.current_internal_credit_rating IS 'Internal credit rating issued to the Loan at NPL Portfolio Cut-Off Date and please provide the internal methodology used to decide the rating as a part of the transaction documents. Documentation';
COMMENT ON COLUMN loan.current_maturity_date IS 'Contractual maturity date of the Loan as at NPL Portfolio Cut-Off Date. Documentation';
COMMENT ON COLUMN loan.current_reversion_interest_rate IS 'Current level of reversion interest rate according to the Loan Agreement and applicable as at NPL Portfolio Cut-Off Date, reversion means that after the interest fixed period the Institution would rev';
COMMENT ON COLUMN loan.date_of_default IS 'Date that the Loan defaulted. Documentation';
COMMENT ON COLUMN loan.date_of_origination IS 'Date that the Loan originated as per the Loan Agreement. Documentation';
COMMENT ON COLUMN loan.days_in_pastdue IS 'Number of days that the Loan is currently past-due as at the NPL Portfolio Cut-Off Date. Documentation';
COMMENT ON COLUMN loan.default_penalty_interest_margin IS 'Additional margin charged on the balance of the Loan in default according to the Loan Agreement and applicable as of the NPL Portfolio Cut-Off Date. Documentation';
COMMENT ON COLUMN loan.description_of_bespoke_repayment IS 'Description of the bespoke repayment profile when "Bespoke Repayment" is selected in field "Amortisation Type". Documentation';
COMMENT ON COLUMN loan.description_of_current_interest_rate_type IS 'Description of current interest rate type when "Mixed" is selected in field "Current Interest Rate Type". Documentation';
COMMENT ON COLUMN loan.description_of_original_interest_rate_type IS 'Description of original interest rate type when "Mixed" is selected in field "Original Interest Rate Type". Documentation';
COMMENT ON COLUMN loan.description_of_relevant_schemes IS 'Description of the relevant scheme if YES is selected in the field Relevant Schemes. Documentation';
COMMENT ON COLUMN loan.details_of_origination_channel IS 'Description of the origination channel when "Broker" or "Other" is selected in field "Channel of Origination". Documentation';
COMMENT ON COLUMN loan.early_redemption_penalty IS 'Additional charge on the early redemption made by the Counterparty according to the Loan Agreement and applicable as of the NPL Portfolio Cut-Off Date. Documentation';
COMMENT ON COLUMN loan.end_date_of_current_fixed_interest_period IS 'Date that the current fixed interest period ends according to the Loan Agreement and applicable as at the NPL Portfolio Cut-Off Date. Documentation';
COMMENT ON COLUMN loan.end_date_of_interest_grace_period IS 'Date that the interest payment ends postponement according to the Loan Agreement and applicable as of the NPL Portfolio Cut-Off Date. Documentation';
COMMENT ON COLUMN loan.end_date_of_interest_only_period IS 'Date that the interest repayment only period ends according to the current Loan Agreement and applicable as at the NPL Portfolio Cut-Off Date. Documentation';
COMMENT ON COLUMN loan.end_date_of_principal_grace_period IS 'Date that the principal payment ends postponement according to the Loan Agreement and applicable as of the NPL Portfolio Cut-Off Date. Documentation';
COMMENT ON COLUMN loan.end_date_of_subsidy IS 'Date that the current subsidy ends. Documentation';
COMMENT ON COLUMN loan.external_credit_rating_at_origination IS 'External credit rating issued to the Loan applicable at the point of time when the counterparty became a customer. In case several ratings are assigned, the approach described in Art. 138 of the CRR a';
COMMENT ON COLUMN loan.final_bullet_repayment IS 'Total amount of principal repayment to be paid at the maturity date of the loan. Documentation';
COMMENT ON COLUMN loan.governing_law_of_loan_agreement IS 'Governing law is the law of the country in which the Loan Agreement was entered into. This does not necessarily correspond to the country where the loan was originated. Documentation';
COMMENT ON COLUMN loan.interest_cap_rate IS 'Maximum interest rate which can be charged on the Loan as specified in the current Loan Agreement (if applicable). Documentation';
COMMENT ON COLUMN loan.interest_floor_rate IS 'Minimum interest rate of a loan which can be charged on the Loan as specified in the current Loan Agreement (if applicable). Documentation';
COMMENT ON COLUMN loan.interest_payment_frequency IS 'Frequency of interest payments based on the current Loan Agreement as at the NPL Portfolio Cut-Off Date. Documentation';
COMMENT ON COLUMN loan.interest_reset_interval IS 'Number of months between two interest reset dates according to the Loan Agreement and applicable as of the NPL Portfolio Cut-Off Date. Documentation';
COMMENT ON COLUMN loan.internal_credit_rating_at_origination IS 'Internal credit rating issued to the Loan applicable at the point of time when the counterparty became a customer and please provide the internal methodology used to decide the rating as a part of the';
COMMENT ON COLUMN loan.last_covenant_test_date IS 'Date that the covenant levels were tested last time by the institution. Documentation';
COMMENT ON COLUMN loan.last_interest_reset_date IS 'Date that the last interest reset event happened. Documentation';
COMMENT ON COLUMN loan.last_payment_amount IS 'Amount of last payment. Documentation';
COMMENT ON COLUMN loan.last_payment_date IS 'Date that the last payment was made. Documentation';
COMMENT ON COLUMN loan.legal_balance IS 'Total claim amount, i.e. Total Balance + Accrued Interest Balance (Off book). Documentation';
COMMENT ON COLUMN loan.legal_balance_at_chargeoff_date IS 'Total claim amount when the Loan went into charge-off. A charge-off is the declaration by the Institution commonly on Unsecured Retail when the Borrower is severely delinquent, and the Institution sta';
COMMENT ON COLUMN loan.loan_commitment IS 'Total available credit extended as at the NPL Portfolio Cut-Off Date. Documentation';
COMMENT ON COLUMN loan.loan_covenants IS 'List of the covenants as agreed in the current Loan Agreement as at the NPL Portfolio Cut-Off Date (LTV, ICR, DSCR etc.), each in a separate column. Documentation';
COMMENT ON COLUMN loan.loan_currency IS 'Currency which the Loan is expressed in as per latest Loan Agreement. Documentation';
COMMENT ON COLUMN loan.loan_purpose IS 'ultimate financing purpose of the Loan, e.g. Residential real estate purchase for own use, Residential real estate purchase for investment, Commercial real estate purchase, Margin lending, Debt financ';
COMMENT ON COLUMN loan.loan_status IS 'Loan status, e.g. performing and non-performing. Documentation';
COMMENT ON COLUMN loan.marp_applicable IS 'Indicator as to whether the Institution operates a Mortgage Arrears Resolution Process when dealing with Corporates or Private Individual Counterparties in Mortgage Arrears. Documentation';
COMMENT ON COLUMN loan.marp_entry IS 'Date loan entered current MARP status. Documentation';
COMMENT ON COLUMN loan.marp_status IS 'The status of the current Mortgage Arrears Resolution Process; Not in MARP, Exited MARP, Provision 23,24,28,29,42,45,47,Self Cure, Alternative Repayment Arrangement (ARA). Documentation';
COMMENT ON COLUMN loan.next_interest_reset_date IS 'Date that the next interest reset event happened. Documentation';
COMMENT ON COLUMN loan.next_interest_scheduled_repayment_amount IS 'Amount of next scheduled interest repayment as at the NPL Portfolio Cut-Off Date. Documentation';
COMMENT ON COLUMN loan.next_interest_scheduled_repayment_date IS 'Date that the next interest repayment is made as at the NPL Portfolio Cut-Off Date. Documentation';
COMMENT ON COLUMN loan.next_principal_scheduled_repayment_amount IS 'Amount of next scheduled principal repayment as at the NPL Portfolio Cut-Off Date. Documentation';
COMMENT ON COLUMN loan.next_principal_scheduled_repayment_date IS 'Date that the next principal repayment is made as at the NPL Portfolio Cut-Off Date. Documentation';
COMMENT ON COLUMN loan.nonperforming_reason IS 'Main reason why the non-performing status was provided, i.e. impaired (according to the applicable accounting standard), defaulted (CRR Art. 178), more than 90 ,DPD, unlikely to pay. Documentation';
COMMENT ON COLUMN loan.number_of_pastdue_events IS 'Number of times that the Loan was previously categorised as past-due. Documentation';
COMMENT ON COLUMN loan.original_interest_base_rate IS 'Original base rate of the Loan when "Variable" is selected in field "Original Interest Rate Type". Documentation';
COMMENT ON COLUMN loan.original_interest_margin IS 'Original margin above the base rate at loan origination. Documentation';
COMMENT ON COLUMN loan.original_interest_rate IS 'Original total interest rate of the Loan as states in the Loan Agreement and as applicable as of Loan Origination. Documentation';
COMMENT ON COLUMN loan.original_interest_rate_reference IS 'Original interest rate base / reference of the Loan when "Variable" is selected in field "Original Interest Rate Type". Documentation';
COMMENT ON COLUMN loan.original_interest_rate_type IS 'Original interest rate type as states in the Loan Agreement and as applicable as of Loan origination i.e. Fixed / Variable / Mixed. Documentation';
COMMENT ON COLUMN loan.original_maturity_date IS 'Original contractual maturity date of the Loan. Documentation';
COMMENT ON COLUMN loan.origination_amount IS 'Loan amount advanced to the Borrower / drawn down by the Borrower at the origination date on the loan. Documentation';
COMMENT ON COLUMN loan.other_balances IS 'Current amount of other outstanding amounts, e.g. other charges, commissions, fees etc., as recognised on the balance sheet. Documentation';
COMMENT ON COLUMN loan.other_pastdue_amounts IS 'Accumulated amount of other past-due amounts, e.g. fees, as recognised on balance sheet at NPL Portfolio Cut-Off Date. Documentation';
COMMENT ON COLUMN loan.other_syndicate_counterparties IS 'Who the other syndicate Counterparties are when "Yes" is selected in field "Syndicated Loan". Documentation';
COMMENT ON COLUMN loan.pastdue_interest_amount IS 'Accumulated amount of past-due interest as recognised on balance sheet as at NPL Portfolio Cut-Off Date. Documentation';
COMMENT ON COLUMN loan.pastdue_penalty_interest_margin IS 'Additional margin charged on the past-due portion of the Loan according to the Loan Agreement and applicable as of the NPL Portfolio Cut-Off Date. Documentation';
COMMENT ON COLUMN loan.pastdue_principal_amount IS 'Accumulated amount of past-due principal as recognised on balance sheet at NPL Portfolio Cut-Off Date. Documentation';
COMMENT ON COLUMN loan.principal_balance IS 'Current amount of outstanding principal as recognised on the balance sheet at Cut-Off Date. Documentation';
COMMENT ON COLUMN loan.principal_payment_frequency IS 'Frequency that the principal payment is currently made based on the current Loan Agreement as at the NPL Portfolio Cut-Off Date. Documentation';
COMMENT ON COLUMN loan.product_type IS 'Product type of the Loan, e.g. Loan and Overdraft. Documentation';
COMMENT ON COLUMN loan.relevant_schemes IS 'Indicator as to whether the Loan is involved with any relevant schemes, e.g. Right to Buy Scheme in UK. Documentation';
COMMENT ON COLUMN loan.recourse_to_other_assets IS 'Indicator as to whether the Institution has the legal right to access other assets of the Borrower. Documentation';
COMMENT ON COLUMN loan.securitised IS 'Indicator as to whether the Loan has been securitised or within covered bond pool. Documentation';
COMMENT ON COLUMN loan.source_of_current_external_credit_rating IS 'From which agency the external credit rating at NPL Portfolio Cut-Off Date was obtained. Documentation';
COMMENT ON COLUMN loan.source_of_external_credit_rating_at_origination IS 'From which agency the external credit rating at origination was obtained. In case several ratings are assigned, the approach described in Art. 138 of the CRR applies.. Documentation';
COMMENT ON COLUMN loan.specialised_product IS 'Indicator as to whether the Loan is a specialised product, e.g. Fractioned Loans in Italy. Documentation';
COMMENT ON COLUMN loan.start_date_of_current_fixed_interest_period IS 'Date that the current fixed interest period started according to the Loan Agreement and applicable as at the NPL Portfolio Cut-Off Date. Documentation';
COMMENT ON COLUMN loan.start_date_of_interest_grace_period IS 'Date that the interest payment starts being postponed according to the Loan Agreement and applicable as of the NPL Portfolio Cut-Off Date. Documentation';
COMMENT ON COLUMN loan.start_date_of_interest_only_period IS 'Date that the interest repayment only period starts according to the most recent Loan Agreement and applicable as  the NPL Portfolio Cut-Off Date. Documentation';
COMMENT ON COLUMN loan.start_date_of_principal_grace_period IS 'Date that the principal payment starts being postponed according to the Loan Agreement and applicable as of the NPL Portfolio Cut-Off Date. Documentation';
COMMENT ON COLUMN loan.start_date_of_subsidy IS 'Date that the current subsidy starts. Documentation';
COMMENT ON COLUMN loan.subsidy IS 'Indicator where contractual payments are subsidised by an external party. Documentation';
COMMENT ON COLUMN loan.subsidy_amount IS 'Amount of the subsidy received. Documentation';
COMMENT ON COLUMN loan.subsidy_provider IS 'Name of the external party who provided the subsidy. Documentation';
COMMENT ON COLUMN loan.syndicated_loan IS 'Indicator as to whether the Loan is provided by a syndicate or consortium of two or more institutions. This means that in the case of a syndicated loan the Institution holds less than 100% of the tota';
COMMENT ON COLUMN loan.syndicated_portion IS 'Percentage of the portion held by the Institution when "Yes" is selected in field "Syndicated Loan". Documentation';
COMMENT ON COLUMN loan.time_in_pastdue IS 'Total number of months that the Loan has been in past-due in the past 12 months. Documentation';
COMMENT ON COLUMN loan.total_balance IS 'Total unpaid balance, i.e. Principal Balance + Accrued Interest Balance (On book) + Other Balances. Documentation';
COMMENT ON COLUMN loan.total_pastdue_amount IS 'Total past-due amount, i.e. Past-Due Principal Amount + Past-Due Interest Amount + Other Past-Due Amount. Documentation';
COMMENT ON COLUMN loan.trigger_levels_of_loan_covenants IS 'Corresponding trigger levels as agreed in the Loan Agreement, as at the NPL Portfolio Cut-Off Date, each in a separate column. Documentation';
COMMENT ON COLUMN loan.type_of_reversion_interest_rate IS 'Type of reversion interest rate after the fixed interest period according to the Loan Agreement and applicable as of the NPL Portfolio Cur-Off Date, reversion means that after the interest fixed perio';
COMMENT ON TABLE nonpropertycollateral IS 'The NonPropertyCollateral model holds Non-Property Collateral data conforming to the EBA NPL Template specification';
COMMENT ON COLUMN nonpropertycollateral.protection_identifier IS 'Institution internal identifier for the Non-Property Collateral. Documentation';
COMMENT ON COLUMN nonpropertycollateral.activation_of_guarantee IS 'Indicator as to whether the guarantee has been activated when "Guarantee" is selected in field "Collateral Type". Documentation';
COMMENT ON COLUMN nonpropertycollateral.collateral_insurance IS 'Indicator as to whether there is an insurance on the Collateral. Documentation';
COMMENT ON COLUMN nonpropertycollateral.collateral_insurance_coverage_amount IS 'Amount that the collateral insurance covers. Documentation';
COMMENT ON COLUMN nonpropertycollateral.collateral_insurance_provider IS 'Name of the collateral insurance provider. Documentation';
COMMENT ON COLUMN nonpropertycollateral.collateral_type IS 'Physical type of the Collateral, e.g. Guarantee and Machinery. Documentation';
COMMENT ON COLUMN nonpropertycollateral.estimated_useful_life IS 'Estimated remaining useful life as at cut-off date. Documentation';
COMMENT ON COLUMN nonpropertycollateral.configuration IS 'Specification and option list of the Collateral. Documentation';
COMMENT ON COLUMN nonpropertycollateral.original_country_of_registration IS 'Country that the Collateral was originally registered in. Documentation';
COMMENT ON COLUMN nonpropertycollateral.current_country_of_registration IS 'Country that the Collateral is currently registered in as at cut-off date. Documentation';
COMMENT ON COLUMN nonpropertycollateral.currency_of_collateral IS 'Currency that the valuation and cash flows related to the Collateral are expressed in. Documentation';
COMMENT ON COLUMN nonpropertycollateral.current_opex_and_overheads IS 'Current annual operational expenses and overheads of running the Collateral as at cut-off date. Documentation';
COMMENT ON COLUMN nonpropertycollateral.date_of_initial_valuation IS 'Date at which the initial valuation was assessed. Documentation';
COMMENT ON COLUMN nonpropertycollateral.date_of_latest_valuation IS 'Date that the latest valuation took place. Documentation';
COMMENT ON COLUMN nonpropertycollateral.description IS 'Detailed description of the collateral. Documentation';
COMMENT ON COLUMN nonpropertycollateral.enforcement_description IS 'Comments/Description of the stage of Enforcement that the Property Collateral is in as at cut-off date. Documentation';
COMMENT ON COLUMN nonpropertycollateral.enforcement_status IS 'Status of the enforcement process that the Collateral is currently in as at cut-off date, e.g. if it is in receivership. Documentation';
COMMENT ON COLUMN nonpropertycollateral.enforcement_status_third_parties IS 'Indicator as to whether any other secured creditors have taken steps to enforce security over the asset? (Y/N). Documentation';
COMMENT ON COLUMN nonpropertycollateral.engine_size IS 'Engine size (litres) of the Collateral. Documentation';
COMMENT ON COLUMN nonpropertycollateral.guarantee_amount IS 'Claim amount of the guarantee when "Guarantee" is selected in field "Collateral Type". Documentation';
COMMENT ON COLUMN nonpropertycollateral.initial_valuation_amount IS 'Value of the Collateral assessed at loan origination. Documentation';
COMMENT ON COLUMN nonpropertycollateral.initial_residual_value IS 'Estimated residual value of the Collateral at loan origination, residual value refers to how much the Collateral will be worth at end of the loan term . Documentation';
COMMENT ON COLUMN nonpropertycollateral.date_of_the_latest_residual_valuation IS 'Date that the latest residual value of the Collateral was assessed, residual value refers to how much the Collateral will be worth at end of the loan term. Documentation';
COMMENT ON COLUMN nonpropertycollateral.initial_residual_valuation_date IS 'Date at which the initial residual value of the Collateral was assessed, residual value refers to how much the Collateral will be worth at end of the loan term. Documentation';
COMMENT ON COLUMN nonpropertycollateral.latest_residual_value IS 'Estimated residual value of the Collateral when last assessed, residual value refers to how much the Collateral will be worth at end of the loan term. Documentation';
COMMENT ON COLUMN nonpropertycollateral.latest_valuation_amount IS 'Value of the Collateral when last assessed. Documentation';
COMMENT ON COLUMN nonpropertycollateral.legal_owner IS 'Legal owner of the Collateral. Documentation';
COMMENT ON COLUMN nonpropertycollateral.manufacturer_of_collateral IS 'Name used to refer to the manufacturer of the Collateral. Documentation';
COMMENT ON COLUMN nonpropertycollateral.name_or_model_of_collateral IS 'Name / model of the Collateral. Documentation';
COMMENT ON COLUMN nonpropertycollateral.new_or_used IS 'Condition of the Collateral at loan origination. Documentation';
COMMENT ON COLUMN nonpropertycollateral.registration_number IS 'Registration number of the Collateral. Documentation';
COMMENT ON COLUMN nonpropertycollateral.type_of_initial_valuation IS 'Type of the initial valuation. Documentation';
COMMENT ON COLUMN nonpropertycollateral.type_of_latest_valuation IS 'Type of the latest valuation for the Collateral, i.e. Full Appraisal, Drive-by, Automated Valuation Model, Indexed, Desktop, Managing / Estate Agent, Purchase Price, Hair Cut, Mark to market and Borro';
COMMENT ON COLUMN nonpropertycollateral.type_of_legal_owner IS 'Type of the legal owner, i.e. Private Individual, Listed Corporate, Unlisted Corporate and Partnership. Documentation';
COMMENT ON COLUMN nonpropertycollateral.asset_purchase_obligation IS 'Indicator as to whether there is an obligation for the Borrower to purchase the Collateral at the end of the lease. Documentation';
COMMENT ON COLUMN nonpropertycollateral.option_to_buy_price IS 'Amount the Borrower will pay at the end of the lease in order to take ownership of the Collateral. Documentation';
COMMENT ON COLUMN nonpropertycollateral.year_of_manufacture IS 'Year that the Collateral was manufactured / first sold. Documentation';
COMMENT ON COLUMN nonpropertycollateral.year_of_registration IS 'Year that the Collateral was registered. Documentation';
COMMENT ON TABLE propertycollateral IS 'The PropertyCollateral model object holds Property Collateral data conforming to the EBA NPL Template specification';
COMMENT ON COLUMN propertycollateral.protection_identifier IS 'Institutions internal identifier for the Property Collateral.Documentation';
COMMENT ON COLUMN propertycollateral.address_of_property IS 'Street address where the Property is located at, including flat / house number or name. Documentation';
COMMENT ON COLUMN propertycollateral.amount_of_vat_payable IS 'Amount of VAT payable on the disposal of the Unit. Documentation';
COMMENT ON COLUMN propertycollateral.area_type_of_property IS 'Area type where the Property is located at , i.e. City centre, Suburban and Rural. Documentation';
COMMENT ON COLUMN propertycollateral.building_area_m2 IS 'Building area (square metres) of the Unit. Documentation';
COMMENT ON COLUMN propertycollateral.building_area_m2_lettable IS 'Building area (square metres) of the Unit that is lettable. Documentation';
COMMENT ON COLUMN propertycollateral.building_area_m2_occupied IS 'Building area (square metres) of the Unit that has been occupied by landlord / tenant. Documentation';
COMMENT ON COLUMN propertycollateral.city_of_property IS 'City where the Property is located at. Documentation';
COMMENT ON COLUMN propertycollateral.completion_of_property IS 'Indicator as to whether the construction of the Unit is complete. Documentation';
COMMENT ON COLUMN propertycollateral.condition_of_property IS 'Quality classification of the property, e.g. Excellent, Good, Fair, Poor. and include explanation of the category, and please provide the internal methodology used to decide the categories as a part o';
COMMENT ON COLUMN propertycollateral.currency_of_property IS 'Currency that the valuation and cash flows related to the Unit are expressed in. Documentation';
COMMENT ON COLUMN propertycollateral.current_annual_passing_rent IS 'Current annual passing rent charged to the Tenants of the Unit as at latest valuation date. Documentation';
COMMENT ON COLUMN propertycollateral.current_net_operating_income IS 'Current annual net operating income generated by the Unit as at the latest valuation date. Documentation';
COMMENT ON COLUMN propertycollateral.current_opex_and_overheads IS 'Current annual operational expenses and overheads of the Unit as at latest valuation date. Documentation';
COMMENT ON COLUMN propertycollateral.date_of_initial_valuation IS 'Date that the initial valuation was assessed. Documentation';
COMMENT ON COLUMN propertycollateral.date_of_latest_valuation IS 'Date that the latest valuation took place. Documentation';
COMMENT ON COLUMN propertycollateral.enforcement_description IS 'Comments/Description of the stage of Enforcement that the Property Collateral is in as at cut-off date. Documentation';
COMMENT ON COLUMN propertycollateral.enforcement_status IS 'Indicator as to whether the property collateral has entered into the enforcement process as at cut-off date. Documentation';
COMMENT ON COLUMN propertycollateral.enforcement_status_third_parties IS 'Indicator as to whether any other secured creditors have taken steps to enforce security over the asset? (Y/N). Documentation';
COMMENT ON COLUMN propertycollateral.estimated_annual_void_cost IS 'Additional costs to "Current Opex And Overheads" when the Units are vacant. Documentation';
COMMENT ON COLUMN propertycollateral.estimated_rental_void IS 'Estimated number of months the property is expected to be void. Documentation';
COMMENT ON COLUMN propertycollateral.geographic_region_classification IS 'NUTS3 classification used for the field "Geographic Region of Property", i.e. NUTS3 2013 (1), NUTS3 2010 (2), NUTS3 2006 (3), NUTS3 2003 (4), Other (5). Documentation';
COMMENT ON COLUMN propertycollateral.geographic_region_of_property IS 'Province / Region where the Property is located at. Documentation';
COMMENT ON COLUMN propertycollateral.initial_estimated_rental_value IS 'Estimated annual gross rental value of the Unit assessed at loan origination. Documentation';
COMMENT ON COLUMN propertycollateral.initial_valuation_amount IS 'Value of the Unit assessed at loan origination. Documentation';
COMMENT ON COLUMN propertycollateral.internal_or_external_initial_valuation IS 'Indicator as to whether the initial valuation was outsource, or done internally. Documentation';
COMMENT ON COLUMN propertycollateral.internal_or_external_latest_valuation IS 'Indicator as to whether the latest valuation was performed internally or by an external appraiser. Documentation';
COMMENT ON COLUMN propertycollateral.land_area_m2 IS 'Land area (square metres) of the Property. Documentation';
COMMENT ON COLUMN propertycollateral.latest_estimated_rental_value IS 'Estimated annual gross rental value of the Unit when last assessed. Documentation';
COMMENT ON COLUMN propertycollateral.latest_valuation_amount IS 'Value of the Unit when last assessed. Documentation';
COMMENT ON COLUMN propertycollateral.legal_owner_of_the_property IS 'Legal owner of the Property Collateral. Documentation';
COMMENT ON COLUMN propertycollateral.number_of_bedrooms IS 'Number of bedrooms that the Unit has. Documentation';
COMMENT ON COLUMN propertycollateral.number_of_car_parking_spaces IS 'Number of car parking spaces relating to the Unit. Documentation';
COMMENT ON COLUMN propertycollateral.number_of_lettable_units IS 'Number of lettable units that the Property has. Documentation';
COMMENT ON COLUMN propertycollateral.number_of_rooms IS 'Number of rooms that the Unit has excluding kitchen and bathroom(s). Documentation';
COMMENT ON COLUMN propertycollateral.number_of_units_occupied IS 'Number of occupied lettable units that the Property has. Documentation';
COMMENT ON COLUMN propertycollateral.number_of_units_vacant IS 'Number of vacant lettable units that the Property has. Documentation';
COMMENT ON COLUMN propertycollateral.party_liable_for_vat IS 'Party who is liable to pay the VAT on the disposal of the Unit i.e. the Institution or the buyer(s). Documentation';
COMMENT ON COLUMN propertycollateral.percentage_complete IS 'The percentage of development completed since construction started (applicable to Units in development). Documentation';
COMMENT ON COLUMN propertycollateral.planned_capex_next_12m IS 'Current planned CAPEX for the next 12 months. Documentation';
COMMENT ON COLUMN propertycollateral.property_country IS 'Country of residence where the Property is located at. Documentation';
COMMENT ON COLUMN propertycollateral.property_postcode IS 'Postcode where the Property is located at. Documentation';
COMMENT ON COLUMN propertycollateral.provider_of_energy_performance_certificate IS 'Name of the provider of the energy performance certificate. Documentation';
COMMENT ON COLUMN propertycollateral.provider_of_initial_valuation IS 'Name of the external appraiser or managing / estate agent is when "Full Appraisal" or "Managing / Estate Agent" is selected in field "Type of Initial Valuation". If the valuation was done internally, ';
COMMENT ON COLUMN propertycollateral.provider_of_latest_valuation IS 'Name of the external appraiser or managing / estate agent when "Full Appraisal" or "Managing / Estate Agent" is selected in field "Type of Latest Valuation". If the valuation was done internally, plea';
COMMENT ON COLUMN propertycollateral.purpose_of_property IS 'Purpose of the Property, e.g. Investment property, owner occupied, Business Use, etc.. Documentation';
COMMENT ON COLUMN propertycollateral.register_of_deeds_number IS 'Registration number of the Property. Documentation';
COMMENT ON COLUMN propertycollateral.remaining_term_of_leasehold IS 'Remaining term of the leasehold when "Leasehold" is selected in field "Tenure". Documentation';
COMMENT ON COLUMN propertycollateral.sector_of_property IS 'Sector which the property is used for, e.g. commercial real estate, residential real estate, etc.. Documentation';
COMMENT ON COLUMN propertycollateral.tenure IS 'Conditions that the Property is held or occupied, e.g. freehold and leasehold. Documentation';
COMMENT ON COLUMN propertycollateral.type_of_initial_valuation IS 'Type of the initial valuation for the Unit i.e. Full Appraisal, Drive-by, Automated Valuation Model, Indexed, Desktop, Managing / Estate Agent, Purchase Price, Hair Cut, Mark to market and Borrowers V';
COMMENT ON COLUMN propertycollateral.type_of_latest_valuation IS 'Type of the latest valuation for the Unit i.e. Full Appraisal, Drive-by, Automated Valuation Model, Indexed, Desktop, Managing / Estate Agent, Purchase Price, Hair Cut, Mark to market and Internal Ins';
COMMENT ON COLUMN propertycollateral.type_of_occupancy IS 'Type of occupancy, i.e. owner occupied, tenanted, not tenanted. Documentation';
COMMENT ON COLUMN propertycollateral.type_of_property IS 'Type of the Property, e.g. Apartment, Semi Detached House, Terraced House, Land, etc.. Documentation';
COMMENT ON COLUMN propertycollateral.value_of_energy_performance_certificate IS 'Value stated on Energy Performance Certificate, i.e. A,B,C,D,E,F and G. Documentation';
COMMENT ON COLUMN propertycollateral.vat_payable IS 'Indicator as to whether the VAT is payable on the disposal of the Unit. Documentation';
COMMENT ON COLUMN propertycollateral.year_of_construction IS 'Year that the Property was completed and refurbished. Documentation';
COMMENT ON COLUMN propertycollateral.year_of_refurbishment IS 'Year in which the last significantly refurbished was completed. Documentation';
COMMENT ON TABLE enforcement IS 'The Enforcement model holds Enforcement data conforming to the EBA NPL Template specification';
COMMENT ON COLUMN enforcement.protection_identifier IS 'Unique Institution internal identifier for the Property / Collateral as defined in sections "Property Collateral" and "Non-Property Collateral". Documentation';
COMMENT ON COLUMN enforcement.amount_of_outstanding_liabilities IS 'Amount of accrued costs and fees paid by the receiver and to be invoiced to the Institution. Documentation';
COMMENT ON COLUMN enforcement.annual_insurance_payment IS 'Annual insurance payment to be paid by receiver. Documentation';
COMMENT ON COLUMN enforcement.contracted_date IS 'Contracted date. Documentation';
COMMENT ON COLUMN enforcement.collateral_repossessed_date IS 'Date that the collateral is repossessed. Documentation';
COMMENT ON COLUMN enforcement.costs_accrued_to_buyer IS 'Costs accrued to the buyer. Documentation';
COMMENT ON COLUMN enforcement.costs_at_end_of_sale IS 'Total costs accrued to the seller at end of sale process. Documentation';
COMMENT ON COLUMN enforcement.court_appraisal_amount IS 'Court appraisal amount of the Property / Collateral. Documentation';
COMMENT ON COLUMN enforcement.court_auction_identifier IS 'Unique identifier for the auction process. Documentation';
COMMENT ON COLUMN enforcement.court_auction_reserve_price_for_first_auction IS 'Court set reserve price for first auction, i.e. minimum price required by the court. Documentation';
COMMENT ON COLUMN enforcement.court_auction_reserve_price_for_last_auction IS 'Court set reserve price for last auction, i.e. minimum price required by the court. Documentation';
COMMENT ON COLUMN enforcement.court_auction_reserve_price_for_next_auction IS 'Court set reserve price for next auction, i.e. minimum price required by the court. Documentation';
COMMENT ON COLUMN enforcement.currency_of_enforcement IS 'Currency that the items related to enforcement are expressed in. Documentation';
COMMENT ON COLUMN enforcement.current_market_status IS 'Current market status of the Property / Collateral as at cut-off date. Documentation';
COMMENT ON COLUMN enforcement.date_next_insurance_payment_is_due IS 'Date that the next insurance payment is due. Documentation';
COMMENT ON COLUMN enforcement.date_of_court_appraisal IS 'Date that the court appraisal happened. Documentation';
COMMENT ON COLUMN enforcement.date_of_receiver_appointment IS 'Date that the receiver was appointed. Documentation';
COMMENT ON COLUMN enforcement.enforcement_description IS 'Comments or description of the stage of enforcement. Documentation';
COMMENT ON COLUMN enforcement.fees_of_receivership IS 'Annual fees charged by the receiver. Documentation';
COMMENT ON COLUMN enforcement.first_auction_date IS 'Date that the first auction has been performed in order to sell the Property / Collateral. Documentation';
COMMENT ON COLUMN enforcement.funds_remitted_full_date IS 'Date that the funds were remitted fully. Documentation';
COMMENT ON COLUMN enforcement.funds_remitted_partial_date IS 'Date that the funds were remitted partially. Documentation';
COMMENT ON COLUMN enforcement.gross_sale_proceeds IS 'Gross sale proceeds, i.e. sales proceeds and costs incurred from the disposal. Documentation';
COMMENT ON COLUMN enforcement.indicator_of_enforcement IS 'Indicator as to whether the Enforcement process has been entered into by a Corporate or Private Individual Counterparty. Documentation';
COMMENT ON COLUMN enforcement.indicator_of_receivership IS 'Indicator as to whether the Corporate or Private Individual Counterparty is in Receivership. Documentation';
COMMENT ON COLUMN enforcement.insurance IS 'Indicator as to whether the receiver has insured the Property / Collateral. Documentation';
COMMENT ON COLUMN enforcement.insurance_coverage_amount IS 'Amount that the insurance covers. Documentation';
COMMENT ON COLUMN enforcement.insurance_provider IS 'Name of the insurance provider. Documentation';
COMMENT ON COLUMN enforcement.jurisdiction_of_court IS 'Location of the court where the case is being heard in. Documentation';
COMMENT ON COLUMN enforcement.last_auction_date IS 'Date that the last auction was performed in order to sell the Property / Collateral. Documentation';
COMMENT ON COLUMN enforcement.name_of_legal_firm IS 'Name of legal firm acting on behalf of the Institution. Documentation';
COMMENT ON COLUMN enforcement.name_of_receiver IS 'Name of the receiver appointed. Documentation';
COMMENT ON COLUMN enforcement.net_sale_proceeds IS 'Net sale proceeds. Documentation';
COMMENT ON COLUMN enforcement.next_auction_date IS 'Date that the next intended auction has been performed in order to sell the Property / Collateral. Documentation';
COMMENT ON COLUMN enforcement.number_of_failed_auctions IS 'Number of failed previous auctions for the Property / Collateral. Documentation';
COMMENT ON COLUMN enforcement.offer_price IS 'The highest price offered by potential buyers. Documentation';
COMMENT ON COLUMN enforcement.on_market_offer_date IS 'On market offer date. Documentation';
COMMENT ON COLUMN enforcement.on_market_price IS 'Price of the Property / Collateral for which it is on the market. Documentation';
COMMENT ON COLUMN enforcement.other_ongoing_enforcement_proceedings IS 'Further comments / details if there is other proceedings in place. Documentation';
COMMENT ON COLUMN enforcement.prepare_property_for_sale_date IS 'Prepare property for sale date. Documentation';
COMMENT ON COLUMN enforcement.property_on_market_date IS 'Property on market date. Documentation';
COMMENT ON COLUMN enforcement.sale_agreed_date IS 'Sale agreed date. Documentation';
COMMENT ON COLUMN enforcement.sale_agreed_price IS 'Agreed price for the disposal of the Property / Collateral. Documentation';
COMMENT ON COLUMN enforcement.sold_date IS 'Sold date. Documentation';
COMMENT ON TABLE externalcollection IS 'The ExternalCollection model holds External Collection data conforming to the EBA NPL Template specification';
COMMENT ON COLUMN externalcollection.institutions_internal_identifier_for_the_loan_or_counterparty IS 'Institutions internal identifier for the Counterparty or the Loan.Documentation';
COMMENT ON COLUMN externalcollection.instrument_identifier IS 'Institutions internal identifier for the Loan part. Documentation';
COMMENT ON COLUMN externalcollection.type_of_identifier IS 'Indicator as to whether the external collections have been prepares on a Counterparty level or on a Loan Level. Documentation';
COMMENT ON COLUMN externalcollection.balance_amount_sent_to_agent IS 'The Balance that was sent to the External Debt Collection Agent. Documentation';
COMMENT ON COLUMN externalcollection.cash_recoveries IS 'Total cash recoveries collected by the external collection agent. Documentation';
COMMENT ON COLUMN externalcollection.costs_accrued IS 'Total amount of costs accrued for external collection as at the NPL Portfolio Cut-Off Date. Documentation';
COMMENT ON COLUMN externalcollection.date_returned_from_agent IS 'Date that the Loan was received back from the external collection agent, i.e. when the agent stopped recovery efforts and passed the Loan back to the Institution. Documentation';
COMMENT ON COLUMN externalcollection.date_sent_to_agent IS 'Date that the Loan was sent to the external collection agent. Documentation';
COMMENT ON COLUMN externalcollection.legal_entity_identifier IS 'Global standard 20-character corporate identifier of the external collection agent. Documentation';
COMMENT ON COLUMN externalcollection.name_of_external_debt_collection_agent IS 'Name of the external collection agent. Documentation';
COMMENT ON COLUMN externalcollection.principal_forgiveness IS 'Amount of the principal that was forgiven by the external collection agent as part of recovery negotiations. Documentation';
COMMENT ON COLUMN externalcollection.quantity_returned_from_agent IS 'Amount of times the at the Loan was received back from the external debt collection agent. Documentation';
COMMENT ON COLUMN externalcollection.registration_number IS 'Company registration number of the external collection agent according to the registration with the country specific registration office. Documentation';
COMMENT ON COLUMN externalcollection.repayment_plan IS 'Indicator as to whether a repayment plan has been agreed with the external collection agency. Documentation';
COMMENT ON COLUMN externalcollection.repayment_plan_description IS 'Description of the repayment plan which has been agreed with the external collection agency. Documentation';
COMMENT ON TABLE forbearance IS 'The Forbearance model holds Forbearance data conforming to the EBA NPL Template specification';
COMMENT ON COLUMN forbearance.type_of_identifier IS 'Indicator as to whether forbearance has been prepared on a Counterparty level or a Loan level. Documentation';
COMMENT ON COLUMN forbearance.institutions_internal_identifier_for_the_loan_or_counterparty IS 'Institutions internal identifier for the Counterparty or the Loan. Documentation';
COMMENT ON COLUMN forbearance.instrument_identifier IS 'Institutions internal identifier for the Loan part. Documentation';
COMMENT ON COLUMN forbearance.amount_of_repayment_step_up IS 'Additional amount that the current agreed forbearance amount is increased by. Documentation';
COMMENT ON COLUMN forbearance.clause_to_stop_forbearance IS 'Indicator as to whether a clause exists to allow the Institution to stop the current forbearance. Documentation';
COMMENT ON COLUMN forbearance.date_of_first_forbearance IS 'Date that the first forbearance happened. Documentation';
COMMENT ON COLUMN forbearance.date_of_principal_forgiveness IS 'Date that the principal forgiveness happened. Documentation';
COMMENT ON COLUMN forbearance.date_of_repayment_step_up IS 'Date at which the current agreed forbearance amount is increased. Documentation';
COMMENT ON COLUMN forbearance.description_of_forbearance IS 'Further comments / details on the current forbearance. Documentation';
COMMENT ON COLUMN forbearance.description_of_the_forbearance_clause IS 'Further comments / details on the clause if "Yes" is selected in field "Clause to Stop Forbearance". Documentation';
COMMENT ON COLUMN forbearance.end_date_of_forbearance IS 'Date that the current forbearance arrangement ends. Documentation';
COMMENT ON COLUMN forbearance.interest_rate_under_forbearance IS 'Interest rate that the Institution and Counterparty agreed under the current forbearance terms. Documentation';
COMMENT ON COLUMN forbearance.number_of_historical_forbearance IS 'Number of forbearance(s) that happened in the past. Documentation';
COMMENT ON COLUMN forbearance.principal_forgiveness IS 'Amount of the principal that was forgiven as part of current forbearance, including principal forgiveness agreed by external collection agencies. Documentation';
COMMENT ON COLUMN forbearance.repayment_amount_under_forbearance IS 'Periodic repayment amount that the Institution and Counterparty agreed under the current forbearance terms. Documentation';
COMMENT ON COLUMN forbearance.repayment_frequency_under_forbearance IS 'Frequency that the repayment under current forbearance terms is made. Documentation';
COMMENT ON COLUMN forbearance.start_date_of_forbearance IS 'Date that the current forbearance arrangement starts. Documentation';
COMMENT ON COLUMN forbearance.type_of_forbearance IS 'Type of current forbearance. Documentation';