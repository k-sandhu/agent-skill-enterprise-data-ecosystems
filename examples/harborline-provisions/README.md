# Harborline Provisions — Worked Example

A complete fictional foodservice distributor: CRM, ERP order-to-cash, contract pricing, WMS lots, TMS routes/deliveries, raw/staging/xref/canonical layers derived via SQL, warehouse facts and dims, mart and control views, DQ results, workflow queues, audit trail, and 11 logged controlled imperfections.

This spec is the primary teaching artifact for the build engine — it exercises every feature documented in `references/generator-spec.md` and passes strict validation with a full realism score. When authoring a new ecosystem, copy patterns from here.

## Run It

```text
python scripts/validate_ecosystem_spec.py examples/harborline-provisions/ecosystem_spec.json
python scripts/build_sqlite_ecosystem.py  examples/harborline-provisions/ecosystem_spec.json --plan
python scripts/build_sqlite_ecosystem.py  examples/harborline-provisions/ecosystem_spec.json --out examples/harborline-provisions/build --force
python scripts/validate_sqlite_database.py --db examples/harborline-provisions/build/harborline_provisions.db --spec examples/harborline-provisions/ecosystem_spec.json --report examples/harborline-provisions/build/validation_report.md
python scripts/profile_sqlite_database.py --db examples/harborline-provisions/build/harborline_provisions.db --report examples/harborline-provisions/build/profile.md
```

At multiplier 1.0 this builds ~240k rows across 31 tables and 4 views in a few seconds.

## Patterns Worth Copying

- `crm.account.created_at`: `sorted` + `backfill_share` — IDs correlate with onboarding dates and 65% of the book predates the data window, so volume grows ~7%/yr instead of ramping from zero.
- `erp.customer` is generated per CRM account with `parent_copy` — two systems share entities coherently; imperfections then make them disagree realistically.
- `erp.sales_order.warehouse_id`: FK affinity matching on region with 5% leakage.
- `erp.sales_order.order_date`: `{"type": "date", "min": "parent.created_at"}` — calendar-shaped activity that never predates the customer.
- Order lifecycle state machine with right-censoring: recent orders legitimately sit in draft/allocated/picked states with NULL downstream timestamps.
- `erp.invoice`, `erp.payment`, all staging/xref/core/warehouse tables: **derived via SQL**, so lineage is real and source defects propagate.
- Every imperfection is aimed at something that catches it: orphan products -> DQ-002, missing xref -> DQ-003, format drift -> DQ-004 via the staging date parse, invoice restatements -> the `control_recon_order_invoice` breaks.

## Things to Query

```sql
select * from mart_sales_daily order by order_date desc limit 14;
select aging_bucket, count(*), round(sum(invoice_total),2) from mart_ar_aging group by 1;
select * from control_recon_order_invoice order by abs(break_amount) desc limit 10;
select rule_code, count(*) from dq_rule_result_current group by 1;
select imperfection_name, count(*) from meta_imperfection_log group by 1 order by 2 desc;
select status, count(*) from erp_sales_order group by 1 order by 2 desc;  -- open pipeline near as_of
```
