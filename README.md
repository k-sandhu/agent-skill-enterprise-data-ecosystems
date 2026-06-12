# Enterprise Data Ecosystems — Agent Skill

An agent skill that designs and builds **realistic fictional enterprise data ecosystems**: multi-system schemas, populated SQLite databases, real SQL lineage, controlled data-quality imperfections, executable validation, a realism scorecard, and a generated read-only **MCP server** over every build — all deterministic and reproducible.

The core idea: realism is engineered once instead of improvised per session. An agent (or you) authors a single **ecosystem spec JSON**; a shipped, stdlib-only engine does the mechanical work and a validation engine proves the result.

```text
author ecosystem_spec.json
  -> validate_ecosystem_spec.py     collect-all diagnostics and realism lints
  -> build_sqlite_ecosystem.py      deterministic build: DDL + populated .db + imperfection log
  -> validate_sqlite_database.py    integrity tiers + imperfection reconciliation + realism scorecard
  -> profile_sqlite_database.py     per-table Markdown profile
  -> generate_mcp_server.py         read-only MCP server over the database, lineage, imperfections, and docs
```

## Why generated data usually looks fake — and what this does differently

Practitioners don't check schemas; they cross-tabulate. Flat segment economics, uniform amounts, no weekend dip, every order delivered, 100% referential integrity — each is an instant tell. The engine bakes the counters in:

- **Business calendars** — weekday shape, seasonality, holidays, growth trend, business-hours clustering (with after-hours stragglers).
- **Statistical texture** — lognormal amounts quantized off price books (duplicate mass like real ledgers), zipf activity skew with configurable exponents, segment-conditioned volumes, heavy-tailed per-entity activity so a whale tier emerges.
- **Lifecycle truth** — entity onboarding sorted so IDs correlate with dates, pre-horizon backfill for tenured books, state machines right-censored at the as-of date so recent records legitimately sit mid-pipeline.
- **Real lineage** — staging, crosswalk, canonical, warehouse, and mart layers are **derived via SQL from the source rows**, never parallel-faked. Defects propagate the way they do in production.
- **Controlled imperfections** — 13 typed injectors (duplicate entities, late arrivals, orphan FKs, format drift, restatement reversals, …) at configured rates, every one logged to `meta_imperfection_log` so validation reconciles them instead of flagging them. Each one is aimed at a DQ rule, reconciliation control, or workflow queue that catches it.
- **Provably fictional data** — names from fictional pools, 555-01xx phones, `example.com` (sub)domains, identifiers only in reserved/test check-digit ranges. PII heuristics in the validator enforce the floor.

Determinism is a contract: same spec + seed produces identical data across machines and `PYTHONHASHSEED` values, proven by the self-test's double-build hash comparison.

## Quickstart

Requires Python >= 3.9 (stdlib only) with SQLite >= 3.31.

```text
git clone https://github.com/k-sandhu/agent-skill-enterprise-data-ecosystems
cd agent-skill-enterprise-data-ecosystems

# prove the toolchain end-to-end (determinism + strict validation)
python scripts/run_self_test.py

# build the canonical example (~760k rows in well under a minute)
python scripts/build_sqlite_ecosystem.py examples/harborline-provisions/ecosystem_spec.json --out examples/harborline-provisions/build --force
python scripts/validate_sqlite_database.py --db examples/harborline-provisions/build/harborline_provisions.db --spec examples/harborline-provisions/ecosystem_spec.json

# generate a read-only MCP server over the build, then connect any MCP client
python scripts/generate_mcp_server.py examples/harborline-provisions/ecosystem_spec.json --build examples/harborline-provisions/build
claude mcp add harborline-provisions-data-ecosystem -- python examples/harborline-provisions/build/mcp/server.py
```

Then open the `.db` in any SQLite browser and start with the queries in the example's README — or explore it through the MCP server from Claude Code, Claude Desktop, or any stdio MCP host.

## Worked examples

Every example builds deterministically and passes **strict** validation (zero critical findings, zero warnings, full realism scorecard). CI rebuilds them all on every push.

| Example | Industry | What it showcases |
| --- | --- | --- |
| [banking](examples/banking/) | Retail and commercial banking | Core banking, cards, payment lifecycle, AML funnel, GL roll-forward, transaction-vs-GL controls |
| [harborline-provisions](examples/harborline-provisions/) | Foodservice distribution | The canonical pattern: chain accounts, segment economics, derived delivery logistics, credit-terms AR with collections, recon breaks from restatements |
| [healthcare-clinic](examples/healthcare-clinic/) | Ambulatory healthcare | Appointment and claim lifecycles, revenue cycle, EMPI mastering, denial worklists, charge-to-claim reconciliation |
| [insurance](examples/insurance/) | Property and casualty insurance | Policy/claim lifecycles, earned premium, reserve development, agency production, written-vs-billed controls |
| [investment-management](examples/investment-management/) | Investment management | OMS/EMS trades, custodian holdings, security-master mapping, private asset NAVs, guideline breach workflow |
| [logistics](examples/logistics/) | Freight brokerage and 3PL | Shipment lifecycle, EDI/POD flows, carrier scorecards, accessorials, carrier-invoice reconciliation |
| [manufacturing](examples/manufacturing/) | Discrete manufacturing | PLM/ERP/MES/CMMS flows, work orders, operations, OEE/yield marts, consumption-vs-BOM controls |
| [retail](examples/retail/) | Omnichannel retail | Store and ecommerce sales, loyalty-tier economics, fulfillment returns, promotion performance, tender controls |
| [saas](examples/saas/) | B2B SaaS | Tenant segmentation, trial-to-paid subscription lifecycle, metered billing, support workflow, seat true-up controls |

## Using it as an agent skill

[SKILL.md](SKILL.md) is the entry point for AI agents (Claude Code, OpenAI-compatible harnesses via [agents/openai.yaml](agents/openai.yaml)). The agent workflow: classify the organization archetype, load the matching industry reference (volumetrics, state machines, invariants for 13 industries), author the spec per [references/generator-spec.md](references/generator-spec.md), then run the toolchain until strict validation passes.

Key references:

- [generator-spec.md](references/generator-spec.md) — the complete spec language (generators, traits, state machines, derivations, imperfections).
- [data-realism.md](references/data-realism.md) — choosing distributions, skew anchors, imperfection rates, identifier safety.
- [industry deep-dives](references/) — volumetrics and lifecycle numbers for investment management, banking, healthcare, manufacturing, SaaS, logistics, food distribution, diagnostic labs, pension administration, insurance, retail, utilities, and real estate.

## Repository layout

```text
SKILL.md                     agent entry point and workflow
scripts/
  build_sqlite_ecosystem.py  the deterministic build engine
  validate_sqlite_database.py  validation engine (integrity + realism scorecard)
  validate_ecosystem_spec.py   pre-build spec diagnostics
  profile_sqlite_database.py   per-table profiling
  run_self_test.py             end-to-end proof incl. determinism across hash seeds + MCP battery
  validate_all_examples.py     CI gate: every example must strict-pass (incl. MCP smoke)
  generate_ddl.py / generate_schema_catalog.py / generate_seed_plan.py   doc artifacts + non-SQLite DDL
  generate_mcp_server.py / mcp_server_template.py / test_mcp_server.py   read-only MCP server: generator, template, battery
references/                  spec language, realism playbook, MCP server guide, 13 industry deep-dives
examples/                    worked example ecosystems (spec + README each)
```

## Safety

Everything generated is fictional by construction. No real PII, PHI, PCI, account, or company data — identifier generators are constrained to reserved/test ranges, and the validator treats violations as critical failures. When a user references a real company, the skill creates a fictional equivalent instead.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). The short version: stdlib only, determinism is a contract, docs move in lockstep with code, and `run_self_test.py` + `validate_all_examples.py` must be green.

## License

[MIT](LICENSE)
