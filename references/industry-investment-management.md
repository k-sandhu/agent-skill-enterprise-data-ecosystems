# Industry: Investment Management

## Domains

portfolio, trading, security_master, market_data, custodian, manager_feed, private_assets, real_estate, infrastructure, performance, benchmark, risk, treasury, finance, compliance.

## Source Systems

Portfolio accounting, order management, execution management, security master, market data vendor feeds, custodian feeds, external manager portal, private asset portal, performance engine, risk platform, treasury workstation, ERP/GL, data warehouse.

## Core Tables

- `portfolio.portfolio`, `portfolio.account`, `portfolio.pool`, `portfolio.portfolio_pool_membership`
- `portfolio.holding_position`, `portfolio.cash_position`, `portfolio.transaction`
- `trading.trade_order`, `trading.execution`, `trading.trade_allocation`
- `security_master.security`, `security_master.security_identifier`, `security_master.issuer`
- `market_data.price`, `market_data.fx_rate`, `market_data.benchmark_level`
- `custodian.raw_position`, `custodian.raw_transaction`, `custodian.account_mapping`
- `manager_feed.manager_statement`, `manager_feed.manager_holding`
- `private_assets.commitment`, `private_assets.capital_call`, `private_assets.distribution`, `private_assets.nav_statement`
- `performance.return_monthly`, `performance.attribution_monthly`
- `risk.exposure`, `risk.guideline_breach`
- `finance.journal_entry`, `finance.gl_balance`

## Facts and Dimensions

- `fact_holding_daily`: one portfolio-security-business_date.
- `fact_cash_balance_daily`: one portfolio-currency-business_date.
- `fact_trade_allocation`: one allocated execution per portfolio-security-trade_date.
- `fact_private_asset_cashflow`: one private asset cash flow event.
- `fact_performance_monthly`: one portfolio or composite per month.
- `fact_risk_exposure_daily`: one portfolio-risk_factor-business_date.

Dimensions: portfolio, security, issuer, asset_class, currency, custodian, manager, benchmark, date, legal_entity.

## Dataflows

- Trade-to-settle: order -> execution -> allocation -> custodian confirmation -> transaction -> holding -> GL.
- Position reconciliation: custodian raw position -> staging -> internal holding -> reconciliation break/workflow.
- Performance: holdings + transactions + prices + FX -> return calculation -> benchmark comparison -> executive reporting.
- Private asset NAV: commitment -> capital call/distribution -> manager statement -> NAV -> valuation adjustment -> performance.

## Controls

- Custodian positions tie to internal holdings by portfolio/security/date.
- Cash balances tie to bank/custodian statements.
- Trades tie to confirmations and settlement.
- Market values tie to security prices and FX rates.
- Private asset NAVs tie to manager statements and valuation committee approvals.

## Imperfections

Unmapped securities, stale prices, late custodian files, corrected trades, restated private NAVs, mismatched FX, manager statements with missing holdings, legacy portfolio codes, duplicate security identifiers.
