---
name: agent-skill-enterprise-data-ecosystems
description: Design and build realistic fictional enterprise data ecosystems, mock enterprise databases, synthetic data platforms, SQLite-local demo databases, data warehouse/lakehouse models, source-to-target mappings, business marts, governance/control/security/audit layers, executable validation, dashboards, and mock-data generation plans. Use when an AI agent is asked to create or plan realistic mock organizational data for demos, QA, training, analytics, database design, seed data, dbt models, DDL, lineage, reconciliation, enterprise data architecture, or a populated local database. Do not use for simple one-table fake data unless the user asks to make it enterprise-realistic.
---

# Enterprise Data Ecosystems

## Core Rule

Generate a simplified but coherent business operating model before generating tables or rows. Realistic enterprise data comes from systems, identifiers, events, controls, governance, and imperfect integration, not from random records.

When the user references a real company, create a fictional equivalent unless they explicitly request public-source research. Never imply fictional schemas, systems, dataflows, or controls are actual internal structures of a real organization. Never generate real PII, PHI, PCI, or account data — the engine's generators are constrained to provably fictional ranges; do not bypass them.

## The Build Engine

This skill ships a deterministic build engine. Do not hand-write row generators — author a single ecosystem spec JSON and let the toolchain do the mechanical work:

```text
1. Author  <project>/ecosystem_spec.json        (the creative work lives here)
2. python scripts/validate_ecosystem_spec.py spec.json        -> fix all errors, weigh warnings
3. python scripts/build_sqlite_ecosystem.py spec.json --plan  -> sanity-check the volume forecast
4. python scripts/build_sqlite_ecosystem.py spec.json --out <dir> --force   (use --scale-multiplier 0.3 while iterating)
5. python scripts/validate_sqlite_database.py --db <dir>/<org>.db --spec spec.json --report <dir>/validation_report.md --json <dir>/validation_results.json
6. python scripts/profile_sqlite_database.py --db <dir>/<org>.db --report <dir>/profile.md
```

The engine provides: weighted business calendars (weekday/seasonality/holidays/growth), statistical distributions, persona/place/company pools, check-digit identifiers in fictional ranges, per-parent row skew, FK affinity matching, state-machine lifecycles with right-censoring at the as-of date, SQL derivations for real lineage, and typed imperfections logged to `meta_imperfection_log`. The validator reconciles every defect against that log, so intentional imperfections never read as failures — and unexplained ones do.

Load `references/generator-spec.md` before authoring a spec. Copy patterns from `examples/harborline-provisions/ecosystem_spec.json` — it exercises every feature and passes strict validation with a full realism score. `python scripts/run_self_test.py` proves the toolchain end-to-end if anything seems off.

## Default Delivery Behavior

Prefer an end-to-end package over a partial artifact when the user asks to design, build, generate, populate, or demo an ecosystem.

If the user does not explicitly ask for brief-only output:

1. Interview briefly for missing essentials: organization type, target platform, scale, time horizon, dashboard need, and privacy constraints.
2. Propose a concrete artifact package with defaults. Default platform is local SQLite when the user wants a portable database.
3. Ask for approval before creating or overwriting files or generating a large database.
4. After approval, continue through spec authoring, spec validation, build, database validation, profiling, and summary without requiring the user to prompt "continue" between stages. Iterate at reduced scale until strict validation passes, then build full scale.
5. Report artifact paths, database path, row counts, the validation verdict and realism score, known controlled imperfections, and run commands.

Use concise progress updates while working. Stop early only when the user explicitly requests a design-only artifact or when approval/input is required.

## Workflow

1. Classify the organization archetype and operating model with `references/archetypes.md`.
2. Load the matching industry reference. It supplies domains, source systems, core tables, fact grains, state machines with branch probabilities and dwell times, volumetrics and distributions, business-rule invariants, controls with expected break rates, seasonality, and imperfection rates — author the spec from these numbers, not from intuition.
3. Design the application landscape and layered architecture using `references/common-layers.md` and `references/enterprise-patterns.md`. Source/operational layers are generated; staging, xref, canonical, warehouse, and mart layers must be **derived via SQL** from the source layers so lineage is real.
4. Choose distribution parameters and imperfection rates with `references/data-realism.md`. The realism levers that matter most: per-parent skew, segment-conditional parameters (`case`), FK affinity matching, sorted onboarding dates with pre-horizon backfill, price-book quantization (`fk_copy` price x integer quantity), state-machine right-censoring, and 1-5% imperfection rates aimed at DQ rules and recon controls that catch them.
5. Author the ecosystem spec per `references/generator-spec.md`. Define explicit grain for every fact. Add `validation.required_views` and `validation.expected_row_ranges` so the database validator gates on them.
6. Run the toolchain (steps 2-6 in The Build Engine). Fix every critical finding; treat warnings as realism debt and either fix them or document why they stand. Target a full realism score.
7. Produce the requested output mode. Use `references/output-templates.md` for structure and `references/validation-checklists.md` before finalizing.

## Parallel Execution

When the active AI harness supports parallel workers, subagents, background tasks, forked workspaces, or independent agent threads, use them after user approval for separable work. Keep this guidance harness-neutral: do not assume harness-specific APIs, thread semantics, or worktree behavior.

Load `references/delegation-patterns.md` before delegating. Use `references/worker-prompts.md` as prompt templates. If parallel workers are unavailable, execute the same roles sequentially in the main agent.

The main agent must retain ownership of: user interview and approval, the spec (workers may draft table groups, the main agent integrates and validates), final integration, destructive operations, end-to-end validation, and the final user-facing summary.

## Reference Selection

Load only the files needed for the current request:

- `references/generator-spec.md`: the spec language for the build engine — load before authoring any spec.
- `references/data-realism.md`: choosing distributions, skew, temporal shape, identifier safety, imperfection rates.
- `references/archetypes.md`: archetype selection and combined operating models.
- `references/common-layers.md`: reusable enterprise data layers and base schemas.
- `references/enterprise-patterns.md`: identifiers, effective dating, events, roll-forwards, controls, DQ, security, documents, imperfections.
- Industry deep-dives (volumetrics, state machines, invariants, controls, seasonality, imperfection rates per industry):
  `industry-investment-management.md`, `industry-banking.md`, `industry-healthcare.md`, `industry-manufacturing.md`, `industry-saas.md`, `industry-logistics.md`, `industry-food-distribution.md`, `industry-diagnostic-lab.md`, `industry-pension-admin.md`, `industry-insurance.md`, `industry-retail.md`, `industry-utility.md`, `industry-real-estate.md`.
- `references/sqlite-target.md`: SQLite naming, type mapping, required files, scale profiles.
- `references/executable-validation.md`: validation tiers, imperfection reconciliation, exit codes.
- `references/delegation-patterns.md` and `references/worker-prompts.md`: parallel-worker guidance and prompt templates.

## Output Modes

Match the user's requested depth:

- Architecture brief: assumptions, domains, systems, layers, dataflows, controls, risks.
- Schema catalog: schemas, tables, table purpose, grain, key columns, owners, sensitivity.
- Column model: DDL-ready columns, keys, effective dates, audit/source fields, status fields.
- SQL DDL: platform-specific DDL for PostgreSQL, Snowflake, BigQuery, SQL Server, Databricks, or SQLite.
- dbt/lakehouse plan: sources, staging, intermediate, marts, tests, exposures, snapshots, seeds.
- Synthetic data plan: row counts, generation order, distributions, event scenarios, imperfections, validation.
- Full package: architecture report, schema catalog, DDL, seed plan, dataflows, controls, DQ rules, security/privacy model, lineage, executable validation, and optional dashboard.
- Complete local SQLite ecosystem: ecosystem spec, DDL artifacts, populated `.db`, validation report with realism score, profile summary, and optional local dashboard.

## Script Use

- `scripts/build_sqlite_ecosystem.py`: spec -> DDL artifacts + populated SQLite database + meta tables. Flags: `--plan`, `--out`, `--db`, `--seed`, `--scale-multiplier`, `--force`, `--schema-only`, `--quiet`.
- `scripts/validate_ecosystem_spec.py`: collect-all spec diagnostics (errors + realism lints) before building.
- `scripts/validate_sqlite_database.py`: integrity, grain, FK-vs-imperfection-log reconciliation, PII heuristics, realism scorecard. `--strict` fails on warnings and failed realism signatures.
- `scripts/profile_sqlite_database.py`: per-table Markdown profile.
- `scripts/run_self_test.py`: end-to-end toolchain proof including determinism across hash seeds.
- `scripts/generate_schema_catalog.py`, `scripts/generate_ddl.py`, `scripts/generate_seed_plan.py`: documentation artifacts and non-SQLite DDL from the same spec.

For platforms other than SQLite, author the same spec for design artifacts (`generate_ddl.py` renders PostgreSQL/Snowflake/BigQuery/SQL Server/Databricks DDL) and state clearly that executable population currently targets SQLite.

## Quality Bar

Before finalizing, verify structural realism, business realism, data realism, reconciliation realism, privacy realism, and documentation realism per `references/validation-checklists.md` — and that `validate_sqlite_database.py` reports zero critical findings with a strong realism score whenever a database was generated. Prefer a smaller coherent ecosystem over a broad list of disconnected table names.
