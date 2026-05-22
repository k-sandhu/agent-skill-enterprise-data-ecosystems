# Executable Validation

Use executable validation for every generated database package. Conceptual checklists are not enough once files and data have been created.

## Required Script

Create or use:

```text
scripts/validate_sqlite_database.py
```

The script should accept:

```text
--db path/to/database.db
--spec path/to/ecosystem_spec.json
--report path/to/validation_report.md
--json path/to/validation_results.json
```

Use practical defaults when optional arguments are missing.

## Check Categories

Critical failures:

- database cannot be opened
- `pragma integrity_check` fails
- `pragma foreign_key_check` returns rows
- required tables are missing
- required columns are missing
- core tables have zero rows after population
- fact tables have duplicate grains
- generated data appears to contain real sensitive identifiers

Warnings:

- expected DQ failures are missing
- expected reconciliation breaks are missing
- row counts are outside scale profile thresholds
- controlled imperfections are too rare or too frequent
- indexes are missing for major joins
- mart views are empty

Informational:

- row counts
- status distributions
- amount totals
- open exception summaries
- largest reconciliation breaks

## Validation Report Shape

```text
1. Database path
2. Build timestamp
3. Scale profile
4. Object counts
5. Critical checks
6. Warning checks
7. Business realism checks
8. Reconciliation checks
9. Privacy checks
10. Recommended fixes
```

## Exit Codes

- `0`: all critical checks passed
- `1`: one or more critical checks failed
- `2`: script usage/configuration error
