# Meridian Freightways - Worked Example

A complete fictional freight brokerage and 3PL: OMS customers, TMS
lanes/shipments/carriers, EDI status traffic, accessorials, POD documents,
carrier settlement invoices, exception-workflow cases, raw/staging/xref/core/
warehouse layers, on-time and carrier-scorecard marts, and logged controlled
imperfections. The example emphasizes operational texture: lane distance drives
charges, shipments move through a right-censored lifecycle, PODs and invoices
derive from delivered loads, and late EDI/status defects feed both on-time
restatement and invoice reconciliation stories.

## Run It

```text
python scripts/validate_ecosystem_spec.py examples/logistics/ecosystem_spec.json
python scripts/build_sqlite_ecosystem.py  examples/logistics/ecosystem_spec.json --plan
python scripts/build_sqlite_ecosystem.py  examples/logistics/ecosystem_spec.json --out examples/logistics/build --force
python scripts/validate_sqlite_database.py --db examples/logistics/build/meridian_freightways.db --spec examples/logistics/ecosystem_spec.json --report examples/logistics/build/validation_report.md
python scripts/profile_sqlite_database.py --db examples/logistics/build/meridian_freightways.db --report examples/logistics/build/profile.md
```

At multiplier 1.0 this builds roughly 398k rows across 30 tables and four
required views, and it passes strict validation with a full realism score.
CI-style `--scale-multiplier 0.3` builds also pass strict.

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
- **Control views stay live**: `control_recon_shipment_carrier_invoice`
  reflects post-derivation restatements and billing delays instead of frozen
  validation output.

## Things to Query

```sql
select * from mart_on_time_performance order by ship_month desc, service_level;
select * from mart_carrier_scorecard order by shipments desc limit 10;
select * from control_recon_shipment_carrier_invoice order by abs(break_amount) desc limit 10;
select rule_code, count(*) from dq_rule_result_current group by 1 order by 1;
select status, count(*) from tms_shipment group by 1 order by 2 desc;
select carrier_id, count(*) loads from tms_shipment group by 1 order by 2 desc limit 10;
```
