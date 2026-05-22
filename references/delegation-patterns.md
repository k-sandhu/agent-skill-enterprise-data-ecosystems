# Harness-Agnostic Delegation Patterns

Use this reference when the runtime supports parallel workers, subagents, background tasks, forks, worktrees, or independent agent threads.

Do not assume a specific product API. Treat "worker" as a generic delegated execution unit that can inspect files, create artifacts, run checks, and report results.

## Contents

- Decision Rule
- Default Worker Roles
- Parallelization Plan
- Integration Rules
- Safety Rules

## Decision Rule

Use parallel workers when all conditions are true:

- The user has approved implementation, not just discussion.
- The runtime exposes a way to run independent work in parallel.
- Tasks have separable outputs or read-only validation responsibilities.
- The main agent can integrate and verify the outputs.

Do not use workers for:

- the initial user interview
- approval negotiation
- final integration decisions
- destructive changes
- tasks whose outputs are tightly coupled and likely to conflict

If workers are unavailable, perform the same workflow sequentially.

## Default Worker Roles

### Ecosystem Architect

Owns:

- organization archetype
- operating model
- source systems
- business domains
- state machines
- controls and reconciliation requirements
- privacy/security/audit/governance expectations

Output contract:

- architecture assumptions
- domain list
- application landscape
- critical dataflows
- control catalog draft
- expected imperfections

### SQLite Schema Builder

Owns:

- SQLite naming convention
- DDL
- primary keys and foreign keys
- indexes
- raw, staging, core, xref, warehouse, mart, control, DQ, workflow, audit, privacy tables

Output contract:

- `sqlite/01_sqlite_schema.sql`
- `sqlite/02_sqlite_indexes.sql`
- schema notes
- known compromises caused by SQLite limitations

### Data Generator

Owns:

- deterministic synthetic data script
- dependency-order population
- realistic distributions
- state-machine event generation
- roll-forward balances
- controlled imperfections

Output contract:

- `scripts/generate_sqlite_data.py`
- configurable scale parameters
- record count summary
- generation notes

### Validation Reviewer

Owns:

- executable schema validation
- executable data validation
- referential integrity checks
- reconciliation checks
- realism checks
- validation report

Output contract:

- `scripts/validate_sqlite_database.py`
- `validation_report.md`
- pass/fail summary
- critical issues and suggested fixes

### Dashboard Builder

Owns:

- local visualization app
- business analysis views
- operational exception views
- drill-down or SQL explorer
- local run instructions

Output contract:

- `app.py` or equivalent local dashboard
- dashboard sections
- smoke-test notes

## Parallelization Plan

After approval, split work as:

1. Main agent writes the ecosystem spec and artifact plan.
2. Architect worker validates operating model and controls.
3. Schema worker creates SQLite DDL and indexes.
4. Data generator worker creates population script against the agreed schema.
5. Validation worker creates validation scripts using the same schema contract.
6. Dashboard worker creates visualization after table names and key metrics are stable.
7. Main agent integrates outputs, resolves conflicts, runs the build, runs validation, and reports results.

## Integration Rules

- Assign each worker a clear write scope.
- Give every worker the same approved artifact plan and target database convention.
- Require every worker to list changed files and assumptions.
- Prefer append-only reports from validation workers.
- The main agent owns final conflict resolution and end-to-end execution.
- Do not let a worker silently change the approved scope, naming convention, or scale profile.

## Safety Rules

- Generate fictional data only.
- Never use real PII, PHI, PCI, account numbers, member names, employer confidential data, or production extracts.
- Keep local SQLite as the default build target unless the user explicitly chooses another platform.
- Make destructive operations explicit: reset, overwrite, delete, or rebuild.
- Validate generated data before presenting it as complete.
