# Meridian Freightways - Worked Example

A complete fictional freight brokerage and 3PL: OMS customers, TMS
lanes/shipments/carriers, EDI 204/214 landing feeds, carrier invoice files,
POD document feeds, accessorials, settlement invoices, workflow cases, raw/
staging/xref/core/warehouse layers, a full normalized/business/materialized/
BU view stack, code-object catalog, job history, lineage edges, manual carrier
alias mappings, and logged controlled imperfections. The example emphasizes
operational texture: lane distance drives charges, shipments move through a
right-censored lifecycle, landed files are staged with guarded parsing and
deduplication, and settlement-vs-network-ops carrier spend intentionally
differs because only settlement applies the alias spreadsheet.

## Run It

```text
python scripts/validate_ecosystem_spec.py examples/logistics/ecosystem_spec.json
python scripts/build_sqlite_ecosystem.py  examples/logistics/ecosystem_spec.json --plan
python scripts/build_sqlite_ecosystem.py  examples/logistics/ecosystem_spec.json --out examples/logistics/build --force
python scripts/validate_sqlite_database.py --db examples/logistics/build/meridian_freightways.db --spec examples/logistics/ecosystem_spec.json --report examples/logistics/build/validation_report.md --strict
python scripts/profile_sqlite_database.py --db examples/logistics/build/meridian_freightways.db --report examples/logistics/build/profile.md
```

CI-style iteration can use:

```text
python scripts/build_sqlite_ecosystem.py examples/logistics/ecosystem_spec.json --out %TEMP%/logistics-build --force --scale-multiplier 0.3
python scripts/validate_sqlite_database.py --db %TEMP%/logistics-build/meridian_freightways.db --spec examples/logistics/ecosystem_spec.json --strict
```

At multiplier 0.3 this builds about 211k rows across 45 populated tables,
including 13 required views and the `mv_week_end_lane_summary` materialized
table, and passes strict validation with zero warnings and a full realism
score.

## Patterns Worth Copying

- **Shipment lifecycle is the spine**: booked, pickup, in-transit, delivered,
  exception, and POD timestamps come from the machine, so recent loads
  legitimately remain open.
- **Derived settlement prevents contradictions**: carrier invoices and POD
  records are derived from shipment outcomes, so missing-POD and late-billing
  populations are controlled rather than random.
- **Lane and carrier economics show concentration**: lanes, customers, and
  carriers use skewed parent activity, giving scorecards the top-heavy shape
  brokers expect.
- **EDI defects are observable**: duplicate gateway messages, unmapped PRO
  numbers, late statuses, and out-of-order events all show up through DQ views
  or the carrier invoice reconciliation.
- **Layered views stack on views**: `nv_*` views rejoin facts to dimensions,
  `bv_*` views calculate business metrics, `mv_week_end_lane_summary` stores a
  refreshed lane summary, and BU marts sit above those views.
- **Manual aliases are asymmetric**: `manual_carrier_alias_mapping` is applied
  in `mart_settlement_carrier_spend` but not in
  `mart_networkops_carrier_spend`, creating an intentional carrier-spend
  discrepancy and mapping-request workflow cases.
- **Code is cataloged**: deployed views self-register from `sqlite_master`;
  procedure, function, extract, job, run-history, and lineage rows make the
  ecosystem queryable as code plus data.

## Things to Query

```sql
select * from mart_on_time_performance order by ship_month desc, service_level;
select * from mart_carrier_scorecard order by loads desc limit 10;
select * from control_recon_shipment_carrier_invoice order by abs(break_amount) desc limit 10;
select rule_code, count(*) from dq_rule_result_current group by 1 order by 1;
select status, count(*) from tms_shipment group by 1 order by 2 desc;
select carrier_id, count(*) loads from tms_shipment group by 1 order by 2 desc limit 10;

-- View-stack lineage.
select source_object, transformation_object, target_object, edge_type
from catalog_lineage_edge
where target_object like 'mart_%'
   or target_object like 'bv_%'
   or target_object = 'mv.week_end_lane_summary'
order by lineage_edge_id;

-- Settlement-vs-network-ops carrier spend discrepancy.
select month_key, carrier_identity, networkops_spend, settlement_spend,
       amount_delta, break_type
from control_recon_settlement_ops_carrier_spend
order by abs(amount_delta) desc
limit 20;

-- Code catalog: self-registered views plus modeled routines and extracts.
select object_type, object_name, owner_team, deployment_status
from catalog_code_object
order by object_type, object_name;

-- Job-run history with failures and partials.
select j.job_name, r.run_status, count(*) runs, sum(r.rows_processed) rows_processed
from integration_job j
join integration_job_run r on r.job_id = j.job_id
group by j.job_name, r.run_status
order by j.job_name, r.run_status;
```
