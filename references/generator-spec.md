# Ecosystem Spec Language

Reference for the JSON spec consumed by `scripts/build_sqlite_ecosystem.py`. The worked example at `examples/harborline-provisions/ecosystem_spec.json` demonstrates most features — copy its patterns. Not shown there (documented below only): `scd2` history, `self_fk` hierarchies, `soft_delete`, `price_endings`, most `identifier` kinds.

## Pipeline

```text
author spec.json
  -> python scripts/validate_ecosystem_spec.py spec.json          (collect-all diagnostics; exit 1 on errors)
  -> python scripts/build_sqlite_ecosystem.py spec.json --plan    (volume forecast before committing to a build)
  -> python scripts/build_sqlite_ecosystem.py spec.json --out build [--force] [--seed N] [--scale-multiplier X]
  -> python scripts/validate_sqlite_database.py --db build/<org>.db --spec spec.json --report ... --json ...
  -> python scripts/profile_sqlite_database.py --db build/<org>.db --report ...
```

Builds are deterministic (same spec + seed = identical data, proven across `PYTHONHASHSEED` values) and atomic (built to `<db>.building`, integrity-checked, then renamed). There is no resume — rebuild is the correct semantics. Iterate at `--scale-multiplier 0.3` for speed, then build full scale. `python scripts/run_self_test.py` proves the toolchain end-to-end.

## Top-Level Fields

```jsonc
{
  "spec_version": 2,
  "organization": {"name", "archetype", "industry", "currency"},
  "platform": "sqlite",
  "seed": 7,
  "scale": {"profile": "small", "multiplier": 1.0},           // profile is descriptive metadata only; multiplier is the volume lever (also --scale-multiplier)
  "time": {"start_date", "end_date", "as_of_date"},          // bare date/timestamp draws span start..min(end, as_of); only date_offset with clamp_as_of:false can land after as_of (deliberate future dates: due dates, expiry)
  "calendar": {
    "weekday_weights": [..7, Mon..Sun],                       // weekend dip
    "month_weights": [..12],                                   // seasonality
    "holidays": ["2024-12-25"], "annual_growth": 0.07,
    "business_hours": [7, 18]                                  // human timestamps cluster here (~4% stragglers)
  },
  "vocab": {"pool_name": ["phrase", ...]},                     // extends built-in text pools
  "tables": [...], "state_machines": [...], "derivations": [...], "imperfections": [...],
  "controls": [...], "dq_rules": [...], "dataflows": [...],    // documentation-level (catalog/validator)
  "validation": {"required_views": [...], "expected_row_ranges": {"schema.table": [lo, hi]}}
}
```

Any key starting with `_` (e.g. `_note`) is a comment, stripped before validation — annotate specs freely.

## Tables

```jsonc
{
  "schema": "erp", "name": "sales_order",        // logical name erp.sales_order -> physical erp_sales_order
  "layer": "transaction",                         // see common-layers.md
  "purpose": "...", "grain": "one row per order", // facts MUST state grain
  "source": "generator",                          // generator | derivation | state_machine | empty
  "source_system": "LedgerWorks ERP",
  "primary_key": ["order_id"], "natural_key": ["order_number"],
  "indexes": [["customer_id"], ["order_date"]],   // FK columns are auto-indexed
  "traits": ["audited", "source_stamped"],
  "rows": 650,                                    // OR {"base": 650} OR {"per_parent": ...} below
  "scale_exempt": true,                           // reference/dim tables ignore the multiplier
  "columns": [...]
}
```

- `source: "generator"` (default) — engine generates rows; needs `rows`.
- `source: "derivation"` — populated by SQL in `derivations`; columns define DDL only (no `gen`).
- `source: "state_machine"` — history table filled by a machine; first four columns must be entity pk, sequence, state, entered_at.
- Layer rule (use these exact layer strings — the validator's vocabulary): `source`/`operational`/`transaction`/`event` layers generate; `staging`/`xref`/`canonical`/`warehouse_fact`/`warehouse_dimension`/`mart` layers **derive** — that is what makes lineage real. Other recognized layers: `app`, `control`, `dq`, `workflow`, `audit`, `integration`, `raw`.
- Identifiers (table/column/key/index names) must match `[A-Za-z_][A-Za-z0-9_]*` — they are interpolated into SQL and the engine rejects anything else.

**Rows per parent** (realistic skew — children counted per parent):

```jsonc
"rows": {"per_parent": "erp.customer",
         "distribution": {"distribution": "lognormal", "median": 9, "sigma": 0.7},
         "scale_by": {"parent_column": "segment",                    // volume conditioned on a parent attribute
                      "factors": {"national_chain": 9.0, "institution": 4.0}, "default": 1.0},
         "per_parent_multiplier": {"distribution": "lognormal", "median": 1.0, "sigma": 0.9},  // heavy-tailed activity weight -> whales
         "min": 0, "max": 420}
```

Always set `max` (one hot draw can explode counts). Parent counts already scale with the multiplier; child counts are not re-scaled. `scale_by` + `per_parent_multiplier` are the customer-economics levers — without them every parent has the same expected volume, which fails the first segment cross-tab a reviewer runs.

**Traits** auto-append standard column packs (explicit columns win over trait columns):

| Trait | Columns added |
| --- | --- |
| `audited` | created_at, created_by, updated_at, updated_by (zipf-weighted staff actors; updated_at >= created_at) |
| `source_stamped` | source_system, source_updated_at, ingested_at (lags source), batch_id |
| `soft_delete` | active_flag |
| `effective_dated` | effective_start_date, effective_end_date, current_flag |

**SCD2 history**: `"history": {"strategy": "scd2", "change_rate": 0.25, "max_versions": 3, "track": ["col"]}` on an effective-dated table emits predecessor versions with chained dates. History versions get synthetic surrogate keys and are excluded from FK/per_parent pools — `fk:` against an scd2 table always resolves to current versions.

## Generators — three tiers

**Tier 1 — omit `gen` and let inference work** (write nothing for these):

| Column name | Inferred generator |
| --- | --- |
| single integer PK column | sequence |
| email / phone / fax / mobile | safe fictional email (example.com) / phone (555-01xx) |
| first_name / last_name / full_name / contact_name | persona names (coherent with email within a row) |
| company_name / legal_name / account_name / customer_name / supplier_name | company name |
| street_address / city / state / region / postal_code / zip | coherent city+state+zip+area-code place |
| country, currency | constants (US / organization.currency) |
| created_by / updated_by / assigned_to | zipf-weighted staff user |
| notes / comment | domain text pool |
| typed date / timestamp with no gen | calendar-weighted in-horizon value |

Columns matching none of these do NOT error — they fall through to generic type-based fillers (string -> `"VAL-#####"` pattern, integer -> uniform 0..100, decimal -> lognormal money median 100, boolean -> 50/50). Treat any `VAL-####` values in profiling output as a missing `gen`.

**Tier 2 — string shorthands** (most columns should use these):

```text
"seq" | "seq:CUST-%06d"            sequence id with format
"pattern:ORD-########"             # digit, @ upper, ? lower, * alnum; add "unique": true in object form
"fk:erp.product@zipf"              FK pick (weightings: uniform | zipf | recency)
"fk:erp.product@zipf(0.5)"         zipf with explicit exponent — default 1.1 is heavy; use ~0.5 for product
                                   popularity so the top SKU stays ~2-4% of lines, not 20%
"choice:NET30=0.6,NET45=0.3,COD=0.1"
"int:lognormal(median=5,sigma=0.9,min=1,max=200)"
"money:lognormal(median=120,sigma=0.8)"
"bool:0.9"  "const:draft"  "copy:other_col"
"expr:round(quantity * unit_price, 2)"
"text:delivery_note"               built-in pools: support_topic, support_action, delivery_note, audit_comment, exception_note (+ your vocab)
"identifier:gtin13"                kinds: masked_card, aba_routing, iban, isin, cusip, npi, gtin13, vin, lei, luhn — all in provably fictional/test ranges
"company:restaurant"               flavors: generic, food, restaurant, healthcare, finance, tech, logistics, manufacturing, retail, insurance, energy, realestate
"uuid" "date" "timestamp" "person_full" "addr_city" "staff_user" "parent_key" "child_index" "skip" ...
```

**Tier 3 — object form** for the realism levers:

```jsonc
// Calendar-weighted date bounded by another column (THE pattern for activity dates):
{"type": "date", "min": "parent.created_at"}                  // never before the parent existed; keeps weekday/seasonal shape

// Sorted entity onboarding with pre-horizon backfill (tenured book; IDs correlate with dates).
// Only valid on fixed-count tables — NOT per_parent (row count unknown upfront); for child
// entities use date_offset from parent.<col> or {"type": "timestamp", "min": "parent.<col>"}:
{"type": "timestamp", "sorted": true, "backfill_share": 0.65, "backfill_start": "2019-01-01"}

// Short process lags ONLY (ship after order). NEVER for long activity windows —
// clamping piles rows onto the as_of date and ignores the calendar:
{"type": "date_offset", "from": "order_date", "unit": "days",
 "offset": {"distribution": "lognormal", "median": 2, "sigma": 0.5, "min": 1}, "business_days": true, "as": "date"}

// Segment-conditional parameters (the cross-column correlation lever):
{"type": "case", "on": "segment", "cases": {"enterprise": {"type": "money", "median": 150000, "sigma": 0.4},
 "smb": {"type": "money", "median": 8000, "sigma": 0.6}}, "default": "..."}

// FK affinity: pick parents whose attribute matches a local column, with leakage:
{"type": "fk", "ref": "wms.warehouse", "match": {"parent_column": "region", "local_column": "region", "leak_rate": 0.05}}

// Denormalize a parent attribute through a FK (price snapshots, region copies).
// fk_copy's "column" (the local FK) must be declared BEFORE the fk_copy column:
{"type": "fk_copy", "column": "product_id", "ref": "erp.product", "source_column": "list_price", "jitter": 0.05}

// Text from templates over vocab pools and/or earlier columns ({pool_name} or {col.<name>}):
{"type": "text_template", "templates": ["{protein_product}", "Called about {support_topic}."]}

// choice object forms (weights optional): {"type": "choice", "values": ["a","b"], "weights": [0.8, 0.2]}
// or values as [{"value": "a", "weight": 0.8}, ...]
// company_name with "unique": true de-duplicates (city-suffix disambiguation), for entity name columns
// company_name with "chain_pool": N draws from N shared brands with numbered locations
// ("Cedar Point Cantina #3") — use for chain segments so multi-location accounts share a brand

// B2B account emails: role/proprietor addresses on a company-derived example.com subdomain
// (orders@cedar-point-cantina.example.com — RFC 2606 keeps subdomains fictional-safe):
{"type": "business_email", "company_column": "account_name", "roles": ["orders", "ap", "info"], "role_share": 0.55}

// Per-parent tables: "parent_key", {"type": "parent_copy", "source_column": "x"}, "child_index"
// Self-referencing hierarchy: {"type": "self_fk", "root_share": 0.25}
// Money with price endings: {"type": "money", "median": 42, "sigma": 0.7, "price_endings": [0.99, 0.49, 0.0]}
```

Any column accepts `"null_rate": 0.07` (design-level missingness; logged imperfections are separate). Columns generate in listed order — `expr`/`copy`/`case`/`fk_copy` may only reference earlier columns.

**Price realism rule**: transactional amounts must be `fk_copy(price)` x integer quantity via `expr` — never direct continuous draws. Real amount columns repeat exact values; the validator checks duplicate mass.

Distributions: `uniform(min,max)`, `normal(mean,stdev)`, `lognormal(median,sigma)`, `poisson(lam)`, `pareto(alpha,xm)`, `beta(alpha,beta,scale)`, `exponential(mean)`, `geometric(p)`, `triangular(min,max,mode)`, `zipf(n,s)`, `constant(value)`. See `references/data-realism.md` for choosing parameters.

## State Machines

```jsonc
{
  "name": "sales_order_lifecycle",
  "table": "erp.sales_order", "status_column": "status", "start_column": "order_date",
  "entry_state": "draft",
  "states": ["draft", "submitted", "shipped", "paid", "cancelled"],
  "transitions": [
    {"from": "draft", "to": "submitted", "probability": 0.975,
     "dwell": {"distribution": "lognormal", "median": 3, "sigma": 1.0, "unit": "hours"}},
    {"from": "draft", "to": "cancelled", "probability": 0.025, "dwell": {...}}
  ],
  "timestamp_columns": {"shipped": "shipped_at", "paid": "paid_at"},
  "history_table": "erp.sales_order_event",
  "truncate_at_as_of": true
}
```

- Give `status` the generator `"const:<entry_state>"` and per-state timestamp columns `"skip"` (nullable) — the machine overwrites them.
- Residual probability below 1.0 means "stay in state"; sums above 1.0 auto-normalize with a note.
- `truncate_at_as_of` right-censors: recent entities legitimately sit mid-pipeline with NULL later-stage timestamps. Never force everything terminal.
- Dwell units: `hours`, `days`, `minutes`, `business_days`.

## Derivations

Ordered SQL run in-database after generation — staging/canonical/warehouse/marts are **derived from** source rows, so lineage and propagated defects are real.

```jsonc
{"name": "core_customer", "expect": {"at_least_rows": 500},
 "sql": ["insert into core.customer", "select ... from stg.crm_account s ..."]}
```

- Write logical names (`core.customer`); the engine rewrites them to physical names.
- `sql` may be a string or list of lines. `create view ...` derivations become views (marts, control recon, DQ results) — views always reflect post-imperfection data.
- Sandbox: no ATTACH/DETACH/PRAGMA, no writes to `meta_*`. Failures report the derivation name, statement index, and SQL.
- No `random()`/`datetime('now')` in derivation SQL — they break determinism. Derive variation from existing columns (e.g. `case when id % 10 < 5 ...`).
- Indexes exist before derivations run; insert-selects can join at scale.

**The full view stack** (see "The Layered Warehouse Stack" in `references/common-layers.md` for the rung-by-rung model and SQL complexity targets in `references/enterprise-patterns.md`):

- Derivations run in order, so **views may select from earlier views** — build normalized views (`nv_*`) over facts/dims, business views (`bv_*`) over normalized views, and business-unit custom views (`mart_<bu>_*`) over business views. Deep dependency chains are the realistic shape.
- **Materialized views** (`mv_*`): SQLite has none natively — model each as a table with `source: "derivation"`, layer `mart`, populated by an insert-select from a business view. Pair it with a `catalog.code_object` row for the refresh procedure and `integration.job_run` history.
- **Human-entered mappings**: declare mapping tables (e.g. `manual.cost_center_mapping`) as plain generator tables, then join them in *some* view derivations and deliberately not others, with an `'UNMAPPED'` fallback via `left join` + `coalesce`. The cross-BU metric discrepancy this creates is a feature — aim a recon control at it.
- Gate the whole stack: every view in `validation.required_views`, every materialized table in `validation.expected_row_ranges`.

## Imperfections

Typed, rate-controlled, all logged to `meta_imperfection_log` so validation reconciles instead of flagging them. Rates are fractions (engine errors above 0.5). `stage`: `pre_derivation` (defects propagate through lineage) or `post_derivation` (defects in derived layers, e.g. recon breaks).

| Type | Params | Typical use |
| --- | --- | --- |
| typo | column | hand-keyed names (digit-bearing values only get case/whitespace noise — keeps fictional phones safe) |
| duplicate_entity | fuzz_columns | MDM merge-queue fodder |
| late_arrival | column, lag_days dist | feed outages |
| orphan_fk | column | hard-deleted parents |
| missing_xref | — (deletes rows) | unmapped identifiers |
| conflicting_source_values | column, variants? | cross-system disagreement |
| format_drift | column, format: us_date/uppercase/padded | legacy extracts; breaks staging parses realistically |
| restatement_reversal | amount_columns, reason_column | reversal+restated pairs; creates recon breaks |
| out_of_order_events | sequence_column, group_column | CDC disorder |
| duplicate_webhook | — | retried deliveries |
| stale_mapping | column (valid_to) | expired but referenced mappings |
| manual_override | column, value, note_column | month-end human overrides |
| null_field | column | logged missingness |

Design pattern: aim each imperfection at a DQ rule, recon control, or workflow queue that catches it — defects nobody would notice aren't realism, they're noise.

## Determinism and Engineering Conventions

- RNG substreams: `random.Random(sha256("\x1f".join([seed, table, "col:<name>"]))[:8])` — per-column streams, so adding a column or table doesn't reshuffle the rest. Never use `hash()` or iterate unsorted sets in engine code.
- All money is REAL rounded to 2 decimals; validators compare sums with count-scaled tolerance.
- Timestamps are timezone-naive in one fictional business timezone; ISO text in SQLite.
- All file writes are `encoding='utf-8', newline='\n'`; stdout reconfigured to UTF-8.
- Engine requires SQLite >= 3.31 and Python >= 3.9; environment versions are recorded in `meta_build_info`.
- Build outputs (`build/` directories, `*.db`) stay out of version control.
