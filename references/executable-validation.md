# Executable Validation

Use executable validation for every generated database package. Conceptual checklists are not enough once files and data have been created. The skill ships the validator — run it, do not rewrite it:

```text
python scripts/validate_sqlite_database.py --db build/<org>.db --spec ecosystem_spec.json \
    --report build/validation_report.md --json build/validation_results.json [--strict]
```

## Verdict Tiers

The validator follows a no-flake policy: a check that can fire on a correct build is never critical.

**Critical (exit 1)** — the build is wrong:

- database cannot be opened or `pragma integrity_check` fails
- spec tables, columns, or `validation.required_views` missing
- generator tables empty after population
- duplicate primary keys; duplicate natural-key groups beyond logged duplicate imperfections
- **unexplained** foreign-key violations (see reconciliation below)
- status values outside declared state-machine states
- PII heuristics: emails outside safe fictional domains, phones outside 555-01xx, SSN-shaped values, full card numbers outside test BINs — scoped to columns whose names indicate that data type

**Warning (exit 0; exit 1 with `--strict`)** — realism or accounting drift:

- `meta_table_stats` counts not reconciling with COUNT(*) plus logged net imperfection rows
- row counts outside `validation.expected_row_ranges` (scaled by the build multiplier)
- imperfection rates far from configured rates; logged imperfections not observable in data
- empty or below-floor derivations; empty required views
- every state-machine entity terminal (a real as-of snapshot has open pipeline)
- timestamps beyond as_of beyond logged late arrivals; updated_at before created_at

**Realism scorecard (x/y in the report)** — statistical signatures (failed signatures count as warnings under `--strict`):

- weekend share matches the configured weekday weights
- zipf FK columns concentrate volume in the top decile of parents
- money expression columns show duplicate mass (price quantization)
- sequence IDs correlate with sorted date columns
- actor columns concentrate on a few heavy users
- business-hours clustering on human timestamps

## Imperfection Reconciliation

Controlled imperfections are features, not failures. The engine logs every injected defect to `meta_imperfection_log`; the validator reconciles both directions:

- Forward: sampled log entries are probed in the data (orphaned rows exist, deleted xref rows are gone, duplicates exist).
- Backward: every `pragma foreign_key_check` row is classified per violating row — **logged** (the row's primary key appears in the imperfection log for that table under any type, since copy-injectors legitimately clone already-ghosted FKs), **derived-from-logged** (in a derivation-populated table, where source-layer defects legitimately propagate — warning, verify lineage), or **unexplained** (critical).

Do not "fix" intentional orphans or recon breaks that reconcile to the log — they are the realism. Fix unexplained ones.

## Validation Report Shape

The report leads with a verdict, then: critical findings, warnings, failed realism signatures, passed realism signatures, informational counts. The final user-facing summary must quote the verdict and the realism score.

## Exit Codes

- `0`: no critical findings (warnings allowed unless `--strict`)
- `1`: critical findings (or, with `--strict`, any warning or failed realism signature)
- `2`: usage/configuration error

`scripts/run_self_test.py` runs the spec validator, a double build across different `PYTHONHASHSEED` values (logical per-table hashes must match), strict database validation, and the profiler. Run it whenever engine behavior is in doubt.
