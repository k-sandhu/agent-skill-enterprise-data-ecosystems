# Industry: Healthcare

Use for ambulatory, hospital, clinic, payer-provider, and health-system operating models. For diagnostic labs, also load `industry-diagnostic-lab.md`.

## Domains

patient, provider, scheduling, registration, encounter, clinical, orders, medication, lab, radiology, surgery, ADT, bed_management, billing, claims, payer, quality, privacy, care_management.

## Source Systems

EHR, practice management, scheduling, lab information system, radiology system, pharmacy system, medication administration, ADT/bed management, billing/claims, payer portal, patient portal, quality reporting, identity provider, data warehouse.

## Core Tables

- `patient.patient`, `patient.patient_identifier`, `patient.coverage`
- `provider.provider`, `provider.organization`, `provider_location`
- `scheduling.appointment`, `scheduling.appointment_status_history`
- `adt.admission`, `adt.transfer`, `adt.discharge`, `bed_management.bed_assignment`
- `clinical.encounter`, `clinical.diagnosis`, `clinical.procedure`, `clinical.observation`
- `orders.order`, `orders.order_status_history`
- `medication.medication_order`, `medication.administration`
- `lab.order`, `lab.specimen`, `lab.result`
- `billing.charge`, `claims.claim`, `claims.claim_line`, `claims.remittance`
- `privacy.sensitive_access_log`, `quality.measure_result`

## Facts and Dimensions

- `fact_encounter`: one patient encounter.
- `fact_patient_movement`: one ADT movement event.
- `fact_order`: one clinical order.
- `fact_medication_administration`: one medication administration event.
- `fact_charge`: one posted charge.
- `fact_claim_line`: one claim line.
- `fact_quality_measure`: one patient-measure-period.

Dimensions: patient, provider, facility, department, diagnosis, procedure, payer, plan, date, time, bed, medication.

## Dataflows

- Patient visit: registration -> appointment/check-in -> encounter -> orders/procedures -> charges -> claim -> remittance.
- Hospital stay: admission -> bed assignment -> transfers -> orders -> medication administration -> discharge -> coding -> billing.
- Quality reporting: clinical observations + diagnoses + procedures -> measure logic -> numerator/denominator -> submission.

## Controls

- Encounter charges tie to claims.
- Medication orders tie to administrations.
- ADT bed occupancy ties to capacity reports.
- Claims tie to remittances.
- Sensitive record access ties to permitted treatment/payment/operations purpose.

## Imperfections

Duplicate patients, merged MRNs, late charges, claim denials, amended results, invalid diagnosis/procedure combinations, cancelled appointments, no-shows, emergency transfers, stale insurance coverage, break-glass access events.
