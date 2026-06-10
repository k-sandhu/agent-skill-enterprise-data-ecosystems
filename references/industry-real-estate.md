# Industry: Real Estate Operator

## Operating Context

- Owns and operates a mixed portfolio (multifamily, office, retail) of 60-120 properties / 8k-15k rentable units across 3-6 regional markets; third-party managed for a minority of assets.
- Money flows in via tenant rent, recoveries (CAM, tax, insurance), parking/ancillary fees; out via property opex, capex, vendor invoices, debt service, and investor distributions.
- Each property sits in its own legal entity (SPE); lender reporting and covenant tests run at the loan/borrower level, investor reporting at the fund/portfolio level.
- Key constraints: landlord-tenant law (notice periods, deposit handling, eviction process), fair-housing rules on screening, lender covenants (DSCR, LTV, occupancy floors), GAAP straight-line rent.
- Scale anchors: ~12k units, ~9k active leases, ~3.5k work orders/month, ~70 loans, annual external appraisals plus quarterly internal valuations.
- Value is managed through the property -> building -> unit -> lease hierarchy: occupancy and rent roll drive NOI, NOI drives valuations, valuations drive covenants and refinancing.

## Domains

property, unit, tenant, lease, leasing_pipeline, renewals, rent_billing, accounts_receivable, collections, CAM_recoveries, maintenance, vendors, capex, valuations, debt, covenants, budgeting, GL, investor_reporting, compliance.

## Source Systems

| System | Role | System-of-record domains | Typical data quirks |
| --- | --- | --- | --- |
| Property management system (PMS) | Units, leases, charges, receipts, move-in/out | property, unit, lease, rent_billing, accounts_receivable | Unit merges/splits leave legacy unit IDs; charge codes vary by property onboarding vintage |
| Lease administration platform | Commercial lease abstraction, options, clauses | lease terms, options, CAM clauses | Abstract lags execution by weeks; square footage disagrees with PMS |
| Tenant portal / payment gateway | Online payments, maintenance requests | payment events, ticket intake | Duplicate webhooks; payments post before PMS charge exists |
| Lockbox / bank feed | Check and ACH receipts | cash receipts | One day of float; unapplied cash; partial payments |
| Work order system (CMMS) | Tickets, dispatch, preventive maintenance | maintenance, vendors (operational) | Free-text unit references; tickets closed without cost capture |
| AP / vendor invoicing module | Vendor bills, approvals, payments | vendor invoices, capex spend | Invoices arrive 30-90 days late; duplicate vendor masters |
| Corporate GL / accounting platform | Journals, trial balance, entity accounting | GL, budgets (actuals) | Property-to-entity mapping changes at acquisitions |
| Budgeting and reforecast tool | Opex/capex budgets, NOI forecasts | budget, reforecast | Spreadsheet uploads; account mapping drift vs GL chart |
| Valuation workspace | Appraisals, internal DCF/direct cap models | valuations, cap rate assumptions | Model NOI differs from GL NOI; stale rent roll snapshots |
| Debt management system | Loans, amortization, covenants, lender reporting | debt, covenants | Manual covenant inputs; waiver letters tracked as documents |
| Leasing CRM | Prospects, tours, applications, renewal offers | leasing_pipeline, renewals | Prospects unlinked to executed leases; duplicate contacts |
| Utility billing service | Submetered utility charges (RUBS) | utility recharges | Estimated reads later trued up; meter-to-unit map stale |

## Core Tables

- `property.property`, `property.building`, `property.unit`, `property.unit_status_history`, `property.space_measurement`, `property.legal_entity`
- `lease.tenant`, `lease.guarantor`, `lease.lease`, `lease.lease_unit` (multi-unit commercial leases), `lease.lease_charge_schedule`, `lease.lease_amendment`, `lease.lease_option`, `lease.security_deposit`
- `leasing.prospect`, `leasing.tour`, `leasing.application`, `leasing.screening_result`, `leasing.renewal_offer`, `leasing.notice_to_vacate`
- `ar.charge`, `ar.tenant_statement`, `ar.receipt`, `ar.receipt_application`, `ar.adjustment`, `ar.delinquency_status`, `ar.payment_plan`, `ar.write_off`
- `cam.expense_pool`, `cam.pool_gl_mapping`, `cam.lease_pool_share`, `cam.estimate_billing`, `cam.reconciliation`, `cam.reconciliation_line`, `cam.true_up_invoice`, `cam.dispute`
- `maint.ticket`, `maint.work_order`, `maint.work_order_task`, `maint.preventive_schedule`, `maint.inspection`, `maint.vendor`, `maint.vendor_invoice`, `maint.vendor_invoice_line`
- `capex.project`, `capex.project_budget`, `capex.project_draw`
- `valuation.appraisal`, `valuation.valuation_run`, `valuation.cap_rate_assumption`, `valuation.noi_bridge`
- `debt.loan`, `debt.loan_collateral`, `debt.debt_service_schedule`, `debt.debt_service_payment`, `debt.covenant`, `debt.covenant_test`, `debt.waiver`
- `gl.journal_entry`, `gl.journal_line`, `gl.trial_balance`, `gl.account`, `budget.budget_line`, `budget.reforecast_line`
- `investor.fund`, `investor.fund_property_allocation`, `investor.distribution`

## Warehouse Facts and Dimensions

- `fact_rent_roll_monthly`: one row per lease x charge_type x month (scheduled rent, in-place rent, straight-line adjustment as measures).
- `fact_occupancy_daily`: one row per unit x business_date (status, occupied_flag, days_vacant counter).
- `fact_ar_activity`: one row per AR transaction (charge, receipt application, adjustment, write-off).
- `fact_ar_aging_monthly`: one row per lease x aging_bucket x month_end.
- `fact_work_order`: one row per work order (created/completed dates, labor and material cost, recoverable_flag).
- `fact_cam_reconciliation_line`: one row per lease x expense_pool x reconciliation_year.
- `fact_leasing_event`: one row per pipeline event (tour, application, approval, signing, renewal offer, notice).
- `fact_valuation`: one row per property x valuation_date x method.
- `fact_covenant_test`: one row per loan x covenant x test_period.
- `fact_debt_service`: one row per loan x payment_period (scheduled vs paid principal/interest/escrow).
- `fact_gl_balance_monthly`: one row per legal_entity x gl_account x month.

Dimensions: property, building, unit, unit_type, tenant, lease, charge_type, expense_pool, vendor, trade, loan, lender, fund, market, property_type, legal_entity, gl_account, date.

## Critical Dataflows

- Lease-to-rent-roll: lease executed -> abstraction -> charge schedule -> monthly charge generation -> rent roll snapshot -> straight-line revenue -> GL -> investor reporting.
- Cash application: tenant portal / lockbox receipt -> receipt staging -> match to open charges -> receipt application -> AR aging -> GL cash and AR.
- Renewal cycle: expiry watchlist (rolling 12 months) -> renewal offer -> negotiation -> executed renewal or notice to vacate -> move-out -> make-ready work orders -> re-lease.
- CAM cycle: opex budget -> monthly estimate billing -> actual expense accumulation in pools (AP/GL) -> year-end reconciliation -> true-up invoices/credits -> disputes -> settlement.
- Maintenance-to-cost: ticket intake -> triage -> work order -> vendor dispatch or in-house tech -> completion -> vendor invoice -> AP -> GL opex -> CAM pool (if recoverable).
- Valuation-to-covenant: rent roll + GL actuals -> NOI bridge -> valuation run (direct cap / DCF) -> appraised value -> LTV and DSCR covenant tests -> lender certificate -> waiver workflow on breach.
- Delinquency: missed payment -> late fee -> reminder/notice sequence -> payment plan or legal action -> resolution or write-off.

## State Machines

- Lease (residential): prospect -> tour (0.45 of prospects, 1-5 days) -> application (0.55 of tours) -> screened -> approved (0.78, 1-2 business days) | denied (0.17) | withdrawn (0.05) -> executed (1-7 days) -> active -> renewal (0.55) | notice_given (0.40) | eviction (0.05) -> moved_out -> deposit_settled (uniform 14-30 days).
- Lease (commercial): loi -> negotiation (lognormal, median 45 days, p90 120 days) -> executed -> fit_out (30-180 days) -> commenced -> active -> option_exercised (0.30) | renewed (0.35) | expired_vacated (0.30) | early_terminated (0.05).
- Work order: submitted -> triaged (0.95, median 4 hours) | cancelled (0.05) -> assigned -> scheduled -> in_progress -> completed (lognormal, median 2 days, p90 10 days) -> verified -> closed | reopened (0.06, within 14 days).
- Renewal offer: offer_sent (90-150 days before expiry) -> accepted (0.55, median 18 days) | countered (0.20) | declined (0.15) | expired_no_response (0.10); countered -> accepted (0.60) | declined (0.40).
- CAM reconciliation: pools_closed -> draft_calculated (5-15 business days) -> reviewed -> statements_issued -> paid (0.84, median 30 days) | disputed (0.08) | credit_applied (0.08); disputed -> adjusted (0.55) | upheld (0.45), median 45 days.
- Delinquency: current -> late (day 6 after due) -> notice_sent (day 10-15) -> payment_plan (0.35) | paid_in_full (0.45) | legal_filed (0.15) | write_off (0.05); legal_filed -> resolved (0.70, median 60 days) | write_off (0.30).
- Covenant test: data_collected -> calculated -> passed (0.93) | breached (0.07); breached -> waiver_requested -> waived (0.70, 10-30 business days) | cured (0.20) | default_noticed (0.10).

## Volumetrics and Distributions

| Metric | Typical value or range | Distribution | Notes |
| --- | --- | --- | --- |
| Properties in portfolio | 60-120 | n/a | ~70% multifamily, 20% office, 10% retail by count |
| Units per property | median 100, range 8-450 | lognormal | Commercial suites counted as units |
| Physical occupancy | 0.92-0.95 stabilized | beta(60, 4) per property | Lease-up assets 0.55-0.85 |
| Residential lease term | 12 months (0.80), 6 (0.10), MTM (0.10) | weighted choice | MTM carries 1.1-1.25x rent premium |
| Commercial lease term | 36-120 months, median 60 | lognormal | Options for 1-2 x 60-month extensions |
| Monthly residential rent | median 1,650, p95 3,200 | lognormal | Varies 0.7-1.5x by market dim |
| Commercial rent per sf per year | median 28, p95 55 | lognormal | Plus recoveries on NNN leases |
| Residential renewal rate | 0.52-0.60 | n/a | Renewal uplift normal(0.04, 0.02) |
| Work orders per unit per year | 3.5 | poisson | Top 10% of units = ~35% of tickets |
| Work order cost | median 130, p90 850, p99 6,000 | lognormal | p99 tail reclassified to capex |
| Emergency ticket share | 0.08-0.12 | n/a | After-hours, 4-hour SLA |
| Delinquent AR (30+ days) | 0.04-0.07 of monthly billings | n/a | Spikes after rent increases |
| Receipts per lease per month | 1.1 | poisson | Partial/split payments drive >1 |
| CAM recovery ratio | 0.85-0.95 of pooled expense | normal(0.90, 0.03) | Caps and gross-up reduce recovery |
| CAM true-up per commercial lease | median 1,800 owed, 0.25 are credits | lognormal on abs value | Disputes on 0.08 of statements |
| Vendor spend concentration | top 10% vendors = ~60% of spend | zipf s=1.2 | ~400 active vendors |
| Loans outstanding | 50-80 (0.6-0.8 per property) | n/a | 10-15% of assets unencumbered |
| DSCR across loans | mean 1.45, sd 0.25, floor covenant 1.20-1.25 | normal | ~0.07 of tests breach |
| Valuation events per property per year | 1 external + 4 internal | n/a | Direct cap and DCF methods |
| Cap rate by property type | 4.5-7.5%, multifamily lowest | normal per type, sd 0.4pp | Drives 0.9-1.1x value swings |

## Business Rules and Invariants

- Unit belongs to exactly one building; building to exactly one property; lease references >=1 unit via `lease.lease_unit`.
- No two active leases overlap on the same unit for the same date range.
- `lease_end_date >= lease_start_date`; `move_out_date >= notice_date >= lease_start_date`; amendment `effective_date >= lease_start_date`.
- Occupied unit on date D implies an active lease covering D; occupancy = occupied units / rentable units (exclude down/admin units from denominator).
- Monthly rent roll total per property = sum of active charge schedule amounts for that month (after amendments and concessions).
- AR roll-forward per lease per month: opening AR + charges + adjustments - receipt applications - write-offs = closing AR.
- Sum of `receipt_application.amount` per receipt <= receipt amount; remainder sits as unapplied cash, never negative.
- Late fee charge exists only if a base rent charge for the period is unpaid past the grace day.
- Straight-line rent: cumulative straight-line revenue over full term = cumulative contractual rent over full term (within rounding).
- Security deposit liability >= 0; deposit refund + deductions = deposit held; settled within statutory window post move-out.
- CAM: lease pool shares within one expense pool sum to <= 1.0 (after gross-up); true-up = actual pool expense x share - estimates billed, capped per lease clause.
- CAM pool expense ties to mapped GL accounts via `cam.pool_gl_mapping` for the same year.
- Work order timestamps: `closed_at >= verified_at >= completed_at >= in_progress_at >= assigned_at >= submitted_at`.
- Vendor invoice references a completed work order or capex project; invoice total = sum of line amounts + tax.
- DSCR = period NOI / period debt service from the same test period; LTV = loan balance / latest appraised value.
- Covenant breach record requires a covenant_test row with `result = breached`; waiver references the breach.
- Valuation (direct cap): value = stabilized NOI / cap rate within 0.5% tolerance of stored value.
- Distribution per fund <= available cash after debt service and reserves for the period.

## Controls and Reconciliations

| Control | Grain | Tolerance | Expected break rate |
| --- | --- | --- | --- |
| Rent roll to GL rental revenue | property x month | 0.1% or 50 | 0.03 |
| Bank/lockbox deposits to receipts | bank account x day | 0.01 | 0.02 |
| AR subledger to GL AR balance | legal entity x month | 10 | 0.04 |
| Charge schedule to billed charges | lease x month | 0 | 0.02 |
| CAM pool expense to GL opex accounts | pool x year | 0.5% | 0.08 |
| CAM estimates billed to true-up statements | lease x year | 0.01 | 0.05 |
| Unit inventory PMS vs lease admin | property x month | 0 units | 0.01 |
| Vendor invoice to AP posting | invoice | 0.01 | 0.03 |
| Debt service paid to lender statement | loan x month | 1 | 0.01 |
| Covenant inputs to financial statements | loan x quarter | 1% | 0.05 |
| Valuation NOI to GL NOI bridge | property x quarter | 2% | 0.10 |
| Occupancy snapshot vs lease status | unit x day | 0 | 0.02 |
| Security deposit liability to deposits held | property x month | 5 | 0.03 |

## Seasonality and Temporal Patterns

- Residential leasing and move-ins peak May-September (~1.4x the December-February trough); make-ready work orders follow with a 1-2 week lag.
- Rent receipts concentrate on days 1-5 of the month (~75% of cash); late fees and reminder notices spike days 6-12.
- Work orders: HVAC tickets ~1.5x baseline June-August, heating tickets ~1.4x December-February; plumbing roughly flat; emergency tickets skew to evenings/weekends (~0.10 of volume).
- Ticket submissions are weekday-heavy (Mon-Tue peak after weekend backlog); vendor completions cluster Tuesday-Thursday.
- CAM reconciliation workload spikes January-April after year-end close; true-up invoices issue mostly in Q2; disputes trail into Q3.
- Covenant tests and internal valuations cluster at calendar quarter ends; external appraisals cluster at fiscal year-end and refinancing events.
- GL journal volume spikes in the first 5 business days of each month (close); budget/reforecast uploads spike in Q4 and mid-year.
- Commercial lease expiries cluster on month-end dates and December 31; renewal offers go out 90-150 days prior.

## Controlled Imperfections

| Imperfection | Where it appears | Typical rate | Downstream symptom |
| --- | --- | --- | --- |
| missing_xref | PMS tenant lacks leasing CRM contact ID | 0.04 of tenants | Renewal funnel undercounts; marketing attribution gaps |
| orphan_fk | Receipt application points to reversed/cancelled charge | 0.005 of applications | AR aging negative buckets; recon breaks |
| duplicate_entity | Same tenant duplicated across properties or after re-lease | 0.02 of tenants | Inflated tenant counts; split payment history |
| duplicate_entity | Duplicate vendor master records in AP | 0.03 of vendors | Split spend; missed concentration limits |
| late_arrival | Vendor invoices land 30-90 days after work order completion | 0.10 of invoices | CAM pool restatements; accrual true-ups |
| conflicting_source_values | Square footage differs PMS vs lease abstract | 0.06 of commercial leases | CAM share disputes; rent-per-sf metric drift |
| format_drift | Lockbox bank file layout changes columns | 1-2 events/year | Receipt staging failures; unapplied cash spike |
| typo | Unit number keyed wrong on manual ticket entry | 0.01 of tickets | Work order maps to wrong unit; cost misallocation |
| restatement_reversal | CAM true-up restated after dispute upheld | 0.03 of recon lines | Prior-year revenue restated; investor report deltas |
| out_of_order_events | Lease amendment recorded after its effective date | 0.02 of amendments | Rent roll snapshot differs from as-of replay |
| duplicate_webhook | Tenant portal payment webhook delivered twice | 0.003 of payments | Double receipts pending dedup; bank recon breaks |
| stale_mapping | Charge-code-to-GL or pool-GL mapping not updated after chart change | 0.01 of mappings/year | Revenue misclassified; CAM pool ties fail |
| manual_override | Manual concession or rent override outside charge schedule | 0.03 of leases | Rent roll vs schedule variance; audit flags |
| missing_xref | Loan collateral missing property legal-entity link | 0.02 of loans | Covenant tests pull wrong NOI scope |
