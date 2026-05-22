# Industry: Logistics

## Domains

customer, order, shipment, booking, transport, asset, route, leg, stop, tracking, warehouse, customs, carrier, driver, document, billing, claims, compliance.

## Source Systems

Order management, transportation management, warehouse management, driver mobile app, carrier portal, EDI gateway, GPS/telematics, customs brokerage, billing, claims platform, document management, data warehouse.

## Core Tables

- `order_mgmt.order`, `order_mgmt.order_line`
- `shipment.shipment`, `shipment.shipment_line`, `shipment_container`
- `transport.route`, `transport.leg`, `transport.stop`, `transport.carrier_assignment`
- `asset.truck`, `asset.trailer`, `asset.container`, `asset.driver`
- `tracking.tracking_event`, `tracking.location_ping`
- `warehouse.pick_task`, `warehouse.load_task`, `warehouse.crossdock_event`
- `customs.entry`, `customs.release_event`
- `driver_app.proof_of_delivery`, `driver_app.exception_photo`
- `billing.freight_invoice`, `billing.accessorial_charge`
- `claims.claim`, `document.document`

## Facts and Dimensions

- `fact_shipment`: one shipment.
- `fact_shipment_event`: one shipment tracking event.
- `fact_route_stop`: one route stop.
- `fact_asset_utilization_daily`: one asset-date.
- `fact_freight_invoice_line`: one freight invoice charge line.
- `fact_claim`: one claim.

Dimensions: customer, carrier, route, asset, driver, location, shipment_status, service_level, date, commodity.

## Dataflows

- Shipment-to-delivery: order -> booking -> shipment -> legs/stops -> tracking events -> proof of delivery -> invoice -> claim when needed.
- Customs: shipment -> customs documents -> entry filing -> hold/release -> delivery eligibility.
- Carrier billing: carrier invoice -> rated charges -> accessorial validation -> customer invoice.

## Controls

- Shipment delivered status requires proof of delivery or validated exception.
- Freight invoice charges tie to shipment legs and rate agreements.
- Carrier invoice ties to customer invoice margin.
- Customs release required before cross-border delivery.
- Tracking event sequence must be plausible.

## Imperfections

Late carrier events, duplicate EDI messages, missing proof of delivery, damaged goods claims, detention charges, customs holds, GPS gaps, split shipments, reroutes, failed delivery attempts, manual accessorial overrides.
