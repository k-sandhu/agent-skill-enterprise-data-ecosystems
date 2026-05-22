# Industry: Banking

## Domains

party, customer, account, deposits, payments, cards, loans, ledger, treasury, risk, fraud, AML, KYC, compliance, branch, digital, customer_service.

## Source Systems

Core banking, digital banking, payment hub, card processor, loan servicing, deposit platform, customer onboarding/KYC, AML case management, fraud engine, general ledger, statement processor, data warehouse.

## Core Tables

- `party.party`, `party.person`, `party.organization`, `party.relationship`
- `accounts.account`, `accounts.account_holder`, `accounts.account_status_history`
- `deposits.deposit_account`, `deposits.interest_accrual`
- `payments.payment_instruction`, `payments.payment_event`, `payments.payment_return`
- `cards.card_account`, `cards.card_authorization`, `cards.card_transaction`
- `loans.loan_account`, `loans.loan_schedule`, `loans.loan_payment`
- `ledger.subledger_entry`, `ledger.journal_entry`, `ledger.gl_balance`
- `kyc.customer_due_diligence`, `aml.alert`, `aml.case`
- `fraud.score`, `fraud.case`, `risk.risk_rating`

## Facts and Dimensions

- `fact_account_balance_daily`: one account-business_date.
- `fact_transaction`: one posted transaction.
- `fact_payment_event`: one payment lifecycle event.
- `fact_card_authorization`: one authorization attempt.
- `fact_loan_payment`: one loan payment due/received.
- `fact_gl_balance_daily`: one GL account-legal_entity-business_date.

Dimensions: customer, account, branch, product, channel, currency, merchant, risk_rating, date.

## Dataflows

- Payment lifecycle: initiation -> validation -> sanctions/fraud screening -> authorization -> release -> settlement -> return/reversal when needed.
- Account balance: posted transactions -> subledger -> account balance -> GL balance -> regulatory report.
- KYC onboarding: application -> identity verification -> risk scoring -> due diligence -> account opening.

## Controls

- Account balances roll forward from transactions.
- Payment totals tie to settlement files.
- Subledger ties to GL.
- Card processor transactions tie to posted account transactions.
- AML alerts tie to cases and dispositions.

## Imperfections

Returned payments, duplicate payment messages, late settlement files, stale KYC documents, name/address mismatches, manual fee reversals, suspicious activity cases, closed accounts receiving transactions, legacy account IDs.
