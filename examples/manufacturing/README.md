# Ironvale Equipment Works - Worked Example

A complete fictional discrete manufacturer of industrial equipment: PLM parts
and BOMs, ERP items/work centers, MES work orders and operations, machine
downtime, maintenance orders, quality inspections, inventory movements,
raw/staging/xref/core/warehouse layers, OEE/yield marts, and logged controlled
imperfections. The model is built around manufacturing invariants: work-order
operations roll through a machine lifecycle, material consumption reconciles to
BOM expectations, yield and downtime vary by work center, and quality escapes
plus maintenance delays appear as catchable operational defects.

## Run It

```text
python scripts/validate_ecosystem_spec.py examples/manufacturing/ecosystem_spec.json
python scripts/build_sqlite_ecosystem.py  examples/manufacturing/ecosystem_spec.json --plan
python scripts/build_sqlite_ecosystem.py  examples/manufacturing/ecosystem_spec.json --out examples/manufacturing/build --force
python scripts/validate_sqlite_database.py --db examples/manufacturing/build/ironvale_equipment_works.db --spec examples/manufacturing/ecosystem_spec.json --report examples/manufacturing/build/validation_report.md
python scripts/profile_sqlite_database.py --db examples/manufacturing/build/ironvale_equipment_works.db --report examples/manufacturing/build/profile.md
```

At multiplier 1.0 this builds roughly 259k rows across 30 tables and four
required views, and it passes strict validation with a full realism score.
CI-style `--scale-multiplier 0.3` builds also pass strict.

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
- **DQ rules match shop-floor failure modes**: duplicate part setup,
  missing/stale xrefs, format drift, and manual overrides are routed to named
  DQ/control queues.

## Things to Query

```sql
select * from mart_oee_daily order by production_date desc limit 14;
select * from mart_yield_by_work_center order by yield_rate limit 10;
select * from control_recon_consumption_vs_bom order by abs(variance_amount) desc limit 10;
select rule_code, count(*) from dq_rule_result_current group by 1 order by 1;
select status, count(*) from production_work_order group by 1 order by 2 desc;
select work_center_id, count(*) operations from mes_operation group by 1 order by 2 desc limit 10;
```
