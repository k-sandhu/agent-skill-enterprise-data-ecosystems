# Bluestone Mutual Bank — Worked Example

A complete fictional regional retail/commercial bank: core banking customers and accounts, debit cards with merchant-skewed spend, an ACH/wire payment hub with a right-censored lifecycle state machine, an AML alert-to-case-to-SAR funnel, raw/staging/xref/canonical layers derived via SQL, a double-entry GL daily summary, a window-sum balance roll-forward where opening + credits − debits = closing holds by construction, warehouse facts and dims, mart/control/DQ views, and 12 logged controlled imperfections — every one aimed at a DQ rule, the GL reconciliation, or a workflow queue. Identifier safety throughout: `iban`, `aba_routing`, and `masked_card` identifier kinds only, with 555-01xx phones and example.com emails.

At multiplier 1.0 this builds ~290k rows across 31 tables and 4 views in well under a minute and passes strict validation (zero critical, zero warnings, full realism score).

## Run It

```text
python scripts/validate_ecosystem_spec.py examples/banking/ecosystem_spec.json
python scripts/build_sqlite_ecosystem.py  examples/banking/ecosystem_spec.json --plan
python scripts/build_sqlite_ecosystem.py  examples/banking/ecosystem_spec.json --out examples/banking/build --force
python scripts/validate_sqlite_database.py --db examples/banking/build/bluestone_mutual_bank.db --spec examples/banking/ecosystem_spec.json --report examples/banking/build/validation_report.md
python scripts/profile_sqlite_database.py --db examples/banking/build/bluestone_mutual_bank.db --report examples/banking/build/profile.md
```

## Patterns Worth Copying

- **Weekend dip on human channels with flat card volume** — one global calendar can't shape two channels differently, so the calendar carries the consumer-card week (mild Fri/Sat lift) and the `core_posted_transaction` derivation rolls ACH/wire posting to the next business day. The mart shows zero weekend ACH/wire rows, a 3x Monday catch-up spike, and seven-day card spend — three real banking signatures from one CASE expression.
- **Vintage-tier throttle kills the as_of pile-up** — per-parent volume draws don't know how long a parent has existed, so an account opened in December dumps a two-year transaction count into its last three weeks. `corebank.account.activity_tier` and `cardlink.card.usage_tier` are expression columns that string-compare the ISO-serialized parent onboarding date (`status if customer_since < '2025-04-01' else ...`) and feed `scale_by`, cutting late-vintage volume to a ramp rate. Before the fix, 2025-12-31 carried 15x normal card volume; after, it's a plausible year-end bump.
- **Recurring-payment duplicate mass via quantization** — `payment_instruction.amount` is `round(round(amount_raw / rounding_unit) * rounding_unit, 2)` where `rounding_unit` is segment- and type-conditioned (0.01 exact-cents one-offs; 5/25/100 recurring bills and payroll; 100/1000 round wires). The top-20 exact values carry ~17% of rows — real amount columns repeat.
- **Wire value skew without distorting ACH** — `wire_scale` (retail 0.32, commercial 2.6) applies only inside the amount expression's conditional (`amount_raw * (wire_scale if is_wire == 1 else 1)`), so commercial customers (5% of the book) carry ~60% of wire value while payroll deposits stay segment-neutral.
- **Balance roll-forward derived, never sampled** — `wh.fact_account_balance` is a window-sum over the posting ledger with a deterministic per-account opening anchor (`(account_id * 263) % 17500` — no `random()`), so opening + credits − debits = closing holds on every row.
- **Recon breaks from derivation ordering** — `ledger.gl_daily_summary` is double-entry by construction (deposits GL vs channel clearing GLs, debits = credits per day) and derives *before* the post-derivation `restatement_reversal` pairs land in `core.posted_transaction`. The `control_recon_txn_vs_gl` view is exactly the late-restatement story a finance-controls team chases.
- **AML funnel with coherent terminal stamps** — alerts fire on ~1.3% of payment instructions, skewed to wires via `scale_by` on payment_type, generated next morning by the overnight batch (`date_offset` +1 day). Two terminal states (`closed_false_positive`, `closed_no_action`) map to the *same* `closed_at` column; `aml.case_file` derives from escalated alerts so every case references an alert by construction.
- **Every imperfection has a catcher** — ghost merchants → DQ-004 and `UNKNOWN MERCHANT` postings; missing/stale xref → DQ-002/DQ-005; padded raw dates → DQ-003; CDC event swaps → DQ-006; nulled emails → DQ-007; the product-affinity 2% leak → DQ-001; GL restatements → the recon view; analyst overrides → `mart_aml_funnel`.

## Things to Query

```sql
-- Weekend dip on ACH/wire, flat card week, 3x Monday ACH catch-up
select channel, strftime('%w', txn_date) as weekday, count(*) as txns
from core_posted_transaction group by 1, 2 order by 1, 2;

-- Recurring payments repeat exact amounts (50/100/1000 lead)
select amount, count(*) from paystream_payment_instruction
group by 1 order by 2 desc limit 10;

-- Commercial customers: 5% of the book, ~60% of wire value
select segment, count(*) as wires, round(sum(amount)/1e6, 1) as value_mm
from paystream_payment_instruction where payment_type like 'wire%' group by 1;

-- Balance equation holds on every roll-forward row
select count(*) from wh_fact_account_balance
where abs(opening_balance + total_credits - total_debits - closing_balance) > 0.02;

-- GL recon breaks from late restatement reversals
select * from control_recon_txn_vs_gl order by abs(break_amount) desc limit 10;

-- AML funnel: false positives dominate, a few SARs, open items mid-flight
select * from mart_aml_funnel order by alerts desc;

-- Payments initiated in the final week sit legitimately mid-pipeline
select status, count(*) from paystream_payment_instruction
where initiated_date >= '2025-12-25' group by 1;

-- DQ results reconcile to the logged imperfections that caused them
select rule_code, count(*) from dq_rule_result_current group by 1 order by 1;
```
