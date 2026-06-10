# Enterprise Realism Patterns

## Contents

- Identifiers
- Effective Dating
- State Machines
- Roll-Forward Logic
- Reconciliation
- Data Quality
- Governance and Semantic Layer
- Security and Privacy
- Workflow and Human Review
- Documents
- Controlled Imperfections

## Identifiers

Major entities should have canonical IDs and source IDs. Examples:

- Customer: CRM account ID, ERP customer ID, billing customer ID, support org ID, legacy customer ID.
- Patient: enterprise patient ID, MRN, provincial/state health number surrogate, lab patient ID, payer member ID.
- Security: internal security ID, ISIN, CUSIP, SEDOL, Bloomberg ID, custodian security ID.
- Product: enterprise SKU, supplier item number, warehouse item ID, ecommerce SKU, legacy item number.
- Shipment: order ID, shipment ID, carrier PRO, container number, route ID, stop ID.

## Effective Dating

Use effective dating for relationships, assignments, contracts, prices, statuses, roles, hierarchies, coverage, locations, and ownership.

Common columns:

```text
effective_start_date
effective_end_date
valid_from
valid_to
current_flag
status
status_reason
created_at
updated_at
source_updated_at
ingested_at
```

## State Machines

Generate statuses through plausible event sequences, not random status values.

Examples:

- Payment: initiated, validated, screened, authorized, released, settled, returned, reversed.
- Subscription: trial_started, converted, upgraded, invoice_issued, payment_failed, dunning_started, renewed, cancelled, reactivated.
- Shipment: booked, picked_up, departed_origin, arrived_terminal, customs_cleared, out_for_delivery, delivered, invoiced.
- Lab order: ordered, specimen_collected, accessioned, test_performed, result_validated, result_delivered, claim_submitted.
- Work order: planned, released, in_progress, quality_hold, completed, closed, reworked, scrapped.

## Roll-Forward Logic

Use dependent records where balances or positions exist.

- Banking balance: opening balance + credits - debits + reversals + interest - fees = closing balance.
- Investment holding: beginning market value + purchases - sales + income +/- market movement +/- FX = ending market value.
- Private asset NAV: beginning NAV + capital calls - distributions +/- valuation change = ending NAV.
- Inventory: beginning inventory + receipts - consumption - shipments + adjustments - scrap = ending inventory.
- SaaS invoice: subscription + usage + overages - credits + tax = invoice total.

## Reconciliation

Add controls for major flows:

- Order-to-invoice.
- Inventory-to-GL.
- Custodian positions-to-internal holdings.
- Claim-to-remittance.
- Subscription-to-invoice.
- Specimen-to-result.
- Payment-to-bank statement.
- Shipment-to-delivery-to-billing.

Each reconciliation rule should define source dataset, target dataset, grain, tolerance, frequency, owner, severity, and expected break rate.

## Data Quality

Common rules:

- Required field present.
- Valid code.
- Foreign key exists.
- No duplicate active record.
- Valid date sequence.
- Valid state transition.
- Row count/source-to-target threshold.
- Late-arriving record detection.
- Stale reference data.
- Unmapped external identifier.
- Amount variance within tolerance.

Include expected failures, not just passing rules.

## Governance and Semantic Layer

Model:

- Data domains, owners, stewards, policies, certifications.
- Business glossary terms and competing definitions.
- Metrics with versions, calculation rules, components, owners, and certified datasets.
- Reports and dashboard dependencies.

Useful ambiguity examples: active customer, revenue, ARR, AUM, delivered, available balance, gross margin, on-time delivery, encounter, member, claim, eligible shipment.

## Security and Privacy

Classify sensitive data:

```text
public
internal
confidential
restricted
PII
PHI
PCI
financially_sensitive
trade_secret
```

Define row-level security, column masking, role permissions, access reviews, retention policies, consent or processing purpose, privileged access logs, and sensitive record access logs.

Never use real PII, PHI, PCI, employee, customer, patient, or account data.

## Workflow and Human Review

Realistic queues:

- Duplicate customer review.
- Unmapped securities.
- Claim denial review.
- GL reconciliation break.
- Inventory adjustment approval.
- Failed delivery resolution.
- Sensitive access review.
- Lab QC failure investigation.
- Privacy deletion request.

Workflow cases should include case type, related entity, status, priority, assigned queue, assigned user, created/due/resolved timestamps, SLA, comments, and resolution code.

## Documents

Represent document metadata even when binary files are not generated.

Examples: contracts, invoices, lab requisitions, clinical notes, delivery receipts, proof of delivery photos, capital call notices, manager statements, trade confirmations, purchase orders, inspection reports, spreadsheets, emails.

## Controlled Imperfections

Use explicit, documented imperfections. The build engine implements these as a closed enum, injects them at configured rates, and logs every one to `meta_imperfection_log` (see `references/generator-spec.md`):

- `missing_xref`: unmapped external/source identifiers.
- `duplicate_entity`: near-duplicate entities with fuzzed attributes.
- `late_arrival`: ingestion lag well past the event date.
- `orphan_fk`: references to hard-deleted parents.
- `conflicting_source_values`: systems disagree on the same attribute.
- `format_drift`: legacy batches with different date formats, casing, padding.
- `typo`: hand-keyed text noise.
- `restatement_reversal`: reversal + restated pairs that move totals.
- `out_of_order_events`: CDC/webhook sequence disorder.
- `duplicate_webhook`: retried event deliveries.
- `stale_mapping`: expired mappings still referenced.
- `manual_override`: human overrides with audit notes, clustered at period end.
- `null_field`: logged missingness beyond design-level null rates.

Each imperfection should trace to a scenario, rule, dataflow, or workflow case — and to a DQ rule or reconciliation that catches it. Typical rates are in `references/data-realism.md`.
