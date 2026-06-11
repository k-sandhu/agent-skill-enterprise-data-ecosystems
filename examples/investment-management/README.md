# Northbridge Capital Partners - Investment Management Example

A complete fictional institutional investment manager: portfolio accounting,
OMS/EMS trading, security master, custodian position feeds, private fund
commitments and NAV statements, risk guideline monitoring, integration load
logs, raw/staging/xref/core/warehouse layers, AUM/NAV/trade-funnel marts,
reconciliation controls, and DQ views. The example focuses on
investment-operations realism: trade orders move through compliance, execution,
allocation, and settlement states; custodian positions are independently mapped
into canonical holdings; private assets have lumpy quarterly NAVs; and
security-master/custodian mapping defects are logged and observable.

## Run It

```text
python scripts/validate_ecosystem_spec.py examples/investment-management/ecosystem_spec.json
python scripts/build_sqlite_ecosystem.py  examples/investment-management/ecosystem_spec.json --plan
python scripts/build_sqlite_ecosystem.py  examples/investment-management/ecosystem_spec.json --out examples/investment-management/build --force
python scripts/validate_sqlite_database.py --db examples/investment-management/build/northbridge_capital_partners.db --spec examples/investment-management/ecosystem_spec.json --report examples/investment-management/build/validation_report.md
python scripts/profile_sqlite_database.py --db examples/investment-management/build/northbridge_capital_partners.db --report examples/investment-management/build/profile.md
```

## Patterns Worth Copying

- **Custodian vs IBOR separation**: custodian positions land raw, parse through
  staging, map through `xref.security_identifier_map`, then become canonical
  holdings. Mapping defects remain visible instead of being silently repaired.
- **Trade lifecycle truth**: OMS orders pass through compliance, route, fill,
  allocation, and settlement states; blocked and failed-settlement records
  remain in the dataset as real workflow populations.
- **Private asset lumpiness**: commitments produce uneven quarterly NAV
  statements; restatement reversals create valuation-review evidence.
- **Security master controls are first-class**: duplicate setup, stale mappings,
  and missing crosswalk rows are modeled as DQ issues with named catcher views.
- **Warehouse and marts are derived**: facts and views are populated by SQL from
  source layers, so lineage is inspectable and defects propagate.

## Things to Query

```sql
select * from mart_aum_by_asset_class order by position_date desc, market_value desc limit 20;
select * from mart_private_nav_rollforward order by committed desc;
select * from mart_trade_settlement_funnel order by orders desc;
select * from control_recon_custodian_vs_ibor order by abs(break_amount) desc limit 10;
select * from control_private_nav_restatement order by versions desc limit 10;
select rule_code, count(*) from dq_rule_result_current group by 1 order by 1;
select status, count(*) from trading_trade_order group by 1 order by 2 desc;
```
