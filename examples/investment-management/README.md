# Northbridge Capital Partners - Investment Management Example

A complete fictional institutional investment manager: portfolio accounting,
OMS/EMS trading, security master, custodian position and transaction feeds,
private fund commitments and NAV statements, risk guideline monitoring,
integration job history, raw/staging/xref/core/warehouse layers, normalized and
business view stacks, materialized month-end AUM snapshots, business-unit marts,
reconciliation controls, DQ views, workflow mapping queues, and code/lineage
catalogs.

The example focuses on investment-operations realism: custodian files land with
file and batch metadata, resent custodian files are deduped in staging, trades
move through compliance and settlement lifecycles, manual performance-composite
mappings are imperfect and audited, performance and client-reporting marts use
competing AUM definitions, and deployed views/procedures/extracts register in
the code catalog.

## Run It

```text
python scripts/validate_ecosystem_spec.py examples/investment-management/ecosystem_spec.json
python scripts/build_sqlite_ecosystem.py  examples/investment-management/ecosystem_spec.json --plan
python scripts/build_sqlite_ecosystem.py  examples/investment-management/ecosystem_spec.json --out examples/investment-management/build --force
python scripts/validate_sqlite_database.py --db examples/investment-management/build/northbridge_capital_partners.db --spec examples/investment-management/ecosystem_spec.json --report examples/investment-management/build/validation_report.md --strict
python scripts/profile_sqlite_database.py --db examples/investment-management/build/northbridge_capital_partners.db --report examples/investment-management/build/profile.md
```

## Patterns Worth Copying

- **Deep landing and staging**: custodian position files, custodian transaction
  files, OMS trade extracts, security-master vendor feeds, and private manager
  statements land raw with `file_batch_id` and `ingested_at`, then parse through
  guarded staging tables.
- **Layered view stack**: `nv_*` views rejoin warehouse facts to dimensions,
  `bv_*` views add business logic, `mv.month_end_aum_snapshot` models a SQLite
  materialized view, and BU marts sit above the snapshot.
- **Asymmetric manual mapping**: `manual.strategy_composite_mapping` is audited
  and effective-dated; performance applies it with an `UNASSIGNED` fallback,
  while client reporting does not.
- **Code as data**: `catalog.code_object` self-registers SQLite views from
  `sqlite_master` and adds modeled procedures, a function, and extract
  definitions; `catalog.lineage_edge` links them to upstream/downstream objects.
- **Observable operations**: `integration.job` and `integration.job_run` show
  feed, procedure, materialized-view refresh, and extract history with failed
  and partial runs.

## Things to Query

```sql
select * from nv_holding_detail order by position_date desc, market_value desc limit 20;
select * from bv_holdings_rollforward order by month_key desc, ending_market_value desc limit 20;
select * from bv_guideline_breach_funnel order by breach_month desc, breaches desc;
select * from mart_performance_aum_by_strategy order by snapshot_month desc, performance_aum desc;
select * from mart_clientreporting_aum_by_strategy order by snapshot_month desc, client_reporting_aum desc;
select * from control_recon_performance_vs_client_aum order by abs(aum_delta) desc limit 20;
select * from workflow_mapping_request_queue order by created_at desc limit 20;
select rule_code, count(*) from dq_rule_result_current group by 1 order by 1;
```

## Lineage And Operations Queries

```sql
select source_object, target_object, transformation_object, edge_type
from catalog_lineage_edge
order by lineage_edge_id;

select snapshot_month, performance_aum, client_reporting_aum, aum_delta, break_type
from control_recon_performance_vs_client_aum
order by abs(aum_delta) desc;

select object_schema, object_name, object_type, owner_team, deployment_status
from catalog_code_object
order by object_type, object_name;

select j.job_name, j.job_type, r.run_started_at, r.run_status, r.rows_processed, r.error_note
from integration_job_run r
join integration_job j on j.job_id = r.job_id
where r.run_status in ('failed', 'partial')
order by r.run_started_at desc
limit 25;
```
