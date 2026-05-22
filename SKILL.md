---
name: agent-skill-enterprise-data-ecosystems
description: Design and build realistic fictional enterprise data ecosystems, mock enterprise databases, synthetic data platforms, SQLite-local demo databases, data warehouse/lakehouse models, source-to-target mappings, business marts, governance/control/security/audit layers, executable validation, dashboards, and mock-data generation plans. Use when an AI agent is asked to create or plan realistic mock organizational data for demos, QA, training, analytics, database design, seed data, dbt models, DDL, lineage, reconciliation, enterprise data architecture, or a populated local database. Do not use for simple one-table fake data unless the user asks to make it enterprise-realistic.
---

# Enterprise Data Ecosystems

## Core Rule

Generate a simplified but coherent business operating model before generating tables or rows. Realistic enterprise data comes from systems, identifiers, events, controls, governance, and imperfect integration, not from random records.

When the user references a real company, create a fictional equivalent unless they explicitly request public-source research. Never imply fictional schemas, systems, dataflows, or controls are actual internal structures of a real organization.

## Default Delivery Behavior

Prefer an end-to-end package over a partial artifact when the user asks to design, build, generate, populate, or demo an ecosystem.

If the user does not explicitly ask for brief-only output:

1. Interview briefly for missing essentials: organization type, target platform, scale, time horizon, dashboard need, and privacy constraints.
2. Propose a concrete artifact package with defaults. Default platform is local SQLite when the user wants a portable database.
3. Ask for approval before creating or overwriting files or generating a large database.
4. After approval, continue through architecture, schema, DDL, SQL flows, synthetic data generation, validation, and summary without requiring the user to prompt "continue" between stages.
5. Run executable validation whenever a database is generated.
6. Report artifact paths, database path, row counts, validation results, known imperfections, and run commands.

Use concise progress updates while working. Stop early only when the user explicitly requests a design-only artifact or when approval/input is required.

## Parallel Execution

When the active AI harness supports parallel workers, subagents, background tasks, forked workspaces, or independent agent threads, use them after user approval for separable work. Keep this guidance harness-neutral: do not assume Codex-specific APIs, thread semantics, or worktree behavior.

Load `references/delegation-patterns.md` before delegating. Use `references/worker-prompts.md` as prompt templates. If parallel workers are unavailable, execute the same roles sequentially in the main agent.

The main agent must retain ownership of:

- user interview and approval
- artifact plan
- final integration
- destructive operations
- end-to-end validation
- final user-facing summary

## Workflow

1. Classify the organization archetype and operating model. Use `references/archetypes.md` to select one or more archetypes.
2. Select relevant business domains and source systems. Use the industry reference file only when the archetype calls for it.
3. Propose the delivery package: architecture, schema catalog, SQLite DDL, SQL flows, synthetic data generator, validation scripts, populated database, and optional dashboard.
4. If using parallel workers, split work only after the package is approved.
5. Design the application landscape with owners, criticality, system-of-record domains, and integration responsibilities.
6. Create layered data architecture: source operational schemas, raw/staging, canonical, xref/MDM, warehouse, marts/views, semantic, catalog, DQ, control, security, privacy, audit, workflow, document, integration, manual/shadow, and ML layers as appropriate. Use `references/common-layers.md`.
7. Define major business processes as state machines and dataflows. Include source-specific identifiers, effective dating, late-arriving data, restatements, manual overrides, and controlled data-quality issues. Use `references/enterprise-patterns.md`.
8. Define warehouse fact grains explicitly. Every fact must state its grain before columns are listed.
9. Add controls and reconciliation rules for major flows. Include expected breaks and workflow queues for unresolved exceptions.
10. Add security, privacy, audit, document, catalog, lineage, and governance models when the ecosystem includes sensitive, regulated, financial, clinical, operational, or executive reporting data.
11. For SQLite packages, load `references/sqlite-target.md` and create executable local artifacts.
12. For populated databases, load `references/executable-validation.md`, run validation scripts, and fix critical failures.
13. Produce the requested output mode. Use `references/output-templates.md` for structure and `references/validation-checklists.md` before finalizing.

## Reference Selection

Load only the files needed for the current request:

- `references/archetypes.md`: archetype selection and combined operating models.
- `references/common-layers.md`: reusable enterprise data layers and base schemas.
- `references/enterprise-patterns.md`: identifiers, effective dating, events, roll-forwards, controls, DQ, security, documents, and imperfections.
- `references/industry-investment-management.md`: portfolios, holdings, trading, custodians, private assets, performance, risk.
- `references/industry-banking.md`: accounts, payments, deposits, loans, cards, ledger, fraud, AML/KYC.
- `references/industry-healthcare.md`: ambulatory and hospital healthcare.
- `references/industry-manufacturing.md`: products, BOMs, work orders, inventory, quality, maintenance, field service.
- `references/industry-saas.md`: tenants, identity, entitlements, subscriptions, usage, billing, support, audit.
- `references/industry-logistics.md`: shipments, legs, assets, tracking, customs, warehouses, freight billing.
- `references/industry-food-distribution.md`: customers, contract pricing, warehouse picking, lots, routes, proof of delivery, recalls.
- `references/industry-diagnostic-lab.md`: requisitions, specimens, accessioning, instruments, results, claims, privacy, quality.
- `references/industry-pension-admin.md`: members, employers, contributions, benefits, retiree payroll, actuarial, investment integration.
- `references/sqlite-target.md`: SQLite naming, type mapping, required files, indexes, and validation expectations.
- `references/executable-validation.md`: executable validation behavior for generated local databases.
- `references/delegation-patterns.md`: harness-neutral guidance for parallel workers, subagents, background tasks, or independent agent threads.
- `references/worker-prompts.md`: reusable prompt templates for delegated workers.

## Output Modes

Match the user's requested depth:

- Architecture brief: assumptions, domains, systems, layers, dataflows, controls, risks.
- Schema catalog: schemas, tables, table purpose, grain, key columns, owners, sensitivity.
- Column model: DDL-ready columns, keys, effective dates, audit/source fields, status fields.
- SQL DDL: platform-specific DDL for PostgreSQL, Snowflake, BigQuery, SQL Server, Databricks, or SQLite.
- dbt/lakehouse plan: sources, staging, intermediate, marts, tests, exposures, snapshots, seeds.
- Synthetic data plan: row counts, generation order, distributions, event scenarios, imperfections, validation.
- Full package: architecture report, schema catalog, DDL, seed plan, dataflows, controls, DQ rules, security/privacy model, lineage, executable validation, and optional dashboard.
- Complete local SQLite ecosystem: SQLite DDL, SQL flows, deterministic data generator, populated `.db`, validation report, profile summary, and optional local dashboard.

## Script Use

Use scripts when the user asks for machine-readable artifacts or deterministic generation from a structured ecosystem spec:

- `scripts/generate_schema_catalog.py`: create a Markdown schema catalog from JSON.
- `scripts/generate_ddl.py`: create simple DDL from JSON for supported SQL platforms.
- `scripts/generate_seed_plan.py`: create a generation sequence and row-count plan from JSON.
- `scripts/validate_ecosystem_spec.py`: check for missing grains, layer coverage, weak controls, missing xrefs, and privacy gaps.
- For SQLite packages, prefer or create generated-project scripts named `generate_sqlite_data.py`, `validate_sqlite_database.py`, and `profile_sqlite_database.py` when not already present.

The scripts expect a JSON spec with top-level fields such as `organization`, `platform`, `schemas`, `tables`, `relationships`, `dataflows`, `controls`, `dq_rules`, `roles`, and `imperfections`. Generate or adapt the spec before running scripts.

## Quality Bar

Before finalizing, verify the ecosystem has structural realism, business realism, data realism, reconciliation realism, privacy realism, documentation realism, and executable validation when files or a database were generated. Prefer a smaller coherent ecosystem over a broad list of disconnected table names.
