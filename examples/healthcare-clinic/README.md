# Cedar Summit Health Partners — Ambulatory Healthcare Network

A complete fictional 12-clinic ambulatory network modeling the **full layered warehouse stack** end to end: practice management (patients, coverage, appointments with booked services), EHR clinicals (encounters, diagnoses, procedures derived from completed visits — real lineage), revenue cycle (charges, claims, remittances, denial/mapping worklist); landing (`raw_*`) and staging (`stg_*`) tables per source feed (PM patient extract, EHR encounter extract, RCM charge interface, clearinghouse 837 claim file, 835 remittance file); an EMPI `raw`→`stg`→`xref`→`core` patient-mastering flow; warehouse dims and facts; a stacked view tier (`nv_*` normalized → `bv_*` business → `mv_*` materialized → `mart_<bu>_*` per-business-unit); a human-entered payer-plan grouping applied asymmetrically across revenue-cycle vs clinical-ops; a code-object catalog (`catalog.code_object`/`lineage_edge`) with self-registered views and authored procedures/function/extracts; `integration.job`/`job_run` scheduled run history; reconciliation and DQ views; and 14 logged controlled imperfections. Two state machines run on the appointment table: a scheduling lifecycle (scheduled → checked_in → completed / no_show / cancelled, ~13% no-show) and a claim lifecycle anchored on the visit's completion timestamp (denial rate ~11% of adjudicated, with resubmission and appeal paths). No real PII anywhere: surrogate MRNs, persona-pool names, birth year only, 555-01xx phones, example.com emails, NPIs in the provably fictional 9xxxxxxxxx range.

## Run It

```text
python scripts/validate_ecosystem_spec.py examples/healthcare-clinic/ecosystem_spec.json
python scripts/build_sqlite_ecosystem.py  examples/healthcare-clinic/ecosystem_spec.json --plan
python scripts/build_sqlite_ecosystem.py  examples/healthcare-clinic/ecosystem_spec.json --out examples/healthcare-clinic/build --force
python scripts/validate_sqlite_database.py --db examples/healthcare-clinic/build/cedar_summit_health_partners.db --spec examples/healthcare-clinic/ecosystem_spec.json --report examples/healthcare-clinic/build/validation_report.md
python scripts/profile_sqlite_database.py --db examples/healthcare-clinic/build/cedar_summit_health_partners.db --report examples/healthcare-clinic/build/profile.md
```

At multiplier 1.0 this builds ~1.16M rows across 47 tables and 13 views in under a minute and passes strict validation (0 critical, 0 warnings, realism 10/10); `--scale-multiplier 0.3` builds ~360k rows and also passes strict.

## Patterns Worth Copying

- **Two machines on one table, chained by a timestamp**: the scheduling machine writes `completed_at`; the claim machine (declared second) anchors its `start_column` on it, so rows that never completed are *skipped* and legitimately stay `not_billed`. This is how to make a second lifecycle exist only for entities that reached a milestone — no orphan claims for no-shows, ever.
- **Status-dependent children via derivation, status-independent children via generation**: services are *booked with* the appointment (generator, per_parent — they validly exist for visits that later no-show), while encounters/procedures/charges are SQL-derived only from visits that checked in / completed. Coherence falls out of the join, not patching.
- **`fk_copy` price × integer units at the booking line**: `fee_snapshot` snapshots the chargemaster fee (whole-dollar `price_endings: [0.0]`), `booked_amount = fee × units`, and the same exact amounts flow by derivation through procedure → charge → claim line — honest duplicate mass at every layer.
- **Residual probability as workqueue fodder**: 1.5% of past appointments never leave `scheduled` (front-desk reconciliation backlog → DQ-010) and 1.5% of completed visits never reach charge entry (DNFB → DQ-001). Open pipeline is guaranteed at any scale multiplier, not dependent on right-censoring luck.
- **Remittance disposition identity by construction**: contractual = billed − allowed, patient responsibility by payer type (20% coinsurance Medicare, copay-capped commercial via the coverage row's own `copay_amount`, full balance self-pay), paid = allowed − patient responsibility. The 835 invariant `paid + adjustment + patient = billed` holds to the cent on every row.
- **Self-pay as a configured financial class**: a "Self-Pay / Patient Direct" payer row lets self-pay visits flow through the same claim machinery with zero payer payment and the balance as patient responsibility — the way real PM systems actually model it.
- **Root-cause correlation in derived attributes**: denied claims whose registration bypassed eligibility verification (`manual_override` imperfection) draw 'eligibility' as their denial reason ~75% of the time vs ~25% baseline — the cross-tab a denial analyst would actually run tells the intended story.
- **Recon breaks from snapshot-vs-moving-target**: claim lines snapshot posted charges at claim generation; post-derivation charge restatement pairs and interface drops then move `billing.charge`, so `control_recon_charge_claim` shows ~700 explained breaks, exactly how real charge-to-claim recons fail.
- **Landing + staging per feed**: one `raw_*` table per source feed (PM patient, EHR encounter, RCM charge, clearinghouse 837, 835 remit) landed as text with file/batch ids and `ingested_at`, then a `stg_*` table per landing table that trims, types, dedups, and parses dates with a `case`-guard so drifted formats land NULL. `format_drift` corrupts the landed dates and the DQ views catch them. **Re-sent clearinghouse files are real**: a rejected 837 batch is resubmitted under a new `batch_id`, so the same `claim_id` lands twice (`BATCH-837A` then `BATCH-837B`); `stg.claim_837` dedups to the latest batch via `row_number`, and DQ-013 reports the superseded first copy.
- **The view stack stacks** (`nv_* → bv_* → mv_* / mart_<bu>_*`): normalized re-joins (`nv_encounter`, `nv_charge`, `nv_claim`) carry no metric logic; business views add window functions — `bv_revenue_cycle_funnel` (charge→claim→remit lag windows via `lag()`), `bv_ar_by_payer` (aging case ladder), `bv_provider_productivity` (`rank()`/`ntile()` over encounters and RVUs); `mv_month_end_ar_snapshot` is a materialized table refreshed by insert-select from a business view; mart views read business/normalized views, never raw facts. Each rung reads the rung beneath it.
- **A human-entered mapping applied asymmetrically**: `manual.payer_plan_grouping` (a revenue-cycle spreadsheet upload — 12 of 13 live plan codes mapped, one unapproved draft row leaving `HBR-EPO` UNMAPPED, two retired-plan rows, one conflicting `MCR-ADV-PPO` re-upload) is joined by `mart_revcycle_encounter_volume` (left join + `coalesce` to `UNMAPPED`, dedup to the latest approved active row) but **not** by `mart_clinicalops_encounter_volume`. The competing metric is **encounter volume**: clinical ops counts all completed encounters with the raw plan code; revenue cycle counts billable encounters only (completed AND gross_charges > 0, dropping zero-charge / no-show-converted visits) under the financial-class grouping. They legitimately disagree; `control_recon_revcycle_clinicalops` proves the entire gap equals the non-billable count (`unexplained_difference` is 0, because the mapping is total-preserving) and quantifies the UNMAPPED bucket. The gap feeds DQ-011 and the `rev_cycle_mapping` workflow queue.
- **Code is catalogued as data**: `catalog.code_object` self-registers every deployed view from `sqlite_master` (the catalog provably matches the code) and carries authored target-platform source for a nightly claim-scrubbing procedure, a month-end charge-close procedure, the `mv_month_end_ar_snapshot` refresh procedure, an `age_at_service` function (intentionally stale — references the column `patient.date_of_birth_year` renamed to `birth_year` in the 2024 PM upgrade, flagged as known debt), and two outbound extracts (837 submission feed, state immunization registry); `catalog.lineage_edge` links them to the tables they read/write; `integration.job`/`job_run` give them scheduled run history with occasional failures.

## Things to Query

```sql
-- Weekday clinic shape + ~13% no-show rate by site
select clinic_code, sum(appointments_booked) booked, round(avg(no_show_rate), 3) no_show_rate
from mart_clinic_volume_daily group by 1 order by 2 desc;

-- Revenue cycle by month: denial rate ~11%, days-to-pay ~33, December right-censored (open AR)
select * from mart_revenue_cycle_monthly order by claim_month desc limit 6;

-- Charge-to-claim recon breaks (restatements + interface drops)
select * from control_recon_charge_claim order by abs(break_amount) desc limit 10;

-- Every DQ rule fires against a logged defect or designed backlog
select rule_code, count(*) from dq_rule_result_current group by 1 order by 1;

-- Chronic/complex whales: appointments per patient by utilization tier
select p.utilization_tier, count(distinct p.patient_id) patients,
       round(1.0 * count(a.appointment_id) / count(distinct p.patient_id), 1) appts_per_patient
from patient_patient p left join scheduling_appointment a on a.patient_id = p.patient_id
group by 1 order by 3;

-- Payer mix and net collection rate (~34% of gross, by payer type)
select py.payer_type, count(*) claims, round(sum(r.paid_amount) / sum(r.billed_amount), 3) net_rate
from claims_remittance r join ref_payer py on py.payer_id = r.payer_id group by 1 order by 2 desc;

-- Eligibility overrides at registration skew toward eligibility denials downstream
select eligibility_override_flag,
       round(1.0 * sum(case when denial_reason = 'eligibility' then 1 else 0 end) /
             nullif(sum(case when denial_reason is not null then 1 else 0 end), 0), 3) elig_share_of_denials
from claims_claim group by 1;

-- Denial follow-up queue, routed by root cause
select queue, priority, count(*), round(sum(billed_amount), 2) at_risk
from workflow_denial_worklist where case_type = 'denial_followup' group by 1, 2 order by 4 desc;
```

### The competing encounter-volume metric and its reconciliation

Clinical ops counts *all* completed encounters with the raw plan code; revenue cycle counts *billable* encounters only and applies the human-entered financial-class mapping. The two legitimately disagree — the control view proves the gap is fully explained by the documented non-billable exclusion (`unexplained_difference` is 0) and the mapping is total-preserving.

```sql
-- One row: difference == excluded_count, unexplained_difference == 0
select * from control_recon_revcycle_clinicalops;

-- Clinical ops: every completed encounter, raw plan code, no mapping
select reported_plan_code, payer_name, completed_encounters
from mart_clinicalops_encounter_volume order by completed_encounters desc;

-- Revenue cycle: billable only, grouped into financial classes; HBR-EPO falls to UNMAPPED
select financial_class, financial_class_name, billable_encounters
from mart_revcycle_encounter_volume order by billable_encounters desc;

-- The unmapped plan code feeds DQ-011 and the rev_cycle_mapping queue
select rule_code, entity_id from dq_rule_result_current where rule_code = 'DQ-011';
select case_type, related_entity, queue from workflow_denial_worklist where case_type = 'plan_mapping_request';
```

### The view-stack lineage

Each rung reads only the rung beneath it: facts/dims → `nv_*` → `bv_*` → `mv_*` / `mart_<bu>_*`.

```sql
-- Materialized AR snapshot (insert-selected from the bv_ar_by_payer business view; ~24 months)
select * from mv_month_end_ar_snapshot order by month_key desc limit 6;

-- Business views: revenue-cycle funnel lag windows, AR aging ladder, provider productivity ranks
select payer_name, claim_status, charge_to_submit_days, submit_to_remit_days, days_since_prior_payer_claim
from bv_revenue_cycle_funnel where submit_to_remit_days is not null order by submit_to_remit_days desc limit 12;
select payer_name, open_claims, ar_billed, ar_over_90 from bv_ar_by_payer order by ar_billed desc;
select provider_name, specialty, completed_encounters, total_rvu, encounter_rank, rvu_quartile
from bv_provider_productivity order by encounter_rank limit 12;
```

### The code-object catalog and lineage

`catalog.code_object` self-registers every view from `sqlite_master` and carries authored source for the procedures, the function, and the outbound extracts; `lineage_edge` links them to the tables they touch; `integration.job_run` gives them scheduled run history with failures.

```sql
-- Catalog composition: 13 views + 6 authored objects (3 procedures, 1 function, 2 extracts)
select object_type, count(*) from catalog_code_object group by 1 order by 1;

-- The authored procedures/function/extracts (note the known-debt stale function)
select object_name, object_type, notes from catalog_code_object where object_type != 'view' order by object_type, object_name;

-- Lineage edges for the authored code objects
select code_object, operation, table_name from catalog_lineage_edge order by edge_id;

-- Scheduled job-run history with failures (each run belongs to a catalog job)
select j.job_name, r.run_status, count(*) runs, round(avg(r.rows_processed)) avg_rows
from integration_job_run r join integration_job j on j.job_id = r.job_id
group by 1, 2 order by 1, 2;
```
