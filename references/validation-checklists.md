# Validation Checklists

## Structural Realism

- Multiple operational systems exist.
- Source-specific schemas exist.
- Landing and staging are distinct rungs (raw extracts per feed, then typed/cleaned staging per extract).
- Canonical layer exists for major entities.
- Crosswalks exist for source-to-canonical identifiers.
- Warehouse facts and dimensions exist.
- The view stack is layered (medium/high realism): normalized views, business views, materialized-view tables, and business-unit custom views — views depending on views, not one flat mart tier.
- Code objects exist: view definitions, ELT/derivation scripts, and (as catalog data) stored procedures, functions, and extract definitions with job-run history.
- Human-entered mapping tables exist and are applied asymmetrically across consumers.
- Governance, DQ, controls, security, audit, workflow, document, and integration layers exist when relevant.

## Business Realism

- Entities reflect the selected industry.
- Event sequences follow plausible state machines.
- Facts have explicit grains.
- Transactions or movements roll forward to balances where applicable.
- Relationships and statuses are effective-dated.
- Legal entities, contracts, geography, calendars, and hierarchies are included when they affect reporting.

## Data Realism

- Data volumes and distributions are plausible.
- Includes current, inactive, retired, closed, cancelled, and legacy records.
- Includes edge cases.
- Includes duplicates, missing mappings, late records, source conflicts, or manual overrides when realism is medium/high.
- Uses fictional records only.

## Reconciliation Realism

- Major flows have reconciliation rules.
- Some breaks are intentional and documented.
- Breaks create workflow cases or manual signoffs.
- Tolerances and expected break rates are stated.
- As-of/currently-known reporting differences are handled where relevant.

## Privacy and Security Realism

- Sensitive fields are classified.
- Masking policies exist for restricted fields.
- Row-level or tenant-level access exists where needed.
- Access logs exist for sensitive or privileged actions.
- Retention policies exist for regulated data.
- No real PII, PHI, PCI, customer, employee, patient, account, or transaction data is used.

## Documentation Realism

- Tables have descriptions.
- Facts have grains.
- Views have business purpose, source tables, caveats, owner, and certification status.
- Metrics have definitions and owners.
- Lineage exists for critical reporting flows.
- DQ and control catalogs have owners and frequencies.

## Executable SQLite Validation

- SQLite database opens successfully.
- `pragma integrity_check` returns `ok`.
- `pragma foreign_key_check` returns zero rows.
- Required tables and views exist.
- Required columns exist.
- Major joins have indexes.
- Core records are populated.
- Fact records are populated.
- Fact grains have no duplicate active records.
- Source-to-core crosswalk coverage is plausible.
- Reconciliation breaks exist where controlled imperfections were generated.
- DQ failures exist where controlled imperfections were generated.
- Mart views return rows.
- Privacy/audit logs exist when sensitive data is modeled.
- Generated data avoids real PII, PHI, PCI, bank account, customer, employee, patient, or member identifiers.

## Validation Severity

Critical:

- database cannot be opened
- schema failed to apply
- integrity check failed
- foreign key check failed
- required table/column missing
- critical fact grain duplicates
- generated data contains realistic sensitive identifiers

Warning:

- expected controlled imperfections missing
- row counts outside approved scale profile
- reconciliation break rate far outside expected range
- DQ failure rate far outside expected range
- dashboard or mart views empty

Info:

- row counts
- status distributions
- amount totals
- top reconciliation breaks
- open workflow queues

## Red Flags

- Flat one-table-per-entity model.
- Random status values.
- No source-system boundaries.
- No effective dates.
- No crosswalks.
- No reconciliation or DQ failures.
- Perfectly clean data.
- A single flat view tier — no view depends on another view.
- Tables only — no view definitions, procedures, functions, or extract code anywhere in the ecosystem.
- Every business unit reports identical numbers; manual mappings (if any) applied uniformly everywhere.
- Sensitive data without privacy model.
- Fictional output presented as a real company's internal schema.
