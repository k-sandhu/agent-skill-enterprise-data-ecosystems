# Industry: Pension Administration

## Domains

member, employer, employment, service_credit, contribution, benefit_calculation, pension_estimate, retirement, retiree_payroll, beneficiary, actuarial, compliance, investment_interface, finance.

## Source Systems

Member administration, employer portal, contribution remittance system, payroll interface, benefit calculation engine, retiree payroll, document management, call center/CRM, actuarial valuation system, investment accounting interface, finance/GL, data warehouse.

## Core Tables

- `member.member`, `member.member_identifier`, `member.beneficiary`
- `employer.employer`, `employer.payroll_group`, `employer.remittance`
- `employment.employment_period`, `employment.service_credit`
- `contribution.contribution_batch`, `contribution.contribution_line`, `contribution.adjustment`
- `benefit.benefit_option`, `benefit.estimate`, `benefit.calculation`, `benefit.election`
- `retirement.retirement_application`, `retiree_payroll.payment`, `retiree_payroll.deduction`
- `actuarial.valuation_member_snapshot`, `actuarial.liability_result`
- `finance.journal_entry`, `workflow.case`, `document.document`

## Facts and Dimensions

- `fact_contribution_line`: one contribution line per member-employer-pay-period.
- `fact_service_credit`: one member-service-period.
- `fact_benefit_payment`: one retiree payment.
- `fact_benefit_calculation`: one calculation run per member.
- `fact_actuarial_liability`: one member or cohort valuation result.
- `fact_member_interaction`: one call/case/document interaction.

Dimensions: member, employer, plan, employment_status, contribution_type, benefit_option, pay_period, date, geography.

## Dataflows

- Contribution-to-service: employer payroll remittance -> contribution lines -> validation -> service credit -> member statement -> GL.
- Retirement: application -> document checklist -> benefit calculation -> election -> approval -> retiree payroll.
- Actuarial: member snapshot + service + salary + assumptions -> liabilities -> funded status reporting.

## Controls

- Employer remittance totals tie to contribution lines and deposits.
- Contributions tie to service credits.
- Benefit payments tie to elections and payroll.
- Actuarial snapshots tie to certified member data as of valuation date.
- Member statements tie to contribution and service history.

## Imperfections

Late employer remittances, missing payroll periods, retro salary corrections, service purchase adjustments, beneficiary changes, benefit recalculations, deceased retiree holds, duplicate member records, legacy plan codes, document checklist exceptions.
