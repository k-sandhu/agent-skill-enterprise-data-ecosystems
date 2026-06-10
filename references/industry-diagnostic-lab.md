# Industry: Diagnostic Laboratory

## Operating Context

- Regional diagnostic laboratory network: patient service centres (PSCs), at-home kit program, and clinic/hospital outreach feeding 2-4 core labs plus an esoteric send-out desk.
- Scale anchors: 40-80 PSCs, 8k-15k requisitions/day, 1.5M-3M unique patients/year, 300-600 orderable tests in catalog, 60-120 analyzers.
- Money flows: payer claims (~70-80% of revenue) at payer-contracted rates, client-bill contracts with clinics/hospitals, patient self-pay remainder; revenue recognized at result delivery, cash lags via remittance.
- Demand is referral-driven by ordering providers; lab controls fulfillment (collection, logistics, testing, delivery) but not order volume.
- Regulated under clinical lab accreditation regimes: QC documentation, proficiency testing, personnel competency, critical-value notification SLAs, result retention, and health-privacy law.
- Margin levers: autoverification rate, courier route density, denial recovery rate, reagent cost per reportable result.

## Domains

patient, provider, clinic, scheduling, requisition, order, specimen, accession, test_catalog, lab_instrument, result, critical_value, result_delivery, courier, kit, inventory, claims, payer, privacy, quality.

## Source Systems

| System | Role | System-of-record domains | Typical data quirks |
| --- | --- | --- | --- |
| Patient service centre scheduling | PSC appointments, walk-in queueing, wait times | scheduling | walk-ins back-filled as appointments; wait-time sampling gaps overnight |
| EMR integration gateway | Inbound electronic orders, outbound result delivery to EMRs | requisition (electronic channel) | per-clinic interface dialects; format_drift on clinic upgrades; free-text diagnosis codes |
| Laboratory information system | Order, specimen, result lifecycle; test catalog | order, specimen, result, test_catalog | test codes versioned; some extracts overwrite amended results in place |
| Accessioning system | Specimen receipt, labeling, rejection capture | accession | duplicate accession scans; manual-entry typos from paper requisitions |
| Analyzer/instrument middleware | Analyzer connectivity, autoverification, QC capture | lab_instrument, raw results, QC | clock skew vs LIS; reruns surface as duplicate raw results |
| Courier logistics platform | Routes, stops, chain of custody, temperature logs | courier | missed pickup scans; temperature logger gaps on rural routes |
| Patient/provider portal | Result viewing, kit ordering, delivery receipts | result_delivery (portal channel), kit | delivery confirmation only for portal channel; fax confirmations unreliable |
| Billing/claims platform | Charge capture, claim scrubbing, AR | billing, claims | charge-to-order lag; payer code mappings maintained manually |
| Payer portal / clearinghouse | Eligibility, claim status, electronic remittance files | payer responses, remittance | remits arrive 14-45 days late; partial payments split across files |
| Quality management system | Nonconformance, CAPA, proficiency testing | quality | free-text root causes; closure dates backdated |
| Privacy/audit platform | Sensitive access logging, break-glass events | privacy | purpose codes missing on legacy app events |
| Inventory system | Reagents, kits, collection supplies, lots | inventory | lot/expiry keyed manually; negative on-hand from missed receipts |
| Data warehouse | Analytics, regulatory and SLA reporting | none (consumer) | late-arriving claims restate revenue marts |

## Core Tables

- `patient.patient`, `patient.identifier`, `patient.consent`
- `provider.provider`, `provider.clinic`, `provider.emr_connection`
- `payer.payer`, `payer.payer_contract`, `billing.fee_schedule`
- `scheduling.appointment`, `scheduling.site_wait_time`
- `orders.requisition`, `orders.lab_order`, `orders.order_status_history`
- `specimen.specimen`, `specimen.collection_event`, `specimen.accession`, `specimen.rejection`
- `lab.test_panel`, `lab.test_component`, `lab.instrument`, `lab.instrument_qc`, `lab.qc_rule_violation`
- `result.result_component`, `result.result_status_history`, `result.result_amendment`, `result.critical_value_notification`, `result.delivery_event`
- `courier.route`, `courier.pickup_event`, `courier.temperature_log`
- `kit.kit`, `kit.kit_shipment`, `kit.kit_return`
- `billing.charge`, `claims.claim`, `claims.claim_line`, `claims.denial`, `claims.appeal`, `claims.remittance`
- `inventory.reagent_lot`, `inventory.supply_consumption`
- `quality.nonconformance`, `quality.proficiency_event`, `quality.capa`
- `privacy.sensitive_access_log`

## Warehouse Facts and Dimensions

- `fact_lab_order`: grain = one orderable test per requisition.
- `fact_specimen_event`: grain = one specimen lifecycle event (collection, pickup, receipt, accession, rejection, storage, disposal).
- `fact_result_component`: grain = one verified result component per specimen per test component; amendments append versioned rows.
- `fact_turnaround_time`: grain = one SLA measurement per order per TAT segment (collection-to-receipt, receipt-to-verified, verified-to-delivered).
- `fact_critical_value_notification`: grain = one notification attempt per critical result.
- `fact_qc_run`: grain = one QC measurement per instrument per analyte per control level per run.
- `fact_claim_line`: grain = one billed claim line (one billing code per claim per service date).
- `fact_remittance_line`: grain = one payer remittance line per claim line per remittance file.
- `fact_courier_stop`: grain = one courier stop per route per day.

Dimensions: patient, provider, clinic/site, test, specimen_type, instrument, courier_route, payer, kit_type, rejection_reason, denial_reason, date, time, result_status.

## Critical Dataflows

- Order-to-result: EMR/requisition -> order -> specimen collection -> courier pickup -> accession -> instrument run -> result validation -> provider/patient delivery -> billing.
- Critical value: result validation -> critical flag -> provider notification -> acknowledgement -> compliance reporting.
- At-home kit: kit shipped -> sample collected -> courier/mail receipt -> accession -> result -> billing.
- Claims cycle: charge capture -> claim scrub -> clearinghouse submission -> payer adjudication -> remittance posting -> denial workqueue -> appeal -> recovery or write-off.
- QC gate: QC run -> rule evaluation -> pass (autoverification enabled) | fail -> instrument hold -> investigation -> recalibration -> patient reruns -> release.
- Amendment: amended result -> link to original -> re-delivery to provider -> warehouse restatement.

## State Machines

- Lab order: ordered -> specimen_collected (0.93; lognormal, median 1 day, p90 8 days) | cancelled_uncollected (0.07). specimen_collected -> accessioned (0.99) -> in_process -> resulted -> verified (autoverified 0.80 near-instant; manual review 0.20, lognormal, median 2h, p90 8h) -> delivered -> claim_submitted.
- Specimen: collected -> picked_up (lognormal, median 3h, p90 7h) -> received_at_lab (median 2h transit) -> accessioned (median 0.5h) -> testing (0.988) | rejected (0.012). rejected -> recollection_ordered (0.70) | order_cancelled (0.30).
- Critical value: flagged -> notification_attempted (median 12 min) -> acknowledged (0.97; lognormal, median 18 min from flag, p90 28 min) | escalated (0.03) -> acknowledged (median 50 min from flag).
- Claim line: submitted -> clearinghouse_accepted (0.97) | front_end_rejected (0.03, resubmitted within 1-3 business days). accepted -> paid (0.86; lognormal, median 21 days, p90 45 days) | denied (0.14). denied -> appealed (0.55; submitted median 14 days) | written_off (0.45). appealed -> overturned_paid (0.60; median 30 days) | upheld_written_off (0.40).
- QC run: scheduled -> run -> pass (0.975) | rule_violation (0.025). rule_violation -> repeat_pass (0.60, within 1h) | investigation (0.40; lognormal, median 4h, p90 24h) -> recalibrated -> rerun_pass.
- At-home kit: kit_shipped -> delivered (0.97; median 3 days) | lost_in_transit (0.03). delivered -> sample_returned (0.62; lognormal, median 9 days, p90 30 days) | never_returned (0.38). returned -> accessioned -> testing (0.96) | rejected (0.04, higher than PSC).

## Volumetrics and Distributions

| Metric | Typical value or range | Distribution | Notes |
| --- | --- | --- | --- |
| Requisitions per day (network) | 8,000-15,000 | poisson around weekday mean | weekday shape in Seasonality |
| Orderable tests per requisition | median 3, p90 8, max ~25 | lognormal | requisition:test ratio ~1:3.4 |
| Result components per orderable test | mean 4.5 | weighted choice by panel | CBC ~10 components, metabolic panel ~14, single analyte 1 |
| Requisitions per patient per year | mean 2.8 | zipf s=1.2 over patients | chronic-monitoring patients form the tail |
| Provider ordering skew | top 10% of providers = ~55% of requisitions | zipf s=1.1 | |
| Stat-priority share of orders | 0.06-0.10 | weighted choice | concentrated in hospital outreach |
| Specimen rejection rate (PSC/clinic) | 0.010-0.015 | weighted choice per specimen | at-home kit specimens 0.04 |
| Rejection reason mix | hemolysis 0.45, insufficient quantity 0.20, mislabeled 0.10, clotted 0.10, wrong container 0.08, expired transport 0.07 | weighted choice | |
| Collection-to-receipt TAT | median 5h, p90 10h | lognormal | courier route dependent |
| Receipt-to-verified TAT (routine) | median 6h, p90 20h | lognormal | esoteric send-outs 3-14 days |
| Receipt-to-verified TAT (stat) | median 0.8h, p90 1.8h | lognormal | SLA 2h |
| Autoverification rate | 0.75-0.85 | weighted choice per component | delta/flag failures route to manual review |
| Critical-result rate | 0.004-0.008 of verified components | weighted choice | ~2x higher on hospital outreach orders |
| QC runs per instrument per day | 2-6 | uniform | 2 control levels x 1-3 shifts |
| QC failure rate | 0.02-0.03 of QC runs | weighted choice | multirule violations |
| Amended-result rate | 0.002-0.004 of verified components | weighted choice | clerical and analytic corrections |
| Claim lines per requisition | mean 2.4 | lognormal | panel bundling rules reduce lines vs tests |
| Claim line billed amount | median $24, p90 $110, max ~$3,000 | lognormal | tail = genetic/esoteric tests |
| Initial claim denial rate | 0.12-0.16 of claim lines | weighted choice | medical necessity, missing diagnosis, eligibility |
| Payer concentration | top 3 payers = ~60% of billed amount | weighted choice | one government payer ~30% |

## Business Rules and Invariants

- Every verified result component ties to an accessioned specimen; no result rows for rejected specimens.
- Timestamp ordering per order: ordered_at <= collected_at <= picked_up_at <= received_at <= accessioned_at <= resulted_at <= verified_at <= delivered_at.
- Every critical result has a notification record; acknowledged_at within SLA or an escalation row exists.
- Result amendments link to the original result_id; the original row keeps status superseded, never deleted.
- Claims tie to delivered orders; every remittance line ties to exactly one claim line via claim control number.
- Per remittance line: paid_amount + contractual_adjustment + patient_responsibility = billed_amount.
- Claim line billed_amount matches the fee schedule effective on the service date for that payer contract.
- No verified result from an instrument run that occurred while the instrument was under QC hold.
- Specimens with temperature excursions have a nonconformance record before any affected result is released.
- Rejected specimens carry a rejection reason code from the controlled vocabulary.
- Kit accession requires a prior kit_shipment in delivered status.
- Reagent lot roll-forward per lot per day: opening + receipts - consumption - waste = closing.
- Sensitive access events have a permitted purpose code or a linked investigation case.

## Controls and Reconciliations

| Control | Grain | Tolerance | Expected break rate |
| --- | --- | --- | --- |
| Specimen-to-result completeness | order line per day | 0 unresulted after 72h (non-send-out) | 0.003 |
| Order-to-charge capture | requisition per day | 0 uncharged after 5 business days | 0.008 |
| Claim-to-remittance match | claim line | exact match on claim control number | 0.01 |
| Billed vs contracted rate | claim line | $0.01 | 0.02 (stale fee schedules) |
| Critical-notification SLA | notification | 30 min flag-to-acknowledgement | 0.03 |
| Instrument-to-LIS result count | instrument per shift | 0 | 0.005 (middleware drops) |
| Courier manifest vs accessioned specimens | route per day | 0 unmatched after 24h | 0.004 |
| QC documentation completeness | instrument-analyte per day | 0 missing scheduled runs | 0.01 |
| Revenue mart vs billing ledger | payer per day | 0.5% | 0.02 (late remittance files) |
| Amendment linkage | amendment | 0 orphans | 0.002 |
| Patient duplicate-record rate | patient master | < 0.5% active duplicates | steady-state 0.004 |

## Seasonality and Temporal Patterns

- Weekday shape: Monday peak ~1.25x weekday mean (weekend backlog), tapering to Friday ~0.95x; Saturday ~0.45x, Sunday ~0.15x (stat and hospital work only).
- January and Nov-Dec routine volume +8-12% (annual physicals, deductible-met effect); July-August dip ~-8%.
- Respiratory season (Dec-Feb) lifts infectious-disease panels 1.5-2.5x baseline.
- Intraday collections: fasting-draw peak 7-10 am (~45% of PSC volume); accessioning peaks 11 am-3 pm and again 8-11 pm as evening courier routes land; verification follows with a 2-6h lag.
- Claims submitted in nightly batches; remittances cluster on weekly payer payment cycles; month-end spike in write-offs and re-bills.
- Quarter-end: proficiency-testing events and fiscal-close restatement of revenue accruals from open denials.

## Controlled Imperfections

| Imperfection | Where it appears | Typical rate | Downstream symptom |
| --- | --- | --- | --- |
| duplicate_entity | duplicate patients across registration channels (PSC, portal, EMR feeds) | 0.004 of active patients | split result history; MDM merge queue cases |
| missing_xref | missing provider identifiers on paper/fax requisitions | 0.03 of requisitions | claims held for provider enrollment; denial risk |
| late_arrival | late courier pickups and delayed receipt manifests | 0.05 of stops > 1h late | TAT SLA misses; stability-based specimen rejections |
| late_arrival | delayed result delivery on fax/print channels | 0.01 of deliveries > 24h | provider callbacks; duplicate re-orders |
| restatement_reversal | amended results restating fact_result_component | 0.003 of verified components | mart reloads; trend-report corrections |
| duplicate_webhook | duplicated EMR gateway order messages | 0.005 of electronic orders | duplicate requisitions pending dedup |
| conflicting_source_values | patient demographics differ LIS vs EMR vs portal | 0.02 of multi-source patients | survivorship overrides in golden record |
| format_drift | EMR interface and payer remittance layout changes | 2-4 events/year | staging load failures; raw_error rows |
| typo | manual accession entry from paper requisitions | 0.008 of manual entries | wrong test performed; credit and rebill |
| orphan_fk | lost kits: kit_shipment with no accession ever linked | 0.03 of kits shipped | aged open kits; replacement cost leakage |
| stale_mapping | payer code and fee schedule mapping tables | 0.02 of mappings out of date | underbilled claims; rate-variance breaks |
| manual_override | break-glass sensitive record access | 0.001 of access events | privacy review queue cases |
| out_of_order_events | instrument middleware timestamps vs LIS clock skew | 0.01 of result events | negative TAT segments in fact_turnaround_time |
| missing_xref | unmapped instrument result codes after test-catalog version change | 0.002 of raw results | results parked in exception queue |
