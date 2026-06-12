# Cloudvane Systems - B2B SaaS Example

A complete fictional multi-tenant B2B SaaS vendor: tenants with size segments, IdP users and SSO connections, a published price book, subscriptions flowing through a trial -> active -> dunning -> churn machine, usage events with an automated 7-day feel, monthly invoices derived from subscriptions plus deduplicated metered usage, a +3/+7/+14/+20-day dunning schedule, support tickets through a triage machine with CSAT, entitlement and audit layers, raw landing/staging feeds for IdP, billing, metering, and support, warehouse dims/facts, nv/bv/mv/business-unit mart views, a self-registering code catalog, job-run history, lineage, manual SKU revenue mapping, workflow exceptions, and controlled imperfections aimed at DQ rules or reconciliations.

Passes strict validation with zero criticals, zero warnings, and a full realism score.

## Run It

```text
python scripts/validate_ecosystem_spec.py examples/saas/ecosystem_spec.json
python scripts/build_sqlite_ecosystem.py  examples/saas/ecosystem_spec.json --plan
python scripts/build_sqlite_ecosystem.py  examples/saas/ecosystem_spec.json --out examples/saas/build --force
python scripts/validate_sqlite_database.py --db examples/saas/build/cloudvane_systems.db --spec examples/saas/ecosystem_spec.json --report examples/saas/build/validation_report.md --strict
python scripts/profile_sqlite_database.py --db examples/saas/build/cloudvane_systems.db --report examples/saas/build/profile.md
```

At `--scale-multiplier 0.3` this builds about 265k rows across 52 populated tables and 15 required views in a few seconds; strict validation reports zero criticals and zero warnings. Full multiplier 1.0 builds the same stack at the larger demo scale.

## Patterns Worth Copying

- **Segment drives everything**: `app.tenant.segment` is drawn first, then `scale_by` conditions user counts, usage volume, workspaces, and ticket volume on it, while `case`-on-segment picks seats, billing method, and payment terms.
- **MRR is quantized, never sampled**: `seats` x `price_per_seat` from the 6-row price book via `expr`, so subscription amounts repeat like a real billing system.
- **Landing and staging are load-bearing**: IdP tenant/user exports, billing invoice extracts, support ticket exports, and raw metering events land with file ids, batch ids, and `ingested_at`; staging performs guarded date parsing and deduplicates replayed metering events before rating.
- **The warehouse stack is deliberately deep**: `nv_*` views rejoin subscription, invoice, and usage facts to tenant/plan/date dimensions; `bv_*` views add ARR, usage, and trial-funnel logic; `mv_month_end_arr_snapshot` materializes month-end ARR; finance and customer-success marts intentionally disagree on ARR.
- **Manual SKU mapping is asymmetric**: `manual_sku_revenue_line_mapping` has 87.5% live SKU coverage plus stale/conflicting rows. Finance applies it, customer success does not, and unmapped SKUs feed DQ-012 plus `workflow_mapping_request_case`.
- **Code and jobs are data too**: deployed views self-register into `catalog_code_object` from `sqlite_master`, stored procedure/function/extract definitions are cataloged as rows, `integration_job_run` has failed and partial history, and `catalog_lineage_edge` links code to upstream/downstream objects.
- **Status can never contradict timestamps in the canonical layer**: `core.tenant.lifecycle_status` is derived from subscription machine states rather than drawn independently.
- **Deliberate tenant-isolation leak as a catchable defect**: `usage_event.user_id` uses FK affinity matching on tenant with a small leak rate; DQ-008 reports those cross-tenant events.

## Things To Query

```sql
-- MRR trend by segment
select period_month, segment, subscriptions, mrr, arpa
from mart_mrr_monthly
order by period_month desc limit 9;

-- Trial-to-paid funnel from the business view
select trial_month, segment, signup_channel, trials_started, trials_converted, conversion_rate
from bv_trial_funnel
order by trial_month desc, segment, signup_channel
limit 12;

-- Finance-vs-customer-success ARR discrepancy caused by mapping and metered ARR treatment
select period_month, segment, finance_arr, customer_success_arr, arr_variance, unmapped_line_count
from control_recon_arr_finance_vs_cs
order by abs(arr_variance) desc limit 10;

-- Lineage edges through the landing, warehouse, mart, and extract stack
select upstream_object, downstream_object, code_object_name, edge_type
from catalog_lineage_edge
order by lineage_edge_id;

-- Code catalog: self-registered views plus procedure/function/extract definitions
select object_type, object_name, owner_team, deployment_status
from catalog_code_object
order by object_type, object_name;

-- Job-run history with deterministic failed/partial runs
select j.job_name, r.run_status, count(*) as runs, sum(r.rows_read) as rows_read
from integration_job_run r
join integration_job j on j.job_id = r.job_id
group by j.job_name, r.run_status
order by j.job_name, r.run_status;

-- Dunning retry echo at +3/+7/+14/+20 days and recovery curve
select attempt_number, attempt_result, count(*)
from bill_dunning_attempt
group by 1, 2
order by 1, 2;

-- Invoice-vs-lines recon breaks created by quarter-end restatement reversals
select *
from control_recon_invoice_lines
order by abs(break_amount) desc limit 10;

-- Seat true-up: provisioned staged IdP users vs billed seats
select *
from control_seat_trueup
order by seat_gap desc limit 10;

-- Every DQ rule returns a live failure population
select rule_code, count(*)
from dq_rule_result_current
group by 1
order by 1;
```
