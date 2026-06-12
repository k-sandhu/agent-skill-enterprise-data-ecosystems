# Copperleaf Mercantile - Omnichannel Retail Example

A complete fictional omnichannel retailer: 24 stores plus a web channel, a 3,000-customer loyalty book whose tier drives both store and online volume, a category-coherent item master with retail price endings, promo-tiered line pricing, a right-censored ecommerce fulfillment state machine whose delivered orders feed returns, feed-specific raw/staging landings for POS TLOG, ecommerce order export, item master, and returns files, xref/canonical customer mastering, warehouse dims and facts, a full `nv_*` -> `bv_*` -> `mv_*` -> `mart_*` view stack, cataloged code objects and lineage, a manual merchandising hierarchy override applied only in merchandising marts, and logged controlled imperfections aimed at DQ rules, recon views, or workflow queues.

## Run It

```text
python scripts/validate_ecosystem_spec.py examples/retail/ecosystem_spec.json
python scripts/build_sqlite_ecosystem.py  examples/retail/ecosystem_spec.json --plan
python scripts/build_sqlite_ecosystem.py  examples/retail/ecosystem_spec.json --out examples/retail/build --force
python scripts/validate_sqlite_database.py --db examples/retail/build/copperleaf_mercantile.db --spec examples/retail/ecosystem_spec.json --report examples/retail/build/validation_report.md --strict
python scripts/profile_sqlite_database.py --db examples/retail/build/copperleaf_mercantile.db --report examples/retail/build/profile.md
```

At multiplier 1.0 this builds about 542k rows across 48 tables and 15 views in well under a minute and passes strict validation with a full realism score. It is also verified at `--scale-multiplier 0.3`.

## Patterns Worth Copying

- **Retail-inverted calendar**: weekend-heavy `weekday_weights` (Sat 1.55, Sun 1.28, Mon-Tue about 0.8) and a Q4 ramp in `month_weights` (Nov 1.42, Dec 1.85).
- **Loyalty tier as the economic spine**: `crm.customer.loyalty_tier` is drawn once, then `scale_by` multiplies both store transactions and web orders per tier, with a heavy-tailed `per_parent_multiplier` on top.
- **Feed-specific landing and staging**: `raw.pos_tlog_file`, `raw.ecom_order_export`, `raw.merch_item_master_feed`, and `raw.returns_file` retain file/batch IDs and `ingested_at`; matching `stg.*` tables use guarded date parsing, and POS staging deduplicates re-polled transaction-log batches.
- **Full layered view stack**: `nv_sales_line` and `nv_return_line` rejoin facts to product, store, channel, loyalty-tier, and date dimensions; `bv_*` views add running totals, lagged comp-store sales, loyalty tier ranking, and promo lift; `mv.week_end_sales_snapshot` models a refreshed materialized view.
- **Manual hierarchy asymmetry**: `manual.merch_hierarchy_override` is audited and effective-dated with stale and conflicting rows. `mart_merch_category_sales` applies the override with fallback; `mart_finance_net_sales` does not, and also nets returns on original sale date while excluding the training store.
- **Code as data**: `catalog.code_object` self-registers deployed views from `sqlite_master` and adds procedure/function/extract rows; `catalog.lineage_edge` links the layered stack and outbound extracts to code objects.
- **Promo application visible in line prices**: lines draw `promo_depth`, a scalar `case` maps it to `promo_multiplier` (1.0/0.9/0.8/0.7), and a single `expr` prices the line.
- **Channel return economics by construction**: the fulfillment machine's `delivered -> return_requested (0.24) -> returned (0.93)` path feeds the web return derivation, while store returns are a deterministic 1-in-14 slice of completed lines.
- **Split tenders that sum exactly, then break on purpose**: `pos.tender` is derived, so the only breaks in `control_recon_tender_to_transaction` are logged `restatement_reversal` pairs.

## Things to Query

```sql
select * from mart_sales_daily order by sale_date desc limit 14;

select substr(return_date,1,7) as ym, channel, sum(returns), sum(refund_total)
from mart_returns_daily
group by 1, 2
order by 1;

select * from mart_promotion_performance order by channel, promo_depth;

select * from control_recon_tender_to_transaction
order by abs(break_amount) desc
limit 10;

select * from control_recon_finance_merch_net_sales
order by abs(break_amount) desc
limit 10;

select rule_code, count(*)
from dq_rule_result_current
group by 1
order by 1;

select source_object, target_object, edge_type, code_object_name
from catalog_lineage_edge
order by edge_id;

select object_type, object_name, owner_team, schedule, destination_system
from catalog_code_object
order by object_type, object_name;

select j.job_name, r.run_status, count(*) as runs, round(avg(r.rows_processed)) as avg_rows
from integration_job_run r
join integration_job j on j.job_id = r.job_id
group by j.job_name, r.run_status
order by j.job_name, r.run_status;

select status, count(*)
from ecom_order_header
group by 1
order by 2 desc;

select c.loyalty_tier, count(distinct c.customer_id) as customers,
       round(sum(f.net_amount) / count(distinct c.customer_id)) as net_per_customer
from crm_customer c
join wh_fact_sales_line f on f.customer_key = c.customer_id
group by 1
order by 3;

select case cast(strftime('%w', sale_date) as integer)
         when 0 then 'Sun'
         when 6 then 'Sat'
         else 'weekday'
       end as day_type,
       count(*) as lines,
       round(sum(net_amount)) as net
from wh_fact_sales_line
group by 1;
```
