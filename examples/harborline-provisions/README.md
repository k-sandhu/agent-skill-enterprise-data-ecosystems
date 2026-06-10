# Harborline Provisions — Worked Example

A complete fictional foodservice distributor: CRM, ERP order-to-cash, contract pricing, WMS lots, TMS drivers/routes/deliveries, raw/staging/xref/canonical layers derived via SQL, warehouse facts and dims, mart and control views, DQ results, workflow queues, audit trail, and 11 logged controlled imperfections.

This spec is the primary teaching artifact for the build engine — it exercises most features documented in `references/generator-spec.md` (not shown: `scd2` history, `self_fk`, `soft_delete`, `price_endings`) and passes strict validation with a full realism score. When authoring a new ecosystem, copy patterns from here.

## Run It

```text
python scripts/validate_ecosystem_spec.py examples/harborline-provisions/ecosystem_spec.json
python scripts/build_sqlite_ecosystem.py  examples/harborline-provisions/ecosystem_spec.json --plan
python scripts/build_sqlite_ecosystem.py  examples/harborline-provisions/ecosystem_spec.json --out examples/harborline-provisions/build --force
python scripts/validate_sqlite_database.py --db examples/harborline-provisions/build/harborline_provisions.db --spec examples/harborline-provisions/ecosystem_spec.json --report examples/harborline-provisions/build/validation_report.md
python scripts/profile_sqlite_database.py --db examples/harborline-provisions/build/harborline_provisions.db --report examples/harborline-provisions/build/profile.md
```

At multiplier 1.0 this builds ~760k rows across 32 tables and 4 views in well under a minute; `--scale-multiplier 3` produces ~2.5M rows.

## Patterns Worth Copying

- `crm.account.created_at`: `sorted` + `backfill_share` — IDs correlate with onboarding dates and 65% of the book predates the data window, so volume grows ~7%/yr instead of ramping from zero.
- `erp.customer` is generated per CRM account with `parent_copy` — two systems share entities coherently; imperfections then make them disagree realistically.
- `erp.sales_order.rows`: `scale_by` on segment plus a heavy-tailed `per_parent_multiplier` — national chains buy ~5-9x what independents do and a whale tier emerges (top 5% of accounts ≈ a third of revenue).
- `erp.sales_order.warehouse_id`: FK affinity matching on region with 5% leakage.
- `erp.sales_order.order_date`: `{"type": "date", "min": "parent.created_at"}` — calendar-shaped activity that never predates the customer.
- `erp.product`: category drawn first, then name/pack/zone/shelf-life all conditioned on it — the product master cross-tabs cleanly.
- Order lifecycle state machine with right-censoring: recent orders legitimately sit in draft/allocated/picked states with NULL downstream timestamps.
- `tms.route` and `tms.delivery_stop` are **derived from shipped orders** — delivery dates, warehouses, stop sequencing, and arrival times are coherent by construction. Never wire delivery events to orders with a random FK.
- `erp.invoice` honors each customer's credit terms for due dates and ages into a collections lifecycle (overdue → in_collections → written_off); payments include partials and short-pays.
- Every imperfection is aimed at something that catches it: orphan products -> DQ-002, missing xref -> DQ-003, format drift -> DQ-004 via the staging date parse, invoice restatements -> the `control_recon_order_invoice` breaks.

## Things to Query

```sql
select * from mart_sales_daily order by order_date desc limit 14;
select aging_bucket, count(*), round(sum(invoice_total),2) from mart_ar_aging group by 1;
select * from control_recon_order_invoice order by abs(break_amount) desc limit 10;
select rule_code, count(*) from dq_rule_result_current group by 1;
select imperfection_name, count(*) from meta_imperfection_log group by 1 order by 2 desc;
select status, count(*) from erp_sales_order group by 1 order by 2 desc;  -- open pipeline near as_of
select c.segment, round(sum(f.extended_amount) / count(distinct c.customer_id)) as revenue_per_account
from wh_fact_order_line f join erp_customer c on c.customer_id = f.customer_key group by 1;
```
