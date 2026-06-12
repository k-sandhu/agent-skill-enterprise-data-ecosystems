# Ironvale Equipment Works - Worked Example

A complete fictional discrete manufacturer of industrial equipment: PLM parts
and BOMs, ERP items/work centers, MES work orders and operations, machine
downtime, maintenance orders, quality inspections, inventory movements,
raw/staging/xref/core/warehouse layers, OEE/yield/WIP marts, cataloged code and
lineage, and logged controlled
imperfections. The model is built around manufacturing invariants: work-order
operations roll through a machine lifecycle, material consumption reconciles to
BOM expectations, yield and downtime vary by work center, and quality escapes
plus maintenance delays appear as catchable operational defects. ERP, MES,
CMMS, and quality feeds land into raw file tables before guarded staging
parsing and deduplication.

## Run It

```text
python scripts/validate_ecosystem_spec.py examples/manufacturing/ecosystem_spec.json
python scripts/build_sqlite_ecosystem.py  examples/manufacturing/ecosystem_spec.json --plan
python scripts/build_sqlite_ecosystem.py  examples/manufacturing/ecosystem_spec.json --out examples/manufacturing/build --force --scale-multiplier 0.3
python scripts/validate_sqlite_database.py --db examples/manufacturing/build/ironvale_equipment_works.db --spec examples/manufacturing/ecosystem_spec.json --report examples/manufacturing/build/validation_report.md --strict
python scripts/profile_sqlite_database.py --db examples/manufacturing/build/ironvale_equipment_works.db --report examples/manufacturing/build/profile.md
```

The multiplier 1.0 plan forecasts about 95k generated rows before SQL
derivations. A CI-style `--scale-multiplier 0.3` build currently produces
156,045 rows across 47 populated tables and passes strict validation with
0 criticals, 0 warnings, and a full realism score.

## Patterns Worth Copying

- **BOM and routing are operational anchors**: work orders, operations,
  material movement, and yield derive from product structure rather than
  parallel fake facts.
- **Machine calendars are imperfect**: downtime and maintenance work orders
  create realistic OEE dents by work center and shift.
- **Quality signals correlate with operations**: inspection outcomes,
  scrap/rework, and yield marts are tied to production flow rather than uniform
  rates.
- **Consumption-vs-BOM recon is live**:
  `control_recon_consumption_vs_bom` surfaces material over/under-consumption
  created by controlled restatements and operational drift.
- **Warehouse views are layered**: `nv_*` views rejoin facts to dimensions,
  `bv_*` views calculate OEE, yield, and WIP roll-forward metrics,
  `mv_month_end_wip_snapshot` materializes month-end close state, and BU marts
  intentionally disagree where definitions differ.
- **Manual mappings are asymmetric**:
  `manual_work_center_cost_center_mapping` is applied only by cost accounting;
  plant operations keeps raw work-center definitions. Gaps and conflicts feed
  `workflow_mapping_request` and DQ rules.
- **Code is cataloged**: deployed views self-register from `sqlite_master`, and
  procedures/functions/extracts/feeds are represented in `catalog_code_object`,
  `catalog_lineage_edge`, and `integration_job_run`.
- **DQ rules match shop-floor failure modes**: duplicate part setup,
  missing/stale xrefs, format drift, and manual overrides are routed to named
  DQ/control queues.

## Things to Query

```sql
select * from bv_oee_daily order by production_date desc limit 14;
select * from bv_yield_by_routing order by unit_scrap_rate desc limit 10;
select * from mv_month_end_wip_snapshot order by month_end_date desc, plant limit 20;
select * from control_recon_consumption_vs_bom order by abs(variance_value) desc limit 10;
select * from control_recon_scrap_metric_discrepancy order by abs(scrap_rate_delta) desc limit 10;
select rule_code, count(*) from dq_rule_result_current group by 1 order by 1;
select object_name, object_type, owner, stale_flag from catalog_code_object order by object_type, object_name;
select code_object_name, source_dataset, target_dataset, edge_type from catalog_lineage_edge order by lineage_edge_id limit 20;
select job_name, run_status, count(*) runs, sum(rows_processed) rows_processed from integration_job_run group by 1, 2 order by 1, 2;
select status, count(*) from production_work_order group by 1 order by 2 desc;
select work_center_id, count(*) operations from mes_operation group by 1 order by 2 desc limit 10;
```
