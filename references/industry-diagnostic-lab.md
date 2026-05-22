# Industry: Diagnostic Laboratory Network

## Domains

patient, provider, clinic, scheduling, requisition, order, specimen, accession, test_catalog, lab_instrument, result, critical_value, result_delivery, courier, kit, inventory, claims, payer, privacy, quality.

## Source Systems

Patient service centre scheduling, EMR integration gateway, laboratory information system, accessioning system, analyzer/instrument middleware, courier logistics, patient/provider portal, billing/claims, payer portal, quality management, privacy/audit platform, inventory system, data warehouse.

## Core Tables

- `patient.patient`, `patient.identifier`, `patient.consent`
- `provider.provider`, `provider.clinic`, `provider.emr_connection`
- `scheduling.appointment`, `scheduling.site_wait_time`
- `orders.requisition`, `orders.lab_order`, `orders.order_status_history`
- `specimen.specimen`, `specimen.collection_event`, `specimen.accession`
- `lab.test_panel`, `lab.test_component`, `lab.instrument`, `lab.instrument_qc`
- `result.result_component`, `result.result_status_history`, `result.critical_value_notification`
- `courier.route`, `courier.pickup_event`, `courier.temperature_log`
- `billing.charge`, `claims.claim`, `claims.remittance`
- `quality.nonconformance`, `privacy.sensitive_access_log`

## Facts and Dimensions

- `fact_lab_order`: one lab order.
- `fact_specimen_event`: one specimen lifecycle event.
- `fact_result_component`: one result component per specimen/test.
- `fact_turnaround_time`: one order or component SLA measurement.
- `fact_critical_value_notification`: one critical result notification.
- `fact_claim_line`: one billed claim line.

Dimensions: patient, provider, clinic/site, test, specimen_type, instrument, courier_route, payer, date, time, result_status.

## Dataflows

- Order-to-result: EMR/requisition -> order -> specimen collection -> courier pickup -> accession -> instrument run -> result validation -> provider/patient delivery -> billing.
- Critical value: result validation -> critical flag -> provider notification -> acknowledgement -> compliance reporting.
- At-home kit: kit shipped -> sample collected -> courier/mail receipt -> accession -> result -> billing.

## Controls

- Every resulted test ties to an accessioned specimen.
- Critical values require notification within SLA.
- Result amendments link to original result.
- Claims tie to orders and remittances.
- Sensitive access events have permitted purpose or investigation case.

## Imperfections

Rejected specimens, insufficient quantity, hemolysis, late courier pickup, instrument QC failure, amended results, duplicate patients, missing provider identifiers, delayed result delivery, payer denials, break-glass access, lost kits.
