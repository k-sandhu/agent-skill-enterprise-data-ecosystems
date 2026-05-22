# SQLite Target

Use SQLite as the default local database target for complete ecosystem packages unless the user explicitly chooses another platform.

## Naming

SQLite has no true schema namespaces. Convert logical schemas to table prefixes:

- `raw_employer.contribution_line` -> `raw_employer_contribution_line`
- `core.member` -> `core_member`
- `wh.fact_contribution_line` -> `wh_fact_contribution_line`
- `control.reconciliation_break` -> `control_reconciliation_break`

Use consistent prefixes:

- `app_`
- `integration_`
- `raw_`
- `stg_`
- `xref_`
- `mdm_`
- `core_`
- `wh_dim_`
- `wh_fact_`
- `mart_`
- `control_`
- `dq_`
- `workflow_`
- `document_`
- `security_`
- `privacy_`
- `audit_`
- `semantic_`

## Type Mapping

- string/varchar -> `text`
- integer -> `integer`
- decimal/numeric -> `real`
- boolean -> `integer` with `0`/`1`
- date -> ISO `text` in `YYYY-MM-DD`
- timestamp -> ISO `text`
- JSON/payload -> `text`

## Required SQLite Files

For a complete package, create:

- `sqlite/01_sqlite_schema.sql`
- `sqlite/02_sqlite_indexes.sql`
- `sqlite/03_sqlite_reference_seed.sql`
- `sqlite/04_sqlite_flow_views.sql`

Optional but recommended:

- `scripts/generate_sqlite_data.py`
- `scripts/validate_sqlite_database.py`
- `scripts/profile_sqlite_database.py`
- `app.py`

## Validation

Always run:

```text
pragma integrity_check;
pragma foreign_key_check;
```

Also validate:

- required tables exist
- required columns exist
- expected row-count ranges
- no duplicate natural keys for current records
- no duplicate fact grains
- crosswalk coverage
- reconciliation breaks match expected tolerance and rates
- DQ failures exist for controlled imperfections
- no generated realistic PII such as SINs, real bank accounts, or real names

## Scale Profiles

Small:

- 1k-5k primary entities
- 10k-100k transaction/fact rows
- suitable for fast tests

Medium:

- 25k-100k primary entities
- 500k-2M transaction/fact rows
- suitable for demos and dashboard testing

Large:

- 250k+ primary entities
- 5M+ transaction/fact rows
- use only when the user accepts larger files and slower validation
