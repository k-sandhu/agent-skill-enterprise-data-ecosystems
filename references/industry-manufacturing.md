# Industry: Manufacturing and Industrial Services

## Domains

product, engineering, BOM, routing, production, work_order, MES, machine, inventory, lot, serial, quality, maintenance, procurement, field_service, warranty, IoT, finance.

## Source Systems

ERP, product lifecycle management, manufacturing execution system, warehouse management, quality management, maintenance management, field service platform, supplier portal, SCADA/historian, IoT platform, finance/GL.

## Core Tables

- `product.product`, `product.revision`, `product.bom`, `product.bom_component`
- `production.routing`, `production.operation`, `production.work_order`, `production.work_order_operation`
- `mes.production_event`, `mes.machine_event`
- `inventory.item_location_balance`, `inventory.inventory_movement`, `inventory.lot`, `inventory.serial_number`
- `quality.inspection`, `quality.defect`, `quality.nonconformance`, `quality.corrective_action`
- `maintenance.asset`, `maintenance.work_order`, `maintenance.pm_schedule`
- `field_service.service_case`, `field_service.installed_asset`, `field_service.service_visit`
- `warranty.claim`, `iot.sensor_reading`

## Facts and Dimensions

- `fact_production_order`: one work order.
- `fact_operation_event`: one work order operation event.
- `fact_inventory_movement`: one item-location-lot movement.
- `fact_inventory_balance_daily`: one item-location-lot-date.
- `fact_quality_defect`: one defect per inspection.
- `fact_machine_downtime`: one downtime interval.
- `fact_service_visit`: one field service visit.

Dimensions: product, component, lot, serial, location, machine, supplier, defect_code, work_center, date, technician.

## Dataflows

- Work-order-to-inventory: planned order -> material issue -> operation completion -> quality inspection -> finished goods receipt -> inventory balance -> GL.
- Procure-to-production: purchase order -> receipt -> inspection -> lot assignment -> material issue.
- Service-to-warranty: customer case -> installed asset -> service visit -> part replacement -> warranty claim.

## Controls

- Inventory balances roll forward from movements.
- Material consumption ties to BOM and work orders.
- Finished goods receipts tie to completed work orders.
- Scrap and rework tie to quality defects.
- Maintenance downtime ties to production capacity loss.

## Imperfections

Lot genealogy gaps, cycle count adjustments, quality holds, scrap, rework, machine downtime, late supplier receipts, substitute parts, stale standard costs, missing serial scans, sensor dropouts.
