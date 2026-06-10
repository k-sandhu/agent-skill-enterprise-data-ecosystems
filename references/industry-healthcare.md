# Industry: Healthcare

## Operating Context

- Covers ambulatory, hospital, clinic, payer-provider, and health-system operating models. For diagnostic labs, also load `industry-diagnostic-lab.md`.
- Mid-size regional health system anchor: 2 hospitals, 350-450 staffed beds, 25-40 ambulatory clinics, 250k-400k active patients (seen within 3 years), 18k-25k admissions/year, 70k-90k ED visits/year, 700k-1.0M ambulatory encounters/year.
- Money flows: services rendered -> charges -> coded claims -> payer adjudication -> remittance + patient responsibility. Gross charges are inflated list prices; net revenue is 30-45% of gross after contractual adjustments.
- Payer mix drives economics: government payers pay fixed/DRG rates, commercial payers pay negotiated rates, self-pay collects poorly (0.10-0.25 of billed).
- Key constraints: privacy regulation on PHI access (treatment/payment/operations purpose), claim coding standards (ICD-10-CM diagnoses, CPT/HCPCS procedures, DRG groupers, 837 claims, 835 remittances), timely filing limits (90-365 days by payer), prior authorization requirements.
- Revenue cycle KPIs that the data must support: clean claim rate, initial denial rate, DNFB (discharged-not-final-billed) days, AR days, cost-to-collect.

## Domains

patient, provider, scheduling, registration, encounter, clinical, orders, medication, lab, radiology, surgery, ADT, bed_management, coding, billing, claims, payer, denials, quality, privacy, care_management.

## Source Systems

| System | Role | System-of-record domains | Typical data quirks |
| --- | --- | --- | --- |
| EHR | Clinical documentation, orders, results | encounter, clinical, orders, medication | Free-text fields, amended notes, copy-forward documentation, late-signed encounters |
| Practice management system | Ambulatory scheduling, registration, professional billing | scheduling, registration (ambulatory) | Duplicate patient registrations, stale demographics, manual insurance entry |
| ADT / bed management system | Admissions, transfers, discharges, census | ADT, bed_management | Out-of-order event feeds, cancelled admits, retroactive bed corrections |
| Lab information system | Lab orders, specimens, results | lab | Amended/corrected results, mismatched patient IDs on specimens |
| Radiology system | Imaging orders, reads, reports | radiology | Addendum reports, unread study backlogs |
| Pharmacy system + eMAR | Medication orders, dispensing, administration | medication | Discontinued orders still showing active, barcode scan overrides |
| Patient accounting / billing platform | Charges, claims generation, AR | billing, claims (provider side) | Late charges, charge reversals, chargemaster drift |
| Claims clearinghouse | Claim scrubbing, 837 submission, status | claim transit status | Batch rejects, duplicate acknowledgments, edit-rule version churn |
| Payer portal / remittance feeds | 835 remits, eligibility (270/271), prior auth | payer adjudication outcomes | Adjustment code usage drift, partial remits, takebacks |
| Enterprise master patient index | Golden patient identity | patient (canonical) | Merge/unmerge events, low-confidence matches, overlay errors |
| Patient portal | Self-scheduling, messaging, payments | patient engagement events | Unverified proxy accounts, duplicate self-registrations |
| Quality reporting platform | Measure logic, registry submissions | quality | Measure version changes mid-year, late attribution updates |
| Identity provider | Workforce identity, access | security | Orphaned accounts after termination |
| Data warehouse | Integrated analytics | none (consumer) | Late-arriving facts, snapshot vs event-grain mixing |

## Core Tables

- `patient.patient`, `patient.patient_identifier`, `patient.coverage`, `patient.coverage_eligibility_check`, `patient.patient_merge`
- `provider.provider`, `provider.organization`, `provider.provider_location`, `provider.provider_schedule`
- `scheduling.appointment`, `scheduling.appointment_status_history`, `scheduling.appointment_slot`
- `adt.admission`, `adt.transfer`, `adt.discharge`, `adt.adt_event`, `bed_management.bed`, `bed_management.bed_assignment`
- `clinical.encounter`, `clinical.diagnosis`, `clinical.procedure`, `clinical.observation`, `clinical.note_metadata`
- `orders.order`, `orders.order_status_history`
- `medication.medication_order`, `medication.administration`
- `lab.order`, `lab.specimen`, `lab.result`
- `radiology.imaging_order`, `radiology.report`
- `coding.coding_record`, `coding.drg_assignment`, `coding.coder_worklist`
- `billing.charge`, `billing.charge_reversal`, `billing.encounter_account`, `billing.payment`, `billing.adjustment`
- `claims.claim`, `claims.claim_line`, `claims.claim_status_history`, `claims.remittance`, `claims.remittance_line`, `claims.denial`, `claims.resubmission`, `claims.prior_authorization`
- `payer.payer`, `payer.plan`, `payer.contract_rate`
- `privacy.sensitive_access_log`, `quality.measure_result`, `workflow.denial_review_case`

## Warehouse Facts and Dimensions

- `fact_encounter` — grain: one patient encounter (visit or stay).
- `fact_patient_movement` — grain: one ADT event (admit, transfer, discharge, bed change).
- `fact_order` — grain: one clinical order.
- `fact_medication_administration` — grain: one administration event (one dose given/held/refused).
- `fact_charge` — grain: one posted charge line (reversals as negative rows).
- `fact_claim_line` — grain: one claim line per submission version (resubmissions create new rows keyed to original claim).
- `fact_remittance_line` — grain: one remittance line (paid/adjusted/denied amounts per claim line per remit).
- `fact_denial` — grain: one denial event per claim line per adjudication.
- `fact_census` — grain: one occupied-bed snapshot per facility-unit-bed-midnight (semi-additive).
- `fact_quality_measure` — grain: one patient-measure-period.

Dimensions: patient, provider, facility, department, bed, encounter_type, diagnosis, procedure, drg, payer, plan, denial_reason, order_type, medication, date, time.

## Critical Dataflows

- Ambulatory visit: registration -> eligibility check -> appointment/check-in -> encounter -> orders/procedures -> charge capture -> coding -> claim -> remittance -> patient billing.
- Hospital stay: pre-admit/ED arrival -> admission -> bed assignment -> transfers -> orders -> medication administration -> discharge -> HIM coding -> DRG assignment -> claim -> remittance.
- ADT feed: ADT system events -> integration engine -> EHR/billing/warehouse subscribers -> census and movement facts.
- Denial management: 835 denial -> denial_review_case -> root-cause coding -> corrected resubmission or appeal -> overturned payment or write-off.
- Quality reporting: clinical observations + diagnoses + procedures -> measure logic -> numerator/denominator -> registry submission.
- Privacy monitoring: sensitive_access_log -> treatment-relationship check -> exception queue -> access review.

## State Machines

- Appointment: scheduled -> confirmed -> checked_in -> roomed -> visit_complete -> charges_posted. Branches: scheduled -> cancelled (0.12, lead time lognormal, median 3 days before visit) | no_show (0.08) | rescheduled (0.10, counts as new appointment). checked_in -> visit_complete (0.99, dwell 0.5-2 hours).
- Inpatient stay (ADT): pre_admit -> admitted -> [transferred x N, N ~ poisson lambda 0.8] -> discharged -> coded -> billed. Admission source: ED 0.65, direct 0.15, elective/surgical 0.20. LOS lognormal, median 3.4 days, p90 9 days. admitted -> admit_cancelled (0.005). discharged -> coded (1.0, lognormal, median 4 days, p90 9 days).
- Clinical order: ordered -> acknowledged -> in_progress -> completed -> verified. Branches: ordered -> cancelled (0.05, within 4 hours) | discontinued (0.08 for medication orders). completed -> verified (0.98, 0-24 hours).
- Claim lifecycle: charge_review -> coded -> claim_generated -> scrub_pass (0.88) | scrub_fail (0.12, rework lognormal, median 2 business days) -> submitted -> clearinghouse_accepted (0.985) | clearinghouse_rejected (0.015) -> payer_accepted (0.97) | front_end_rejected (0.03) -> adjudicated (government: 14-21 days; commercial: lognormal, median 28 days, p90 55 days) -> paid_full (0.80) | paid_partial (0.06) | denied (0.14).
- Denial follow-up: denied -> corrected_resubmission (0.45) | appealed (0.25) | written_off (0.30). Resubmission -> paid (0.65, 20-40 days) | denied_again (0.35). Appeal -> overturned (0.50, 30-60 days) | upheld (0.50). Net unrecovered denials ~0.02-0.03 of net revenue.
- Prior authorization: requested -> auto_approved (0.30, under 1 hour) | manual_review (0.70) -> approved (0.78, 1-5 business days) | denied (0.12) | pended_for_info (0.10, adds 3-7 business days).
- Coverage: active -> termed (plan year end or employment change) -> replaced | lapsed. January replacement spike; stale coverage on file 0.05 of visits.

## Volumetrics and Distributions

| Metric | Typical value or range | Distribution | Notes |
| --- | --- | --- | --- |
| Staffed beds | 350-450 | n/a | Two-hospital regional system anchor |
| Midnight bed occupancy | 0.78 | normal, sd 0.06 | Winter peaks to 0.90+ |
| Admissions per year | 18k-25k | poisson daily, lambda ~55 | ED-to-admit conversion 0.17 |
| ED visits per year | 70k-90k | poisson daily, lambda ~220 | Weekend and Monday heavy |
| Ambulatory encounters per active patient per year | 3.2 | lognormal, median 2, p90 8 | High utilizers are chronic/complex patients |
| Activity skew | top 10% of patients = ~65% of gross charges | pareto, alpha 1.2 | Also drives readmission and care-management cohorts |
| Orders per inpatient stay | median 80 | lognormal, p90 250 | Labs + meds + imaging + nursing orders |
| Orders per ambulatory encounter | 1.5 | poisson, lambda 1.5 | ~30% of visits have zero orders |
| Medication administrations per inpatient day | 9-12 | poisson, lambda 10 | Held/refused doses 0.03 |
| Diagnoses per inpatient claim | mean 9, max 25 | lognormal, median 8 | Ambulatory claims: 1-4 diagnoses |
| Claim lines per claim | professional 2.4, institutional 15 | lognormal | Institutional p90 ~40 lines |
| Claims per patient per year | 8 | lognormal, median 5 | Counts professional + institutional |
| Gross charge per ambulatory visit | $250-450 | lognormal, median $320 | Net collected ~0.35 of gross |
| Gross charge per inpatient stay | median $42k | lognormal, p90 $110k | Net payment median $13k; DRG outliers in tail |
| Payer mix (by encounter) | Medicare 0.40, Medicaid 0.15, commercial 0.35, self-pay 0.05, other 0.05 | weighted choice | Commercial share higher in ambulatory, lower in ED |
| E/M office code mix | 99211 0.02, 99212 0.10, 99213 0.38, 99214 0.40, 99215 0.10 | weighted choice | 99214 share drifting upward ~1 pt/year |
| Denial reason mix (share of denials) | eligibility 0.25, prior auth 0.20, coding 0.20, medical necessity 0.15, timely filing 0.05, other 0.15 | weighted choice | Eligibility denials spike Jan-Feb |
| DNFB days | 5 | lognormal, median 4, p90 10 | Coding backlog metric |
| AR days (net) | 42 | normal, sd 5 | By payer: government ~30, commercial ~48, self-pay ~90 |
| Primary care panel size | 1,800 patients per provider | normal, sd 300 | Specialists tracked by referral volume instead |

## Business Rules and Invariants

- `discharge_at >= admit_at`; every transfer timestamp within [admit_at, discharge_at]; transfer N+1 time >= transfer N time.
- Bed assignment intervals are non-overlapping per bed; census = count of open bed assignments at snapshot time.
- Every coded encounter has >= 1 diagnosis; inpatient coded encounters have exactly one principal diagnosis and one final DRG.
- Charge `service_date` falls within the encounter date range; late charges flagged when posted > 3 days after discharge.
- Claim total billed = sum of claim line billed amounts; per remittance line: paid + contractual adjustment + patient responsibility + denied amount = billed amount.
- Claim submitted only after coding_record status = complete; claim service dates within coverage effective dates of the billed plan.
- Resubmission rows reference the original claim_id; claim_status_history transitions follow the claim state machine (no paid -> submitted).
- Medication administration requires an active medication order at administration time; admin time within order start/stop window.
- Lab result only after specimen accessioned; specimen only after order; amended result references original result_id.
- At most one active primary coverage per patient per service date; merged MRNs are inactive and point to a surviving patient_id.
- Sum of payments + adjustments per encounter_account never exceeds gross charges; account balance roll-forward holds per account per day.
- Quality measure numerator <= denominator per patient-measure-period.
- Sensitive record access maps to a treatment relationship, billing role, or documented break-glass reason.

## Controls and Reconciliations

| Control | Grain | Tolerance | Expected break rate |
| --- | --- | --- | --- |
| Encounter charges tie to claim lines | encounter_account | $0.01 | 0.01 |
| Claim billed ties to remittance disposition | claim line | $0.01 | 0.02 |
| Medication orders tie to administrations (MAR check) | order-day | 0 missed doses unexplained | 0.01 |
| ADT bed occupancy ties to capacity/census report | facility-unit-midnight | 0 beds | 0.005 |
| Clearinghouse submitted count ties to payer acknowledgments | submission batch | 0 claims | 0.01 |
| Cash posted ties to bank deposits | deposit-day | $50 | 0.01 |
| Patient accounting revenue ties to GL | facility-month | $500 | 0.05 |
| Sensitive record access ties to permitted treatment/payment/operations purpose | access event | n/a | 0.002 |
| EMPI active patients tie to source registrations (no orphan MRNs) | patient | 0 | 0.003 |
| Quality registry submission counts tie to internal measure results | measure-period | 0 patients | 0.02 |

## Seasonality and Temporal Patterns

- Weekday shape: ambulatory volume peaks Monday (index ~1.15), tapers Friday (~0.90), near zero weekends; ED runs 7 days with Saturday/Sunday/Monday peaks.
- Intraday: ambulatory check-ins bimodal 9-11am and 1-3pm; ED arrivals ramp 10am-10pm; discharge orders cluster 11am-2pm; med administrations cluster at standard times (06:00, 09:00, 12:00, 18:00, 21:00).
- Winter respiratory season: ED visits and medical admissions +15-25% Dec-Feb; occupancy pressure and boarding increase.
- Elective procedures dip in mid-summer and late December; deductible-met surge lifts elective volume +10-15% in Nov-Dec.
- January effect: coverage churn spikes eligibility denials +20-30% in Jan-Feb; new-deductible self-pay balances rise.
- Revenue cycle rhythm: month-end billing push (claim submissions +20% in last 3 business days); fiscal year-end coding cleanup compresses DNFB.
- Payer behavior: government remits arrive on a steady ~weekly cycle; commercial remits lumpy with end-of-month batches.

## Controlled Imperfections

| Imperfection | Where it appears | Typical rate | Downstream symptom |
| --- | --- | --- | --- |
| duplicate_entity | Duplicate patient registrations / duplicate MRNs pending merge | 0.015 of patients | Split clinical history, double-counted encounters until EMPI merge |
| duplicate_entity | Merge artifacts: merged MRNs with records still pointing at retired ID | 0.003 of patients | Orphaned encounters in patient-level rollups |
| missing_xref | Payer member ID not mapped to coverage record | 0.01 of coverages | Eligibility check failures, front-end claim rejects |
| orphan_fk | Charges referencing cancelled or voided encounters | 0.003 of charges | Charge-to-claim reconciliation breaks |
| late_arrival | Late charges posted > 3 days after discharge | 0.04 of charges | Rebills, restated daily revenue |
| late_arrival | ADT feed messages delayed > 1 hour | 0.01 of events | Census snapshot vs event-log mismatch |
| conflicting_source_values | Patient DOB/sex differs between EHR and practice management | 0.005 of patients | EMPI low-confidence matches, claim demographic rejects |
| stale_mapping | Retired chargemaster or CPT code still mapped in interfaces | 0.002 of charge lines | Scrub failures, coding denials |
| stale_mapping | Expired insurance coverage on file used at registration | 0.05 of visits | Eligibility denials, reworked claims |
| restatement_reversal | Amended/corrected lab results | 0.005 of results | Result versioning, quality measure recalculation |
| restatement_reversal | Charge reversals and corrected claim resubmissions | 0.01 of charges | Negative fact rows, AR restatements |
| out_of_order_events | ADT transfer/discharge arrives before admit in feed | 0.002 of events | Movement fact sequencing errors, negative LOS until repair |
| duplicate_webhook | Duplicate 835 remittance file postings | 0.001 of remits | Double-posted payments until dedup |
| manual_override | Registration bypasses failed insurance verification | 0.02 of registrations | Downstream eligibility denials traced to override flag |
| manual_override | Break-glass access to restricted records | 0.001 of accesses | Privacy review queue entries |
| format_drift | Payer remittance adjustment-code usage shifts by quarter | 1-2 payers per quarter | Denial-reason trend discontinuities |
| typo | Free-text allergy and medication entries | 0.01 of entries | Failed exact-match joins to medication dimension |
| typo | Invalid diagnosis/procedure code combinations from manual coding | 0.004 of claims | Coding denials, edit-queue rework |
| out_of_order_events | Emergency transfers documented after the fact | 0.005 of transfers | Bed assignment overlap exceptions |
| late_arrival | Cancelled appointments and no-shows backfilled next day | 0.03 of status updates | Intraday schedule-utilization misstatement |
