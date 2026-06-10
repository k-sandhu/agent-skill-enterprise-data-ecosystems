# SQLite Target

Use SQLite as the default local database target for complete ecosystem packages unless the user explicitly chooses another platform. The build engine (`scripts/build_sqlite_ecosystem.py`) owns naming, typing, DDL, and population — author the spec; do not hand-write DDL or loaders.

## Naming

SQLite has no true schema namespaces. The engine converts logical `schema.table` names to underscore-prefixed physical names automatically:

- `raw.crm_account_extract` -> `raw_crm_account_extract`
- `core.customer` -> `core_customer`
- `wh.fact_order_line` -> `wh_fact_order_line`

Author specs and derivation SQL with logical dotted names; the engine rewrites them. Use the layer prefixes from `references/common-layers.md` (`app_`, `raw_`, `stg_`, `xref_`, `mdm_`, `core_`, `wh_dim_`, `wh_fact_`, `mart_`, `control_`, `dq_`, `workflow_`, `document_`, `security_`, `privacy_`, `audit_`, `semantic_`, `integration_`). The `meta_` prefix is reserved for the engine (`meta_build_info`, `meta_table_stats`, `meta_derivation_stats`, `meta_imperfection_log`).

## Type Mapping (engine-applied)

- string/text -> `text`
- integer/bigint -> `integer`
- decimal/number/float -> `real` (money rounded to 2 decimals; validators compare sums with count-scaled tolerance)
- boolean -> `integer` with `0`/`1`
- date -> ISO `text` `YYYY-MM-DD`; timestamp -> ISO `text` `YYYY-MM-DD HH:MM:SS`
- json -> `text`

## Files the Engine Produces

Under the `--out` directory:

- `<org>.db` — populated database (built atomically via `<db>.building` then renamed)
- `sqlite/01_schema.sql`, `sqlite/02_indexes.sql`, `sqlite/03_derivations.sql`, `sqlite/04_views.sql`
- `build_summary.json` — per-table row counts, seed, multiplier, imperfection count, timing

Then produce with the other scripts: `validation_report.md` + `validation_results.json` (validator) and `profile.md` (profiler). Optional extras you may add per request: `app.py` local dashboard, README with run commands.

## Scale Profiles

Author specs at "small" base counts and scale with `--scale-multiplier` (per-parent children scale through their parents automatically; mark reference/dim tables `scale_exempt`):

| Profile | Primary entities | Transaction/event rows | Multiplier guide | Build time guide |
| --- | --- | --- | --- | --- |
| smoke | hundreds | 10k-60k | 0.2-0.3 | seconds — use while iterating |
| small | 1k-5k | 100k-500k | 1.0 | well under a minute |
| medium | 25k-100k | 500k-2M | 5-20 | a few minutes |
| large | 250k+ | 5M+ | 50+ | only with explicit user buy-in |

Run `--plan` first: it prints the per-table volume forecast so a surprise 10M-row table surfaces before the build, not after.

## Validation

Always run `scripts/validate_sqlite_database.py` after building (see `references/executable-validation.md`). Foreign keys are declared in DDL but `pragma foreign_keys` stays off so controlled orphans can exist; the validator reconciles `pragma foreign_key_check` output against `meta_imperfection_log`.

## Known Environment Caveats

- Requires Python >= 3.9 and SQLite >= 3.31 (checked at startup; versions recorded in `meta_build_info`).
- On Windows, a `.db` open in another tool (DB browser, a previous validator) or being synced (OneDrive) can block the final atomic rename — close handles and prefer build output paths outside synced folders.
- Keep `build/` outputs and `.db` files out of version control.
