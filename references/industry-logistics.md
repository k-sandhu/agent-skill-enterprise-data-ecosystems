# Industry: Logistics and Freight

## Operating Context

- Mid-size freight broker / asset-light 3PL: books shipments for shippers, assigns carriers (own fleet plus contracted carriers), manages multi-leg moves across truckload, LTL, intermodal, and cross-border lanes.
- Revenue = customer freight invoices (linehaul + fuel surcharge + accessorials); cost = carrier settlements; margin typically 0.12-0.18 of revenue.
- Scale anchors: 2k-8k active shipper customers, 500-2,000 contracted carriers, 30k-80k shipments/month, 5-15 terminals/crossdocks, 200-600 owned assets.
- Key constraints: transport safety regulators (hours-of-service, inspections), customs authorities for cross-border, cargo liability conventions, hazmat rules, customer routing guides and SLAs.
- Money pain points: accessorial disputes (detention, lumper, redelivery), POD lag delaying billing, claims for loss/damage, carrier invoice mismatches.
- EDI-heavy integration: tender (204), status (214), invoice (210) message archetypes drive much of the data flow and most of the data quality problems.

## Domains

customer, order, shipment, booking, transport, asset, route, leg, stop, tracking, warehouse, customs, carrier, driver, rating, document, billing, settlement, claims, compliance.

## Source Systems

| System | Role | System-of-record domains | Typical data quirks |
| --- | --- | --- | --- |
| Order management | Customer orders, routing guides | customer, order | Free-text reference numbers; duplicate orders from portal retries |
| Transportation management (TMS) | Booking, planning, rating, tendering | shipment, booking, route, leg, stop, rating | Manual re-rates; leg re-plans overwrite history unless snapshotted |
| Warehouse management (WMS) | Pick, load, crossdock at terminals | warehouse | Device-time skew; events batched at shift end |
| Driver mobile app | Stop arrivals, POD capture, exception photos | tracking (own fleet), document | Offline buffering causes out-of-order and late events; missing signatures |
| Carrier portal | Contracted carrier status updates, document upload | tracking (partner legs) | Sparse updates; statuses keyed manually; PRO number typos |
| EDI gateway | Tender/status/invoice messages with carriers and shippers | integration | Duplicate messages, format drift by trading partner, dropped acks |
| GPS/telematics | Position pings, geofence events for own fleet | tracking | GPS gaps in rural/border areas; ping floods near terminals |
| Customs brokerage | Entry filing, holds, releases | customs | Broker reference IDs differ from shipment IDs; late release notices |
| Billing | Customer freight invoices, accessorial charges | billing | Held invoices awaiting POD; manual accessorial overrides |
| Carrier settlement | Carrier invoice intake, pay approval | settlement | Carrier invoices arrive 5-30 days late; rate mismatches |
| Claims platform | Loss/damage/shortage claims | claims | Claims filed against wrong shipment leg; slow subrogation updates |
| Document management | POD, BOL, customs docs, photos | document | OCR misreads; documents linked to wrong stop |
| Data warehouse | Analytics and reporting | (consumer) | Late-arriving tracking events restate on-time metrics |

## Core Tables

- `order_mgmt.order`, `order_mgmt.order_line`, `order_mgmt.routing_guide`
- `shipment.shipment`, `shipment.shipment_line`, `shipment.shipment_container`, `shipment.shipment_reference`
- `transport.route`, `transport.leg`, `transport.stop`, `transport.carrier_assignment`, `transport.tender`
- `rating.rate_agreement`, `rating.rate_line`, `rating.fuel_surcharge_schedule`, `rating.shipment_rate`
- `asset.truck`, `asset.trailer`, `asset.container`, `asset.driver`, `asset.driver_assignment`
- `tracking.tracking_event`, `tracking.location_ping`, `tracking.geofence_event`, `tracking.eta_snapshot`
- `warehouse.pick_task`, `warehouse.load_task`, `warehouse.crossdock_event`, `warehouse.dock_appointment`
- `customs.entry`, `customs.entry_line`, `customs.hold`, `customs.release_event`
- `driver_app.proof_of_delivery`, `driver_app.exception_photo`, `driver_app.stop_arrival`
- `billing.freight_invoice`, `billing.freight_invoice_line`, `billing.accessorial_charge`, `billing.invoice_hold`
- `settlement.carrier_invoice`, `settlement.carrier_invoice_line`, `settlement.pay_approval`
- `claims.claim`, `claims.claim_event`, `claims.claim_payment`
- `compliance.driver_log_summary`, `compliance.inspection_event`
- `document.document`, `document.document_link`

## Warehouse Facts and Dimensions

- `fact_shipment`: grain = one shipment. Measures: linehaul revenue, fuel surcharge, accessorial total, carrier cost, margin, weight, distance, leg count, transit days, on_time_flag, exception_flag.
- `fact_shipment_leg`: grain = one shipment leg. Measures: leg distance, planned vs actual transit hours, dwell hours at origin/destination, leg cost.
- `fact_shipment_event`: grain = one tracking event per shipment. Degenerate: event code, message source; measures: event lag minutes.
- `fact_route_stop`: grain = one stop on one route execution. Measures: planned vs actual arrival delta, dwell minutes, detention minutes.
- `fact_asset_utilization_daily`: grain = one asset per day. Measures: miles, loaded miles, engine hours, idle hours, utilization pct.
- `fact_freight_invoice_line`: grain = one charge line on one freight invoice. Measures: charge amount, rated amount, variance.
- `fact_carrier_settlement_line`: grain = one carrier invoice line. Measures: invoiced amount, contracted amount, variance.
- `fact_claim`: grain = one claim. Measures: claimed amount, reserved amount, paid amount, days to resolution.
- `fact_pod`: grain = one proof-of-delivery capture. Measures: pod_lag_hours (delivery to POD receipt), legibility flag.

Dimensions: customer, carrier, route, lane (origin-destination pair), asset, driver, location, terminal, shipment_status, service_level, mode, commodity, charge_type, claim_type, date, currency.

## Critical Dataflows

- Shipment-to-delivery: order -> booking -> rating -> tender -> carrier assignment -> shipment -> legs/stops -> tracking events -> proof of delivery -> invoice release -> claim when needed.
- Customs: shipment -> customs documents -> entry filing -> hold/release -> delivery eligibility -> cross-border leg dispatch.
- Carrier billing: carrier invoice -> match to legs and rate agreement -> accessorial validation -> pay approval -> customer invoice margin check.
- Visibility: GPS pings + driver app + carrier EDI 214 -> event normalization -> ETA snapshots -> exception detection -> customer notifications.
- POD-to-cash: delivery event -> POD capture/upload -> document OCR/validation -> invoice hold release -> customer invoice -> cash application.

## State Machines

- Shipment: booked -> tendered -> picked_up (0.97; tender-to-pickup lognormal, median 1 day, p90 3 days) | cancelled (0.03) -> in_transit -> at_terminal (0.55 of shipments touch a terminal; dwell lognormal, median 9h, p90 30h) -> customs_hold (0.04 of cross-border; dwell lognormal, median 1 day, p90 5 days) -> out_for_delivery -> delivered (0.92 first attempt) | delivery_failed (0.08, retry within 1-2 business days) -> pod_received (lag lognormal, median 8h, p90 72h) -> invoiced.
- Tender: offered -> accepted (0.78, median 2h) | declined (0.15) | expired (0.07); declined/expired -> re-offered to next carrier (up to 3 waterfall rounds).
- Freight invoice: draft -> pod_hold (0.30 of invoices wait on POD) -> issued -> paid (0.90, DSO normal mean 38 days sd 12) | disputed (0.08, resolution lognormal median 12 business days) | written_off (0.02).
- Carrier invoice: received -> auto_matched (0.72) | exception_review (0.28; manual match 1-5 business days) -> approved -> paid (net-30 standard, net-7 quick-pay 0.15 of carriers).
- Claim: filed -> acknowledged (1-2 business days) -> investigating -> approved (0.55, lognormal median 25 business days) | denied (0.30) | withdrawn (0.15) -> paid (5-10 business days after approval) -> subrogation (0.20 of paid claims).
- Customs entry: submitted -> accepted (0.93, median 4h) | rejected (0.07, resubmit 4-24h) -> released (0.96) | held (0.04; exam dwell lognormal median 1 day, p90 5 days) -> released.

## Volumetrics and Distributions

| Metric | Typical value or range | Distribution | Notes |
| --- | --- | --- | --- |
| Shipments per customer per month | median 6, p90 60 | lognormal | Top 10% of customers = ~65% of volume, zipf s=1.15 |
| Legs per shipment | 1-4, mean 1.6 | weighted choice: 1 (0.55), 2 (0.28), 3 (0.12), 4+ (0.05) | Cross-border and intermodal skew higher |
| Stops per leg | 2-6, mean 2.4 | weighted choice | Multi-stop LTL routes up to 12 |
| Lines per order | mean 3, max ~40 | lognormal, median 2 | Retail customers skew high |
| Tracking events per shipment | mean 14, p90 35 | poisson per leg + ping bursts | Own fleet richer than partner carriers |
| Linehaul revenue per shipment | median 850, p90 3,200, tail 25k | lognormal | Currency-neutral demo units |
| Accessorial charges per shipment | 0.35 have >=1; amount median 75, p90 350 | count poisson lambda 0.5; amount lognormal | Detention, lumper, liftgate, redelivery dominate |
| Fuel surcharge pct of linehaul | 0.12-0.22 | normal, mean 0.16 sd 0.03 | Indexed weekly |
| Net margin pct per shipment | mean 0.15, sd 0.07 | normal, floor -0.05 | ~0.04 of shipments ship at a loss |
| On-time pickup rate | 0.93 | weighted choice per stop | Varies by carrier tier 0.85-0.97 |
| On-time delivery rate | 0.90 | weighted choice per shipment | Definition ambiguity: appointment vs day-level |
| Exception rate (any exception event) | 0.12 of shipments | weighted choice | Weather, breakdown, refusal, damage, customs |
| Claims per 1,000 shipments | 4-8 | poisson | Claimed amount lognormal, median 600, p90 6k, tail 100k |
| POD lag (delivery to POD on file) | median 8h, p90 72h, p99 14 days | lognormal | Partner carriers slower than own fleet |
| Dwell at terminal per touch | median 9h, p90 30h | lognormal | Crossdock target <12h |
| Detention minutes per detention event | median 95, p90 240 | lognormal | Billable over 120 free minutes |
| Carrier invoice variance vs rated | 0.28 mismatch >1% | weighted choice; variance amount lognormal median 40 | Drives exception_review queue |
| Active carriers used per month | 300-700 of contracted base | zipf s=1.2 over carrier base | Top 20 carriers = ~50% of loads |
| Shipments per lane per month | top lane ~600, long tail of 1s | pareto | ~2,500 distinct active lanes |

## Business Rules and Invariants

- shipment.delivered_at >= shipment.picked_up_at >= shipment.booked_at.
- Stop actual_departure >= actual_arrival; stop sequence numbers strictly increasing per leg; leg n destination = leg n+1 origin.
- Delivered status requires proof_of_delivery record or validated exception (delivery_failed with reason code).
- freight_invoice.total = sum(freight_invoice_line.amount) = linehaul + fuel_surcharge + sum(accessorial_charge.amount) - discounts.
- Every freight_invoice_line ties to a shipment leg and a rate_agreement line (or carries manual_override flag with approver).
- Margin invariant: customer invoice total - sum(matched carrier_invoice totals) = shipment margin; negative margin requires override reason.
- Customs release_event must precede dispatch of any post-border leg; held entries block delivery eligibility.
- detention billable minutes = max(0, dwell_minutes - free_time_minutes) per rate agreement.
- claim.claimed_amount <= declared shipment value; claim_payment.total <= approved reserve; one open claim per shipment-commodity.
- Tracking event sequence must be a valid path through the shipment state machine; no delivered event before pickup event.
- on_time_delivery_flag = actual_delivery <= appointment_window_end (certified definition); day-level variant must be labeled as competing metric version.
- fact_asset_utilization_daily.loaded_miles <= miles; driver hours per day <= regulatory max.
- Every tracking_event maps to a shipment via shipment_reference or carrier PRO xref; unmapped events route to exception queue.

## Controls and Reconciliations

| Control | Grain | Tolerance | Expected break rate |
| --- | --- | --- | --- |
| Shipment-to-delivery-to-billing recon (every delivered shipment invoiced within 5 business days) | shipment per day | 0 missing after 5 bd | 0.02 |
| Freight invoice lines tie to shipment legs and rate agreements | invoice line | 1% or 5 units | 0.03 |
| Carrier invoice to customer invoice margin check | shipment | margin >= 0 unless overridden | 0.04 |
| POD-on-file before invoice release | invoice | 0 exceptions without override | 0.05 |
| Customs release precedes cross-border delivery | cross-border shipment | 0 | 0.005 |
| Tracking event sequence plausibility | shipment | valid state path | 0.03 |
| Tender acceptance to carrier assignment match | tender | 0 orphan assignments | 0.01 |
| Accessorial charge has supporting event (detention timer, lumper receipt) | accessorial line | 0 unsupported | 0.06 |
| GPS ping coverage for in-transit own-fleet legs | leg per day | >= 1 ping per 2h | 0.04 |
| Claims-to-shipment linkage and reserve roll-forward | claim per month | exact | 0.01 |
| Warehouse crossdock in = out per terminal per day | terminal-day unit counts | 0.5% | 0.02 |

## Seasonality and Temporal Patterns

- Weekday shape: pickups peak Mon-Wed (index 1.15), trough Sat (0.25), Sun near zero except expedited; deliveries peak Tue-Thu.
- Intraday: stop arrivals bimodal 06:00-10:00 and 13:00-16:00 local; POD uploads spike at end of driver shift (17:00-19:00); EDI batches land hourly with a 02:00 nightly bulk.
- Month-end: shipment volume +10-20% in final week as shippers push quarter-end revenue; invoice issuance spikes at month close.
- Q4 peak season: volume index 1.25-1.4 Oct-Dec; accessorial and exception rates rise ~1.3x; tender acceptance drops ~5pts.
- Weather seasonality: winter months exception rate 1.5x baseline on northern lanes; summer produce season tightens reefer capacity.
- Customs dwell lengthens around holiday periods and fiscal year-end inspections.

## Controlled Imperfections

| Imperfection | Where it appears | Typical rate | Downstream symptom |
| --- | --- | --- | --- |
| late_arrival | Carrier EDI 214 status events arriving 1-5 days late | 0.06 of partner events | On-time metrics restate; ETA snapshots wrong |
| duplicate_webhook | Duplicate EDI messages from gateway retries | 0.02 of messages | Duplicate tracking events inflate event counts |
| missing_xref | Carrier PRO not mapped to shipment ID | 0.015 of partner shipments | Orphan tracking events in exception queue |
| orphan_fk | tracking_event referencing cancelled or re-planned leg | 0.008 | Event-to-leg join drops rows |
| out_of_order_events | Driver app offline buffering | 0.04 of own-fleet stops | Delivered before arrival in raw feed |
| missing_xref | POD document_link absent for partner carrier deliveries | 0.05 at day 5 | Invoice holds; POD lag tail |
| conflicting_source_values | GPS vs driver app vs EDI disagree on arrival time | 0.05 of stops | Dwell and detention disputes |
| manual_override | Accessorial charges added/waived by billing analysts | 0.07 of accessorial lines | Charges without supporting event |
| duplicate_entity | Same carrier onboarded twice (DBA vs legal name) | 0.01 of carriers | Split scorecards, settlement misroutes |
| format_drift | Trading-partner EDI layout changes unannounced | 2-4 partners per quarter | Staging load failures, raw_error rows |
| stale_mapping | Fuel surcharge schedule or rate agreement not updated | 0.01 of active lanes | Rating variance; carrier invoice mismatches |
| typo | Hand-keyed PRO and reference numbers from carrier portal | 0.02 of manual entries | Failed auto-match in settlement |
| restatement_reversal | Re-rated shipments after rate dispute resolution | 0.015 of invoices | Negative adjustment lines; margin restated |
| late_arrival | Damage claims filed days after delivery | 0.25 of claims filed >7 days post-delivery | Claims lag distorts monthly claim rate |
| late_arrival | GPS pings buffered or never received on rural and border corridors | 0.04 of leg-hours | Coverage control breaks; ETA staleness |
| restatement_reversal | Re-planned legs mid-transit replacing original plan rows | 0.03 of shipments | Plan vs actual leg mismatch; orphan plan rows |
