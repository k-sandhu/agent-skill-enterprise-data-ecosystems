# Cedar Summit Health Partners — Ambulatory Healthcare Network

A complete fictional 12-clinic ambulatory network: practice management (patients, coverage, appointments with booked services), EHR clinicals (encounters, diagnoses, procedures derived from completed visits — real lineage), revenue cycle (charges, claims, remittances, denial worklist), an EMPI raw/staging/xref/canonical patient mastering flow, warehouse dims and facts, mart/control/DQ views, and 12 logged controlled imperfections. Two state machines run on the appointment table: a scheduling lifecycle (scheduled → checked_in → completed / no_show / cancelled, ~13% no-show) and a claim lifecycle anchored on the visit's completion timestamp (denial rate ~11% of adjudicated, with resubmission and appeal paths). No real PII anywhere: surrogate MRNs, persona-pool names, birth year only, 555-01xx phones, example.com emails, NPIs in the provably fictional 9xxxxxxxxx range.

## Run It

```text
python scripts/validate_ecosystem_spec.py examples/healthcare-clinic/ecosystem_spec.json
python scripts/build_sqlite_ecosystem.py  examples/healthcare-clinic/ecosystem_spec.json --plan
python scripts/build_sqlite_ecosystem.py  examples/healthcare-clinic/ecosystem_spec.json --out examples/healthcare-clinic/build --force
python scripts/validate_sqlite_database.py --db examples/healthcare-clinic/build/cedar_summit_health_partners.db --spec examples/healthcare-clinic/ecosystem_spec.json --report examples/healthcare-clinic/build/validation_report.md
python scripts/profile_sqlite_database.py --db examples/healthcare-clinic/build/cedar_summit_health_partners.db --report examples/healthcare-clinic/build/profile.md
```

At multiplier 1.0 this builds ~875k rows across 34 tables and 4 views in ~15 seconds and passes strict validation (0 critical, 0 warnings, realism 10/10); `--scale-multiplier 0.3` builds ~270k rows and also passes strict.

## Patterns Worth Copying

- **Two machines on one table, chained by a timestamp**: the scheduling machine writes `completed_at`; the claim machine (declared second) anchors its `start_column` on it, so rows that never completed are *skipped* and legitimately stay `not_billed`. This is how to make a second lifecycle exist only for entities that reached a milestone — no orphan claims for no-shows, ever.
- **Status-dependent children via derivation, status-independent children via generation**: services are *booked with* the appointment (generator, per_parent — they validly exist for visits that later no-show), while encounters/procedures/charges are SQL-derived only from visits that checked in / completed. Coherence falls out of the join, not patching.
- **`fk_copy` price × integer units at the booking line**: `fee_snapshot` snapshots the chargemaster fee (whole-dollar `price_endings: [0.0]`), `booked_amount = fee × units`, and the same exact amounts flow by derivation through procedure → charge → claim line — honest duplicate mass at every layer.
- **Residual probability as workqueue fodder**: 1.5% of past appointments never leave `scheduled` (front-desk reconciliation backlog → DQ-010) and 1.5% of completed visits never reach charge entry (DNFB → DQ-001). Open pipeline is guaranteed at any scale multiplier, not dependent on right-censoring luck.
- **Remittance disposition identity by construction**: contractual = billed − allowed, patient responsibility by payer type (20% coinsurance Medicare, copay-capped commercial via the coverage row's own `copay_amount`, full balance self-pay), paid = allowed − patient responsibility. The 835 invariant `paid + adjustment + patient = billed` holds to the cent on every row.
- **Self-pay as a configured financial class**: a "Self-Pay / Patient Direct" payer row lets self-pay visits flow through the same claim machinery with zero payer payment and the balance as patient responsibility — the way real PM systems actually model it.
- **Root-cause correlation in derived attributes**: denied claims whose registration bypassed eligibility verification (`manual_override` imperfection) draw 'eligibility' as their denial reason ~75% of the time vs ~25% baseline — the cross-tab a denial analyst would actually run tells the intended story.
- **Recon breaks from snapshot-vs-moving-target**: claim lines snapshot posted charges at claim generation; post-derivation charge restatement pairs and interface drops then move `billing.charge`, so `control_recon_charge_claim` shows ~700 explained breaks, exactly how real charge-to-claim recons fail.

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
from workflow_denial_worklist group by 1, 2 order by 4 desc;
```
