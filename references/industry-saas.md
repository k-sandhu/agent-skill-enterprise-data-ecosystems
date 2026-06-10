# Industry: B2B SaaS

## Operating Context

- Multi-tenant B2B software platform selling seat- and usage-based subscriptions; revenue = recurring subscriptions + metered overages.
- Mixed motion: self-serve trials for SMB plans, sales-assisted deals for mid-market/enterprise; CRM owns pipeline, billing platform owns revenue.
- Money flows: card-on-file for SMB (auto-charge), invoiced net-30 terms for enterprise; payment processor settles to bank, dunning recovers failed charges.
- Key constraints: SOC 2 / ISO-style audit posture, data residency commitments, tenant isolation guarantees, PCI scope pushed to payment processor.
- Scale anchor: mid-size vendor, 4k-8k active paying tenants, 120k-250k active users, $40M-$90M ARR, 30-80M product usage events/day.
- Finance closes monthly; ARR/MRR reporting is the board-level metric and the most-disputed semantic definition in the company.

## Domains

tenant, identity, authn, authz, product, entitlement, subscription, billing, usage, metering, support, customer_success, audit, security, observability, integrations, data_platform.

## Source Systems

| System | Role | System-of-record domains | Typical data quirks |
| --- | --- | --- | --- |
| Product app database | Operational store for the application | tenant, product, workspace/project objects | Soft deletes, tenant merges, schema migrations mid-history |
| Identity provider | SSO, user lifecycle, MFA | identity, authn | Orphan users after offboarding, duplicate emails across tenants |
| Authorization service | Roles, permissions, policy decisions | authz | Stale role assignments, policy version drift |
| Billing/subscription platform | Plans, subscriptions, invoices, credits | subscription, billing, entitlement | Proration edge cases, backdated plan changes, comped accounts |
| Payment processor | Charges, refunds, disputes, payouts | payment transactions | Duplicate webhooks, delayed settlement, currency rounding |
| Metering pipeline | Usage event ingestion and aggregation | usage, metering | Out-of-order events, late arrivals up to 48h, replay duplicates |
| Support ticketing | Tickets, SLAs, CSAT | support | Free-text tenant references, merged tickets, requester not in IdP |
| Customer success platform | Health scores, playbooks, renewals | customer_success | Score model versions change silently, manual overrides |
| CRM | Accounts, opportunities, quotes | pre-sale account, pipeline | Account-to-tenant mapping gaps, duplicate accounts |
| Marketing automation | Leads, campaigns, attribution | lead/campaign | UTM loss, lead-to-account match conflicts |
| Security event platform | Auth and admin event monitoring | security | High volume, sampled retention, clock skew across sources |
| Observability stack | Errors, latency, uptime | observability | Sampling, cardinality limits drop tenant tags |
| Data warehouse | Analytics consolidation | none (consumer) | Late-arriving usage restates daily rollups |

## Core Tables

- `tenant.tenant`, `tenant.tenant_status_history`, `tenant.tenant_merge_event`
- `identity.user`, `identity.group`, `identity.user_group_membership`, `identity.sso_connection`
- `authz.role`, `authz.permission`, `authz.role_assignment`
- `product.workspace`, `product.project`, `product.feature`, `product.feature_flag_assignment`
- `subscription.subscription`, `subscription.plan`, `subscription.entitlement`, `subscription.status_history`, `subscription.trial`, `subscription.plan_change_event`
- `usage.event`, `usage.meter_reading`, `usage.daily_rollup`
- `billing.invoice`, `billing.invoice_line`, `billing.payment`, `billing.credit_note`, `billing.dunning_attempt`, `billing.payment_method`
- `support.ticket`, `support.ticket_comment`, `support.csat_response`, `customer_success.health_score`, `customer_success.renewal_forecast`
- `crm.account`, `crm.opportunity`, `xref.account_tenant_map`
- `audit.change_event`, `security.login_event`, `observability.error_event`
- `integration.webhook_event`, `integration.cdc_event`

## Warehouse Facts and Dimensions

- `fact_usage_event` - grain: one product usage event (tenant, user, feature, event timestamp).
- `fact_usage_daily` - grain: one tenant-feature-date rollup.
- `fact_subscription_mrr_daily` - grain: one subscription per calendar date (semi-additive MRR snapshot).
- `fact_invoice_line` - grain: one invoice line.
- `fact_payment` - grain: one payment transaction (charge, refund, or dispute).
- `fact_dunning_attempt` - grain: one retry attempt on one failed invoice.
- `fact_trial` - grain: one trial per tenant per trial episode.
- `fact_support_ticket` - grain: one support ticket (accumulating snapshot: created/first-response/resolved).
- `fact_security_event` - grain: one security event.

Dimensions: tenant, user, plan, feature, subscription, product_area, channel, date, support_priority, payment_method, billing_country, acquisition_source.

## Critical Dataflows

- Quote-to-renewal: CRM opportunity -> subscription -> entitlement -> usage -> invoice -> payment -> renewal/cancel.
- Meter-to-bill: usage event -> metering aggregation -> rated usage -> invoice line -> payment.
- Trial-to-paid: marketing lead -> trial signup -> activation events -> conversion -> first invoice.
- Dunning: payment failure webhook -> dunning schedule -> retry attempts -> recovery or involuntary churn -> subscription status update.
- Identity-to-audit: login -> authorization decision -> product action -> audit event -> security monitoring.
- Health-to-renewal: usage rollup + ticket volume + invoice status -> health score -> CS playbook -> renewal forecast.

## State Machines

- Trial: trial_started -> activated (0.55, lognormal, median 2 days, p90 9 days) | stalled (0.45); activated -> converted (0.30, median 11 days into trial) | expired (0.66) | extended (0.04, +14 days, then converts 0.25). Net trial-to-paid 0.17.
- Subscription: trial_converted/won -> active; active -> renewed (0.982 per month) | cancelled_voluntary (0.011) | cancelled_involuntary (0.007, via dunning exhaustion); cancelled -> reactivated (0.06 within 90 days). Active -> upgraded (0.022/mo) | downgraded (0.008/mo).
- Invoice: draft -> issued (instant) -> paid (0.93 card auto-charge, within 1h) | payment_failed (0.07) -> dunning; net-30 invoices: issued -> paid (0.80 by due date; lognormal, median 24 days, p90 52 days) -> overdue -> paid (0.17) | written_off (0.03, after 90 days).
- Dunning (card): failed -> retry_1 day 3 (recovers 0.30) -> retry_2 day 7 (0.20 of remainder) -> retry_3 day 14 (0.12) -> final_notice day 21 -> cancelled_involuntary; cumulative recovery 0.52 of failed invoices.
- Support ticket: new -> triaged (0.98, median 1h) | spam_closed (0.02); triaged -> in_progress -> waiting_customer (0.40 of tickets at least once) -> resolved (lognormal, median 1.5 business days, p90 8 business days) -> closed (auto, +3 days) | reopened (0.06, returns to in_progress); escalated_to_engineering 0.09 of tickets.
- Tenant: prospect -> trialing -> active -> (suspended_nonpayment 0.007/mo -> active 0.5 | churned 0.5) -> churned; merged_into absorbs 0.002/mo.

## Volumetrics and Distributions

| Metric | Typical value or range | Distribution | Notes |
| --- | --- | --- | --- |
| Active paying tenants | 4,000-8,000 | n/a | Cardinality anchor for mid-size vendor |
| Seats per tenant | median 12, p90 85, max ~3,000 | lognormal | Enterprise tail drives the max |
| Plan mix (paying) | starter 0.55 / pro 0.35 / enterprise 0.10 | weighted choice | Enterprise = custom contracts in CRM |
| MRR per tenant | median $420, p90 $3,800, p99 $28,000 | lognormal | ARPA blends to ~$900/mo |
| MRR concentration | top 10% tenants = ~62% of MRR | zipf s=1.05 | Drives renewal-risk concentration |
| Usage events per active user per day | median 60, p90 280 | lognormal | Power users are admins/integrations |
| Usage events per tenant per day | median 700, p90 12,000 | lognormal | Top 5% tenants = ~50% of event volume |
| DAU/MAU per tenant | 0.30-0.55 | beta(5,6) | Below 0.20 is a churn-risk signal |
| Trials started per month | 900-1,500 | poisson | Marketing-campaign spikes 2-3x |
| Trial-to-paid conversion | 0.17 overall; 0.30 of activated | n/a | Sales-assisted trials convert 0.35 |
| Monthly logo churn | 0.018 (0.011 voluntary + 0.007 involuntary) | n/a | SMB churns 3x enterprise rate |
| Monthly gross revenue churn | 0.014 | n/a | Lower than logo churn (small tenants churn) |
| Monthly expansion rate | 0.025 of MRR | n/a | Seats 60%, plan upgrades 25%, overage 15% |
| Net revenue retention (annual) | 1.06-1.12 | n/a | Enterprise cohort ~1.18, SMB ~0.92 |
| Card payment failure rate | 0.07 of card invoices | n/a | Expired/insufficient/decline mix 40/35/25 |
| Dunning recovery | 0.52 of failed invoices | n/a | Most recovery at first retry |
| Invoice lines per invoice | 1-4, median 2 | weighted choice (1:0.35, 2:0.35, 3:0.20, 4+:0.10) | Base fee + seats + overage + credit |
| Tickets per 100 active tenants per month | 9-14 | poisson | ~0.5 tickets per 100 active users/mo |
| Ticket priority mix | low 0.45 / normal 0.40 / high 0.12 / urgent 0.03 | weighted choice | Urgent correlates with incident windows |
| CSAT response rate / score | 0.22 respond; 4.3/5 mean | beta, ceiling effect | Detractors over-respond after escalations |

## Business Rules and Invariants

- invoice.total = sum(invoice_line.amount) + tax - credits_applied; never negative (refunds are credit notes or negative payments, not negative invoices).
- MRR roll-forward holds per month: opening MRR + new + expansion - contraction - churned = closing MRR.
- subscription.status = active implies exactly one current row in subscription.status_history with null end date.
- Active entitlements match the subscription plan's feature set plus explicit overrides (each override row requires an audit.change_event).
- usage.daily_rollup per tenant-feature-date = sum of usage.event for that key within the late-arrival watermark (48h).
- Rated overage on invoice lines ties to usage.meter_reading totals for the billing period.
- trial.converted_at, subscription.start_date >= trial.started_at; cancelled_at >= start_date; reactivated subscriptions get a new subscription_id linked via previous_subscription_id.
- payment.captured_at >= invoice.issued_at; dunning_attempt.attempt_number strictly increases per invoice; no dunning_attempt after invoice.status = paid.
- Every usage.event and product table row carries tenant_id; no cross-tenant foreign keys (tenant isolation invariant).
- support.ticket.first_response_at >= created_at; resolved_at >= first_response_at; SLA breach flag = (first_response_at - created_at) > sla.target for the priority.
- Every privileged admin action in the product has a matching audit.change_event within 5 minutes.
- A user holds at most one active role_assignment per role per tenant (no duplicate active grants).

## Controls and Reconciliations

| Control | Grain | Tolerance | Expected break rate |
| --- | --- | --- | --- |
| Entitlement-to-plan match (active entitlements = plan features + overrides) | tenant-feature-day | 0 | 0.004 of tenant-days (entitlement drift) |
| Meter-to-bill: usage events vs meter readings vs invoiced overage | tenant-meter-billing period | 0.5% of units | 0.02 of tenant-periods |
| Invoice-to-payment: invoice totals vs payments + credits + write-offs | invoice | $0.01 | 0.01 (open dunning, disputes) |
| MRR report vs billing platform subscription detail | tenant-month | $1 | 0.008 (backdated changes, comps) |
| Payment-to-payout: processor charges vs bank settlement | payout batch | $0.01 | 0.005 (timing, FX rounding) |
| CRM account-to-tenant crosswalk completeness | account | 0 missing for paying tenants | 0.03 of accounts unmapped |
| Daily rollup vs raw event counts (post-watermark) | tenant-date | 0.1% rows | 0.01 of tenant-dates (late events) |
| Tenant isolation: row-level access policy coverage | table | 0 uncovered tables | rare; 1-2 findings per quarterly review |
| Privileged action-to-audit-log tie-out | admin action | 0 | 0.002 (logging pipeline drops) |
| Seat license true-up: provisioned users vs billed seats | tenant-month | 2 seats or 5% | 0.05 of tenants (lagging deprovisioning) |

## Seasonality and Temporal Patterns

- Usage intraday: business-hours bimodal peak (10:00 and 14:00 tenant-local), trough overnight; weekend volume 0.15-0.25 of weekday.
- Trials and signups: Tue-Thu peak; January and September signup waves; December trough (-30%).
- Renewals and churn: cluster at month-end and quarter-end anniversary dates; voluntary churn spikes in January (budget resets) and at annual renewal dates.
- Billing: invoice issuance spikes on the 1st (calendar-aligned subscriptions ~60%), with anniversary-date long tail; dunning retries echo at +3/+7/+14 days.
- Enterprise sales: Q4 close pushes 35-40% of annual new bookings into the last month of the fiscal year; quarter-end discounting raises credit-note volume the following month.
- Support: Monday peak (1.4x average), post-release spikes (2-3x for 48h), urgent tickets cluster during incident windows.
- Finance close: days 1-5 of month; MRR restatements land days 3-7 as late plan changes post.

## Controlled Imperfections

| Imperfection | Where it appears | Typical rate | Downstream symptom |
| --- | --- | --- | --- |
| duplicate_webhook | integration.webhook_event from payment processor | 0.01 of events | Double-counted payments until dedupe by event_id |
| out_of_order_events | usage.event arrival vs event timestamp | 0.03 of events | Daily rollups restated within 48h watermark |
| late_arrival | usage.event > 48h late from offline/mobile SDKs | 0.004 of events | Permanent rollup vs raw count breaks |
| missing_xref | xref.account_tenant_map for CRM accounts | 0.03 of accounts | Pipeline-to-revenue reporting gaps |
| duplicate_entity | tenant.tenant after self-serve re-signup; crm.account dupes | 0.01 of tenants | Tenant merges, split usage history pre-merge |
| stale_mapping | authz.role_assignment after offboarding; entitlement vs plan drift | 0.02 of users; 0.004 of tenant-days | Access review findings, entitlement control breaks |
| manual_override | Comped/discounted subscriptions set by sales or CS | 0.015 of subscriptions | MRR report vs billing detail mismatch |
| conflicting_source_values | CRM contract value vs billing MRR; CS health score vs warehouse | 0.04 of enterprise accounts | Renewal forecast disputes |
| restatement_reversal | billing.credit_note after quarter-end discounting | 0.02 of invoices | Prior-month revenue restated in close |
| format_drift | Metering SDK version changes event property names | 1-2 episodes/year | Feature adoption metrics drop to zero falsely |
| typo | Free-text tenant/company name in support.ticket | 0.05 of tickets | Ticket-to-tenant matching needs fuzzy join |
| orphan_fk | support.ticket.requester not found in identity.user | 0.03 of tickets | Ticket-per-user ratios skew |
| duplicate_entity | Churn/reactivation creating overlapping subscriptions | 0.005 of subscriptions | Double-counted MRR on reactivation day |
| late_arrival | SLA escalation events posting after breach window | 0.01 of escalations | Support escalation breach reports understate |
