# Bluestone Mutual Bank — Worked Example

A complete fictional regional retail/commercial bank modeling the **full layered warehouse stack** end to end: core banking customers and accounts, debit cards with merchant-skewed spend, an ACH/wire payment hub with a right-censored lifecycle state machine, an AML alert-to-case-to-SAR funnel; landing (`raw_*`) and staging (`stg_*`) tables per source feed (core extract, card settlement file, payment stream, GL extract); `xref`/canonical normalization; a double-entry GL daily summary and a window-sum balance roll-forward where opening + credits − debits = closing holds by construction; warehouse facts and dims; a stacked view tier (`nv_*` normalized → `bv_*` business → `mv_*` materialized → `mart_<bu>_*` per-business-unit); a human-entered GL account mapping applied asymmetrically across finance vs branch-ops; a code-object catalog (`catalog.code_object`/`lineage_edge`) with self-registered views and authored procedures/function/extracts; reconciliation and DQ views; workflow queues; and 15 logged controlled imperfections — every one aimed at a DQ rule, a reconciliation, or a workflow queue. Identifier safety throughout: `iban`, `aba_routing`, and `masked_card` identifier kinds only, with 555-01xx phones and example.com emails.

At multiplier 1.0 this builds ~408k rows across 45 tables and 13 views in well under a minute and passes strict validation (zero critical, zero warnings, full realism score).

## Run It

```text
python scripts/validate_ecosystem_spec.py examples/banking/ecosystem_spec.json
python scripts/build_sqlite_ecosystem.py  examples/banking/ecosystem_spec.json --plan
python scripts/build_sqlite_ecosystem.py  examples/banking/ecosystem_spec.json --out examples/banking/build --force
python scripts/validate_sqlite_database.py --db examples/banking/build/bluestone_mutual_bank.db --spec examples/banking/ecosystem_spec.json --report examples/banking/build/validation_report.md
python scripts/profile_sqlite_database.py --db examples/banking/build/bluestone_mutual_bank.db --report examples/banking/build/profile.md
```

## Patterns Worth Copying

- **Landing + staging per feed**: one `raw_*` table per source feed (core customer extract, card settlement file, payment stream, GL extract) landed as text with file/batch ids and `ingested_at` (the next-morning batch, clamped to as_of), then a `stg_*` table per landing table that trims, types, dedups (`row_number` against re-sent batches), and parses dates with a `case`-guard so drifted formats land NULL. `format_drift` corrupts the landed dates and the DQ views catch them (DQ-003/009/010).
- **The view stack stacks** (`nv_* → bv_* → mv_* / mart_<bu>_*`): `nv_transaction`/`nv_account_balance`/`nv_gl_posting` re-join facts to dims with no metric logic; `bv_balance_rollforward` surfaces the opening + credits − debits = closing equation with a window recency rank, `bv_deposit_portfolio` aggregates each account's latest balance by segment×product, `bv_aml_alert_funnel` is the alert→investigation→SAR case ladder; `mv_eod_balance_snapshot` is a day-grain materialized table refreshed by insert-select from a business view; mart views read business/normalized views, never raw facts. Each rung reads the rung beneath it.
- **A human-entered mapping applied asymmetrically**: `manual.gl_account_mapping` (a finance spreadsheet upload mapping product code → GL account hierarchy node — 12 of 14 live products mapped, one unapproved draft, two retired rows, one conflicting SAV-CORE re-upload) is joined by `mart_finance_deposits` (left join + `coalesce` to `UNMAPPED`, dedup to the latest approved row) but **not** by `mart_branchops_deposits`. Finance also **excludes internal/settlement accounts** (a deterministic `account_id % 50 = 0` slice) that branch ops includes. The two legitimately disagree on total deposits; `control_recon_finance_branchops` proves the gap equals exactly the internal/settlement balance (`unexplained_difference` is 0) and quantifies the UNMAPPED bucket. The gap feeds DQ-008 and the `gl_mapping_request` workflow queue.
- **Code is catalogued as data**: `catalog.code_object` self-registers every deployed view from `sqlite_master` (the catalog provably matches the code) and carries authored target-platform source for an end-of-day batch posting procedure, a GL close procedure, the `rebuild_mv_eod_balance_snapshot` refresh procedure, a `deposit_interest_accrual` function (intentionally stale — references a retired column, flagged as known debt), and the regulatory-transaction-report and card-network-settlement outbound extracts; `catalog.lineage_edge` links them to the tables they read/write; `integration.job`/`job_run` give them scheduled run history with occasional failures.
- **Weekend dip on human channels with flat card volume** — the calendar carries the consumer-card week (mild Fri/Sat lift) and the `core_posted_transaction` derivation rolls ACH/wire posting to the next business day, so the mart shows zero weekend ACH/wire rows and seven-day card spend from one CASE expression.
- **Balance roll-forward derived, never sampled** — `wh.fact_account_balance` is a window-sum over the posting ledger with a deterministic per-account opening anchor (`(account_id * 263) % 17500` — no `random()`), so opening + credits − debits = closing holds on every row and `bv_balance_rollforward.rollforward_break` is 0 everywhere.
- **Recon breaks from derivation ordering** — `ledger.gl_daily_summary` is double-entry by construction and derives *before* the post-derivation `restatement_reversal` pairs land in `core.posted_transaction`. The `control_recon_txn_vs_gl` view is exactly the late-restatement story a finance-controls team chases.
- **Every imperfection has a catcher** — ghost merchants → DQ-004 and `UNKNOWN MERCHANT` postings; missing/stale xref → DQ-002/DQ-005; padded raw dates → DQ-003/009/010; CDC event swaps → DQ-006; nulled emails → DQ-007; the unmapped product gap → DQ-008 + `control_recon_finance_branchops`; GL restatements → the recon view; analyst overrides → `mart_aml_funnel`.

## Things to Query

```sql
-- The competing-metric discrepancy and its reconciliation
select * from control_recon_finance_branchops;   -- difference == internal_excluded; unexplained_difference == 0
select gl_account_node, total_deposits from mart_finance_deposits order by 2 desc;     -- GL-mapped, internal excluded, UNMAPPED bucket
select reported_product_code, round(sum(total_deposits),2) from mart_branchops_deposits group by 1 order by 2 desc;  -- raw code, internal included

-- The code catalog and lineage
select object_type, count(*) from catalog_code_object group by 1;
select object_name, notes from catalog_code_object where object_type != 'view';  -- authored procs/function/extracts (note the known-debt function)
select * from catalog_lineage_edge order by edge_id;

-- Job-run history with occasional failures
select j.job_name, r.run_status, count(*) from integration_job_run r
join integration_job j on j.job_id = r.job_id group by 1, 2 order by 1, 2;

-- The materialized snapshot and the business views
select * from mv_eod_balance_snapshot order by posting_date desc limit 7;            -- day-grain bank-wide EOD, bounded ~730 rows
select * from bv_deposit_portfolio order by total_balance desc limit 10;             -- segment x product latest balances
select funnel_stage, alerts, linked_cases, sars_filed from bv_aml_alert_funnel order by stage_order;

-- Balance equation holds on every roll-forward row
select count(*) from bv_balance_rollforward where abs(rollforward_break) > 0.02;

-- Weekend dip on ACH/wire, flat card week
select channel, strftime('%w', txn_date) as weekday, count(*) as txns
from nv_transaction group by 1, 2 order by 1, 2;

-- GL recon breaks from late restatement reversals
select * from control_recon_txn_vs_gl order by abs(break_amount) desc limit 10;

-- DQ results reconcile to the logged imperfections that caused them
select rule_code, count(*) from dq_rule_result_current group by 1 order by 1;        -- DQ-001..010
select imperfection_name, count(*) from meta_imperfection_log group by 1 order by 2 desc;
```
