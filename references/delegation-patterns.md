# Harness-Agnostic Delegation Patterns

Use this reference when the runtime supports parallel workers, subagents, background tasks, forks, worktrees, or independent agent threads.

Do not assume a specific product API. Treat "worker" as a generic delegated execution unit that can inspect files, create artifacts, run checks, and report results.

Since the skill ships a deterministic build engine, workers do **not** hand-write DDL, row generators, or validators — those are mechanical. Workers contribute the creative inputs: spec fragments, derivation SQL, realism review, and the optional dashboard. The main agent merges fragments into one spec and runs the toolchain.

## Decision Rule

Use parallel workers when all conditions are true:

- The user has approved implementation, not just discussion.
- The runtime exposes a way to run independent work in parallel.
- Tasks have separable outputs (disjoint spec domains, disjoint files) or read-only review responsibilities.
- The main agent can integrate and verify the outputs.

Do not use workers for: the initial user interview, approval negotiation, final spec merge, running builds, destructive changes, or tightly coupled outputs.

If workers are unavailable, perform the same workflow sequentially.

## Default Worker Roles

### Ecosystem Architect

Owns: archetype and operating model, source systems, domains, state machines (states, probabilities, dwell times), controls with expected break rates, imperfection scenario list, privacy/security expectations.

Output contract: an architecture brief the spec authors consume — domain list, application landscape, dataflows, control catalog draft, imperfection plan with rates.

### Spec Domain Author (one per business domain)

Owns: the `tables`, `state_machines` entries, and column generators for one domain (e.g. order-to-cash, or claims), authored as a JSON fragment following `references/generator-spec.md` and the relevant industry reference's volumetrics.

Output contract: a valid JSON fragment (tables + machines + imperfections for the domain), the FK refs it expects other domains to provide, and assumed row volumes. Must use logical `schema.table` names and the agreed naming convention.

### Derivation Author

Owns: the SQL that populates staging, xref, canonical, warehouse, and mart/control/DQ views from the source tables — the lineage layer.

Output contract: `derivations` entries (logical names, list-of-lines SQL), each with an `expect.at_least_rows` floor where meaningful, plus the `validation.required_views` list.

### Realism Reviewer (read-only)

Owns: adversarial review of the merged spec against `references/data-realism.md` and the industry reference — distribution parameters, skew, seasonality, imperfection rates, price quantization, lifecycle coverage. After the first build, reviews the validation report and profile for realism debt.

Output contract: prioritized findings with exact spec paths and replacement values.

### Dashboard Builder

Owns: optional local visualization (`app.py` or equivalent) connecting read-only to the built SQLite database; executive overview, domain analysis, controls/DQ/workflow exception views.

Output contract: changed files, run command, smoke-test result.

## Parallelization Plan

1. Main agent interviews, classifies the archetype, gets approval, and fixes the naming convention, time horizon, seed, and scale.
2. Architect worker produces the brief.
3. Spec domain authors run in parallel on disjoint domains; derivation author runs once source-table names are stable.
4. Main agent merges fragments into one spec, resolves FK seams, runs `validate_ecosystem_spec.py` until clean, then `--plan`, then builds at reduced scale.
5. Realism reviewer critiques the validation report and profile; main agent applies fixes and rebuilds.
6. Full-scale build, strict validation, profile, dashboard (if requested), final summary.

## Integration Rules

- Assign each worker a clear write scope (files or spec domains); spec fragments must be syntactically valid JSON on their own.
- Give every worker the same approved plan, naming convention, seed, time horizon, and scale profile.
- Require every worker to list outputs, FK expectations, and assumptions.
- The main agent owns the merged spec, conflict resolution, all toolchain runs, and the final summary.
- Do not let a worker silently change the approved scope, naming convention, or scale profile.

## Safety Rules

- Generate fictional data only. Never use real PII, PHI, PCI, account numbers, member names, employer confidential data, or production extracts. Use the engine's safe generators; never bypass them with hand-rolled identifier code.
- Keep local SQLite as the default build target unless the user explicitly chooses another platform.
- Make destructive operations explicit: reset, overwrite (`--force`), delete, or rebuild.
- Validate generated data before presenting it as complete.
