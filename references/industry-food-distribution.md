# Industry: Foodservice Distribution

## Operating Context

- Broadline distributor: buys from food suppliers, warehouses in temperature zones (dry, cooler, freezer), sells and delivers to restaurants, healthcare, education, and hospitality operators.
- Money flows: sell-side gross margin (12-20%) plus supplier-side earned income (rebates, allowances, promotions) that can equal 20-40% of total margin.
- Revenue splits between contract pricing (national accounts, GPOs, cost-plus agreements) and street pricing (independent operators, rep-negotiated).
- Constraints: food safety traceability (lot/expiry tracking, recall readiness), cold chain integrity, driver hours-of-service limits, customer credit exposure.
- Scale anchors: regional distributor, 8k-15k active customers, 12k-18k active SKUs, 3-6 distribution centers, 150-300 delivery routes per day.
- Daily rhythm: orders placed by evening cutoff, picked overnight, delivered next morning; next-day order-to-delivery is the dominant cycle.

## Domains

customer, national_account, CRM, ecommerce, EDI, product_master, supplier, purchasing, pricing, order_mgmt, warehouse, inventory, lot, temperature_zone, route, driver, proof_of_delivery, returns, claims, recall, rebate, finance.

## Source Systems

| System | Role | System-of-record domains | Typical data quirks |
| --- | --- | --- | --- |
| CRM | Accounts, contacts, territories, national account hierarchy | customer, national_account, CRM | Duplicate accounts per ship-to; hierarchy lags billing reality |
| Ecommerce ordering | Customer self-service ordering and order guides | ecommerce | Cart abandonment noise; order edits after submit |
| EDI gateway | Chain and GPO order intake, acknowledgements, invoices out | EDI | Duplicate transmissions; correction orders; partner-specific code lists |
| ERP | Orders, purchasing, AR/AP, customer credit | order_mgmt, purchasing, finance (subledger) | Legacy customer numbers; credit holds applied out of band |
| Product information management | Item master, allergens, storage requirements | product_master | Supplier catalog drift; pack/size unit-of-measure conflicts |
| Contract pricing engine | Contract prices, cost-plus rules, deviated billing | pricing | Stale contracts after renewal; effective-date gaps |
| Warehouse management | Picks, waves, loads, lot-level inventory | warehouse, inventory, lot | Short picks; cycle count adjustments; lot splits |
| Transportation management | Route plans, stops, delivery windows | route | Re-sequenced stops; route delays not synced back |
| Driver mobile app | Proof of delivery, exceptions, returns capture | proof_of_delivery | Offline sync delays; missing signatures; photo-only PODs |
| Supplier portal | Supplier items, POs, rebate agreements, recall notices | supplier, rebate (agreements) | Manual agreement entry; late recall notices |
| Food safety / recall system | Recall events, lot tracing, holds | recall | Lot ranges entered free-text; partial trace coverage |
| Billing | Invoices, credit memos, deviated billbacks | billing | Rebill/credit-rebill churn; price override trail incomplete |
| Finance / GL | Journal entries, rebate accruals, margin reporting | finance | Month-end accrual true-ups; mapping table drift |
| Data warehouse | Conformed reporting layer | none (consumer) | Late-arriving POD and credit data; restated margin |

## Core Tables

- `crm.account`, `crm.contact`, `crm.sales_territory`, `crm.national_account`, `crm.account_hierarchy`
- `ecommerce.cart`, `ecommerce.order_event`, `ecommerce.order_guide`
- `edi.inbound_order`, `edi.order_acknowledgement`, `edi.transmission_log`
- `product.product`, `product.supplier_item`, `product.allergen`, `product.storage_requirement`, `product.uom_conversion`
- `supplier.supplier`, `purchasing.purchase_order`, `purchasing.purchase_order_line`, `purchasing.receipt`
- `pricing.price_list`, `pricing.contract_price`, `pricing.price_override`, `pricing.rebate_agreement`
- `order_mgmt.sales_order`, `order_mgmt.sales_order_line`, `order_mgmt.order_substitution`, `order_mgmt.credit_hold`
- `warehouse.pick_wave`, `warehouse.pick_task`, `warehouse.load_task`, `warehouse.cycle_count_task`
- `inventory.lot`, `inventory.inventory_movement`, `inventory.item_location_balance`, `inventory.quality_hold`
- `transport.route`, `transport.route_stop`, `transport.delivery_window`
- `driver_app.proof_of_delivery`, `driver_app.delivery_exception`
- `returns.return_request`, `returns.credit_memo`, `returns.credit_memo_line`
- `food_safety.recall`, `food_safety.recall_lot`, `food_safety.customer_notice`
- `rebate.rebate_accrual`, `rebate.rebate_claim`, `rebate.settlement`
- `billing.invoice`, `billing.invoice_line`, `finance.journal_entry`

## Warehouse Facts and Dimensions

- `fact_order_line`: grain = one sales order line (order, product, ordered/shipped qty, contract vs street flag).
- `fact_invoice_line`: grain = one invoice line (includes rebills; degenerate invoice number).
- `fact_inventory_movement`: grain = one product-location-lot movement (receipt, pick, adjustment, return).
- `fact_inventory_balance_daily`: grain = one product-location-lot-date (semi-additive on-hand qty and value).
- `fact_pick_task`: grain = one warehouse pick task (short-pick qty as measure).
- `fact_delivery_stop`: grain = one route stop (planned vs actual arrival, cases delivered).
- `fact_credit_memo_line`: grain = one credit memo line (reason code, original invoice line reference).
- `fact_rebate_accrual`: grain = one agreement-product-month accrual.
- `fact_recall_impact`: grain = one recall-lot-customer exposure.

Dimensions: customer, national_account, product, supplier, warehouse, lot, route, driver, sales_rep, price_contract, rebate_agreement, credit_reason, date, temperature_zone.

## Critical Dataflows

- Order-to-cash: CRM/ecommerce/EDI order -> order management -> credit check -> price resolution (contract vs street) -> available-to-promise -> pick/load -> route delivery -> proof of delivery -> invoice -> GL.
- Procure-to-stock: demand forecast -> purchase order -> supplier confirmation -> receipt -> lot creation -> putaway -> perpetual balance -> AP invoice match.
- Pricing and margin: contract price -> order line price -> invoice line -> rebate accrual -> earned income settlement -> margin reporting.
- Returns and credit: delivery exception or customer claim -> return request -> driver pickup -> warehouse receipt/disposition -> credit memo -> AR adjustment -> GL.
- Recall impact: supplier recall -> affected lots -> warehouse inventory hold + shipped-customer trace -> customer notices -> returns/credits -> disposition -> closure.
- Rebate lifecycle: rebate agreement -> eligible purchase/sale tracking -> monthly accrual -> claim to supplier -> settlement or dispute -> accrual true-up.

## State Machines

- Sales order: submitted -> credit_checked (0.93 pass, <1 hour) | credit_hold (0.07, lognormal, median 4 hours, p90 2 business days) -> allocated -> picked (overnight, 2-8 hours) -> loaded -> out_for_delivery -> delivered (0.97) | delivery_exception (0.03) -> invoiced (same day as delivery). Within picking: line short_picked 0.025, substituted 0.015.
- Delivery stop: planned -> en_route -> arrived -> delivered_signed (0.90) | delivered_no_signature (0.06) | refused_partial (0.025) | missed (0.015, redelivered next route day).
- Return/credit: requested -> approved (0.85, 0-1 business days) | denied (0.15) -> picked_up (next delivery, 1-3 business days) -> received -> credited (1-2 business days after receipt).
- Purchase order: created -> confirmed (0.95, 0-2 business days) | rejected (0.05) -> shipped -> received (lead time lognormal, median 4 days, p90 10 days) -> putaway -> ap_matched (0.92 clean) | match_exception (0.08).
- Rebate claim: accrued -> claimed (monthly/quarterly) -> validated (0.80, 5-15 business days) | disputed (0.20, lognormal, median 20 business days, p90 60) -> settled -> trued_up.
- Recall: initiated -> lots_identified (0-1 days) -> inventory_held -> customers_notified (1-2 days) -> returns_processed (1-3 weeks) -> disposed -> closed (median 30 days, p90 90 days).

## Volumetrics and Distributions

| Metric | Typical value or range | Distribution | Notes |
| --- | --- | --- | --- |
| Orders per active customer per week | 1.8 (range 0.5-6) | lognormal | Independents 1-2; chains and healthcare 3-6 |
| Lines per order | median 14, p90 38, max ~150 | lognormal | Order-guide reorders cluster 8-20 lines |
| Order value | median $650, mean $1,100, p99 $12k | lognormal | Drop size below $300 often surcharged |
| Line fill rate (shipped/ordered) | 0.97 | beta(97,3) per line | Seasonal dips to 0.94 during supply shocks |
| Complete-order fill rate | 0.88 | derived | At least one short line on ~12% of orders |
| Contract vs street pricing mix | 0.60 contract / 0.40 street of revenue | weighted choice per customer | Chains ~0.95 contract; independents ~0.15 |
| Order channel mix | 0.45 ecommerce, 0.30 EDI, 0.25 phone/rep | weighted choice | EDI skews to national accounts |
| Route stops per route per day | mean 16 (range 10-24) | normal(16, 3) | Urban routes higher count, smaller drops |
| Cases per stop | median 35, p90 120 | lognormal | |
| Active SKUs ordered per customer per quarter | median 65 (range 20-300) | lognormal | |
| Customer activity skew | top 10% of customers = ~60% of revenue | zipf s=1.05 | National accounts dominate the head |
| SKU velocity skew | top 20% of SKUs = ~75% of cases | pareto alpha=1.3 | Long tail of special orders |
| Credit memo rate | 0.025 of invoice lines | poisson per customer-month | Reasons: shorts 0.4, quality 0.25, pricing 0.2, other 0.15 |
| Manual price override rate | 0.04 of order lines | weighted choice | Concentrated in street-priced lines |
| Substitution rate | 0.015 of order lines | weighted choice | Spikes during outages |
| Rebate accrual rate | 0.03 of eligible COGS (range 0.01-0.08) | per agreement, normal | ~0.60 of purchase spend is rebate-eligible |
| Shelf life by temperature zone | frozen 180-365d, cooler 7-45d, dry 90-540d | uniform within zone band | Drives FEFO picking and expiry write-offs |
| Lots on hand per active SKU | 1-4 | poisson(1.8) | Fast movers turn lots weekly |
| Gross margin per invoice line | mean 0.16 (range 0.05-0.35) | normal(0.16, 0.06) | Negative-margin lines ~0.01 (overrides, cost spikes) |
| Recalls per year | 4-10 events | poisson(6) | Most touch <0.5% of active lots |

## Business Rules and Invariants

- Invoice total = sum of line extended amounts + delivery/fuel surcharges + tax - discounts.
- Invoice line extended amount = shipped qty * unit price - line discount.
- Shipped qty <= ordered qty per line; over-shipment requires an override record.
- Line fill rate = shipped qty / ordered qty, in [0, 1]; order fill derived from lines.
- delivered_at >= loaded_at >= pick_completed_at >= order_submitted_at.
- Every invoiced delivery stop has a proof_of_delivery record or a validated delivery_exception.
- Inventory balance roll-forward holds per item-location-lot-day: opening + receipts - picks - returns_out + returns_in + adjustments = closing.
- Expiry-managed lines ship FEFO: shipped lot expiration_date >= delivery_date + customer min-shelf-life days.
- No shipment from a lot under quality_hold or recall hold.
- Contract-priced lines reference a contract_price row active on order date; otherwise line is street-priced.
- Manual override lines carry override_user and reason code; engine price retained for variance.
- Credit memo line references an original invoice line; credited qty <= shipped qty on that line.
- Rebate accrual = eligible qty * agreement rate for agreements active in the accrual period; settlement variance posts as true-up, never edits history.
- Every recall_lot joins to all shipments of that lot, and each shipped customer has a customer_notice.
- Route stop sequence numbers are unique and contiguous per route per day; POD timestamps non-decreasing in actual visit order.
- Order lines tie forward to pick tasks, delivery stops, invoice lines, and GL revenue at matching quantities.

## Controls and Reconciliations

| Control | Grain | Tolerance | Expected break rate |
| --- | --- | --- | --- |
| Order-to-invoice line tie (qty and amount) | order line per day | qty exact, $0.01 | 0.005 |
| Fill rate tie: ordered vs shipped vs invoiced qty | order line per day | exact | 0.01 |
| Inventory-to-GL valuation | item-location per month | 0.5% or $5k | 0.02 |
| Lot balance roll-forward | item-location-lot per day | zero | 0.002 |
| Perpetual vs cycle count | item-location per count | 1 case or 0.5% | 0.04 |
| Contract price variance (engine vs invoiced) | invoice line per day | $0.00 | 0.03 (mostly flagged overrides) |
| POD-to-invoice coverage | delivery stop per day | 100% coverage | 0.015 |
| Recall lot to shipped-customer trace | recall-lot | 100% coverage | 0.01 |
| Rebate accrual vs supplier settlement | agreement per quarter | 2% | 0.10 |
| Credit memo to original invoice link | credit memo line | 100% linkage | 0.008 |
| AP three-way match (PO/receipt/invoice) | PO line | qty exact, 1% price | 0.08 |
| Temperature exception to disposition | exception event | 100% dispositioned in 24h | 0.02 |

## Seasonality and Temporal Patterns

- Weekday shape: deliveries Mon-Sat with Mon and Thu peaks (restaurant restock); Sunday near zero; order entry peaks Sun and Wed evenings before peak delivery days.
- Intraday: order submissions cluster 16:00-23:00 ahead of cutoff; picking 22:00-06:00; deliveries 04:00-14:00; POD sync trickles until early evening.
- Annual: Nov-Dec holiday peak (+15-25% volume), January trough (-10-15%), spring banquet/graduation bump, summer tourism lift in hospitality segment.
- Education segment drops 60-80% June-August; healthcare flat year-round.
- Month-end: rebate accrual postings, credit memo cleanup, and inventory adjustments spike in the last 3 business days; quarter-end adds rebate claim submissions.
- Commodity volatility: produce, dairy, and protein costs reprice weekly; street prices lag cost moves by 1-2 weeks, compressing margin in up-markets.

## Controlled Imperfections

| Imperfection | Where it appears | Typical rate | Downstream symptom |
| --- | --- | --- | --- |
| duplicate_entity | CRM accounts vs ERP customers (same operator, multiple ship-tos) | 0.02 of accounts | Split purchase history; wrong contract eligibility |
| missing_xref | supplier_item to enterprise SKU mapping | 0.01 of supplier items | Receipts land on placeholder SKU; cost gaps |
| manual_override | pricing.price_override on order lines | 0.04 of order lines | Contract price variance breaks; margin leakage |
| late_arrival | driver_app POD and exception events (offline sync) | 0.05 of stops >4h late | Invoices issued before POD lands; rec breaks |
| conflicting_source_values | national account hierarchy: CRM vs billing parentage | 0.03 of chain accounts | Rebate and contract rollups disagree by source |
| duplicate_webhook | EDI inbound orders retransmitted or corrected | 0.01 of EDI orders | Duplicate/zombie orders needing cancellation |
| out_of_order_events | route stop events arriving out of visit sequence | 0.02 of stops | Implausible stop timelines in delivery fact |
| stale_mapping | contract_price not refreshed after renewal | 0.02 of active contracts | Wrong invoice price; retro rebill waves |
| restatement_reversal | invoice rebill (credit-rebill pairs) after pricing fixes | 0.01 of invoices | Same delivery appears twice net of credit |
| typo | phone/rep order entry (qty and item keying errors) | 0.005 of phone-entered lines | Returns and credits with reason=entry_error |
| orphan_fk | invoice line referencing expired promotion or purged contract | 0.003 of invoice lines | Margin report joins drop lines |
| format_drift | supplier catalog and price files (pack/size, UoM columns) | ~1 supplier file per month | PIM load failures; UoM conversion errors |
