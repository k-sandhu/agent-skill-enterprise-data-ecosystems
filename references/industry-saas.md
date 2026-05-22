# Industry: SaaS

## Domains

tenant, identity, authn, authz, product, entitlement, subscription, billing, usage, metering, support, customer_success, audit, security, observability, integrations, data_platform.

## Source Systems

Product app database, identity provider, authorization service, billing/subscription platform, payment processor, metering pipeline, support ticketing, customer success platform, CRM, marketing automation, security event platform, observability stack, data warehouse.

## Core Tables

- `tenant.tenant`, `tenant.tenant_status_history`
- `identity.user`, `identity.group`, `identity.user_group_membership`
- `authz.role`, `authz.permission`, `authz.role_assignment`
- `product.workspace`, `product.project`, `product.feature`
- `subscription.subscription`, `subscription.plan`, `subscription.entitlement`, `subscription.status_history`
- `usage.event`, `usage.meter_reading`, `usage.daily_rollup`
- `billing.invoice`, `billing.invoice_line`, `billing.payment`, `billing.credit_note`
- `support.ticket`, `support.ticket_comment`, `customer_success.health_score`
- `audit.change_event`, `security.login_event`, `observability.error_event`

## Facts and Dimensions

- `fact_usage_event`: one product usage event.
- `fact_usage_daily`: one tenant-feature-date.
- `fact_subscription_mrr_daily`: one subscription-date.
- `fact_invoice_line`: one invoice line.
- `fact_payment`: one payment transaction.
- `fact_support_ticket`: one support ticket.
- `fact_security_event`: one security event.

Dimensions: tenant, user, plan, feature, subscription, product_area, channel, date, support_priority.

## Dataflows

- Quote-to-renewal: CRM opportunity -> subscription -> entitlement -> usage -> invoice -> payment -> renewal/cancel.
- Meter-to-bill: usage event -> metering aggregation -> rated usage -> invoice line -> payment.
- Identity-to-audit: login -> authorization decision -> product action -> audit event -> security monitoring.

## Controls

- Active entitlements match subscription plan.
- Usage events tie to meter readings and invoice overages.
- Invoice totals tie to payments, credits, taxes, and ARR/MRR reports.
- Tenant isolation policies cover row-level access.
- Privileged admin actions tie to audit logs.

## Imperfections

Trial conversions, payment failures, dunning, duplicate webhooks, out-of-order usage events, entitlement drift, manually comped accounts, churn/reactivation, tenant merges, stale user roles, support escalation breaches.
