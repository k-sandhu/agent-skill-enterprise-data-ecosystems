# Common Enterprise Layers

Use these layers as a reusable backbone. Include only layers that fit the requested realism and scope. For the warehouse path specifically, see "The Layered Warehouse Stack" below — at medium/high realism, model every rung of that ladder, not a collapsed raw -> staging -> mart shortcut.

| Layer | Purpose | Common objects |
| --- | --- | --- |
| `app.*` | Application catalog and source-system metadata | application, application_module, application_owner, source_object, source_field, integration, data_contract, system_of_record_rule |
| `raw_*` | Raw files, API payloads, event streams, source extracts | raw_file, raw_api_payload, raw_event, raw_extract, raw_error |
| `stg_*` | Cleaned source-specific staging | stg_crm_account, stg_erp_customer, stg_wms_pick_task, stg_billing_invoice |
| `core_*` or `core.*` | Canonical enterprise objects | customer, person, organization, account, product, order, transaction, asset, location, document, case |
| `xref_*` or `xref.*` | Source-to-canonical identifier mapping | entity_identifier, customer_source_identifier, product_source_identifier, account_source_identifier |
| `mdm_*` or `mdm.*` | Golden records, entity resolution, survivorship | match_candidate, merge_event, survivorship_rule, golden_customer |
| `dim_*` | Warehouse dimensions | dim_customer, dim_product, dim_location, dim_date, dim_currency, dim_status |
| `fact_*` | Warehouse facts | fact_order_line, fact_invoice_line, fact_inventory_movement, fact_payment, fact_event |
| `mart_*` | Business-domain marts | mart_sales, mart_finance, mart_operations, mart_quality, mart_risk |
| `semantic_*` or `semantic.*` | Certified business definitions | business_term, metric, metric_version, metric_component, certified_dataset |
| `catalog_*` or `catalog.*` | Metadata, lineage, reports, jobs, code objects | dataset, table, column, report, dashboard, lineage_edge, job, job_run, schema_change, code_object, stored_procedure, user_function, extract_definition |
| `dq_*` or `dq.*` | Data-quality rules and failures | rule, rule_run, rule_result, failed_record, exception, remediation_action |
| `control_*` or `control.*` | Reconciliation and close controls | reconciliation_rule, reconciliation_run, reconciliation_result, reconciliation_break, adjustment, signoff |
| `audit_*` or `audit.*` | User and system change history | change_event, field_change, login_event, admin_action, approval_event, override_event |
| `security_*` or `security.*` | Roles, permissions, masking, access | user, role, permission, group, user_role_assignment, dataset_access, masking_policy |
| `privacy_*` or `privacy.*` | Consent, retention, data subject actions | consent, retention_policy, deletion_request, processing_purpose, sensitive_access_log |
| `workflow_*` or `workflow.*` | Cases, queues, tasks, approvals | case, queue, task, assignment, status_history, comment, sla, escalation, approval |
| `document_*` or `document.*` | Document metadata and extraction | document, document_version, attachment, storage_location, ocr_result, extracted_field, entity_link |
| `integration_*` or `integration.*` | API, batch, CDC, file, stream logs | integration_job, integration_run, source_file, api_request_log, webhook_event, cdc_event, retry, watermark |
| `manual_*` or `shadow_*` | Spreadsheets, overrides, human corrections | override, note, review, approval, spreadsheet_upload, user_uploaded_mapping |
| `ml_*` or `ml.*` | Features, models, predictions, monitoring | feature, feature_set, training_dataset, model, model_version, prediction, monitoring_metric |

## The Layered Warehouse Stack

Real enterprise warehouses are deep: data lands, is staged, normalized, dimensionalized, then climbs a stack of views before any business unit sees it. Model each rung explicitly. Every rung maps onto the engine's `layer` vocabulary and prefixes, so the validator recognizes the result:

| # | Rung | Prefix | Engine `layer` | Populated by |
| --- | --- | --- | --- | --- |
| 1 | Landing | `raw_*` | `raw` | Generator. One table per source feed/extract — verbatim payloads, file/batch ids, `ingested_at`. Multiple landing tables per source system, not one token table. |
| 2 | Staging | `stg_*` | `staging` | Derivation. Typed, trimmed, parsed (drifted dates to NULL), deduplicated. One staging table per landing table. |
| 3 | Normalization (3NF canonical) | `core_*`, `xref_*`, `mdm_*` | `canonical`, `xref` | Derivation. Joins staging through crosswalks; survivorship resolves cross-source conflicts. |
| 4 | Dimensions | `wh_dim_*` | `warehouse_dimension` | Derivation from canonical + reference tables. |
| 5 | Facts | `wh_fact_*` | `warehouse_fact` | Derivation from canonical + operational/transaction tables. Explicit grain, multi-way joins. |
| 6 | Normalized views | `nv_*` | view (`create view` derivation) | Readable, denormalized re-joins of facts/dims with business column names. No metric logic. |
| 7 | Business views | `bv_*` | view (`create view` derivation) | Metric logic: aggregation, window functions, case logic, as-of filters. Built on normalized views. |
| 8 | Materialized views | `mv_*` | `mart` table with `source: "derivation"` | Insert-select from business views. SQLite has no native materialized views — model them as derived tables the build "refreshes", which is also how most warehouses implement them (a scheduled rebuild procedure). |
| 9 | Business-unit custom views | `mart_<bu>_*` (e.g. `mart_finance_*`, `mart_ops_*`) | view (`create view` derivation) | Per-business-unit stacks over business/materialized views: BU-specific filters, renamed columns, extra mappings applied — and deliberately competing definitions. |

Stack rules:

- **Flow rule**: each rung reads only from the rung directly beneath it (plus reference data, crosswalks, and mapping tables). Layer-skipping — a BU view reaching straight into staging — is an anti-pattern in real shops too; include at most one or two documented instances as legacy debt, not as the norm.
- Views stack on views: derivations run in order, so `bv_*` may select from `nv_*`, and `mart_<bu>_*` from `bv_*` and `mv_*`. A view stack where nothing depends on another view is a tell.
- Business units should not agree perfectly. At least one metric (revenue, active customer, on-time delivery) should differ between two BU views because one applies a manual mapping, exclusion list, or fiscal-calendar rule the other does not — and the difference should be documented and caught by a reconciliation control.
- Gate every view rung with `validation.required_views` and every materialized rung with `validation.expected_row_ranges`.

## Required Table Traits

Source and operational tables usually need:

- Primary key and source-specific natural/business key.
- `source_system` or `source_application_id`.
- Business status and status reason.
- `created_at`, `updated_at`, `created_by`, `updated_by`.
- `source_updated_at`, `ingested_at`, and batch/run identifiers for ingested data.
- `active_flag` or delete marker for soft deletes.

Historical and canonical tables often need:

- `effective_start_date`, `effective_end_date`, `valid_from`, `valid_to`.
- `current_flag`.
- `record_source`, `survivorship_rule`, `confidence_score` where MDM is involved.
- Reason codes for changes, reversals, restatements, or overrides.

Warehouse facts must state:

- Grain.
- Additive/semi-additive/non-additive measures.
- Degenerate dimensions where useful, such as invoice number or order number.
- Date roles, such as order date, posting date, service date, settlement date, load date, as-of date.

## Generic Crosswalk

Use this when no domain-specific crosswalk is needed:

```text
xref.entity_identifier
- entity_identifier_id
- canonical_entity_type
- canonical_entity_id
- source_application_id
- source_object_name
- source_record_id
- source_business_key
- valid_from
- valid_to
- active_flag
- confidence_score
- match_method
- created_at
- updated_at
```

Include clean matches, missing mappings, stale mappings, duplicate mappings, low-confidence matches, and legacy mappings when realism level is medium or high.

## Human-Entered Mapping Tables

Distinct from system crosswalks: enterprises run on hand-maintained mapping tables — spreadsheets uploaded by an analyst, then loaded into one layer of the stack and quietly depended on. Model at least one per ecosystem at medium/high realism. Typical subjects: GL account/cost-center mappings, product-hierarchy rollups, region/territory assignments, line-of-business codes, payer/plan groupings, carrier aliases.

Shape (a generator table, e.g. `manual.cost_center_mapping`, layer `operational`, trait `audited`):

```text
manual.<subject>_mapping
- mapping_id
- source_code            -- the code as it appears upstream
- mapped_code            -- the human-assigned target
- mapped_description
- business_unit          -- who maintains it
- effective_start_date / effective_end_date
- uploaded_by, uploaded_at, source_file_name
- approved_flag
```

The realism is in how it is (mis)used:

- **Asymmetric application**: apply the mapping in one downstream consumer and not another — e.g. the finance BU view joins `manual.cost_center_mapping`, the operations BU view uses the raw code. The two views then legitimately disagree; document the discrepancy and aim a reconciliation control at it.
- **Coverage gaps**: 85-95% of live codes mapped, never 100%. Unmapped codes fall to an `'UNMAPPED'` bucket in the views that apply the mapping and feed a DQ rule plus a mapping-request workflow queue.
- **Staleness and duplicates**: a few rows mapping retired codes, a few overlapping effective ranges from a re-upload, occasionally two rows mapping the same source code differently (last upload wins in one consumer, first in another).
- **Layer asymmetry on entry**: human data entered at one layer does not exist at others — the mapping lives beside staging or the marts, never in landing, and nothing upstream knows about it. Never backport it into source tables.
