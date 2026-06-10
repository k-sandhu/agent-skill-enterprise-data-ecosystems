# Copperleaf Mercantile — Omnichannel Retail Example

A complete fictional omnichannel retailer: 24 stores plus a web channel, a 3,000-customer loyalty book whose tier drives both store and online volume, a category-coherent item master with retail price endings, promo-tiered line pricing, a right-censored ecommerce fulfillment state machine whose delivered orders feed the return derivations (web returns ~16% of units vs ~6% in store, by construction), derived tenders with a tender-to-transaction recon control, raw/staging/xref/canonical customer mastering, warehouse dims and facts, daily sales/returns/promotion marts, and 12 logged controlled imperfections each aimed at a DQ rule, recon view, or workflow queue.

## Run It

```text
python scripts/validate_ecosystem_spec.py examples/retail/ecosystem_spec.json
python scripts/build_sqlite_ecosystem.py  examples/retail/ecosystem_spec.json --plan
python scripts/build_sqlite_ecosystem.py  examples/retail/ecosystem_spec.json --out examples/retail/build --force
python scripts/validate_sqlite_database.py --db examples/retail/build/copperleaf_mercantile.db --spec examples/retail/ecosystem_spec.json --report examples/retail/build/validation_report.md
python scripts/profile_sqlite_database.py --db examples/retail/build/copperleaf_mercantile.db --report examples/retail/build/profile.md
```

At multiplier 1.0 this builds ~365k rows across 33 tables and 5 views in well under a minute and passes strict validation with a full realism score (also verified at `--scale-multiplier 0.3`).

## Patterns Worth Copying

- **Retail-inverted calendar**: weekend-heavy `weekday_weights` (Sat 1.55, Sun 1.28, Mon-Tue ~0.8) and a Q4 ramp in `month_weights` (Nov 1.42, Dec 1.85) — the exact opposite of a B2B spec, and the first thing a retail practitioner checks.
- **Loyalty tier as the economic spine**: `crm.customer.loyalty_tier` is drawn once, then `scale_by` multiplies both store transactions (platinum 5.5x) and web orders (platinum 7.0x) per tier, with a heavy-tailed `per_parent_multiplier` on top — revenue per customer climbs monotonically from $846 (none) to $3,892 (platinum) and the top decile carries ~41% of revenue.
- **Promo application visible in line prices**: lines draw `promo_depth`, a scalar `case` maps it to `promo_multiplier` (1.0/0.9/0.8/0.7), and a single `expr` prices the line. Important engine constraint: a `case` whose branches are *different expressions* silently reuses the first compiled expression (cached per column name) — always route case-conditional math through a scalar column and one shared expression.
- **Channel return economics by construction, not dice**: the fulfillment machine's `delivered -> return_requested (0.24) -> returned (0.93)` path feeds the web return derivation (~83% line participation), while store returns are a deterministic 1-in-14 slice of completed lines — web lands at ~16% of units, store at ~6%, with January's post-holiday return surge falling out of December's Q4 volume.
- **Category-coherent item master with retail price points**: category drawn first, then name pools, `money` medians, and cost ratios all conditioned on it; `price_endings: [0.99, 0.49, 0.0]` makes the unit-price duplicate mass look like a real price file, and margin orders itself economically (electronics 23% ... beauty 59%).
- **Split tenders that sum exactly, then break on purpose**: `pos.tender` is derived (every 12th transaction splits 60/40 with the remainder computed by subtraction), so the only breaks in `control_recon_tender_to_transaction` are the logged `restatement_reversal` pairs — a recon with one explainable break population.
- **Deliberate blind returns**: every 97th store return line points at a non-existent sale line inside the derivation SQL itself (deterministic `id % 97`), giving DQ-006 a defect population without needing an imperfection type that the engine can't aim at derived FK columns.
- **A control-layer execution log that cannot contradict the control**: `control.control_run` logs run metadata only (no break counts), so the generated log never disagrees with the live break view.

## Things to Query

```sql
select * from mart_sales_daily order by sale_date desc limit 14;
select substr(return_date,1,7) as ym, channel, sum(returns), sum(refund_total) from mart_returns_daily group by 1, 2 order by 1;  -- January return surge
select * from mart_promotion_performance order by channel, promo_depth;  -- 0.9/0.8/0.7 price ratios by depth
select * from control_recon_tender_to_transaction order by abs(break_amount) desc limit 10;
select rule_code, count(*) from dq_rule_result_current group by 1 order by 1;
select status, count(*) from ecom_order_header group by 1 order by 2 desc;  -- right-censored open pipeline near as_of
select c.loyalty_tier, count(distinct c.customer_id) as customers, round(sum(f.net_amount) / count(distinct c.customer_id)) as net_per_customer
from crm_customer c join wh_fact_sales_line f on f.customer_key = c.customer_id group by 1 order by 3;
select case cast(strftime('%w', sale_date) as integer) when 0 then 'Sun' when 6 then 'Sat' else 'weekday' end as day_type,
       count(*) as lines, round(sum(net_amount)) as net from wh_fact_sales_line group by 1;  -- weekend-heavy retail week
```
