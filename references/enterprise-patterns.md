# Enterprise Realism Patterns

## Contents

- Identifiers
- Effective Dating
- State Machines
- Roll-Forward Logic
- Reconciliation
- Data Quality
- Governance and Semantic Layer
- Code as Part of the Ecosystem
- SQL Flow and Complexity
- Security and Privacy
- Workflow and Human Review
- Documents
- Human-Entered Mappings
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

## Code as Part of the Ecosystem

An enterprise data ecosystem is data **plus the code that moves it**. A database full of tables with no view definitions, procedures, functions, scheduled jobs, or extract definitions reads as synthetic. Represent code in two places:

1. **As shipped SQL artifacts.** The build engine emits `sqlite/01_schema.sql` (DDL), `02_indexes.sql`, `03_derivations.sql` (the ELT scripts — real, runnable lineage SQL), and `04_views.sql` (every view definition). For non-SQLite targets, render DDL with `scripts/generate_ddl.py` and author stored-procedure/function/extract source as `.sql` files alongside the spec.
2. **As catalog data inside the database.** Real enterprises carry routine source in the catalog (`information_schema.routines`, `pg_proc`, `sys.sql_modules`). Model a `catalog.code_object` table — object name, object type (`view`, `procedure`, `function`, `extract`, `etl_script`), language, source text, owner, created/last-altered dates, deployment notes — plus `catalog.lineage_edge` rows linking code objects to the tables they read and write.

Code objects worth modeling:

- **View definitions** for every rung of the view stack. In SQLite these can self-register: a derivation may `insert into catalog.code_object select name, 'view', sql, ... from sqlite_master where type = 'view'` — the catalog then provably matches the deployed code.
- **Stored procedures**: period-end close, `rebuild_mart_*` refresh procs for materialized views, archive/purge jobs, recon runners. On SQLite they cannot execute, so store realistic source for the target platform as catalog rows and pair each with `integration.job` / `job_run` history showing it executing on a schedule (with occasional failures).
- **User-defined functions**: fiscal-period lookup, business-days-between, FX conversion, masking helpers — referenced by name inside view/procedure source text.
- **Extract definitions**: the SELECT statement, target format (CSV/SFTP/API), destination system, schedule, and owner for every outbound feed — plus run history and a row-count control per extract.
- **Ad-hoc and shadow scripts**: one or two analyst-owned scripts with no owner review, referenced by a `manual.*` upload — realistic governance debt.

Rules: stored source text must be real SQL referencing tables that exist in the ecosystem (never lorem ipsum); every procedure/extract appears in lineage and has job runs; at least one code object should be stale (references a renamed column) and flagged by a DQ rule or noted as known debt.

## SQL Flow and Complexity

Derivation SQL is part of the deliverable — practitioners read it. It must flow logically rung to rung (see "The Layered Warehouse Stack" in `common-layers.md`) and carry realistic, graduated complexity. Target profile per rung:

| Rung | Typical statement shape |
| --- | --- |
| Landing -> staging | Single-source select: `trim`/`upper` normalization, `case`-guarded date parsing (drifted formats land NULL), dedup via `group by` natural key or `not exists` anti-join against earlier batch rows. |
| Staging -> canonical | 3-5 way joins through `xref` crosswalks; survivorship as ordered `case` over source priority; `left join` where coverage is genuinely partial; quarantine pattern (`where ... is not null`) for orphans. |
| Canonical -> dims/facts | 4-8 way joins (canonical + operational + reference + calendar); explicit grain enforced with `group by`; degenerate dimensions carried through; measures via `sum(case when ...)`. |
| Facts -> normalized views | Wide re-joins of fact to all its dims; business column aliases; no aggregation. |
| Normalized -> business views | Aggregation with `group by`, window functions (`sum() over`, `row_number`, `lag` for period-over-period), as-of/current filters, bucket `case` ladders (aging, tiers). |
| Business -> materialized/BU views | Views on views: select from `bv_*`/`mv_*`, apply BU filters, manual-mapping joins, renamed business terms. Modest SQL, deep dependency chain. |

Guidance:

- Complexity should be **load-bearing**: every join is there because the grain or mapping demands it, every `left join` actually loses or keeps rows. Decorative complexity (joins that change nothing) is noise.
- Mix join types deliberately: inner where integrity is enforced, left where coverage is partial, anti-joins (`not exists`) for exception/DQ views.
- Reuse the same business rule in two places with a slight variation (one filters test accounts, one does not) — that is how real metric drift happens; pair it with a recon control.
- No `random()` or `datetime('now')` — derive variation from existing columns; determinism is a contract.

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

## Human-Entered Mappings

Enterprises run on hand-maintained mapping data — spreadsheets an analyst uploads that become load-bearing. Always model this at medium/high realism; see "Human-Entered Mapping Tables" in `common-layers.md` for the table shape. The patterns that make it ring true:

- **Entered at one layer, absent at others.** The mapping is inserted beside staging or the marts; landing and source systems have never heard of it. Do not backport human-entered values upstream.
- **Applied asymmetrically.** One BU view joins the mapping; a sibling view uses the raw code. The resulting metric discrepancy is intentional — document it and aim a reconciliation control at it.
- **Imperfect by nature.** 85-95% coverage with an `'UNMAPPED'` fallback bucket, stale rows for retired codes, duplicate/conflicting rows from re-uploads, an unapproved batch — each feeding a DQ rule or mapping-request workflow queue.
- **Audited like human work.** `uploaded_by`, `uploaded_at`, `source_file_name`, approval flags; uploads cluster near period end and reorganizations.

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
