# Industry: Manufacturing and Field Service

## Operating Context

- Discrete manufacturer of industrial equipment with an attached field service and warranty business; mid-size: 2-4 plants, 30-80 work centers, 1 distribution center, 60-150 field technicians.
- Money flows: customer orders -> production -> shipment -> invoice; service contracts and billable visits; warranty costs flow back against product margin.
- Make-to-stock for standard SKUs, make-to-order for configured units; 8k-25k active part numbers, 500-2,000 finished goods SKUs, 300-900 active suppliers.
- Key constraints: ISO-9001-style quality system, lot/serial traceability for regulated components, safety and environmental compliance on the shop floor.
- Capacity is the scarce resource: scheduling, machine uptime (OEE), and material availability drive on-time delivery.
- Installed base of 20k-80k serialized assets in the field generates service cases, preventive maintenance contracts, and warranty claims.

## Domains

product, engineering, BOM, routing, production, work_order, MES, machine, inventory, lot, serial, quality, maintenance, procurement, field_service, warranty, IoT, finance.

## Source Systems

| System | Role | System-of-record domains | Typical data quirks |
| --- | --- | --- | --- |
| ERP | Orders, costing, procurement, GL | procurement, inventory valuation, finance, work_order header | Stale standard costs, batch-posted movements, legacy item numbers |
| Product lifecycle management (PLM) | Engineering masters, revisions, ECOs | product, engineering, BOM (design) | BOM rev lags ERP effectivity, draft revs leak into extracts |
| Manufacturing execution system (MES) | Shop-floor execution, labor, machine events | production events, operation completions | Operator-entered quantities, out_of_order_events, backflush timing gaps |
| Warehouse management (WMS) | Picks, putaways, cycle counts | inventory location balances, lot bins | Cycle count adjustments, missing lot scans on bulk items |
| Quality management (QMS) | Inspections, NCRs, CAPAs | quality, nonconformance | Free-text defect descriptions, duplicate NCRs per event |
| Maintenance management (CMMS) | Assets, PM schedules, maintenance work orders | maintenance | PMs closed late in batches, asset hierarchy drift vs ERP |
| Field service platform | Cases, visits, installed base | field_service, installed_asset | Serial typos at install, visits logged days late from mobile sync |
| Supplier portal | ASNs, supplier quality docs | supplier ASN, certs | Missing ASNs (0.2 of receipts), format_drift in flat files |
| SCADA/historian | Machine signals, downtime detection | machine telemetry | Sensor dropouts, clock skew vs MES, unmapped tag IDs |
| IoT platform | Fielded-asset telemetry | iot sensor readings | Duplicate_webhook bursts, devices offline for weeks |
| Warranty/claims module | Warranty registration and claims | warranty | Claims against unregistered serials, conflicting failure codes |
| Finance/GL | Ledger, WIP, variances | finance postings | Period-end variance dumps, manual journal overrides |

## Core Tables

- `product.product`, `product.revision`, `product.bom`, `product.bom_component`
- `product.engineering_change_order`
- `production.routing`, `production.operation`, `production.work_order`, `production.work_order_operation`
- `production.material_issue`, `production.work_order_completion`
- `mes.production_event`, `mes.machine_event`, `mes.downtime_event`, `mes.labor_transaction`
- `inventory.item_location_balance`, `inventory.inventory_movement`, `inventory.lot`, `inventory.serial_number`
- `inventory.lot_genealogy`, `inventory.cycle_count`
- `procurement.purchase_order`, `procurement.po_line`, `procurement.receipt`, `procurement.supplier`
- `quality.inspection`, `quality.defect`, `quality.nonconformance`, `quality.corrective_action`, `quality.quality_hold`
- `maintenance.asset`, `maintenance.work_order`, `maintenance.pm_schedule`, `maintenance.meter_reading`
- `field_service.service_case`, `field_service.installed_asset`, `field_service.service_visit`, `field_service.part_usage`
- `warranty.claim`, `warranty.registration`
- `iot.sensor_reading`, `iot.device`
- `finance.wip_posting`, `finance.production_variance`

## Warehouse Facts and Dimensions

- `fact_production_order`: grain = one work order (planned/actual qty, yield, scrap, cost).
- `fact_operation_event`: grain = one work order operation event (start/complete/scrap/rework per operation per work order).
- `fact_inventory_movement`: grain = one item-location-lot movement transaction.
- `fact_inventory_balance_daily`: grain = one item x location x lot x date (semi-additive balance).
- `fact_quality_defect`: grain = one defect occurrence per inspection.
- `fact_machine_downtime`: grain = one downtime interval per machine (start, end, reason code).
- `fact_machine_utilization_daily`: grain = one machine x date (runtime, planned time, good count, total count -> OEE components).
- `fact_maintenance_work_order`: grain = one maintenance work order.
- `fact_service_visit`: grain = one field service visit.
- `fact_warranty_claim`: grain = one warranty claim.

Dimensions: product, component, bom_revision, lot, serial, location, machine, supplier, defect_code, downtime_reason, work_center, date, shift, technician, asset, failure_code.

## Critical Dataflows

- Work-order-to-inventory: planned order -> work order release -> material issue -> operation completions -> quality inspection -> finished goods receipt -> inventory balance -> GL WIP relief.
- Procure-to-production: purchase order -> ASN -> receipt -> incoming inspection -> lot assignment -> putaway -> material issue.
- Lot genealogy: supplier lot -> incoming lot -> material issue -> work order -> finished lot/serial -> shipment -> installed asset (forward and backward trace).
- Machine-to-OEE: SCADA signal -> downtime event -> MES machine event -> daily utilization fact -> OEE mart.
- Service-to-warranty: customer case -> installed asset lookup -> service visit -> part replacement -> warranty claim -> supplier recovery.
- Engineering change: ECO draft -> approval -> BOM revision effectivity -> ERP item/BOM sync -> open work order disposition.

## State Machines

- Production work order: planned -> released (0.95, lognormal, median 2 business days, p90 7) | cancelled (0.05); released -> in_progress (0.97, 0.5-2 business days) | cancelled (0.03); in_progress -> quality_hold (0.06) | completed (0.92) | scrapped_full (0.02); quality_hold -> completed after rework (0.70, lognormal, median 2 days, p90 8) | scrapped_full (0.15) | use_as_is_override (0.15); completed -> closed (1.0, 1-5 business days, costing close).
- Purchase order line: created -> acknowledged (0.90, 1-2 business days) | unacknowledged (0.10); acknowledged -> shipped -> received (on-time 0.82; late 0.15, lognormal lateness median 3 days, p90 14; short-shipped 0.03); received -> inspection_passed (0.96) | rejected_to_supplier (0.04).
- Nonconformance: opened -> contained (0.95, 0-1 business days) -> disposition {rework 0.45 | scrap 0.25 | use_as_is 0.20 | return_to_supplier 0.10} -> closed (lognormal, median 6 business days, p90 25); 0.12 of NCRs escalate to corrective_action (median 30 days to close, p90 90).
- Maintenance work order: requested -> approved (0.92, 0-2 business days) | rejected (0.08); approved -> scheduled -> in_progress -> completed (PMs: 0.85 on-time within window; correctives: lognormal, median 1 day, p90 6) -> closed.
- Service case: opened -> triaged (0.98, median 4 hours) -> remote_resolved (0.30) | visit_scheduled (0.65) | cancelled (0.05); visit_scheduled -> visit_completed (first-time-fix 0.75; repeat visit needed 0.25); visit_completed -> warranty_claim_filed (0.35) | billed (0.45) | contract_covered (0.20).
- Warranty claim: submitted -> approved (0.78, lognormal, median 5 business days, p90 20) | rejected (0.15) | more_info (0.07, adds median 7 days); approved -> paid/credited (5-15 business days, uniform).

## Volumetrics and Distributions

| Metric | Typical value or range | Distribution | Notes |
| --- | --- | --- | --- |
| Production work orders per plant per day | 40-120 | poisson per work center, summed | Make-to-order spikes at quarter end |
| BOM depth (levels) for finished goods | 3-7, median 4 | weighted choice: 3 (0.25), 4 (0.35), 5 (0.25), 6 (0.10), 7 (0.05) | Phantom levels collapse 1 level in MES |
| Components per BOM level | 5-40, median 12 | lognormal, median 12, p90 35 | Fasteners/consumables inflate counts |
| Work order quantity (discrete units) | 1-500, median 25 | lognormal | Configured units often qty 1 |
| First-pass yield per operation | 0.92-0.995, median 0.97 | beta(a=60, b=2) per work center | Machining lower, assembly higher |
| Rolled throughput yield per work order | 0.85-0.96 | product of operation yields | Drives scrap + rework split |
| Scrap rate (qty scrapped / qty started) | 0.015-0.04 | beta(a=4, b=120) | Tail events: full-lot scrap 0.002 of work orders |
| Rework rate (units reworked / started) | 0.03-0.08 | beta(a=6, b=100) | Rework adds 0.2-0.5x operation labor |
| Operations per routing | 4-12, median 6 | lognormal | Outside-processing op on 0.10 of routings |
| OEE by work center | 0.55-0.80, median 0.68 | normal, mean 0.68, sd 0.07 | Availability ~0.85, performance ~0.88, quality ~0.97 |
| Unplanned downtime events per machine per week | 1-4 | poisson, lambda 2 | Duration lognormal, median 45 min, p90 4 h |
| PM interval per asset | 30/90/180/365 days | weighted choice: 30 (0.35), 90 (0.35), 180 (0.20), 365 (0.10) | Meter-based PMs on 0.25 of assets |
| Corrective:preventive maintenance ratio | 0.6-1.2 : 1 | -- | Healthy plants nearer 0.6 |
| PO lines per receipt | 1-8, median 2 | lognormal | Bulk MRO orders in tail (20+ lines) |
| Supplier spend concentration | top 10% suppliers = ~65% of spend | zipf, s=1.15 | Single-source parts: 0.20 of part numbers |
| Lots per finished work order (consumed) | 5-25, median 10 | lognormal | One lot per lot-controlled component issue |
| Service cases per 100 installed assets per month | 2-6 | poisson | Skewed to assets >5 years old |
| Service visit duration | 1-6 h, median 2.5 h | lognormal, median 2.5 h, p90 6 h | Travel adds 0.5-2 h, not in wrench time |
| Warranty claim amount | 150-1,200, median 400 | lognormal, median 400, p99 8,000 | Currency-neutral units; recalls in extreme tail |
| Cycle count adjustments per location per month | 0.01-0.03 of counted lines | beta | Adjustment magnitude lognormal, median 2 units |

## Business Rules and Invariants

- Ending inventory = beginning inventory + receipts - issues - shipments + adjustments - scrap, per item-location-lot per day.
- Material issued to a work order ties to its BOM revision effective on release date; substitutes require a substitution record.
- qty_completed + qty_scrapped + qty_in_process <= qty_started per work order operation; qty_started <= qty_released.
- Finished goods receipt quantity <= work order completed quantity; no FG receipt before last routing operation completes.
- Every lot-controlled material issue creates a `lot_genealogy` edge: child finished lot -> parent component lot.
- Serialized units: serial created at final assembly; exactly one active install location per serial in `installed_asset`.
- Scrap and rework transactions tie to a quality defect or NCR record (target coverage 0.95).
- operation_completed_at >= operation_started_at >= work_order_released_at; shipped_at >= fg_receipt_at.
- Inspection result must exist before quality_hold release; specimen of disposition use_as_is requires an override approval record.
- Maintenance downtime intervals must not overlap per machine; downtime ties to lost capacity in utilization fact.
- Warranty claim serial must exist in `warranty.registration` or flag missing_xref; claim date within warranty term for approved claims.
- WIP roll-forward: beginning WIP + material issues + labor + overhead - completions at standard - variances = ending WIP, per work order.
- OEE components each in [0,1]; OEE = availability x performance x quality, recomputed value matches stored value within 0.001.

## Controls and Reconciliations

| Control | Grain | Tolerance | Expected break rate |
| --- | --- | --- | --- |
| Inventory balance roll-forward (movements vs balances) | item x location x lot x day | 0 units | 0.005 of item-days |
| Inventory-to-GL valuation | item x site x period | 0.5% or 100 currency units | 0.02 of items at close |
| Material consumption vs BOM standard (usage variance) | work order | 5% of standard qty | 0.08 of work orders flagged |
| FG receipts tie to completed work orders | work order | 0 units | 0.003 |
| Scrap/rework transactions tie to quality defects | transaction | n/a (existence) | 0.05 missing linkage |
| Maintenance downtime vs MES capacity loss | machine x day | 15 minutes | 0.04 of machine-days |
| PO receipts vs supplier ASN | receipt | 0 lines | 0.20 (ASN coverage gap) |
| Lot genealogy completeness (issues vs edges) | work order | n/a (existence) | 0.02 of lot-controlled issues |
| Serial install base vs shipment records | serial | n/a (existence) | 0.03 orphan installs |
| Warranty claims vs registration | claim | n/a (existence) | 0.06 unregistered serials |
| WIP roll-forward | work order x period | 1 currency unit | 0.01 |
| Cycle count accuracy (book vs count) | location x count | 2% of line value | 0.015 of counted lines adjusted |

## Seasonality and Temporal Patterns

- Production runs 2 shifts (some plants 3); MES events cluster 06:00-22:00 with completion spikes at shift end (operator batch entry).
- Weekday-heavy: Mon-Fri ~0.18 each of weekly volume, Sat 0.07 (overtime), Sun 0.03 (maintenance window).
- Quarter-end push: shipments and FG receipts +25-40% in the last week of each fiscal quarter; scrap and override rates tick up with it.
- Summer/holiday plant shutdowns (1-2 weeks): planned maintenance spikes, production near zero, PM completions surge.
- Cycle counts concentrated month-end; GL variance postings and standard cost updates at period close (day 1-3 spike).
- Field service seasonal: HVAC-like installed bases spike in temperature extremes; otherwise +10-15% case volume Mondays.
- IoT telemetry steady 24x7 with dropout gaps; SCADA downtime events correlate with Monday cold starts.

## Controlled Imperfections

| Imperfection | Where it appears | Typical rate | Downstream symptom |
| --- | --- | --- | --- |
| missing_xref | Lot genealogy edges absent for bulk/backflushed components | 0.02 of issues | Recall trace dead-ends; genealogy completeness control breaks |
| orphan_fk | Serial scans missing at pack-out; installed asset without shipment | 0.03 of serials | Install base vs shipment recon breaks |
| late_arrival | Mobile field-service visits sync 1-5 days late | 0.10 of visits | Service marts restate; SLA metrics shift after load |
| late_arrival | Supplier receipts posted after period cut | 0.04 of receipts | Inventory-to-GL breaks at close, accrual reversals |
| conflicting_source_values | BOM revision differs PLM vs ERP during ECO window | 0.03 of active BOMs | Usage variance false positives |
| duplicate_entity | Duplicate NCRs for one quality event | 0.04 of NCRs | Defect counts inflated in quality mart |
| duplicate_webhook | IoT readings re-delivered in bursts | 0.01 of readings | Telemetry aggregates overcount without dedup |
| out_of_order_events | MES operation completions before starts (clock skew, batch entry) | 0.02 of operations | Negative cycle times; state-machine DQ failures |
| manual_override | Quality use-as-is dispositions; inventory adjustments | 0.15 of holds; 0.02 of balances/month | Audit queue volume; yield metrics flattered |
| stale_mapping | Standard costs not updated after ECO or supplier reprice | 0.05 of items | Purchase price and usage variances drift |
| typo | Serial numbers keyed wrong at install/registration | 0.015 of registrations | Warranty claims reject as unregistered |
| format_drift | Supplier ASN/cert flat files change layout | 2-4 events/year | Integration failures, missing ASN spike |
| restatement_reversal | Cycle count adjustments reversed after recount | 0.10 of adjustments | Balance history shows churn pairs |
| missing_xref | SCADA tag IDs unmapped to MES machines | 0.02 of tags | Downtime undercounted; OEE availability overstated |
| late_arrival | Historian/IoT sensor gaps from offline devices that backfill on reconnect | 0.5-2% of expected readings | Utilization gaps; interpolation flags in marts |
