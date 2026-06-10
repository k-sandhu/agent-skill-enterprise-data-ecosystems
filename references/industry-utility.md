# Industry: Utility

## Operating Context

- Regulated electric/gas distribution utility delivering energy to metered premises inside a franchise service territory; revenue from commission-approved tariffs.
- Money flows through meter-to-cash: read -> validate/estimate -> bill -> payment -> collections; purchased power and fuel costs pass through riders.
- Regulated by a public utility commission: rate cases, reliability reporting (SAIDI/SAIFI/CAIDI), estimated-read rules, disconnection moratoriums (winter, medical).
- Scale anchors: mid-size regional distributor, 150k-350k active service points, 20-21 billing cycles per month, ~90% AMI meter penetration with a manual-read remainder.
- Field workforce executes service orders (connect, disconnect, meter exchange, re-read, outage restoration) dispatched via mobile workforce management.
- Largest cost lines: purchased power, field labor, capital plant; revenue recognized on billed plus unbilled accrual.

## Domains

premise, service_point, meter, customer, account, rates, meter_reading, billing, payments, collections, credit, outage, field_service, asset, work_management, network, regulatory, finance, customer_service.

## Source Systems

| System | Role | System-of-record domains | Typical data quirks |
| --- | --- | --- | --- |
| Customer information system (CIS) | Meter-to-cash core: accounts, rates, bill calc, payments, collections | customer, account, premise, rates, billing, collections | Legacy keys reused after account merges; free-text rate notes; sparse history before migration cutover |
| Meter data management platform (MDM) | Collect, validate, estimate reads (VEE); billing determinants | meter_reading | Interval gaps; estimation flags differ by meter firmware; DST days with 23/25 intervals |
| AMI head-end system | Device comms, remote reads, remote connect/disconnect, last-gasp events | meter telemetry | Duplicate event pushes; comms dead zones; meter clock drift |
| Mobile workforce management | Dispatch and completion of field orders | field_service | Completions batch-synced at shift end; free-text remarks instead of codes |
| Outage management system (OMS) | Outage inference, crew assignment, restoration, reliability stats | outage | Outage extent restated as calls arrive; nested/merged outage events |
| Geographic information system (GIS) | Network connectivity model, asset locations | network | Stale connectivity after switching; orphan service points off-model |
| Enterprise asset management (EAM) | Asset registry, maintenance and capital work orders | asset, work_management | Duplicate meter records after exchanges; missing install dates on legacy plant |
| ERP / general ledger | GL, procurement, payroll | finance | CIS revenue posts as summarized journals; account-level detail only in CIS |
| Payment processor / lockbox | Remittance capture (card, ACH, lockbox) | none (capture only) | Late lockbox files; partial payments misapplied across accounts |
| Customer self-service portal / IVR | Payments, outage reporting, start/stop requests | none (front end) | Duplicate outage reports; typo-prone webform premise data |
| Regulatory reporting platform | Reliability, rate case, compliance filings | regulatory submissions | Manual spreadsheet adjustments before filing; restated metrics |

## Core Tables

- `premise.premise`, `premise.service_point`, `premise.service_point_status_history`
- `asset.meter`, `asset.meter_install_event`, `asset.meter_exchange`, `asset.transformer`, `asset.feeder`, `asset.circuit_segment`
- `customer.customer`, `customer.account`, `customer.account_premise`, `customer.contact`, `customer.account_status_history`
- `rates.rate_schedule`, `rates.rate_component`, `rates.rider`, `rates.account_rate_assignment`
- `meter.read_cycle`, `meter.read_route`, `meter.register_read`, `meter.interval_read`, `meter.read_estimate`, `meter.vee_exception`
- `billing.bill_cycle_run`, `billing.bill`, `billing.bill_line`, `billing.bill_exception`, `billing.bill_adjustment`, `billing.cancel_rebill`
- `payments.payment`, `payments.payment_allocation`, `payments.payment_plan`, `payments.customer_deposit`
- `collections.collection_event`, `collections.disconnect_notice`, `collections.field_disconnect`, `collections.write_off`
- `outage.outage_event`, `outage.outage_call`, `outage.outage_customer`, `outage.crew_assignment`, `outage.restoration_step`
- `field.service_order`, `field.field_activity`, `field.appointment`, `field.crew`, `field.truck_roll`
- `customer.medical_flag`, `customer.lifeline_enrollment`, `customer.start_stop_request`
- `network.switching_event`, `network.feeder_load_daily`
- `regulatory.reliability_metric_monthly`, `regulatory.filing`, `regulatory.filing_schedule`, `regulatory.compliance_event`, `regulatory.rate_case`
- `finance.gl_journal`, `finance.unbilled_revenue_accrual`

## Warehouse Facts and Dimensions

- `fact_meter_read`: one row per meter x read_date x read_type (actual, estimate, customer-supplied).
- `fact_interval_consumption`: one row per meter x interval_start (hourly or 15-min).
- `fact_bill`: one row per bill (account x cycle run); degenerate dim bill_number.
- `fact_billed_usage`: one row per bill x rate_component (kWh/therms, demand, rider amounts).
- `fact_payment`: one row per payment_allocation (payment x account x bill).
- `fact_outage_customer_interruption`: one row per outage_event x affected customer (customer-minutes measure).
- `fact_field_activity`: one row per completed or attempted field activity.
- `fact_collections_event`: one row per collection lifecycle event.
- `fact_unbilled_revenue_daily`: one row per rate_class x business_date (semi-additive accrual balance).

Dimensions: customer, account, premise, service_point, meter, rate_schedule, read_cycle, crew, feeder, outage_cause, weather_zone, channel, date.

## Critical Dataflows

- Meter-to-cash: AMI/manual read -> MDM VEE (validate, estimate) -> billing determinants -> bill calculation -> bill exception review -> bill issued -> payment -> collections.
- Read cycle: route schedule -> read collection -> missing-read detection -> estimation -> bill -> true-up on next actual read (possible cancel/rebill).
- Outage lifecycle: customer calls + AMI last-gasp -> OMS outage inference -> crew dispatch -> restoration -> verification (power-restore pings) -> reliability stats -> regulatory filing.
- Field order: service request (CIS/portal) -> order creation -> scheduling -> dispatch -> field completion -> CIS update -> billing impact (e.g., final read, exchange).
- Move-in/move-out: stop request -> final read order -> final bill -> premise vacant or new account -> initial read -> first bill.
- Unbilled revenue: daily usage estimate -> monthly accrual journal -> reversal when bill issues -> GL.
- Regulatory reporting: OMS/CIS operational data -> monthly metric calc -> manual adjustments -> filing -> occasional restatement.

## State Machines

- Bill: `determinants_ready -> calculated -> auto_pass (0.93, same day) | exception_hold (0.07)`; `exception_hold -> released (0.80, lognormal, median 1 day, p90 4 days) | cancel_rebill (0.15) | written_off_adjustment (0.05)`; `issued -> paid_on_time (0.82, by due date ~21 days) | paid_late (0.13, lognormal, median 8 days late, p90 30 days) | delinquent (0.05)`.
- Meter read: `scheduled -> collected (0.96, same day) | missing (0.04)`; `missing -> estimated (0.90, same day) | reread_ordered (0.10, 1-3 business days)`; `estimated -> trued_up_next_cycle (0.85) | consecutive_estimate (0.15)`; 3+ consecutive estimates -> mandatory field re-read.
- Service order: `created -> scheduled (0.95, uniform 1-10 business days) | cancelled (0.05)`; `scheduled -> dispatched -> completed (0.88, same day) | incomplete_no_access (0.09) | cancelled_on_site (0.03)`; `incomplete_no_access -> rescheduled (0.85) | closed_unable (0.15)`.
- Outage event: `detected -> confirmed (0.92, minutes) | cancelled_false_positive (0.08)`; `confirmed -> crew_assigned (lognormal, median 0.5 h, p90 3 h) -> on_site (median 0.75 h) -> restored (lognormal, median 1.5 h, p90 8 h, storm tail p99 48 h) -> verified -> closed`; `restored -> reopened_nested_outage (0.04)`.
- Collections: `current -> past_due (0.18 of bills) -> reminder_sent (day 5 past due) -> disconnect_notice (0.40 of past_due, day 20) -> paid (0.55) | payment_plan (0.25) | field_disconnect (0.15) | write_off (0.05)`; `field_disconnect -> reconnected (0.80, lognormal, median 3 days, p90 21 days) | final_account (0.20)`.
- Move-out: `requested -> final_read_ordered (same day) -> final_read_complete (0.92, 1-3 business days) | estimated_final (0.08) -> final_bill_issued (1-2 business days) -> paid (0.75) | sent_to_collections (0.25)`.

## Volumetrics and Distributions

| Metric | Typical value or range | Distribution | Notes |
| --- | --- | --- | --- |
| Active service points | 150k-350k | n/a | Cardinality anchor; ~97% have active accounts |
| Meters per premise | 1 (0.88), 2 (0.10), 3+ (0.02) | weighted choice | Dual fuel or multi-unit premises |
| Bills per account per month | 1 | n/a | One per assigned read cycle; off-cycle final bills extra (0.015) |
| Read cycles per month | 20-21 | uniform across business days | Accounts split roughly evenly per cycle |
| AMI daily read success | 0.975-0.995 | beta(a=200, b=3) per day | Drops to 0.90 on storm days |
| Estimated reads (share of billed reads) | 0.02-0.05 | n/a | Spikes to 0.10+ in storm/extreme-weather months |
| Bill exception rate | 0.03-0.08 per cycle | n/a | High-low usage, negative consumption, missing determinants |
| Cancel/rebill rate | 0.005-0.015 of bills | n/a | Mostly estimate true-ups and rate corrections |
| Residential monthly bill amount | median 95, p90 220, p99 600 | lognormal | Currency-agnostic units |
| Usage concentration | top 1% of accounts = ~40% of delivered kWh | pareto (alpha ~1.2) | C&I accounts dominate volume |
| Partial payments | 0.06 of payments | n/a | Drives allocation logic and balance carryover |
| Outage events per month (fair weather) | 80-250 | poisson | 5-15 storm days/year at 10-30x baseline |
| Customers per outage | median 12, p95 800, p99 8000 | lognormal | Feeder lockouts create heavy tail |
| Field orders per 1000 accounts per month | 25-60 | poisson | Mix: re-reads 0.25, connects/disconnects 0.35, exchanges 0.15, collections 0.15, other 0.10 |
| Contact-center calls per customer per year | 0.8-1.5 | poisson | Top 10% of callers = ~50% of call volume, zipf s=1.1 |
| Late payment rate | 0.15-0.20 of bills | n/a | Higher in winter heating months |
| Active payment plans | 0.02-0.04 of accounts | n/a | Rises after moratorium end dates |
| Meter exchanges per year | 0.04-0.08 of meter fleet | n/a | AMI refresh programs spike this 3-5x |

## Business Rules and Invariants

- bill total = sum(bill_line amounts) + taxes + rider charges - credits - adjustments.
- billed usage = closing register read - opening register read, times meter multiplier, adjusted for register rollover.
- opening read of bill N = closing read of bill N-1 for the same meter with no exchange in between.
- meter exchange: removal read date of old meter = install read date of new meter; usage splits across both meters within the bill period.
- every estimated read has read_type = 'estimate' and a matching `meter.vee_exception` row.
- sum of interval consumption over a bill period = register read delta within 0.5% tolerance.
- cancel/rebill: cancelled bill fully reversed before rebill posts; net revenue effect = rebill total - cancelled total.
- payment allocations sum exactly to payment amount; no allocation to closed accounts without a reopen event.
- account balance roll-forward holds per account per day: prior balance + charges - payments - adjustments + deposits applied = current balance.
- service order timestamps: completed_at >= dispatched_at >= scheduled_at >= created_at.
- outage timestamps: closed_at >= verified_at >= restored_at >= on_site_at >= dispatched_at >= detected_at.
- customer interruption minutes = restored_at - interruption_start per affected customer; monthly SAIDI numerator = sum of customer-minutes for qualifying outages.
- field disconnect for non-payment requires a disconnect_notice >= 10 calendar days prior and no active moratorium or medical flag on the account.
- unbilled revenue accrual for a month reverses in full in the month the bill issues.
- no interval reads for a meter dated outside its install-to-removal window.
- final bill period ends on the move-out final read date; no charges accrue to the account after that date.
- accounts with an active medical_flag are excluded from field_disconnect and remote disconnect commands.
- filed reliability metrics for a month must match `regulatory.reliability_metric_monthly` as of filing date; later changes require a restatement record.

## Controls and Reconciliations

| Control | Grain | Tolerance | Expected break rate |
| --- | --- | --- | --- |
| Billed usage vs MDM validated usage | bill period x meter | 0.5% | 0.01 |
| CIS billed revenue vs GL revenue journal | cycle run x rate class | exact after rounding | 0.005 |
| Payments posted vs bank deposit / lockbox file | deposit batch x date | exact | 0.01 |
| Meter inventory: EAM assets vs CIS installed meters | meter | exact match | 0.02 |
| Outage affected-customer count: OMS vs CIS premise map | outage event | 2% | 0.05 |
| Read-to-bill completeness: scheduled reads vs billed accounts | read cycle | 0.5% of accounts | 0.02 |
| SAIDI/SAIFI computed vs filed values | month | exact | 0.01 (restatements) |
| Unbilled accrual vs subsequent actual billings | month x rate class | 3% | 0.10 |
| Remote disconnect commands vs CIS account status | account x day | exact | 0.01 |

## Seasonality and Temporal Patterns

- Consumption: dual-hump seasonality - summer cooling peak and winter heating peak; shoulder months 30-40% below peak; daily load tracks degree-days.
- Billing: volume spread roughly uniformly across 20-21 cycles per month; exception volume spikes for 1-2 cycles after any rate change or tariff rider update.
- Payments: clustered near due dates and the 1st/15th; weekday-heavy; surge in the 48 hours before disconnect-notice deadlines.
- Outages: poisson baseline with storm-day clusters (summer convective storms, winter ice); restoration tails extend 24-72 hours in major events.
- Estimated reads: elevated in storm months and extreme cold/heat (comms failures, meter access issues).
- Field work: weekday daytime; move-in/move-out orders spike at month end and 1.5-2x in summer.
- Contact center: Monday peak; spikes on bill-issuance days and during outages (5-20x during major events).
- Regulatory: monthly reliability metrics finalized by the 10th business day; annual filings cluster in Q1; restatements follow audit findings.
- Fiscal close: unbilled accrual and revenue journals concentrate in the first 3 business days of each month.

## Controlled Imperfections

| Imperfection | Where it appears | Typical rate | Downstream symptom |
| --- | --- | --- | --- |
| missing_xref | meter to GIS service point mapping | 0.01 of meters | Outage affected-customer counts undercount |
| orphan_fk | `meter.interval_read` referencing exchanged-out meter id | 0.003 of interval rows | VEE exceptions; unbillable usage queue |
| duplicate_entity | customer re-created at move-in instead of reusing existing party | 0.02 of move-ins | Split payment history; deposit refund errors |
| late_arrival | manual route reads ingested 1-3 days after read date | 0.04 of manual reads | Estimation then cancel/rebill churn |
| conflicting_source_values | premise address differs between CIS and GIS | 0.03 of premises | Crews misrouted; outage maps wrong |
| format_drift | AMI head-end export adds column / changes timestamp format | 2-3 events per year | Ingest failures; interval gaps for 1-2 days |
| typo | meter serial keyed wrong on manual exchange paperwork | 0.005 of exchanges | Reads attach to wrong meter; negative usage |
| restatement_reversal | cancel/rebill after estimate true-up or rate correction | 0.01 of bills | Revenue restated in marts; metric churn |
| out_of_order_events | OMS restoration step recorded before dispatch step | 0.02 of outage events | Negative durations in naive SAIDI calcs |
| duplicate_webhook | AMI last-gasp / power-restore events delivered twice | 0.03 of device events | Inflated outage detection counts |
| stale_mapping | rate-code-to-GL-account map not updated after tariff change | 1-2 breaks per rate change | Misposted revenue; recon breaks vs GL |
| manual_override | bill exception released with manually keyed amount | 0.005 of bills | Bill total deviates from calculated determinants |
