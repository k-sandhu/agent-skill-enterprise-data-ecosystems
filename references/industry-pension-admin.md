# Industry: Pension Administration

## Operating Context

- Administers a defined-benefit pension plan (small DC supplement) for participating employers; typical scale: 150-400 employers, 50k-80k active members, 15k-25k deferred vested, 30k-45k retirees and beneficiaries in pay.
- Money in: employee and employer contributions remitted per pay period by employers; money out: monthly retiree payroll, contribution refunds, death and survivor benefits.
- Benefit = accrual multiplier x credited service x final average salary, adjusted by option factors; accuracy depends on decades of employment, salary, and service history.
- Governed by plan statute and board policy; tax-authority withholding and annual reporting; annual actuarial valuation and funded-status disclosure are hard deadlines.
- Workload is cyclical: per-pay-period contribution posting, monthly payee payroll run, annual member statements, fiscal-year-end service credit finalization, valuation snapshot.
- Asset side runs in a separate investment operation; administration sees only a monthly investment accounting feed for funded-status reporting.

## Domains

member, employer, employment, service_credit, contribution, service_purchase, benefit_calculation, pension_estimate, retirement, retiree_payroll, beneficiary, death_benefit, actuarial, compliance, investment_interface, finance.

## Source Systems

| System | Role | System-of-record domains | Typical data quirks |
| --- | --- | --- | --- |
| Member administration platform | Member master, employment periods, service credit | member, employment, service_credit, beneficiary | duplicate members from legacy plan merges; effective-dated rows missing end dates |
| Employer portal | Employer self-service enrollment and remittance submission | employer, payroll_group | stale payroll group setup; free-text contact fields |
| Contribution remittance system | File intake, edit checks, posting, suspense | contribution | partial batch posting; suspense items aging silently |
| Payroll interface (employer files) | Inbound per-pay-period payroll detail | none (feeder) | per-employer format_drift; typo-prone national IDs and name fields |
| Benefit calculation engine | Estimates and final benefit calculations | benefit_calculation, pension_estimate | versioned plan rules; manual override fields on calc inputs |
| Retiree payroll system | Monthly payee payments, deductions, tax withholding | retiree_payroll | net-of-recalc adjustment rows; dual payee records after option changes |
| Document management | Imaged forms, application checklists | document | OCR misfiles; duplicate uploads of the same form |
| Call center / CRM | Member interactions, cases, callbacks | workflow (interaction) | inconsistent member identification across channels |
| Actuarial valuation system | Annual liability valuation | actuarial | annual snapshot only; cohort-level grouping loses member detail |
| Investment accounting interface | Asset values and funded-status feed | investment_interface | monthly lag; restated NAVs after audit |
| Finance / GL | Journal entries, cash, payables | finance | summarized postings hard to trace back to contribution lines |
| Enterprise data warehouse | Reporting and reconciliation copy | none (derivative) | conformance lag behind source corrections |

## Core Tables

- `member.member`, `member.member_identifier`, `member.member_status_history`, `member.address`, `member.beneficiary`
- `employer.employer`, `employer.employer_contact`, `employer.payroll_group`, `employer.rate_schedule`, `employer.remittance`
- `employment.employment_period`, `employment.salary_history`, `employment.service_credit`
- `contribution.contribution_batch`, `contribution.contribution_line`, `contribution.adjustment`, `contribution.suspense_item`
- `service_purchase.purchase_quote`, `service_purchase.purchase_agreement`, `service_purchase.purchase_installment`
- `benefit.benefit_option`, `benefit.option_factor`, `benefit.estimate`, `benefit.calculation`, `benefit.calculation_queue`, `benefit.election`
- `retirement.retirement_application`, `retirement.application_checklist_item`, `retirement.death_notification`
- `retiree_payroll.payee`, `retiree_payroll.payment`, `retiree_payroll.deduction`, `retiree_payroll.tax_withholding`, `retiree_payroll.payment_return`, `retiree_payroll.overpayment`
- `actuarial.valuation_member_snapshot`, `actuarial.assumption_set`, `actuarial.liability_result`
- `finance.journal_entry`, `finance.cash_receipt`
- `workflow.case`, `crm.interaction`, `document.document`, `document.checklist`

## Warehouse Facts and Dimensions

- `fact_contribution_line`: grain = one row per member x employer x pay period x contribution type.
- `fact_remittance`: grain = one row per employer remittance batch.
- `fact_service_credit`: grain = one row per member x fiscal year x service type.
- `fact_service_purchase_installment`: grain = one row per purchase agreement x installment payment.
- `fact_benefit_calculation`: grain = one row per calculation run per member.
- `fact_benefit_payment`: grain = one row per payee x payment cycle (degenerate: payment number; date roles: cycle date, issue date, settle date).
- `fact_payment_adjustment`: grain = one row per payment adjustment or return event.
- `fact_actuarial_liability`: grain = one row per member (or cohort) x valuation date x liability measure.
- `fact_member_interaction`: grain = one row per call, case, or document interaction.
- `fact_suspense_snapshot`: grain = one row per open suspense item per day (semi-additive aging).

Dimensions: member, employer, plan, payroll_group, employment_status, contribution_type, benefit_option, retirement_type, payee, payment_type, deduction_type, case_type, pay_period, date, geography.

## Critical Dataflows

- Contribution-to-service: employer payroll remittance -> file intake -> edit checks -> contribution lines posted -> service credit accrual -> member statement -> GL.
- Remittance suspense: edit failure -> suspense_item -> employer correction request -> corrected resubmission -> repost -> suspense closure.
- Service purchase: member inquiry -> cost quote -> signed agreement -> installment payments -> contribution posting -> service credit grant -> calc inputs.
- Retirement: application -> document checklist -> estimate -> calculation queue -> final calculation -> option election -> approval -> payee setup -> first payment.
- Retiree payroll cycle: payee roster -> gross calculation -> deductions and tax -> payment file -> bank -> returns and reissues -> GL posting.
- Death processing: notification -> verification -> payment hold -> survivor benefit setup or estate payout -> overpayment recovery -> GL.
- Actuarial: member snapshot + service + salary + assumption set -> liability results -> funded status reporting.
- Annual statement: contributions + service + estimate -> statement generation -> document management -> member portal delivery.

## State Machines

- Member lifecycle: enrolled -> active_contributing -> [leave_of_absence (0.04/yr, return to active 0.80 within 12 mo) | terminated (0.07/yr) | retired (0.035/yr of eligibles) | deceased_in_service (0.002/yr)]; terminated -> deferred_vested (0.55) | refund_paid (0.40, lognormal median 45 days, p90 120 days) | small_balance_forced_refund (0.05).
- Employer remittance: submitted -> format_validated (0.97, same day) | rejected_file (0.03, resubmit 1-3 business days) -> edits_passed (0.93) | partial_suspense (0.07) -> posted (1-2 business days after receipt); suspense_item -> resolved (0.85, lognormal median 12 business days, p90 45) | written_off (0.05) | escalated (0.10).
- Service purchase: inquiry -> quote_issued (0.90, 5-15 business days) -> agreement_signed (0.45 of quotes, within 90-day quote validity) -> [lump_sum_paid (0.35) | installments_active (0.65)] -> credited (after final payment); installments_active -> defaulted (0.08, partial credit prorated).
- Retirement application: received -> docs_complete (0.70 first pass; 0.30 checklist_exception, +10-25 business days) -> calc_queued -> calc_complete (lognormal, median 25 business days, p90 60; backlog-driven) -> election_made (within 30-60 days) -> approved (0.97) | withdrawn (0.03) -> first_payment (next monthly cycle; interim estimated payment if calc not final, 0.15 of cases).
- Benefit calculation case: queued -> assigned -> in_calc (1-3 business days touch time) -> peer_review -> finalized (0.85) | rework (0.15, +3-7 business days).
- Retiree payment: scheduled -> issued -> settled (0.997, 1-2 business days) | returned (0.003) -> reissued (0.90, 3-7 business days) | held (0.10).
- Death processing: reported -> verified (0.95, 3-10 business days) -> payment_hold -> [survivor_benefit_setup (0.45) | beneficiary_lump_sum (0.35) | estate_payout (0.20)]; overpayment created when verification lags a payment cycle (0.25 of deaths) -> recovered (0.80, lognormal median 60 days, p90 180) | written_off (0.20).

## Volumetrics and Distributions

| Metric | Typical value or range | Distribution | Notes |
| --- | --- | --- | --- |
| Active members | 50k-80k | n/a | cardinality anchor |
| Deferred vested members | 0.25-0.35 of actives | n/a | grows over time |
| Payees (retirees + beneficiaries) | 0.55-0.65 of actives | n/a | one payee can have 2+ payment records after splits |
| Participating employers | 150-400 | zipf s=1.2 on size | top 10% of employers = ~65% of contribution lines |
| Payroll groups per employer | 1-4 | weighted choice (1: 0.6, 2: 0.25, 3: 0.10, 4: 0.05) | |
| Pay frequency mix | biweekly 0.60, semimonthly 0.25, monthly 0.15 | weighted choice | drives remittance cadence |
| Contribution lines per remittance | median 180, p90 1,200, max ~12k | lognormal | proportional to employer size |
| Employee contribution per line | median 310, p90 750, p99 1,600 (currency units) | lognormal | employer share ~1.3-1.8x employee |
| Monthly gross pension per payee | median 2,400, p90 5,800, p99 11,000 | lognormal | deductions average 0.18 of gross |
| Retirement applications per year | 0.03-0.04 of actives | poisson per month with seasonality | clusters at Jan 1 / Jul 1 effective dates |
| Benefit estimates requested per year | 0.08-0.12 of actives | poisson | ~3 estimates per eventual retiree |
| Service purchase quotes per year | 0.015-0.025 of actives | poisson | ~0.45 convert to agreements |
| Calc backlog (open cases) | 400-1,200 | n/a | dwell lognormal, median 25 business days, p90 60 |
| Member interactions per member per year | lambda 0.6 | poisson | top 5% of members = ~30% of contacts |
| Death notifications per year | 0.018-0.025 of payees | poisson, Q1-heavy | 0.25 arrive after a payment cycle |
| Refunds per year | 0.45 of terminations | n/a | amount = contributions + credited interest |
| Returned payments per cycle | 0.002-0.003 of payments | n/a | bank account closures, deaths |
| Suspense items per remittance | 0.07 of remittances have 1+ | poisson lambda 3 items when present | aging pareto-tailed |
| Remittances received per month | employers x pay frequency | n/a | 3-pay-period months twice a year for biweekly |

## Business Rules and Invariants

- remittance.header_total = sum(contribution_line.employee_amount + employer_amount) + sum(adjustment.amount) per remittance.
- sum(service_credit.years) per member per fiscal year <= 1.00.
- Every posted contribution_line maps to an employment_period covering its pay period; otherwise it must sit in suspense.
- contribution_line.pay_period_end <= remittance.received_date, else late_flag = true.
- contribution_line.employer_amount = employee_amount x employer rate from rate_schedule effective on pay_period_end (within rounding).
- benefit.calculation gross = multiplier x credited_service x final_average_salary x option_factor; option_factor <= 1.00 vs single-life.
- benefit.election locked before first payment; fact_benefit_payment.gross = finalized calculation gross (interim payments flagged).
- payment.net = payment.gross - sum(deduction.amount) - tax_withholding.amount; net >= 0.
- retirement_effective_date > last contribution pay_period_end for the member.
- No payment issued with issue_date > verified date_of_death + 1 cycle; violations create an overpayment record.
- refund.amount = sum(member employee contributions) + credited interest at plan rate.
- service_purchase credited service granted only when sum(installment.paid_amount) = agreement.cost (or prorated on default).
- actuarial.valuation_member_snapshot counts tie to certified member_status_history counts as of valuation date.
- Exactly one active golden record per member in member.member; duplicates carry merge_pending status.
- payment_return implies a prior issued payment with matching payment_id; reissue references the returned payment.
- date sequences hold: enrolled_at <= employment_period.start <= pay_period_end <= posted_at; application.received_at <= calc.finalized_at <= election.elected_at <= first_payment.issue_date.

## Controls and Reconciliations

| Control | Grain | Tolerance | Expected break rate |
| --- | --- | --- | --- |
| Employer remittance totals tie to contribution lines | remittance | 0.01 | 0.05 |
| Contribution cash tie to bank deposits and GL | employer x deposit day | 1.00 | 0.02 |
| Contributions tie to service credits | member x fiscal year | 0.01 service years | 0.01 |
| Benefit payments tie to elections and finalized calcs | payee x cycle | 0.01 | 0.003 |
| Retiree payroll gross-to-net ties to bank payment file | payment cycle | 0.00 | 0.001 |
| Tax withheld ties to tax payable GL and remitted amounts | month | 1.00 | 0.01 |
| Actuarial snapshot ties to certified member data | plan x valuation date | 0 members | 0.005 |
| Member statements tie to contribution and service history | member x statement year | 0.01 | 0.01 |
| Suspense aging within threshold | open suspense item | 30 days | 0.15 of items exceed |
| Service purchase receipts tie to agreement schedules | agreement x installment | 0.01 | 0.02 |
| Investment feed funded status ties to GL asset balance | plan x month | 0.001 of assets | 0.03 |

## Seasonality and Temporal Patterns

- Remittance arrivals cluster 1-3 business days after employer pay dates; biweekly employers produce two monthly peaks plus a third-pay-period month twice a year (+50% line volume those months).
- Retirement effective dates cluster on Jan 1 and Jul 1 (0.45 of annual volume); applications spike 60-120 days before, pushing calc backlog to its annual peak in Q2.
- Fiscal year end (Jun 30): service credit finalization, valuation snapshot extract, and employer year-end corrections compress into a 4-6 week close window.
- Retiree payroll is a single monthly run near the 1st; payment returns peak 3-5 business days after; call volume spikes the run day and the day after.
- Call center intraday: morning-heavy, Monday peak ~1.4x daily average; surge for 2 weeks after annual statement mailing and after any payment change.
- Death notifications elevated Jan-Mar (~1.3x average month); year-end tax form questions spike in late Jan.
- Employer portal submissions skew to deadline day: 0.4 of remittances arrive on the due date, intraday peak 3-5 pm.

## Controlled Imperfections

| Imperfection | Where it appears | Typical rate | Downstream symptom |
| --- | --- | --- | --- |
| late_arrival | employer remittances > 5 business days late | 0.06 of remittances | service credit gaps on statements; interest assessments |
| late_arrival | death notifications after a payment cycle | 0.25 of deaths | overpayments requiring recovery |
| missing_xref | payroll file employee ID unmapped to member ID | 0.008 of lines | suspense items; understated member contributions |
| orphan_fk | contribution line with no covering employment_period | 0.004 of lines | posting blocked; recon break on remittance tie-out |
| duplicate_entity | duplicate member records from legacy plan merges | 0.004 of members | split service history; wrong vesting determination |
| restatement_reversal | retro salary corrections reposting prior periods | 0.02 of lines | FAS recalcs; statement restatements |
| restatement_reversal | benefit recalculations after audit or correction | 0.01 of payees per year | payment adjustments; gross != original calc |
| manual_override | service purchase adjustments and calc input overrides | 0.03 of calcs | calc engine value differs from stored inputs |
| conflicting_source_values | beneficiary differs between member admin and retiree payroll | 0.01 of payees | death benefit paid to wrong-of-record beneficiary case |
| stale_mapping | legacy plan codes unmapped to current plan dimension | 0.01 of service rows | misclassified service type in warehouse |
| format_drift | employer payroll file layout changes mid-year | 0.10 of employers per year | rejected files; late remittances |
| typo | national ID or name typos in employer files | 0.005 of lines | failed member match; suspense growth |
| out_of_order_events | employment events (rehire before termination posted) | 0.003 of events | overlapping employment periods; service over-accrual |
| duplicate_webhook | duplicate remittance file submission via portal | 0.002 of remittances | doubled contribution lines until dedupe |
| missing_xref | missing payroll periods (no file for a pay period) | 0.01 of employer-periods | service credit gap; member statement disputes |
| manual_override | document checklist exceptions waived by supervisors | 0.05 of applications | approvals lacking required documents |
| late_arrival | deceased payee holds applied after payment issued | 0.002 of payments | payment_return and overpayment records |
