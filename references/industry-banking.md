# Industry: Banking

## Operating Context

- Regional retail/commercial bank: 300k-700k active customers, 60-120 branches, 2-4 legal entities, one primary currency plus minor FX.
- Money flows: deposits in via payroll/transfers, out via card spend, bill pay, ACH-style batch payments, and wires; loans fund out and repay monthly; everything posts to subledgers that roll to GL.
- Product mix: checking/savings (DDA), debit and credit cards, consumer and small-business loans, mortgages, commercial lines of credit.
- Heavily regulated: KYC/CDD at onboarding, ongoing AML transaction monitoring with alert-to-case-to-SAR funnel, capital and liquidity reporting from GL balances.
- Daily batch rhythm dominates: end-of-day posting, interest accrual, GL balancing, settlement file exchange with card and payment networks.
- Fraud and credit risk are continuous: real-time card auth scoring, payment screening, monthly delinquency aging on loans.

## Domains

party, customer, account, deposits, payments, cards, loans, ledger, treasury, risk, fraud, AML, KYC, compliance, branch, digital, customer_service.

## Source Systems

| System | Role | System-of-record domains | Typical data quirks |
| --- | --- | --- | --- |
| Core banking platform | Account master, posting engine, EOD batch | account, deposits, ledger (subledger) | Legacy account IDs, fixed-width extracts, EOD cutover timestamps |
| Digital banking platform | Online/mobile channel, transfers, bill pay | digital sessions, channel events | Duplicate session events, device IDs not linked to party |
| Payment hub | Batch and wire payment orchestration | payments | Duplicate payment messages, out-of-order lifecycle events |
| Card processor | Auth, clearing, settlement for cards | cards | Settlement file lag T+1/T+2, merchant descriptors inconsistent |
| Loan servicing system | Loan boarding, schedules, payments, delinquency | loans | Re-amortization restates schedules, payoff quotes vs actuals drift |
| Deposit platform | Interest accrual, term deposits | deposit pricing, accruals | Rate-change effective dating errors |
| Customer onboarding / KYC | Identity verification, CDD, document collection | party, kyc | Stale documents, name/address mismatch vs core banking |
| AML case management | Alert triage, cases, SAR workflow | aml | Free-text dispositions, alert backlog timestamps |
| Fraud engine | Real-time scoring, rules, fraud cases | fraud | Score model version changes mid-history, analyst overrides |
| General ledger | Chart of accounts, journals, GL balances | ledger (GL), treasury | Manual journals at close, suspense accounts that linger |
| Statement processor | Periodic statements, notices | documents | Cycle-date vs posting-date mismatches |
| Data warehouse | Conformed analytics layer | none (consumer) | Late-arriving facts, snapshot vs event grain confusion |

## Core Tables

- `party.party`, `party.person`, `party.organization`, `party.relationship`
- `accounts.account`, `accounts.account_holder`, `accounts.account_status_history`, `accounts.account_balance_daily`
- `deposits.deposit_account`, `deposits.interest_accrual`, `deposits.rate_schedule`
- `payments.payment_instruction`, `payments.payment_event`, `payments.payment_return`, `payments.settlement_batch`
- `cards.card_account`, `cards.card`, `cards.card_authorization`, `cards.card_transaction`, `cards.card_dispute`, `cards.merchant`
- `loans.loan_application`, `loans.loan_account`, `loans.loan_schedule`, `loans.loan_payment`, `loans.collateral`, `loans.delinquency_history`
- `ledger.chart_of_accounts`, `ledger.subledger_entry`, `ledger.journal_entry`, `ledger.journal_line`, `ledger.gl_balance`
- `kyc.customer_due_diligence`, `kyc.document`, `kyc.screening_result`
- `aml.monitoring_rule`, `aml.alert`, `aml.case`, `aml.sar_filing`
- `fraud.score`, `fraud.rule`, `fraud.case`, `risk.risk_rating`
- `branch.branch`, `product.product_catalog`, `digital.session`

## Warehouse Facts and Dimensions

- `fact_account_balance_daily` - grain: one row per account per business_date (semi-additive balance).
- `fact_transaction` - grain: one row per posted transaction (debit/credit on an account).
- `fact_payment_event` - grain: one row per payment lifecycle event per payment_instruction.
- `fact_card_authorization` - grain: one row per authorization attempt (approved or declined).
- `fact_card_transaction` - grain: one row per cleared/posted card transaction.
- `fact_loan_payment` - grain: one row per loan installment due or received.
- `fact_loan_delinquency_snapshot` - grain: one row per loan account per month-end (DPD bucket, balance).
- `fact_gl_balance_daily` - grain: one row per GL account per legal_entity per business_date.
- `fact_aml_alert` - grain: one row per alert with funnel disposition attributes.

Dimensions: customer, account, branch, product, channel, currency, merchant, gl_account, legal_entity, risk_rating, aml_rule, date.

## Critical Dataflows

- Payment lifecycle: initiation -> validation -> sanctions/fraud screening -> authorization -> release -> network settlement -> return/reversal when needed.
- Account balance: posted transactions -> subledger -> account balance roll-forward -> GL balance -> regulatory report.
- Card flow: authorization -> hold on available balance -> clearing file (T+1/T+2) -> posted transaction -> network settlement recon -> dispute/chargeback when contested.
- KYC onboarding: application -> identity verification -> screening -> risk scoring -> due diligence -> account opening.
- Loan origination: application -> credit decisioning -> approval -> documentation -> funding -> boarding to servicing -> schedule generation.
- AML funnel: posted transactions -> monitoring rules (overnight batch) -> alert -> triage -> case -> investigation -> SAR filing or close.
- GL close: subledger entries -> journal generation -> GL posting -> daily balancing -> month-end close with manual journals -> reporting extract.

## State Machines

- Payment instruction: initiated -> validated (0.985, minutes) | rejected (0.015); validated -> screened -> authorized (0.995) | screening_hold (0.005, lognormal, median 4 hours, p90 2 business days); authorized -> released -> settled (batch: same day or T+1; wire: minutes-hours); settled -> returned (0.008, 1-3 business days) -> reversed.
- Card authorization: requested -> approved (0.95) | declined (0.05); approved -> posted (0.97, lognormal, median 1 day, p90 3 days) | expired_unmatched (0.03, drops after 7 days).
- Card dispute: filed -> provisional_credit (0.85, 1-2 business days) -> investigation -> resolved_cardholder (0.70) | resolved_merchant (0.30); dwell lognormal, median 18 days, p90 45 days.
- Loan application: submitted -> in_underwriting (lognormal, median 2 business days, p90 7) -> approved (0.65) | declined (0.30) | withdrawn (0.05); approved -> funded (0.90, 2-10 business days) | offer_expired (0.10).
- Loan delinquency (monthly transition): current -> 1-29 DPD (0.030) ; 1-29 -> cured (0.60) | 30-59 (0.40); 30-59 -> cured (0.40) | 60-89 (0.60); 60-89 -> cured (0.25) | 90+ (0.75); 90+ -> charged_off (0.30/month) | cured (0.10/month).
- AML alert: generated -> triaged (lognormal, median 3 business days, p90 15) -> closed_false_positive (0.90) | escalated_to_case (0.10); case -> closed_no_action (0.85, median 20 business days, p90 60) | sar_filed (0.15).
- Account lifecycle: applied -> kyc_review (0.5-3 business days) -> open (0.93) | rejected (0.07); open -> active -> dormant (no activity 12 months, 0.04/year) -> closed; active -> closed (0.08/year attrition).
- Fraud case: flagged -> review -> confirmed_fraud (0.25) | false_positive (0.75); confirmed -> card_reissued/account_restricted -> recovery_attempted.

## Volumetrics and Distributions

| Metric | Typical value or range | Distribution | Notes |
| --- | --- | --- | --- |
| Active customers | 300k-700k | n/a | Scale anchor; ~85% retail, ~15% small business/commercial |
| Accounts per customer | 1.6 avg, max ~8 | weighted choice: 1 (0.55), 2 (0.28), 3+ (0.17) | Joint holders on ~15% of accounts |
| Posted transactions per DDA per month | 35 | poisson, overdispersed | Use lognormal multiplier per account |
| Card transactions per active card per month | 22 | poisson, lambda 22 | ~70% of cards active in a month |
| Card transaction amount | median $32, p95 $180, p99 $650 | lognormal | Tail from travel/electronics |
| Batch payment (ACH-style) amount | median $450, p95 $4,500 | lognormal | Payroll credits cluster at round amounts |
| Wire amount | median $18k, p95 $250k | lognormal, heavy tail | Commercial-dominated |
| Commercial payment value skew | top 10% of commercial customers = ~70% of payment value | zipf, s=1.2 | Retail flatter, s=0.8 |
| Batch payment return rate | 0.008 | n/a | Mostly insufficient funds, closed account |
| Card auth decline rate | 0.05 | n/a | ~40% insufficient funds, ~25% suspected fraud |
| Card fraud loss rate | 0.0010 of purchase volume (10 bps) | n/a | Confirmed fraud txn rate ~0.0008 of transactions |
| Card dispute rate | 0.002 of posted card transactions | n/a | ~25% become chargebacks |
| AML alerts per 1k customers per month | 5 | poisson | Concentrated in cash-intensive and new accounts |
| Alert -> case rate | 0.10 | n/a | Case -> SAR rate 0.15; net SAR per alert ~0.015 |
| Loan applications per month | 0.8-1.5% of customer base | poisson | Spikes with rate moves and promotions |
| Loan approval rate | 0.65 | n/a | Lower (~0.45) for thin-file applicants |
| 30+ DPD delinquency rate | 0.020 of active loans | n/a | Charge-off ~0.010/year of balances |
| GL accounts | 2,500 | n/a | ~120 with daily activity; 5-15 suspense accounts |
| Merchants seen per month | 40k-80k distinct | pareto on txn count | Top 1% of merchants = ~35% of card volume |

## Business Rules and Invariants

- Balance roll-forward holds per account per day: opening + credits - debits + interest - fees + reversals = closing.
- Journal entries balance: sum(debit lines) = sum(credit lines) per journal_entry.
- Daily GL movement = sum of subledger entries mapped to that GL account, legal entity, and date.
- Payment event timestamps monotonic per instruction: initiated_at <= validated_at <= authorized_at <= released_at <= settled_at.
- payment_return references an existing payment_instruction; return amount = original amount; returned_at >= settled_at.
- Card posted_at >= auth_at; posted amount within 20% of auth amount except fuel/tip MCCs; every posted card transaction has a matching auth or is flagged force_post.
- Card auth holds reduce available balance but not ledger balance; available <= ledger + overdraft limit.
- Loan outstanding principal = original principal - sum(principal portions of posted loan payments) + capitalized amounts.
- Loan schedule installment = principal portion + interest portion; sum of schedule principal = funded amount.
- Daily deposit interest accrual = end-of-day balance * annual rate / day-count basis; accruals post at cycle end.
- Every aml.case references >= 1 aml.alert; every closed alert has a disposition and disposition timestamp; sar_filing references a case.
- KYC due diligence completed_at <= account open date; screening_result exists before account open.
- No posted transactions on accounts closed > 30 days (violations exist but are flagged as exceptions).
- fact_account_balance_daily has exactly one row per open account per business date (no gaps, no duplicates).

## Controls and Reconciliations

| Control | Grain | Tolerance | Expected break rate |
| --- | --- | --- | --- |
| Account balance roll-forward (transactions -> balance) | account x business_date | $0.00 | 0.0005 |
| Subledger-to-GL tie-out | gl_account x legal_entity x business_date | $1.00 | 0.002 |
| Card processor settlement-to-posted transactions | settlement batch x day; drill to transaction | $0.01 per txn, $10 per batch | 0.003 of transactions |
| Payment hub-to-network settlement file totals | batch x day | $0.00 | 0.01 of batches (mostly timing) |
| Correspondent/nostro account reconciliation | account x day | $50 | 0.02 of account-days |
| Interest accrual recalculation | account x cycle | $0.05 | 0.005 |
| AML alert-to-case linkage completeness | alert | n/a (count) | 0.001 orphaned |
| Statement-to-ledger balance agreement | account x statement cycle | $0.00 | 0.0002 |
| Suspense account aging (zero by day 30) | suspense gl_account x month | $0 aged > 30 days | 0.10 of suspense accounts breach |
| Loan schedule vs servicing balance | loan x month | $0.10 | 0.004 (re-amortization timing) |

## Seasonality and Temporal Patterns

- Paydays: 1st, 15th, and biweekly Fridays drive 2-3x direct deposit volume; card spend peaks 1-3 days after.
- Weekday shape: card auths peak Friday-Saturday; batch payments peak Monday and day after holidays (catch-up); wires business days only.
- Intraday: card auths peak 12:00-13:00 and 17:00-20:00 local; wire cutoff cluster 15:00-17:00; EOD batch posts 22:00-02:00; AML alerts generate overnight.
- Monthly: loan payments cluster on 1st and 15th due dates; statement cycles spread across the month; delinquency snapshots at month-end.
- Month/quarter-end: manual journal spike days -2 to +5 of close; reconciliation break volume rises ~50% in close week; commercial payment value spikes at quarter-end.
- Annual: December card spend +30% with January trough; tax-season deposit inflows March-April; fraud attempt rate +20-40% in November-December.
- Dormancy sweeps and fee assessments run on fixed monthly batch dates, creating visible posting spikes.

## Controlled Imperfections

| Imperfection | Where it appears | Typical rate | Downstream symptom |
| --- | --- | --- | --- |
| duplicate_webhook | Duplicate payment messages from payment hub into payments.payment_event | 0.001 of instructions | Double-posted payments caught by settlement recon |
| late_arrival | Card/network settlement files arrive T+2 instead of T+1 | 0.02 of files | Recon timing breaks, restated daily card volume |
| restatement_reversal | Manual fee reversals and re-amortized loan schedules | 0.002 of fee postings; 0.01 of loans/year | Negative fee lines, schedule version churn |
| conflicting_source_values | Name/address mismatch between core banking and KYC system | 0.03 of customers | MDM match review queue, KYC remediation cases |
| stale_mapping | Legacy account IDs unmapped or expired in xref after core conversion | 0.01 of accounts | Orphaned transactions in warehouse, unknown-account bucket |
| missing_xref | Card merchant IDs missing from dim_merchant | 0.005 of merchants | "Unknown merchant" rows in card spend marts |
| orphan_fk | Posted transactions on accounts closed > 30 days | 0.0005 of transactions | Exception queue, suspense postings |
| out_of_order_events | Payment lifecycle CDC events land out of sequence | 0.004 of instructions | Status regressions in event history, invalid-transition DQ failures |
| duplicate_entity | Same person onboarded twice via different channels | 0.015 of parties | Split customer view, duplicate AML alerting |
| format_drift | Settlement and statement file layout changes without notice | 1-2 incidents/year | Parser failures, partial-day loads |
| typo | Manually keyed wire beneficiary names/account numbers | 0.003 of wires | Repair queue, returned wires |
| manual_override | Analyst overrides on fraud scores and AML alert dispositions | 0.01 of alerts/scores | Override audit log entries, model-vs-decision divergence |
| stale_mapping | Expired KYC documents not refreshed on review cycle | 0.04 of customers | Stale-document backlog, blocked account changes |
