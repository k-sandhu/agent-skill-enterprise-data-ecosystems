# Granite Point Mutual Insurance - Worked Example

A complete fictional property and casualty insurer: PAS policyholders, policies,
coverages and lifecycle events, claims through FNOL/reserve/payment development,
billing installments and payment gateway events, CRM party mastering,
raw/staging/xref/core/warehouse layers, loss-ratio and reserve-development marts,
and logged controlled imperfections. The example is built around insurance
realities reviewers check first: earned premium is derived over policy exposure
months, claim financials develop over time, agency production has concentration,
and written-premium-to-billing breaks only appear where restatement pairs were
intentionally injected.

## Run It

```text
python scripts/validate_ecosystem_spec.py examples/insurance/ecosystem_spec.json
python scripts/build_sqlite_ecosystem.py  examples/insurance/ecosystem_spec.json --plan
python scripts/build_sqlite_ecosystem.py  examples/insurance/ecosystem_spec.json --out examples/insurance/build --force
python scripts/validate_sqlite_database.py --db examples/insurance/build/granite_point_mutual_insurance.db --spec examples/insurance/ecosystem_spec.json --report examples/insurance/build/validation_report.md
python scripts/profile_sqlite_database.py --db examples/insurance/build/granite_point_mutual_insurance.db --report examples/insurance/build/profile.md
```

At multiplier 1.0 this builds roughly 320k rows across 29 tables and five
required views, and it passes strict validation with a full realism score.
CI-style `--scale-multiplier 0.3` builds also pass strict.

## Patterns Worth Copying

- **Policy lifecycle drives billing and claims**: quoted policies only produce
  downstream earned premium after the lifecycle reaches bound states; recent
  records remain right-censored instead of being forced terminal.
- **Earned premium is derived, not sampled**: monthly premium exposure comes
  from policy term dates and written premium, so loss ratio by line has a real
  denominator.
- **Claim development has multiple accounting views**: reserve transactions and
  payments feed the warehouse fact, while the reserve-development mart shows
  accident quarter and development age.
- **CRM and PAS agree at birth, then drift**: CRM party rows are generated from
  PAS policyholders, then typos, conflicting city values, feed latency, missing
  xrefs, and stale mappings create realistic MDM and mail-return queues.
- **Reconciliation breaks are explainable**: `control_recon_written_vs_billed`
  is a live view, so only installment restatement reversals create breaks.

## Things to Query

```sql
select * from mart_loss_ratio_by_line order by line;
select * from mart_reserve_development order by line, accident_quarter, dev_age_quarters limit 20;
select * from mart_agency_production order by written_premium desc limit 10;
select * from control_recon_written_vs_billed order by abs(break_amount) desc limit 10;
select rule_code, count(*) from dq_rule_result_current group by 1 order by 1;
select status, count(*) from pas_policy group by 1 order by 2 desc;
```
