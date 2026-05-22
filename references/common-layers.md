# Common Enterprise Layers

Use these layers as a reusable backbone. Include only layers that fit the requested realism and scope.

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
| `catalog_*` or `catalog.*` | Metadata, lineage, reports, jobs | dataset, table, column, report, dashboard, lineage_edge, job, job_run, schema_change |
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
