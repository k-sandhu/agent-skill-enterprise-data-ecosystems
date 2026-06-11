# Cloudvane Systems — B2B SaaS Example

A complete fictional multi-tenant B2B SaaS vendor: tenants with size segments, IdP users and SSO connections, a published price book, subscriptions flowing through a trial → active → dunning → churn machine, 157k usage events with an automated 7-day feel, monthly invoices **derived** from subscriptions + metered overage, a +3/+7/+14/+20-day dunning schedule, support tickets through a triage machine with CSAT, entitlement and audit layers, a raw → stg → xref → core mastering flow, warehouse dims and facts, mart/control/DQ views, and 12 logged controlled imperfections — each aimed at a DQ rule or reconciliation that catches it.

Passes strict validation with zero criticals, zero warnings, and a full realism score (11/11 at multiplier 1.0).

## Run It

```text
python scripts/validate_ecosystem_spec.py examples/saas/ecosystem_spec.json
python scripts/build_sqlite_ecosystem.py  examples/saas/ecosystem_spec.json --plan
python scripts/build_sqlite_ecosystem.py  examples/saas/ecosystem_spec.json --out examples/saas/build --force
python scripts/validate_sqlite_database.py --db examples/saas/build/cloudvane_systems.db --spec examples/saas/ecosystem_spec.json --report examples/saas/build/validation_report.md
python scripts/profile_sqlite_database.py --db examples/saas/build/cloudvane_systems.db --report examples/saas/build/profile.md
```

At multiplier 1.0 this builds ~333k rows across 34 tables and 5 views in ~25 seconds; CI-style builds at `--scale-multiplier 0.3` also pass strict validation.

## Patterns Worth Copying

- **Segment drives everything**: `app.tenant.segment` is drawn first, then `scale_by` conditions user counts (enterprise ~8x smb), usage volume (~13x), workspaces, and ticket volume on it, while `case`-on-segment picks seats, billing method, and payment terms — the first cross-tab a reviewer runs comes out right (enterprise: 70 users and 407 events per tenant vs smb's 10 and 30).
- **MRR is quantized, never sampled**: `seats` (integer, segment-conditional) x `price_per_seat` (`fk_copy` from the 6-row price book) via `expr` — the top-20 exact MRR values carry ~49% of subscriptions, exactly how a real billing table looks.
- **Plan choice via fk affinity matching**: subscriptions pick a plan whose `segment_target` matches their tenant segment with a 4% leak — sales exceptions land smb tenants on enterprise plans occasionally instead of never.
- **Trial-to-paid is visible in the machine, not asserted**: every subscription enters at `trialing`; 28% transition to `active`, and only rows with non-NULL `activated_at` ever bill. Dunning recovery lands in a separate `recovered` state so `activated_at` is never overwritten and invoice windows stay anchored to first conversion.
- **Invoices are derived from subscriptions + usage**: a recursive month spine joins converted subscriptions to `bill.meter_reading` (itself rolled up from `app.usage_event` on metered features); ~60% bill on the 1st, the rest anniversary-dated; `included_units` are anchored near each plan's p85 so ~11% of invoices bill overage, concentrated in the smaller plans (upgrade pressure).
- **Usage events with `business_hours: false`** keep the automated 7-day SDK feel while `weekday_weights` still shape weekly volume (weekend ≈ 7% of events); human tables (signups, tickets, audit) stay business-hours clustered.
- **Status can never contradict timestamps in the canonical layer**: `core.tenant.lifecycle_status` is derived FROM subscription machine states rather than drawn independently — a churn flag without a churn timestamp is impossible by construction.
- **Deliberate tenant-isolation leak as a catchable defect**: `usage_event.user_id` uses fk affinity matching on tenant with `leak_rate: 0.004`; the cross-tenant events are exactly what DQ-008 (the isolation monitor) reports. Every other imperfection has a named catcher too: requester orphans → DQ-002, missing xref → DQ-003, format drift → DQ-004 via the staging date parse, webhook retries → DQ-005, comped-but-billed subscriptions → DQ-011, line restatements → the `control_recon_invoice_lines` breaks.

## Things to Query

```sql
-- MRR trend by segment: ~31% growth over the window plus expansion
select period_month, segment, subscriptions, mrr, arpa from mart_mrr_monthly order by period_month desc limit 9;

-- Trial-to-paid funnel straight from the machine (expect ~0.27)
select round(1.0 * sum(case when activated_at is not null then 1 else 0 end) / count(*), 3) as trial_to_paid
from bill_subscription;

-- Dunning retry echo at +3/+7/+14/+20 days and the recovery curve
select attempt_number, attempt_result, count(*) from bill_dunning_attempt group by 1, 2 order by 1, 2;

-- Whale check: top decile of live tenants carries ~73% of MRR
with m as (select tenant_id, sum(mrr_amount) mrr from bill_subscription
           where status in ('active','recovered','past_due','in_dunning') group by 1)
select round(1.0 * sum(case when d = 1 then mrr end) / sum(mrr), 3)
from (select mrr, ntile(10) over (order by mrr desc) d from m);

-- Invoice-vs-lines recon breaks created by quarter-end restatement reversals
select * from control_recon_invoice_lines order by abs(break_amount) desc limit 10;

-- Seat true-up: provisioned IdP users vs billed seats (lagging deprovisioning)
select * from control_seat_trueup order by seat_gap desc limit 10;

-- Every DQ rule returns a live failure population
select rule_code, count(*) from dq_rule_result_current group by 1 order by 1;

-- SLA breach rate by priority from the accumulating-snapshot ticket fact
select priority, round(avg(sla_breached), 3) as breach_rate, count(*) as tickets
from wh_fact_support_ticket where first_response_at is not null group by 1;
```
