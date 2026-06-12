# Contributing

Thanks for your interest in improving this skill. The bar for every change is the same one the toolchain enforces on itself: deterministic, stdlib-only, and strict-validation green.

## Development loop

```text
python scripts/run_self_test.py                 # determinism + strict validation on the canonical example
python scripts/validate_all_examples.py         # every worked example must stay green (CI runs this)
```

Both must pass before a PR. CI runs them on Linux and Windows, Python 3.9 and 3.13.

## Ground rules

- **Stdlib only.** The engine and validators run on a bare Python 3.9+ install (SQLite >= 3.31). No third-party imports. The generated MCP server is held to the same bar: `scripts/mcp_server_template.py` and `scripts/generate_mcp_server.py` are stdlib-only, implement the MCP stdio JSON-RPC subset directly (no `mcp`/FastMCP SDK), and the server never opens a socket or touches the network.
- **Determinism is a contract.** Same spec + seed = identical data, across machines and `PYTHONHASHSEED` values. Never use `hash()`, never iterate unsorted sets where order can reach the RNG or output, never call `random()`/`datetime('now')` inside derivation SQL. RNG access goes through `substream()` keyed per (seed, table, purpose). The emitted MCP package is byte-deterministic too: `server.py` is a verbatim copy of the template, and the manifest/README carry no timestamps or absolute paths.
- **Docs move in lockstep.** If you add or change a generator, trait, distribution, or imperfection type, update `references/generator-spec.md` in the same change. Enum names in prose, code, and docs must match exactly. The MCP protocol subset and 11-tool surface are documented in `references/mcp-server.md`; update it in the same change as any template change, and keep `scripts/test_mcp_server.py` smoke passing for every example in `validate_all_examples.py`.
- **Fictional data only.** Identifier generators must stay inside provably fictional/test ranges (555-01xx phones, example.com domains and subdomains, reserved check-digit prefixes). The PII checks in `validate_sqlite_database.py` are a floor, not the goal.
- **No-flake validation.** A check that can fire on a correct build must not be critical. New validator checks need to hold on every existing example at multipliers 0.3 and 1.0.

## Adding a worked example

1. Create `examples/<name>/ecosystem_spec.json` + `README.md` following `examples/harborline-provisions/` (the canonical pattern) and the matching `references/industry-*.md` volumetrics.
2. Gate: `validate_ecosystem_spec.py` exits 0; `build_sqlite_ecosystem.py --plan` forecasts a sane volume; the full build strict-validates with **zero critical, zero warnings, full realism score**.
3. Set generous `validation.expected_row_ranges` — CI builds at `--scale-multiplier 0.3` and the validator scales ranges by the multiplier.
4. Add the example to the table in the root `README.md`.
5. Never commit `build/` outputs or `.db` files (gitignored).

## Adding an industry reference

Follow the section template used by every `references/industry-*.md` (Operating Context through Controlled Imperfections), keep numbers as defensible practitioner heuristics, use only the engine's distribution and imperfection vocabulary, and never name real vendors or companies.
