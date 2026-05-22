# Industry: Foodservice Distribution

## Domains

customer, national_account, CRM, ecommerce, EDI, product_master, supplier, pricing, order_mgmt, warehouse, inventory, lot, temperature_zone, route, driver, proof_of_delivery, returns, claims, recall, rebate, finance.

## Source Systems

CRM, ecommerce ordering, EDI gateway, ERP, product information management, contract pricing engine, warehouse management, transportation management, driver mobile app, supplier portal, food safety/recall system, billing, finance/GL, data warehouse.

## Core Tables

- `crm.account`, `crm.contact`, `crm.sales_territory`
- `ecommerce.cart`, `ecommerce.order_event`
- `edi.inbound_order`, `edi.order_acknowledgement`
- `product.product`, `product.supplier_item`, `product.allergen`, `product.storage_requirement`
- `pricing.price_list`, `pricing.contract_price`, `pricing.rebate_agreement`
- `order_mgmt.sales_order`, `order_mgmt.sales_order_line`
- `warehouse.pick_wave`, `warehouse.pick_task`, `warehouse.load_task`
- `inventory.lot`, `inventory.inventory_movement`, `inventory.item_location_balance`
- `transport.route`, `transport.route_stop`
- `driver_app.proof_of_delivery`, `driver_app.delivery_exception`
- `food_safety.recall`, `food_safety.recall_lot`
- `billing.invoice`, `billing.invoice_line`, `finance.journal_entry`

## Facts and Dimensions

- `fact_order_line`: one sales order line.
- `fact_invoice_line`: one invoice line.
- `fact_inventory_movement`: one product-location-lot movement.
- `fact_inventory_balance_daily`: one product-location-lot-date.
- `fact_pick_task`: one warehouse pick task.
- `fact_delivery_stop`: one route stop.
- `fact_recall_impact`: one recall-lot-customer exposure.

Dimensions: customer, product, supplier, warehouse, lot, route, driver, sales_rep, price_contract, date, temperature_zone.

## Dataflows

- Order-to-cash: CRM/ecommerce/EDI order -> order management -> price resolution -> available-to-promise -> pick/load -> route delivery -> proof of delivery -> invoice -> GL.
- Recall impact: supplier recall -> affected lots -> warehouse inventory/customer shipments -> customer notices -> returns/credits.
- Pricing: contract price -> order line price -> invoice line -> rebate accrual -> margin reporting.

## Controls

- Order lines tie to pick tasks, delivery stops, invoice lines, and GL revenue.
- Inventory balances roll forward by lot and warehouse.
- Contract pricing variance flags manual overrides.
- Recall lots tie to all shipped customers.
- Fill rate ties ordered quantity to shipped quantity.

## Imperfections

Expired lots, quality holds, substitutions, short picks, route delays, missing delivery signatures, manual price overrides, national account hierarchy changes, duplicate customers, EDI order corrections, recall holds, temperature exceptions.
