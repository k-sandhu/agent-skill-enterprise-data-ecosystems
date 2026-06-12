# Granite Point Mutual Insurance - Worked Example

A complete fictional property and casualty insurer: PAS policyholders, policies,
coverages and lifecycle events, claims through FNOL/reserve/payment development,
billing installments and payment gateway events, CRM party mastering, and the
**full layered warehouse stack** — landing (`raw.*`) and staging (`stg.*`) per
source feed, canonical (`core.*`), warehouse dims/facts, normalized `nv_*` views,
business `bv_*` views, a materialized `mv.*` table, and competing business-unit
`mart_*` views. It also carries a human-entered mapping table applied
asymmetrically, a workflow queue, a code-object catalog with lineage, integration
job-run history, and logged controlled imperfections. The example is built around
insurance realities reviewers check first: earned premium is derived over policy
exposure months, claim financials develop over time, agency production has
concentration, and the two reconciliation controls only break where intentional
restatement pairs / unapproved endorsements were injected.

## Run It

```text
python scripts/validate_ecosystem_spec.py examples/insurance/ecosystem_spec.json
python scripts/build_sqlite_ecosystem.py  examples/insurance/ecosystem_spec.json --plan
python scripts/build_sqlite_ecosystem.py  examples/insurance/ecosystem_spec.json --out examples/insurance/build --force
python scripts/validate_sqlite_database.py --db examples/insurance/build/granite_point_mutual_insurance.db --spec examples/insurance/ecosystem_spec.json --report examples/insurance/build/validation_report.md
python scripts/profile_sqlite_database.py --db examples/insurance/build/granite_point_mutual_insurance.db --report examples/insurance/build/profile.md
```

At multiplier 1.0 this builds roughly 480k rows across 44 tables and fourteen
required views, and it passes strict validation with a full realism score.
CI-style `--scale-multiplier 0.3` builds also pass strict.

## The View Stack (views on views)

Each rung is derived from the one below — real lineage, not parallel-faked data:

```text
wh.dim_* / wh.fact_*                         warehouse dims and facts
  -> nv_written_premium                      normalized re-join: coverage premium + policy/agency dims
  -> nv_premium_earned                       normalized re-join: monthly earned premium + policy dim
  -> nv_claim_transaction                    normalized re-join: claim txns + accident quarter / dev age
     -> bv_earned_premium_monthly            business view: monthly earned + window running total
     -> bv_loss_triangles                    business view: lag()/case development triangles
     -> bv_agency_production                  business view: rank()/ntile() written-premium ranking
        -> mv.quarter_end_reserve_snapshot   materialized table (insert-select, ~8 quarters/line)
        -> mart_actuarial_written_premium    BU view: LOB mapping applied, unapproved endorsements excluded
        -> mart_distribution_written_premium BU view: raw coverage code, everything booked
        -> mart_loss_ratio_by_line           BU view: loss ratio in the 55-75% band
        -> mart_reserve_development           BU view: development surfaced from bv_loss_triangles
        -> mart_agency_production             BU view: production surfaced from bv_agency_production
```

Each source feed lands raw and is cleaned in staging:
`pas.policyholder / cms.claim / billing.installment / core.policy ->
raw.pas_policyholder_extract / raw.cms_claim_extract / raw.billing_installment_extract
/ raw.dist_agency_production_extract -> stg.policyholder / stg.claim / stg.installment
/ stg.agency_production` (case-guarded date parse, dedup; drifted dates land NULL and
feed `DQ-005/014/015/016`).

## Patterns Worth Copying

- **Competing written-premium metric, asymmetric mapping**: both
  `mart_actuarial_written_premium` and `mart_distribution_written_premium` are
  built on the same `nv_written_premium` view. Actuarial joins the human-entered
  `manual.line_of_business_mapping` (left join + coalesce to `UNMAPPED`, dedups the
  conflicting COMP re-upload to the latest approved active row) and **excludes
  unapproved endorsements**. Distribution uses the raw coverage code and counts
  everything an agency booked at submission. The mapping is total-preserving, so
  `control_recon_actuarial_distribution.unexplained_difference` is exactly 0 and the
  whole gap is the unapproved-endorsement amount.
- **Human-entered mapping with audit + effective dating**:
  `manual.line_of_business_mapping` is a small spreadsheet upload (audited,
  effective-dated). 11 live codes map; `WTRBKP` only has an unapproved row so it
  stays `UNMAPPED` and feeds both `DQ-013` and a `lob_mapping_request` workflow
  case; retired codes and one conflicting re-upload exercise the dedup.
- **Full landing/staging per feed**: every source has a verbatim `raw.*` text
  landing table with file/batch ids and a clamped `ingested_at`, then a typed
  `stg.*` table; `format_drift` corrupts the raw date columns post-build.
- **Earned premium is derived, not sampled**: monthly premium exposure comes from
  policy term dates and written premium, so loss ratio by line has a real
  denominator; `bv_earned_premium_monthly` adds a window running total.
- **Claim development as a triangle**: `bv_loss_triangles` builds cumulative
  incurred/paid with window sums and a `lag()` prior-age column; the quarter-end
  reserve snapshot is materialized from it.
- **Code is part of the ecosystem**: `catalog.code_object` self-registers every
  view from `sqlite_master` and carries authored target-platform source for the
  earned-premium and reserve-recalc procedures, the mv refresh procedure, the
  pro-rata earning function, and the outbound bureau/reinsurance extracts.
  `catalog.lineage_edge` and `integration.job` / `integration.job_run` give the
  code reads/writes and a run history with failures (one object is intentionally
  stale, flagged as known debt).
- **Reconciliation breaks are explainable**: `control_recon_written_vs_billed`
  breaks only on installment restatement reversals;
  `control_recon_actuarial_distribution` quantifies the actuarial-vs-distribution
  gap exactly.

## Things to Query

```sql
-- View-stack lineage: a coverage rolls up nv -> bv -> mart
select * from mart_loss_ratio_by_line order by line;
select * from bv_loss_triangles order by line, accident_quarter, dev_age_quarters limit 20;
select * from mart_agency_production order by written_premium desc limit 10;
select * from mv_quarter_end_reserve_snapshot order by line, accident_quarter;

-- The actuarial-vs-distribution written-premium discrepancy.
-- difference = unapproved endorsements excluded; unexplained_difference must be 0.
select * from control_recon_actuarial_distribution;
select round(sum(written_premium),2) as distribution_total from mart_distribution_written_premium;
select round(sum(written_premium),2) as actuarial_total    from mart_actuarial_written_premium;
select lob_node, round(sum(written_premium),2) as premium   -- the UNMAPPED WTRBKP bucket
from mart_actuarial_written_premium where lob_node = 'UNMAPPED' group by 1;

-- The code-object catalog: views self-register; procedures/functions/extracts are authored.
select object_type, count(*) from catalog_code_object group by 1 order by 1;
select object_name, owner, notes from catalog_code_object where object_type in ('procedure','function','extract');
select code_object, operation, table_name from catalog_lineage_edge order by edge_id;

-- Integration job-run history (with failures), joined to the job catalog.
select j.job_name, r.run_status, count(*)
from integration_job_run r join integration_job j on j.job_id = r.job_id
group by 1, 2 order by 1, 2;

-- Human-entered mapping and the queues it feeds.
select rule_code, count(*) from dq_rule_result_current group by 1 order by 1;  -- DQ-013 = unmapped WTRBKP
select case_type, queue, count(*) from workflow_case group by 1, 2 order by 1;
select status, count(*) from pas_policy group by 1 order by 2 desc;            -- open pipeline near as_of
```
