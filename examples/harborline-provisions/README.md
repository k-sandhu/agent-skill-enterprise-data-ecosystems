# Harborline Provisions — Worked Example

A complete fictional foodservice distributor modeling the **full layered warehouse stack** end to end: CRM, ERP order-to-cash, contract pricing, WMS lots, TMS drivers/routes/deliveries; landing (`raw_*`) and staging (`stg_*`) tables per source feed; `xref`/canonical normalization; warehouse facts and dims; a stacked view tier (`nv_*` normalized → `bv_*` business → `mv_*` materialized → `mart_<bu>_*` per-business-unit); a human-entered GL mapping applied asymmetrically across finance vs sales-ops; a code-object catalog (`catalog.code_object`/`lineage_edge`) with self-registered views and authored procedures/functions/extracts; reconciliation and DQ views; workflow queues; audit trail; and 13 logged controlled imperfections.

This spec is the primary teaching artifact for the build engine — it exercises most features documented in `references/generator-spec.md` (not shown: `scd2` history, `self_fk`, `soft_delete`, `price_endings`) and passes strict validation with a full realism score. When authoring a new ecosystem, copy patterns from here.

## Run It

```text
python scripts/validate_ecosystem_spec.py examples/harborline-provisions/ecosystem_spec.json
python scripts/build_sqlite_ecosystem.py  examples/harborline-provisions/ecosystem_spec.json --plan
python scripts/build_sqlite_ecosystem.py  examples/harborline-provisions/ecosystem_spec.json --out examples/harborline-provisions/build --force
python scripts/validate_sqlite_database.py --db examples/harborline-provisions/build/harborline_provisions.db --spec examples/harborline-provisions/ecosystem_spec.json --report examples/harborline-provisions/build/validation_report.md
python scripts/profile_sqlite_database.py --db examples/harborline-provisions/build/harborline_provisions.db --report examples/harborline-provisions/build/profile.md
```

At multiplier 1.0 this builds ~855k rows across 43 tables and 13 views in well under a minute; `--scale-multiplier 3` produces ~2.6M rows.

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
- **Landing + staging per feed**: one `raw_*` table per source feed (CRM, ERP orders, ERP invoices, WMS inventory) landed as text with file/batch ids and `ingested_at`, then a `stg_*` table per landing table that trims, types, dedups (`row_number`), and parses dates with a `case`-guard so drifted formats land NULL. `format_drift` corrupts the landed dates and the DQ views catch them.
- **The view stack stacks** (`nv_* → bv_* → mv_* / mart_<bu>_*`): normalized re-joins carry no metric logic; business views add `sum() over` running totals, aging case ladders, and `ntile`/`rank` whale tiers; `mv_sales_month_snapshot` is a materialized table refreshed by insert-select from a business view; mart views read business views, never raw facts. Each rung reads the rung beneath it.
- **A human-entered mapping applied asymmetrically**: `manual.gl_product_category_mapping` (a finance spreadsheet upload — 6 of 7 live categories mapped, one unapproved batch, two retired rows, one conflicting beverage re-upload) is joined by `mart_finance_revenue` (left join + `coalesce` to `UNMAPPED`, dedup to the latest approved row) but **not** by `mart_salesops_demand_revenue`. The two legitimately disagree; `control_recon_finance_salesops` proves the gap equals the written-off revenue (`unexplained_difference` is 0) and quantifies the UNMAPPED bucket. The gap feeds DQ-005 and the `gl_mapping_request` workflow queue.
- **Code is catalogued as data**: `catalog.code_object` self-registers every deployed view from `sqlite_master` (the catalog provably matches the code) and carries authored target-platform source for a refresh procedure, an AR-close procedure, a `business_days_between` function (intentionally stale — flagged as known debt), and an outbound rebate extract; `catalog.lineage_edge` links them to the tables they read/write; `integration.job`/`job_run` give them scheduled run history with occasional failures.
- Every imperfection is aimed at something that catches it: orphan products -> DQ-002, missing xref -> DQ-003, format drift -> DQ-004/006/007 via the DQ views, invoice restatements -> the `control_recon_order_invoice` breaks, the asymmetric mapping -> `control_recon_finance_salesops` + DQ-005.

## Things to Query

```sql
-- The competing-metric discrepancy and its reconciliation
select * from control_recon_finance_salesops;                       -- difference == written_off_excluded; unexplained == 0
select gl_revenue_line, net_revenue from mart_finance_revenue order by 2 desc;       -- GL-mapped, written-off excluded, UNMAPPED bucket
select reported_category, gross_revenue from mart_salesops_demand_revenue order by 2 desc;  -- raw category, all statuses

-- The code catalog and lineage
select object_type, count(*) from catalog_code_object group by 1;
select object_name, notes from catalog_code_object where object_type != 'view';     -- authored procs/function/extract (note the known-debt function)
select * from catalog_lineage_edge order by edge_id;
select j.job_name, r.run_status, count(*) from integration_job_run r join integration_job j on j.job_id = r.job_id group by 1,2 order by 1,2;

-- The materialized snapshot and the business views
select * from mv_sales_month_snapshot order by month_key desc limit 6;
select * from bv_revenue_daily order by order_date desc limit 14;                    -- running total via sum() over
select customer_tier, count(*), round(sum(revenue),2) from bv_customer_economics group by 1;

-- Classic queries
select aging_bucket, count(*), round(sum(invoice_total),2) from mart_ar_aging group by 1;
select rule_code, count(*) from dq_rule_result_current group by 1 order by 1;        -- DQ-001..008
select imperfection_name, count(*) from meta_imperfection_log group by 1 order by 2 desc;
select status, count(*) from erp_sales_order group by 1 order by 2 desc;             -- open pipeline near as_of
```
