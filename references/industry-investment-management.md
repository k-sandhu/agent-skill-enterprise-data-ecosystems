# Industry: Investment Management

## Operating Context

- Institutional asset owner/manager (pension-style or endowment-style) investing across public assets (equity, fixed income, cash) and private assets (private equity, real estate, infrastructure, private credit).
- Money flows: contributions/inflows -> pooled portfolios -> trades and capital calls -> custodian settlement -> income, distributions, redemptions -> benefit payments or client withdrawals.
- Mix of internally managed public portfolios and externally managed mandates/funds; external managers report via statements, not trade-level feeds.
- Custodian is the independent record of settled positions and cash; internal portfolio accounting is the investment book of record; daily reconciliation between the two is a core control.
- Regulated for fiduciary duty, valuation governance, investment guideline compliance, and financial reporting; valuation committee approves private asset marks and NAV restatements.
- Scale anchors: 20-80B AUM, 150-600 portfolios/accounts, 8k-25k active public securities held, 150-500 private asset commitments, 2-5 custodians, 30-120 external managers.

## Domains

portfolio, trading, security_master, market_data, custodian, manager_feed, private_assets, real_estate, infrastructure, performance, benchmark, risk, treasury, finance, compliance.

## Source Systems

| System | Role | System-of-record domains | Typical data quirks |
| --- | --- | --- | --- |
| Portfolio accounting platform | Investment book of record (IBOR/ABOR) | portfolio, holdings, transactions | as-of corrections, backdated transactions, legacy portfolio codes |
| Order management system | Order capture, compliance pre-trade checks | trade_order | cancelled/replaced orders, allocation rounding residue |
| Execution management system | Broker routing and fills | execution | partial fills, duplicate fill messages, late broker corrections |
| Security master platform | Instrument reference data | security_master | duplicate identifiers across vendors, delayed corporate action updates |
| Market data vendor feeds | Prices, FX, benchmark levels | market_data, benchmark | stale prices on illiquid bonds, vendor format_drift, missing holiday fixings |
| Custodian feeds (per custodian) | Settled positions, cash, settled transactions | custodian (external record) | late files, different security identifiers, T+1 lag vs internal trade-date view |
| External manager portal | Manager statements for external mandates | manager_feed | monthly-only granularity, missing holdings detail, PDF-to-data extraction errors |
| Private asset portal | Commitments, capital calls, distributions, NAV statements | private_assets | quarter-lagged NAVs, restated NAVs, recallable distributions misclassified |
| Performance engine | Returns, attribution, composites | performance | recalculation after restatements, composite membership churn |
| Risk platform | Exposures, guideline monitoring | risk | proxy mappings for unmodeled securities, overnight batch dependency |
| Treasury workstation | Cash forecasting, FX hedging, collateral | treasury | manual wire entries, hedge ratio overrides |
| ERP/GL | Financial ledger, expenses, fees | finance | monthly granularity, summarized investment postings, manual journals |
| Data warehouse | Integrated analytics layer | (consumer, not SOR) | late-arriving custodian data, snapshot vs event mixing |

## Core Tables

- `portfolio.portfolio`, `portfolio.account`, `portfolio.pool`, `portfolio.portfolio_pool_membership`
- `portfolio.holding_position`, `portfolio.cash_position`, `portfolio.transaction`
- `portfolio.position_adjustment`, `portfolio.corporate_action_event`
- `trading.trade_order`, `trading.execution`, `trading.trade_allocation`
- `trading.broker_confirmation`, `trading.settlement_instruction`, `trading.trade_amendment`
- `security_master.security`, `security_master.security_identifier`, `security_master.issuer`
- `security_master.security_classification`, `security_master.unmapped_security_queue`
- `market_data.price`, `market_data.fx_rate`, `market_data.benchmark_level`
- `market_data.price_source_rank`, `market_data.stale_price_flag`
- `custodian.raw_position`, `custodian.raw_transaction`, `custodian.raw_cash_balance`, `custodian.account_mapping`
- `custodian.recon_run`, `custodian.recon_break`
- `manager_feed.manager_statement`, `manager_feed.manager_holding`, `manager_feed.manager_mandate`
- `private_assets.commitment`, `private_assets.capital_call`, `private_assets.distribution`, `private_assets.nav_statement`
- `private_assets.nav_restatement`, `private_assets.valuation_adjustment`, `private_assets.fund_vehicle`
- `real_estate.property_asset`, `real_estate.appraisal`
- `infrastructure.project_asset`, `infrastructure.concession_agreement`
- `performance.return_monthly`, `performance.attribution_monthly`, `performance.composite_membership`, `performance.return_restatement`
- `benchmark.benchmark_definition`, `benchmark.benchmark_assignment`
- `risk.exposure`, `risk.guideline_rule`, `risk.guideline_breach`
- `treasury.cash_forecast`, `treasury.fx_hedge`, `treasury.wire_instruction`
- `finance.journal_entry`, `finance.gl_balance`, `finance.management_fee_accrual`
- `compliance.restricted_list`, `compliance.pre_trade_check_result`

## Warehouse Facts and Dimensions

- `fact_holding_daily`: grain = one row per portfolio per security per business_date (semi-additive market value; quantity, book value, accrued income).
- `fact_cash_balance_daily`: grain = one row per portfolio per currency per business_date (semi-additive balance).
- `fact_trade_allocation`: grain = one row per allocated execution per portfolio per security per trade_date (additive quantity, gross/net amount, commission).
- `fact_transaction`: grain = one row per posted portfolio transaction per posting version (additive amounts; reversal/rebook pairs share a correction_group_id).
- `fact_private_asset_cashflow`: grain = one row per capital call or distribution event per commitment (additive call/distribution amounts; recallable flag).
- `fact_nav_statement`: grain = one row per fund vehicle per valuation period per statement version (latest-version flag; restatements add versions).
- `fact_performance_monthly`: grain = one row per portfolio or composite per month per calculation version (non-additive returns; benchmark return, excess return).
- `fact_risk_exposure_daily`: grain = one row per portfolio per risk_factor per business_date.
- `fact_recon_break`: grain = one row per reconciliation break per recon_run (aged via open/close dates).

Dimensions: dim_portfolio, dim_security, dim_issuer, dim_asset_class, dim_currency, dim_custodian, dim_manager, dim_benchmark, dim_fund_vehicle, dim_legal_entity, dim_date (roles: trade, settle, posting, valuation, as_of).

## Critical Dataflows

- Trade-to-settle: order -> pre-trade compliance check -> execution -> allocation -> broker confirmation -> custodian settlement confirmation -> transaction -> holding -> GL.
- Position reconciliation: custodian raw position file -> staging -> identifier mapping (xref) -> compare vs internal holding -> recon break -> workflow case -> adjustment or accept.
- Cash reconciliation: custodian raw cash balance -> staging -> compare vs internal cash position -> break -> wire/fee investigation -> resolution.
- Performance: holdings + transactions + prices + FX -> daily return calculation -> monthly geometric linking -> benchmark comparison -> attribution -> composite -> executive reporting.
- Private asset NAV: commitment -> capital call/distribution notices -> manager statement -> NAV statement -> valuation committee adjustment -> roll-forward into holdings -> performance.
- NAV restatement ripple: restated manager NAV -> nav_restatement -> reversed/rebooked valuation transactions -> performance recalculation versions -> restated monthly returns -> board reporting footnote.
- Security setup: new identifier on trade or custodian file -> unmapped_security_queue -> data steward enrichment -> security master -> downstream price subscription.
- Corporate actions: vendor announcement -> election (if voluntary) -> position/cash adjustment -> custodian confirmation -> recon tie-out.

## State Machines

- Trade order: created -> compliance_checked (0.97, minutes) | compliance_blocked (0.03) -> routed -> partially_filled -> filled (0.93, same day) | cancelled (0.05) | expired (0.02) -> allocated -> confirmed (0.98, T+0/T+1) -> settled (0.985, T+1/T+2) | failed_settlement (0.015, resolved lognormal median 2 business days, p90 6).
- Recon break: detected -> assigned (within 1 business day) -> investigating -> resolved_timing (0.55, lognormal median 1 business day, p90 3) | resolved_mapping_fix (0.20, median 2 days) | resolved_adjustment (0.15, median 3 days, requires approval) | accepted_within_tolerance (0.08) | escalated (0.02, p90 15 business days).
- Capital call: notice_received -> validated (0.95, 1-2 business days) | disputed (0.05) -> funding_approved -> wire_sent -> cash_settled (due in 7-12 calendar days from notice) -> posted_to_portfolio.
- NAV statement: received -> parsed -> preliminary (quarter-end + lognormal median 45 calendar days, p90 75) -> reviewed -> approved (0.92) | adjusted_by_valuation_committee (0.08) -> final -> restated (0.06 of finals, arriving 1-2 quarters later).
- Guideline breach: detected -> confirmed_active (0.70) | false_positive (0.30) -> remediation_in_progress -> cured (0.95, lognormal median 3 business days, p90 10) | waiver_granted (0.05).
- Unmapped security: queued -> auto_matched (0.60, hours) | steward_review (0.40) -> enriched -> mapped (0.97, lognormal median 1 business day, p90 4) | rejected_duplicate (0.03).

## Volumetrics and Distributions

| Metric | Typical value or range | Distribution | Notes |
| --- | --- | --- | --- |
| Portfolios/accounts | 150-600 | n/a | cardinality anchor; 60-70% public, rest private/overlay |
| Securities held (public) | 8k-25k active | n/a | total security master 3-5x held universe |
| Trade orders per business day | 300-1,500 | poisson, mean 700 | rebalance days 3-5x baseline |
| Executions per order | 1-12 | lognormal, median 2 | large fixed income orders in the tail |
| Allocations per execution | 1-40 | zipf s=1.3 | block trades split across many portfolios |
| Trade notional (public) | 50k-5M typical; tail to 200M | lognormal, median 800k | program trades dominate tail |
| Custodian position rows per day | 30k-120k | n/a | roughly holdings x custodians |
| Recon break rate (positions) | 0.003-0.01 of compared rows | n/a | spikes 3x after corporate action dates |
| Private commitments active | 150-500 | n/a | 5-15 new per quarter |
| Capital calls per commitment per year | 2-6 | poisson, mean 3.5 | front-loaded in years 1-4 of fund life |
| Distributions per commitment per year | 1-5 | poisson, mean 2 | back-loaded in years 5-12 |
| Capital call amount | 0.5-5% of commitment; commitment 10M-150M | lognormal, median 2M | tail calls to 25M |
| NAV restatement rate | 0.04-0.08 of final NAVs | weighted choice by manager quality | clusters around audit season (Q1) |
| Manager statements per month | 30-120 | n/a | one per external mandate/fund |
| Activity skew across portfolios | top 10% of portfolios = ~55% of trade volume | zipf s=1.1 | large pooled funds dominate |
| Guideline breaches per month | 5-30 detected | poisson, mean 12 | 30% false positive |
| Price records per day | 10k-40k | n/a | 1-3% stale on illiquid fixed income |
| FX pairs priced daily | 25-60 | n/a | triangulation for minors |
| Unmapped securities per week | 10-60 | poisson, mean 25 | spikes with new mandates onboarding |

## Business Rules and Invariants

- Holding roll-forward holds per portfolio-security-day: begin_mv + purchases - sales + income +/- market_movement +/- fx_effect = end_mv.
- Cash roll-forward holds per portfolio-currency-day: open + inflows - outflows + trade_settlements + income - fees = close.
- Private NAV roll-forward holds per commitment per period: begin_nav + calls - distributions +/- valuation_change = end_nav.
- sum(trade_allocation.quantity) = execution.fill_quantity per execution; allocation rounding residue assigned to one designated portfolio.
- sum(execution.fill_quantity) <= order.quantity; filled status requires sum = order quantity net of cancels.
- settle_date >= trade_date; transaction posting_date >= trade_date; custodian settled position reflects trades through settle_date only (timing breaks are expected, not errors).
- Every holding_position.security_id exists in security_master.security; unmapped securities sit in unmapped_security_queue, never in holdings.
- cumulative(distributions) <= cumulative(calls) + total_gain per commitment; called_to_date <= commitment_amount + recallable_amount.
- Each nav_restatement reverses a prior fact_nav_statement version: restatement_reversal pairs net to the delta, latest_version_flag unique per fund-period.
- Monthly portfolio return geometrically links from daily returns within tolerance 0.0002; composite return = asset-weighted member returns.
- market_value = quantity x price x fx_rate (to base currency) within tolerance 0.0001 of stored value.
- A guideline_breach must reference an active guideline_rule effective-dated to the breach date.
- GL investment balance per legal entity ties to sum of portfolio market values + accruals at month-end.
- No transaction may post to a closed portfolio (status = closed with effective_end_date < posting_date) without a manual_override record.

## Controls and Reconciliations

| Control | Grain | Tolerance | Expected break rate |
| --- | --- | --- | --- |
| Custodian position vs internal holding | portfolio-security-business_date | 0 units or 0.01% mv | 0.005 of rows; 0.7 of breaks are settlement timing |
| Custodian cash vs internal cash | portfolio-currency-business_date | 100 base currency units | 0.01 of rows |
| Trade vs broker confirmation | execution | exact on qty, 0.01 on price | 0.01 unconfirmed by T+0 close |
| Settlement tie-out | settlement_instruction | exact | 0.015 fail rate, mostly resolved T+3 |
| Price coverage and staleness | security-business_date | price age <= 1 day (public) | 0.02 stale, concentrated in illiquid credit |
| Market value recompute (qty x price x fx) | holding row | 0.0001 relative | 0.002 |
| Private NAV vs manager statement | fund_vehicle-period | exact on stated NAV | 0.03 mismatch (parse or version skew) |
| NAV roll-forward check | commitment-period | 0.001 relative | 0.01 |
| Performance return recompute | portfolio-month | 0.0002 absolute | 0.005, spikes after restatements |
| Composite membership integrity | composite-month | no gaps/overlaps | 0.005 of memberships |
| Investment GL tie-out | legal_entity-month | 1,000 base currency units | 0.02 of entity-months need adjustment |
| Manager statement completeness | mandate-month | all expected statements received by BD+10 | 0.05 late |
| Capital call cash settlement | capital_call | exact, by due date | 0.02 late funding |

## Seasonality and Temporal Patterns

- Trading volume on business days only; Mon-Thu roughly even, Friday -15%; spikes 3-5x on month-end rebalance dates and index reconstitution days.
- Intraday: order creation peaks at market open and close; custodian files arrive overnight (02:00-06:00 local), occasional late files until noon.
- Month-end: price/FX volumes spike, recon volume +50%, performance and GL close runs BD+1 to BD+5.
- Quarter-end: private asset NAV statements arrive 30-75 calendar days after quarter-end; Q4 NAVs (audited) arrive latest and drive Q1 restatement cluster.
- Capital call activity steady year-round with mild Q4 uptick; distributions cluster around fund exit events, lumpy.
- Annual: audit season (Jan-Mar) drives restatements, GL adjustments, and valuation committee meetings; board reporting peaks quarterly.
- Guideline breaches spike on volatile market days and after benchmark rebalances.

## Controlled Imperfections

| Imperfection | Where it appears | Typical rate | Downstream symptom |
| --- | --- | --- | --- |
| missing_xref | custodian security id not in security_master crosswalk | 0.01 of custodian rows | unmapped_security_queue growth, recon false breaks |
| duplicate_entity | same security under two identifiers (vendor vs custodian) | 0.005 of securities | doubled exposure in risk, recon break pairs |
| late_arrival | custodian file arrives after warehouse cutoff | 0.03 of files | fact_holding_daily gap, restated next-day snapshot |
| restatement_reversal | restated private NAV reverses prior fact_nav_statement version | 0.06 of final NAVs | performance recalculation versions, prior-period return changes |
| conflicting_source_values | manager statement NAV differs from portal NAV feed | 0.03 of statements | NAV recon mismatch, steward case |
| stale_mapping | custodian account_mapping points to closed portfolio | 0.01 of mappings | orphaned custodian rows, cash recon breaks |
| format_drift | custodian or vendor file layout change mid-history | 1-2 events per year per feed | staging load failures, partial-day data |
| out_of_order_events | trade amendment processed before original trade CDC event | 0.005 of trade events | negative interim positions, recon noise |
| duplicate_webhook | duplicate fill message from execution venue | 0.003 of fills | inflated executed quantity until dedup |
| manual_override | valuation committee adjustment to manager NAV | 0.08 of NAV approvals | NAV differs from manager statement by design |
| orphan_fk | benchmark_assignment referencing retired benchmark_definition | 0.005 of assignments | null benchmark return in performance |
| typo | fat-fingered price decimal on manual price entry | 0.001 of manual prices | market value spike, recompute control failure |
| late_arrival | illiquid bond carries prior-day (stale) price | 0.02 of fixed income prices | flat return days then jump, attribution noise |
| missing_xref | manager statement holding without instrument detail | 0.10 of manager holdings | look-through exposure gaps in risk |
| format_drift | pre-migration legacy portfolio codes in old transactions | 0.05 of pre-cutover rows | history joins require legacy crosswalk |
