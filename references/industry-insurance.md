# Industry: Insurance Carrier (P&C and Life)

## Operating Context

- Mid-size regional carrier writing personal auto, homeowners, and commercial package (P&C) plus term/whole life (Life); ~700k P&C policies in force, ~220k life policies, ~$1.1B direct written premium, 12 states.
- Money in: premium installments (direct bill) and agency-billed premium; money out: claim payments, commissions (~12-15% of premium), operating expense, reinsurance premium; investment income on reserves offsets underwriting results.
- Distribution through ~2,000 appointed independent agencies plus a small direct digital channel; producers must hold active state licenses and appointments.
- Regulated per state: rate/form filings, market conduct exams, statutory accounting with annual statement by line, risk-based capital, unclaimed property for life benefits.
- Economics tracked as loss ratio + expense ratio = combined ratio; reserve development (favorable/adverse) restates prior accident years.
- Reinsurance program: quota share on commercial lines, per-risk excess of loss on property, catastrophe excess-of-loss treaty with annual reinstatement.

## Domains

party, product, policy, underwriting, rating, billing, payments, claims, reserves, reinsurance, distribution, actuarial, finance, compliance, fraud_siu, customer_service.

## Source Systems

| System | Role | System-of-record domains | Typical data quirks |
| --- | --- | --- | --- |
| P&C policy administration platform | Quote, bind, issue, endorse, cancel, renew | policy, coverage, endorsement | Term-effective versioning; out-of-sequence endorsements; legacy policy number formats from converted book |
| Life policy administration platform | Life policy lifecycle, cash values, riders | life policy, rider, beneficiary | Monthiversary batch processing; converted legacy blocks missing rider detail |
| Rating engine | Filed rates, factors, premium calculation | rate versions, rating worksheets | Rate version drift vs filed rates; re-rate deltas at renewal |
| Underwriting workbench | Submission triage, referrals, decisions | submission, underwriting decision | Free-text notes; manual overrides of system declines |
| Billing system | Invoicing, installment plans, dunning, refunds | billing account, invoice, payment plan | Equity dates vs due dates diverge; NSF reversals; policy-to-billing-account link breaks |
| Claims platform (P&C) | FNOL through settlement and recovery | claim, claim feature, reserve, claim payment | Reopened claims; feature-level vs claim-level reserve confusion; coverage mismatch at FNOL |
| Life claims and benefits system | Death, maturity, surrender benefits | life claim, beneficiary payout | Contestability review flags; multi-beneficiary allocation disputes |
| Reinsurance administration system | Treaties, cessions, recoverables, bordereaux | treaty, cession, recoverable | Late inbound/outbound bordereaux; manual treaty attachment corrections |
| Agency and commission system | Producer management, commission statements | agency, producer, appointment, commission | Terminated producers still mapped to policies; commission clawbacks |
| Payment gateway | Card/ACH premium collection | payment authorization | Duplicate webhook postings; settlement file lag |
| Actuarial reserving system | Triangles, IBNR studies, reserve booking | reserve study | Quarterly snapshots only; restated triangles after data fixes |
| General ledger | Statutory and GAAP books | journal entry, GL balance | Dual-basis books; premium and loss suspense accounts |
| CRM / contact center | Service interactions, complaints | service case | Duplicate party records; channel mislabeling |
| Data warehouse | Analytics and reporting | n/a | Conformed but T+1; claim snapshots only month-end before 2-year history |

## Core Tables

- `party.party`, `party.person`, `party.organization`, `party.address`, `party.relationship`
- `product.product`, `product.line_of_business`, `product.coverage_form`, `product.rate_version`
- `policy.policy`, `policy.policy_term`, `policy.coverage`, `policy.insured_object`, `policy.endorsement`, `policy.policy_status_history`
- `underwriting.submission`, `underwriting.quote`, `underwriting.referral`, `underwriting.decision`
- `billing.billing_account`, `billing.invoice`, `billing.installment`, `billing.payment`, `billing.payment_application`, `billing.dunning_event`, `billing.refund`
- `claims.claim`, `claims.claim_feature`, `claims.reserve_transaction`, `claims.claim_payment`, `claims.recovery`, `claims.litigation`, `claims.claim_note`
- `reserves.reserve_snapshot`, `reserves.ibnr_study`, `reserves.development_triangle_cell`
- `reinsurance.treaty`, `reinsurance.treaty_layer`, `reinsurance.cession`, `reinsurance.recoverable`, `reinsurance.bordereau_line`
- `distribution.agency`, `distribution.producer`, `distribution.appointment`, `distribution.commission_statement`, `distribution.commission_line`
- `life.life_policy_value`, `life.rider`, `life.beneficiary_designation`, `life.surrender_transaction`
- `fraud.siu_referral`, `fraud.siu_case`
- `finance.journal_entry`, `finance.gl_balance`, `finance.statutory_line_mapping`
- `workflow.case`, `document.document`

## Warehouse Facts and Dimensions

- `fact_policy_term`: one row per policy-term; written premium, commission, term dates.
- `fact_premium_transaction`: one row per premium accounting transaction (new business, endorsement, cancellation, audit) per policy-coverage.
- `fact_premium_earned_monthly`: one row per policy-coverage-month; earned and unearned movement.
- `fact_billing_transaction`: one row per billing event (invoice, payment, application, NSF, refund, write-off).
- `fact_claim_transaction`: one row per claim financial transaction (reserve change, payment, recovery) per claim feature.
- `fact_claim_feature_snapshot_monthly`: one row per claim feature per month-end; paid-to-date, case reserve, incurred.
- `fact_cession`: one row per ceded premium/loss transaction per treaty layer.
- `fact_commission_line`: one row per commission line per policy-term-producer.
- `fact_reserve_development`: one row per accident_year x line_of_business x development_age cell.
- `fact_life_policy_value_monthly`: one row per life policy per month; cash value, face amount, premium due/paid.

Dimensions: policy, product, line_of_business, coverage, insured_party, agency, producer, claim, claimant, peril, catastrophe_event, treaty, state, channel, accident_date, date.

## Critical Dataflows

- Quote-to-issue: submission -> rating -> underwriting review -> bind -> policy issue -> commission setup -> billing schedule creation.
- Premium accounting: written premium transaction -> earning schedule -> monthly earned/unearned -> GL -> statutory exhibit.
- Billing-to-cash: invoice -> payment gateway -> payment application -> NSF/dunning -> cancellation pending -> cancel for nonpay or reinstatement.
- Claims lifecycle: FNOL -> coverage verification -> feature setup -> initial reserve -> investigation -> payments -> salvage/subrogation recovery -> close (and possible reopen).
- Reserving: claim transactions -> month-end snapshots -> development triangles -> IBNR study -> booked reserves -> GL.
- Reinsurance: gross premium/loss transactions -> treaty attachment -> cession calculation -> bordereau -> recoverable billing -> cash settlement.
- Renewal: term expiry watch -> re-rate -> renewal offer -> accept/decline -> renewed term or lapse.
- SIU: claim red-flag scoring -> SIU referral -> investigation -> outcome (claim adjusted, denied, or cleared).

## State Machines

- P&C policy: submitted -> quoted (0.85, uniform 0-2 business days) | declined (0.15); quoted -> bound (0.45, lognormal median 3 days, p90 14 days) | lost (0.55); bound -> in_force (1.0, 0-5 days); in_force at term end -> renewed (0.84) | lapsed (0.13) | nonrenewed_by_carrier (0.03); midterm hazard per term: cancelled_nonpay (0.04) | cancelled_insured_request (0.03); cancelled_nonpay -> reinstated (0.35, within 30 days).
- P&C claim: fnol_received -> open (1.0, 0-1 business day) -> closed_paid (0.72, lognormal median 18 days, p90 120 days) | closed_no_payment (0.22, lognormal median 10 days, p90 45 days) | denied (0.06, median 25 days); open -> litigation branch (0.04, dwell lognormal median 14 months); closed -> reopened (0.06, mostly within 90 days of close).
- Injury (bodily injury / liability) features: same chain but dwell lognormal median 7 months, p90 26 months.
- Invoice: issued -> paid (0.93, lognormal median 12 days) | past_due (0.07, at due date + 5 grace days); past_due -> paid_after_dunning (0.60, median 15 days) | cancellation_pending (0.40) -> cancelled_nonpay.
- Life policy: applied -> underwriting (1.0) -> issued (0.75, lognormal median 18 days, p90 50 days) | declined (0.08) | withdrawn (0.17); in_force annual hazards: lapsed (0.06) | surrendered (0.03) | death_claim (0.008); death_claim -> paid (0.93, lognormal median 12 days after proof of death) | contestability_review (0.07, median 60 days).
- Reinsurance recoverable: ceded_calculated -> billed (monthly/quarterly batch) -> collected (0.97, lognormal median 45 days, p90 100 days) | disputed (0.03, median 90 days to resolve).

## Volumetrics and Distributions

| Metric | Typical value or range | Distribution | Notes |
| --- | --- | --- | --- |
| P&C policies in force | ~700k (auto 420k, home 230k, commercial 50k) | n/a | Cardinality anchor |
| Life policies in force | ~220k | n/a | Term 70%, whole life 30% |
| Policies per household party | mean 1.6, max ~6 | weighted choice (1:0.55, 2:0.30, 3+:0.15) | Auto+home bundle common |
| Personal auto annual premium | median 1,400; p99 6,000 | lognormal | Per policy, 1-3 vehicles |
| Homeowners annual premium | median 1,600; p99 8,000 | lognormal | Coastal/cat zones in tail |
| Commercial package annual premium | median 9,000; p99 150,000 | lognormal, heavy tail | Few large accounts dominate |
| Claim frequency: personal auto | 0.055 claims per earned vehicle-year | poisson | All coverages combined |
| Claim frequency: homeowners | 0.045 claims per policy-year | poisson | Spikes 3-8x during cat events |
| Claim frequency: commercial | 0.12 claims per policy-year | poisson | Liability + property |
| Severity: auto physical damage | median 4,200; p99 60,000 | lognormal | Total losses in tail |
| Severity: bodily injury liability | median 18,000; p99 750,000 | lognormal body, pareto tail (alpha 1.8) | Litigation drives tail |
| Severity: homeowners property | median 9,000; p99 250,000 | lognormal | Fire/total losses in tail |
| Features per claim | mean 1.6 | poisson (lambda 0.6) + 1 | Multi-coverage, multi-claimant |
| Loss ratio by line | auto 0.68, home 0.62, commercial 0.58, life mortality A/E ~0.95 | normal around target, sd 0.05 | Home volatile with cats |
| Ceded written premium | 0.12 of direct written | n/a | Quota share + XOL + cat |
| Agency premium concentration | top 10% of agencies = ~55% of premium | zipf (s=1.1) | ~2,000 agencies |
| Payment plan mix | full-pay 0.35, semi-annual 0.10, quarterly 0.15, monthly 0.40 | weighted choice | Monthly skews younger insureds |
| Life face amount | median 250,000; p99 2,000,000 | lognormal | Term skews higher face |
| Catastrophe events per year | 3-6 | poisson (lambda 4) | Each adds 500-8,000 claims over 2-6 weeks |
| Claims per adjuster caseload | 80-140 open features | normal | Spikes post-cat drive backlog |

## Business Rules and Invariants

- earned_premium + unearned_premium = written_premium, cumulatively per policy-coverage-term.
- incurred = paid_to_date + case_reserve at claim feature grain; IBNR exists only at accident_year x line aggregate, never per claim.
- sum of reserve_transactions per feature = current case reserve; case reserve >= 0.
- claim feature paid_to_date <= coverage limit unless extra_contractual_flag = true.
- loss_date within policy term effective dates for occurrence-basis covered claims; loss_date <= reported_at <= closed_at.
- cumulative paid in triangle cells is non-decreasing across development ages, except flagged salvage/subrogation recoveries.
- ceded_amount <= gross_amount per transaction; each cession attaches to exactly one treaty layer per layer period.
- invoice total = sum of installment premium + fees - credits; sum of payment_applications per payment <= payment amount.
- billing account receivable roll-forward holds per account per day: opening + invoiced - payments - write-offs + reversals = closing.
- commission_line amount = commission_rate x written_premium per line; full clawback on flat cancellation.
- policy_status_history transitions follow the state machine; cancellation effective_date >= notice_date + state-mandated notice days.
- every claim references an in-force policy term and an existing coverage as of loss_date (violations only via controlled imperfections).
- life surrender payout = cash value - surrender charge; death benefit <= face amount + paid-up additions.
- reinsurance recoverable balance = ceded incurred - collected - written-off, per treaty.
- statutory line totals = GL balances per legal entity per period.

## Controls and Reconciliations

| Control | Grain | Tolerance | Expected break rate |
| --- | --- | --- | --- |
| Written premium: policy admin to GL | legal entity-line-month | 500 | 0.02 |
| Earned premium recalculation vs booked | policy-term-month | 1 | 0.005 |
| Billing receivable roll-forward | billing account-day | 0.01 | 0.01 |
| Cash applied: gateway settlement to billing | settlement file-day | 0.01 | 0.008 |
| Claims paid: claims platform to GL | legal entity-line-month | 100 | 0.015 |
| Case reserve snapshot vs transaction sum | claim feature-month | 0.01 | 0.003 |
| Ceded premium/loss to treaty bordereau | treaty-quarter | 1,000 | 0.04 |
| Reinsurance recoverable aging (>90 days flag) | treaty-quarter | n/a | 0.05 |
| Commission statements to policy premium | producer-month | 50 | 0.02 |
| Policy count: admin vs warehouse | line-day | 0 | 0.01 |
| Life cash value roll-forward | policy-month | 0.05 | 0.005 |
| Claim-to-policy coverage existence | claim-day | 0 | 0.003 |

## Seasonality and Temporal Patterns

- FNOL weekday shape: Monday peak (weekend losses reported late), ~1.4x daily average; weekend reporting trough.
- Auto FNOL intraday: morning and evening commute peaks; home claims cluster after storms regardless of hour.
- Property cat seasonality: winter freeze spikes (Q1), hail season (Q2), hurricane season (Q3); each cat event drives a 2-6 week claim surge with late-reported tail.
- New business and renewals cluster on the 1st of month and month-end effective dates.
- Installment due dates cluster on the 1st and 15th; payment posting peaks 0-3 days after due date.
- Quarter-end: reserve study, IBNR booking, and reinsurance bordereau spikes; year-end annual statutory statement crunch in January-February.
- Life applications spike Q1 and Q4; lapses cluster at premium anniversary dates.
- Nonpay cancellations peak mid-month following the 1st-of-month due date cohort.

## Controlled Imperfections

| Imperfection | Where it appears | Typical rate | Downstream symptom |
| --- | --- | --- | --- |
| missing_xref | Legacy policy number not mapped to billing account | 0.01 of converted policies | Unapplied cash in premium suspense |
| orphan_fk | Claim feature references coverage removed by out-of-sequence endorsement | 0.003 of claims | Coverage verification workflow queue |
| duplicate_entity | Same insured party in CRM and policy admin with name variants | 0.02 of parties | Inflated customer counts; bundle discounts missed |
| late_arrival | Cat-event FNOLs reported 5-20 days after loss date | 0.10 of cat claims | Frequency understated near event date; IBNR strain |
| conflicting_source_values | Insured address differs between CRM and policy admin | 0.04 of parties | Misrated territory; returned mail cases |
| restatement_reversal | Reserve takedown reversed and re-booked after actuarial review | 2-4 per quarter per line | Triangle cells restated; development distorted |
| out_of_order_events | Endorsement processed after cancellation already booked | 0.002 of endorsements | Negative unearned premium; manual correction case |
| duplicate_webhook | Payment gateway posts the same payment twice | 0.001 of payments | Overstated cash until reversal; refund workflow |
| stale_mapping | Terminated producer still mapped to renewing policies | 0.005 of renewals | Commission paid to wrong producer; clawback |
| manual_override | Underwriter overrides system decline or rate | 0.03 of declines | Decision and rating worksheet disagree |
| format_drift | Inbound reinsurance bordereau column layout changes | 2-3 files per year | Cession load failures; recoverable lag |
| typo | VIN or property address keyed wrong at quote | 0.01 of insured objects | Mismatch vs third-party data; re-rate at renewal |
