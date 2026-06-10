# Industry: Retail and Ecommerce

## Operating Context

- Omnichannel retailer: ~120 physical stores plus ecommerce site and mobile app; revenue mix ~0.68 store / 0.27 ecommerce / 0.05 marketplace.
- Money flows: customer tender (card, cash, gift card, wallet) -> POS/OMS -> payment processor settlement -> GL; merchandise cost flows via vendor POs and trade allowances.
- Typical scale anchors: 1.5M active customers, 45k active SKUs, 2 distribution centers, 9M order/transaction lines per month.
- Margin drivers: initial markup, promotion/markdown depth, shrink, return processing cost, supply chain cost-to-serve.
- Constraints: PCI for cardholder data, consumer privacy regimes (consent, deletion requests), gift card escheatment, product safety recalls.
- Loyalty program identifies ~0.45 of transactions; identified sales fund personalization and promotion targeting.

## Domains

merchandising, inventory, store operations, ecommerce, order management, fulfillment, pricing and promotions, loyalty and marketing, customer, supply chain, payments, returns, finance, workforce

## Source Systems

| System | Role | System-of-record domains | Typical data quirks |
| --- | --- | --- | --- |
| POS platform | Store transactions, tenders, store returns | store sales, tenders | offline-mode batches arrive late; trans voided then re-rung; cashier override codes free-text |
| Ecommerce platform | Web/app storefront, cart, checkout | online orders, sessions | duplicate_webhook on order events; abandoned carts never closed; guest checkout splinters identity |
| Order management system (OMS) | Order orchestration, split shipments, BOPIS | order lifecycle, allocations | order lines re-split after allocation; status events out_of_order |
| Merchandising system | Item master, hierarchy, cost, vendor | product, cost, supplier | SKU re-use after discontinuation; hierarchy reorgs mid-season; pack/each conversion errors |
| Warehouse management system (WMS) | DC receiving, pick/pack/ship | DC inventory, shipments | cycle-count adjustments dumped end-of-day; carton-level not line-level confirms |
| Store inventory system | Store on-hand, counts, transfers | store inventory | negative on-hand persists; counts override perpetual without reason codes |
| Pricing and promotion engine | Price changes, promos, markdowns | price, promotion | overlapping promos stack unexpectedly; price effective-dating gaps |
| Loyalty platform | Members, points, tiers, offers | loyalty member, points ledger | duplicate members per email/phone; points accrual lags sale by 1-2 days |
| Payment processor gateway | Auth, capture, settlement, chargebacks | payment events | settlement file format_drift; partial captures; orphan refunds |
| Customer service platform | Cases, appeasements, return authorizations | service cases | appeasement credits not linked to orders; free-text reason codes |
| ERP / finance system | GL, AP, vendor invoices, allowances | GL, AP | vendor invoice matched at PO not receipt; allowance accruals trued up quarterly |
| Marketing automation platform | Campaigns, sends, attribution | campaign touches | click bots inflate engagement; UTM tagging inconsistent |

## Core Tables

- core.product, core.product_hierarchy, core.supplier, core.cost_record, core.price_record
- core.location (stores, DCs, web), core.customer, core.loyalty_member, core.loyalty_points_ledger
- core.sales_transaction, core.sales_transaction_line, core.tender, core.order_header, core.order_line
- core.shipment, core.fulfillment_task, core.return_header, core.return_line, core.return_disposition
- core.inventory_position, core.inventory_movement, core.inventory_adjustment, core.cycle_count
- core.purchase_order, core.purchase_order_line, core.asn, core.receipt, core.transfer_order
- core.promotion, core.promotion_applied, core.markdown_event, core.gift_card, core.gift_card_transaction
- core.payment_auth, core.payment_capture, core.payment_settlement, core.chargeback
- core.campaign, core.campaign_touch, core.web_session, core.cart, core.cart_item, core.service_case
- xref.product_source_identifier, xref.customer_source_identifier, xref.location_source_identifier
- stg_pos_transaction, stg_ecom_order, stg_oms_order_event, stg_wms_shipment, stg_merch_item, stg_processor_settlement
- workflow.inventory_adjustment_approval, workflow.duplicate_member_review, workflow.chargeback_dispute

## Warehouse Facts and Dimensions

- fact_sales_line — grain: one row per transaction line per sale or return event (returns negative); measures: units, gross_sales, discount_amount, net_sales, cost, margin.
- fact_order_line_status — grain: one row per order line per status event; measures: event_count, hours_in_prior_status.
- fact_inventory_position — grain: one row per SKU per location per day (semi-additive on-hand, on-order, in-transit, reserved).
- fact_inventory_movement — grain: one row per SKU per location per movement event (receipt, sale, transfer, adjustment, shrink, RTV).
- fact_payment — grain: one row per payment event (auth, capture, refund, chargeback) per order.
- fact_promotion_applied — grain: one row per promotion per transaction line where applied; measures: promo_discount, baseline_price.
- fact_loyalty_activity — grain: one row per member per points event (earn, burn, expire, adjust).
- fact_web_session — grain: one row per session; measures: page_views, cart_adds, checkout_started_flag, converted_flag.
- fact_return_line — grain: one row per return line per disposition event.
- Dimensions: dim_date, dim_product, dim_product_hierarchy, dim_location, dim_customer, dim_loyalty_tier, dim_promotion, dim_channel, dim_tender_type, dim_supplier, dim_return_reason, dim_employee.

## Critical Dataflows

- Store sales: POS transaction -> nightly TLOG batch -> stg_pos_transaction -> core.sales_transaction -> fact_sales_line -> mart_sales / GL sales journal.
- Ecommerce order-to-cash: cart -> checkout -> payment_auth -> OMS allocation -> WMS pick/pack -> ship confirm -> capture -> settlement file -> payment-to-settlement recon.
- BOPIS: online order -> store allocation -> store pick task -> customer pickup confirm -> sale recognized at pickup -> unclaimed cancel after 5 days.
- Returns: return initiated (store or RMA) -> received -> inspected -> disposition (restock / damage / RTV) -> refund issued -> inventory and GL update.
- Replenishment: forecast -> order plan -> purchase_order -> vendor ASN -> DC receipt -> putaway -> store transfer -> store receipt.
- Promotion lifecycle: promo created -> approved -> published to POS/ecom -> applied at sale -> lift measurement -> markdown takeover at season end.
- Loyalty accrual: identified sale -> points earn event (T+1) -> ledger -> tier evaluation -> offer issuance -> redemption at POS/checkout.
- Inventory integrity: perpetual position -> cycle counts -> adjustments -> shrink recognition -> inventory-to-GL recon.

## State Machines

- Ecommerce order line: placed -> payment_authorized (0.96, minutes) | auth_declined (0.04); payment_authorized -> allocated (0.97, lognormal median 2h p90 12h) | cancelled_oos (0.03); allocated -> picked -> packed -> shipped (0.985, lognormal median 1 business day p90 3) | cancelled_by_customer (0.015); shipped -> delivered (0.97, lognormal median 3 days p90 7) | delivery_exception (0.03); delivered -> returned (0.20 within 30 days) | closed (0.80).
- Store transaction: rung -> tendered -> completed (0.985) | voided (0.012) | suspended_resumed (0.003); completed -> returned (0.08 within 60 days).
- BOPIS order: placed -> store_allocated -> picked (median 4h, p90 24h) -> ready_for_pickup -> picked_up (0.88, median 1 day) | cancelled_unclaimed (0.12, after 5 days).
- Return: initiated -> received (0.93 for mail RMA, lognormal median 6 days p90 14; 1.0 immediate in store) | abandoned (0.07); received -> inspected (within 2 business days) -> restocked (0.70) | salvage_damage (0.20) | return_to_vendor (0.10); refund issued within 1-3 business days of receipt.
- Purchase order: created -> approved (0.95, 1-2 business days) | rejected (0.05); approved -> sent -> asn_received (0.85) | no_asn (0.15); -> received_full (0.78) | received_short (0.18) | cancelled (0.04); received -> closed_matched (0.92) | invoice_discrepancy (0.08).
- Chargeback: filed -> evidence_submitted (0.65, within 7 business days) | accepted_loss (0.35); evidence_submitted -> won (0.45) | lost (0.55); end-to-end lognormal median 30 days p90 75.
- Promotion: drafted -> approved (0.90, 2-5 business days) | reworked (0.10); approved -> published -> active -> expired; emergency_pulled (0.02 of active).

## Volumetrics and Distributions

| Metric | Typical value or range | Distribution | Notes |
| --- | --- | --- | --- |
| Store transactions per store per day | 350 (180-900) | lognormal | flagship stores in upper tail |
| Ecommerce orders per day | 6,000 (4k-9k) | poisson by day, seasonal multiplier | peaks 4-6x in holiday |
| Units per basket, store | median 2.4, mean 3.1 | lognormal | grocery-adjacent categories raise it |
| Units per order, ecommerce | median 1.8, mean 2.6 | lognormal | single-item orders ~0.42 of orders |
| Average basket value, store | $42 (p90 $110) | lognormal | mean $55 |
| Average order value, ecommerce | $85 (p90 $220) | lognormal | free-shipping threshold bunches at $75 |
| Orders per active customer per year | 3.2 | zipf s=1.15 over customers | top 10% of customers = ~55% of revenue |
| Loyalty penetration (identified sales) | 0.45 of transactions, 0.58 of revenue | n/a | members spend ~1.6x non-members |
| Return rate, store channel | 0.08 of units | beta(8,92) by category | electronics 0.10, basics 0.04 |
| Return rate, ecommerce channel | 0.20 of units | beta(20,80) by category | apparel 0.28, hardlines 0.10 |
| Promotion participation | 0.38 of units sold on some promo | weighted choice by promo type | holiday weeks reach 0.55 |
| Promotion lift vs baseline | 1.6x median (1.2x-3.5x) | lognormal | deep discount (>=30%) skews high; ~0.25 of lift is pull-forward |
| Inventory turns per year | 5.5 blended (3 fashion - 12 consumables) | normal by category | sd 1.2 within category |
| Shrink rate | 0.016 of retail sales | beta(16,984) by store | worst-decile stores >0.03; ~0.55 external theft, 0.25 internal, 0.20 process |
| Active SKU count | 45,000 | n/a | 15% churn per year; long tail: bottom 50% of SKUs = ~8% of units |
| SKU velocity skew | top 10% of SKUs = ~60% of units | zipf s=1.1 | drives allocation logic |
| Web sessions to order conversion | 0.025 sessions convert | beta | cart-to-checkout 0.35, checkout-to-order 0.70 |
| Chargeback rate, ecommerce | 0.006 of orders | poisson | store card-present ~0.0005 |
| Gift card breakage | 0.08 of issued value | n/a | recognized over 24 months |
| PO lines per purchase order | median 12, p90 60 | lognormal | replenishment POs smaller than seasonal buys |

## Business Rules and Invariants

- transaction total = sum(line extended price) - sum(line discounts) + tax; tender total = transaction total (split tenders sum exactly).
- net_sales = gross_sales - discount_amount; margin = net_sales - cost; promo_discount <= baseline_price * units.
- order line lifecycle ordering: placed_at <= authorized_at <= allocated_at <= picked_at <= packed_at <= shipped_at <= delivered_at.
- return line references an original sale line; returned units cumulative <= sold units per sale line; refund amount <= amount paid net of prior refunds.
- captured amount <= authorized amount per auth; sum(captures) + sum(refunds reversed) reconciles to settlement net of fees.
- inventory roll-forward per SKU per location per day: beginning on-hand + receipts + transfers_in - sales - transfers_out + adjustments + returns_restocked = ending on-hand.
- reserved quantity <= on-hand quantity (violations only via documented oversell imperfection).
- every sale line price traces to an effective price_record or promotion_applied row at transaction timestamp; no effective-dating overlap per SKU/location/price type.
- points ledger balance per member = sum(earn) - sum(burn) - sum(expire) + sum(adjust); never negative.
- gift card liability = issued + reloads - redemptions - breakage recognized; card balance never negative.
- receipt quantity <= PO line quantity + over-receipt tolerance (0.05); invoice matched quantity <= received quantity.
- BOPIS sale recognized at pickup_confirmed_at, not placed_at; unclaimed orders auto-cancel and reverse allocation.

## Controls and Reconciliations

| Control | Grain | Tolerance | Expected break rate |
| --- | --- | --- | --- |
| POS TLOG to GL sales journal | store per day | $1.00 | 0.02 of store-days |
| Tender to processor settlement | store/channel per settlement day | $0.50 per batch | 0.03 of batches |
| OMS orders to ecommerce platform orders | order per day | count exact | 0.005 of orders (late events) |
| Shipped units (WMS) to OMS ship confirms | shipment per day | count exact | 0.01 of shipments |
| Perpetual inventory to cycle count | SKU per location per count | 2 units or 2% | 0.12 of counted SKUs adjusted |
| Inventory valuation to GL | location per month | 0.5% of value | 0.05 of location-months |
| Refunds to return receipts | return per day | $0.50 | 0.02 of returns (appeasements unlinked) |
| Loyalty points liability to ledger | member tier per month | 0.1% of liability | 0.01 of months |
| Gift card liability roll-forward | program per day | $5.00 | 0.005 of days |
| PO receipt to vendor invoice (3-way match) | PO line | 2% price, 5% qty | 0.08 of PO lines to discrepancy queue |
| Promotion forecast to actual lift | promotion | reporting only | n/a (review threshold lift < 1.1x) |

## Seasonality and Temporal Patterns

- Weekday shape, store: Sat ~1.5x weekday average, Sun ~1.2x, Mon-Tue lowest; ecommerce flatter with Mon-Tue peak and Sun-evening browse spike.
- Annual: Nov-Dec ~2.0-2.5x average weekly sales (peak week 4-6x for ecommerce); January return surge (return rate +40% relative); back-to-school bump Aug; post-holiday markdown depth peaks Jan and Jul.
- Intraday, store: ramp from open, lunch bump, peak 16:00-19:00; ecommerce peaks 11:00-14:00 and 20:00-23:00 local.
- Promotion cadence: weekly circular cycle starting Wednesday/Thursday; major event spikes (holiday kickoff, mid-summer sale) with 1-2 week pull-forward dip after.
- Inventory: receipts cluster Mon-Wed at DCs; store transfers peak before weekend; cycle counts scheduled low-traffic mornings; fiscal month-end adjustment spike for shrink accruals.
- Fiscal calendar: 4-5-4 retail calendar; quarter close drives allowance true-ups and markdown accrual restatements in week 1 of new quarter.

## Controlled Imperfections

| Imperfection | Where it appears | Typical rate | Downstream symptom |
| --- | --- | --- | --- |
| late_arrival | offline POS TLOG batches | 0.01 of store-days, 1-3 days late | sales journal restated; daily flash vs final mismatch |
| duplicate_webhook | ecommerce order events to OMS | 0.008 of order events | inflated order counts until dedup; double allocation attempts |
| out_of_order_events | OMS status stream | 0.015 of order lines | shipped_at before picked_at; state machine violations |
| duplicate_entity | loyalty members (email vs phone signup) | 0.04 of members | split points balances; member count inflated; review queue |
| missing_xref | marketplace SKUs to enterprise SKU | 0.03 of marketplace items | unmapped sales bucket; margin unreportable for those lines |
| orphan_fk | return lines to original sale line (legacy receipts) | 0.02 of return lines | blind returns; return-rate denominators disputed |
| conflicting_source_values | on-hand: store system vs WMS vs OMS availability | 0.05 of SKU-locations daily | oversells; phantom availability; allocation failures |
| format_drift | processor settlement file layout | 2-3 times per year | settlement recon breaks spike for 1-2 days |
| stale_mapping | store-to-region hierarchy after reorg | 0.01 of locations per reorg | regional sales misallocated for 1-2 weeks |
| manual_override | store inventory adjustments without reason code | 0.10 of adjustments | shrink misclassified as process error |
| restatement_reversal | post-void and re-ring at POS | 0.012 of transactions | gross sales overstated intraday; net corrected nightly |
| typo | cashier-keyed SKU on unscannable items | 0.003 of store lines | wrong product velocity; price override events |
| missing_xref | guest checkout to known customer identity | 0.30 of ecommerce orders unidentified | loyalty penetration understated; CLV undercounted |
| stale_mapping | promotion published to POS after start date | 0.01 of promotions | price mismatch day 1; appeasement refunds at service desk |
