# Archetypes

Use this file to choose the operating model before designing data. Large organizations often combine archetypes.

| Archetype | Realism anchor | Core domains | Load reference |
| --- | --- | --- | --- |
| Investment manager | Holdings, trades, cash, performance, pools, external identifiers | portfolio, trading, security master, market data, custodian, manager feed, private assets, performance, risk, finance | `industry-investment-management.md` |
| Banking | Money must balance across accounts, payments, subledger, GL, and risk views | party, account, payments, cards, loans, deposits, ledger, AML, KYC, fraud, regulatory | `industry-banking.md` |
| Ambulatory healthcare | Clinical plausibility and billing lifecycle align | patient, provider, scheduling, encounters, diagnoses, procedures, orders, labs, payer, claims | `industry-healthcare.md` |
| Hospital healthcare | Patient movement, capacity, orders, medication, charges, and claims synchronize | ADT, bed management, orders, medication, lab, radiology, surgery, ICU, devices, supplies, quality | `industry-healthcare.md` |
| Manufacturing and service | Material genealogy, inventory movement, quality, equipment, and service history tie together | product, BOM, routing, work order, machine, lot, serial, inventory, quality, maintenance, field service | `industry-manufacturing.md` |
| SaaS | Tenant isolation, identity, entitlement, usage, billing, support, and audit agree | tenant, identity, authz, subscription, billing, usage, product, support, security, observability | `industry-saas.md` |
| Logistics | Physical movement, custody chain, documents, events, exceptions, and charges synchronize | order, shipment, transport, asset, tracking, customs, warehouse, billing, claims | `industry-logistics.md` |
| Foodservice distribution | Product master, contract pricing, perishable inventory, route delivery, food safety, and finance tie together | customer, product, supplier, pricing, orders, warehouse, inventory lots, routes, drivers, recalls, rebates, finance | `industry-food-distribution.md` |
| Diagnostic lab | Order-to-specimen-to-result-to-delivery-to-billing lifecycle is coherent | patient, provider, requisition, specimen, accession, test catalog, instruments, results, courier, claims, privacy, quality | `industry-diagnostic-lab.md` |
| Pension administrator | Member service, contributions, benefits, payroll, actuarial, and investment reporting reconcile historically | member, employer, service credit, contributions, benefits, payroll, actuarial, investments, finance | `industry-pension-admin.md` |
| Insurance carrier | Policy, premium, claims, reserves, payments, reinsurance, and regulatory reporting agree | party, policy, product, underwriting, billing, claims, reserves, payments, reinsurance, compliance | Use common patterns plus custom domains |
| Retailer | Customer, product, inventory, store/ecommerce orders, returns, promotions, and margin align | customer, product, store, ecommerce, POS, inventory, promotion, fulfillment, returns, finance | Use common patterns plus logistics/food distribution where relevant |
| Utility | Meter, service point, usage, billing, outage, field work, and regulatory reporting agree | customer, premise, meter, service point, usage, billing, outage, work order, asset, regulatory | Use common patterns plus manufacturing/service patterns |
| Real estate operator | Properties, leases, tenants, rent, maintenance, valuations, debt, and investor reporting tie together | property, lease, tenant, rent, maintenance, valuation, debt, investor reporting, finance | Use common patterns plus investment management where relevant |

## Combined Archetypes

- Public pension plan: pension administration + investment management + finance + risk + real estate/private assets.
- Health system: hospital healthcare + ambulatory healthcare + logistics/supply chain + finance + compliance.
- Food distributor with private fleet: foodservice distribution + logistics + manufacturing/service for fleet maintenance.
- SaaS fintech: SaaS + banking controls + security/compliance.
- Diagnostics network: diagnostic lab + healthcare + logistics + inventory + privacy.

## Classification Questions

Ask only when needed. Otherwise infer:

- What does the organization produce, sell, treat, move, insure, invest, manage, or administer?
- What are the regulated or money-balancing flows?
- Which entities must have source-system identifiers?
- Which events change state over time?
- Which outputs are reported to executives, regulators, customers, or auditors?
