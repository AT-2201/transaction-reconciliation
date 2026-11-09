-- PostgreSQL starting schema. Blank optional CSV fields load as NULL.

CREATE TABLE ingestion_batches (
    batch_id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    exported_at TIMESTAMPTZ NOT NULL,
    state TEXT NOT NULL
);

CREATE TABLE customers (
    customer_id TEXT PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE bank_accounts (
    account_id TEXT PRIMARY KEY,
    merchant_id TEXT NOT NULL,
    currency TEXT NOT NULL
);

CREATE TABLE chart_of_accounts (
    account_code TEXT PRIMARY KEY,
    account_name TEXT NOT NULL
);

CREATE TABLE users (
    user_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    role TEXT NOT NULL
);

CREATE TABLE orders (
    order_id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL,
    order_amount_cents BIGINT NOT NULL,
    currency TEXT NOT NULL,
    status TEXT NOT NULL,
    ordered_at TIMESTAMPTZ NOT NULL,
    source_system TEXT NOT NULL,
    batch_id TEXT NOT NULL,
    source_created_at TIMESTAMPTZ NOT NULL,
    FOREIGN KEY (customer_id) REFERENCES customers (customer_id),
    FOREIGN KEY (batch_id) REFERENCES ingestion_batches (batch_id)
);

CREATE TABLE processor_transactions (
    txn_id TEXT PRIMARY KEY,
    order_id TEXT ,
    related_txn_id TEXT ,
    type TEXT NOT NULL,
    amount_cents BIGINT NOT NULL,
    authorized_amount_cents BIGINT ,
    currency TEXT NOT NULL,
    status TEXT NOT NULL,
    processed_at TIMESTAMPTZ NOT NULL,
    source_system TEXT NOT NULL,
    batch_id TEXT NOT NULL,
    source_created_at TIMESTAMPTZ NOT NULL,
    FOREIGN KEY (order_id) REFERENCES orders (order_id),
    FOREIGN KEY (related_txn_id) REFERENCES processor_transactions (txn_id),
    FOREIGN KEY (batch_id) REFERENCES ingestion_batches (batch_id)
);

CREATE TABLE processor_payouts (
    payout_id TEXT PRIMARY KEY,
    bank_account_id TEXT NOT NULL,
    net_amount_cents BIGINT NOT NULL,
    currency TEXT NOT NULL,
    status TEXT NOT NULL,
    settlement_date DATE NOT NULL,
    expected_arrival DATE NOT NULL,
    bank_reference TEXT NOT NULL,
    source_system TEXT NOT NULL,
    batch_id TEXT NOT NULL,
    source_created_at TIMESTAMPTZ NOT NULL,
    FOREIGN KEY (bank_account_id) REFERENCES bank_accounts (account_id),
    FOREIGN KEY (batch_id) REFERENCES ingestion_batches (batch_id)
);

CREATE TABLE payout_items (
    payout_item_id TEXT PRIMARY KEY,
    payout_id TEXT NOT NULL,
    txn_id TEXT NOT NULL,
    signed_contribution_cents BIGINT NOT NULL,
    source_system TEXT NOT NULL,
    batch_id TEXT NOT NULL,
    source_created_at TIMESTAMPTZ NOT NULL,
    FOREIGN KEY (payout_id) REFERENCES processor_payouts (payout_id),
    FOREIGN KEY (txn_id) REFERENCES processor_transactions (txn_id),
    FOREIGN KEY (batch_id) REFERENCES ingestion_batches (batch_id),
    UNIQUE (txn_id)
);

CREATE TABLE bank_transactions (
    bank_txn_id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    value_date DATE NOT NULL,
    amount_cents BIGINT NOT NULL,
    currency TEXT NOT NULL,
    status TEXT NOT NULL,
    reference TEXT ,
    memo TEXT NOT NULL,
    source_system TEXT NOT NULL,
    batch_id TEXT NOT NULL,
    source_created_at TIMESTAMPTZ NOT NULL,
    FOREIGN KEY (account_id) REFERENCES bank_accounts (account_id),
    FOREIGN KEY (batch_id) REFERENCES ingestion_batches (batch_id)
);

CREATE TABLE ledger_journals (
    journal_id TEXT PRIMARY KEY,
    posting_date DATE NOT NULL,
    status TEXT NOT NULL,
    reference TEXT NOT NULL,
    currency TEXT NOT NULL,
    source_system TEXT NOT NULL,
    batch_id TEXT NOT NULL,
    source_created_at TIMESTAMPTZ NOT NULL,
    FOREIGN KEY (batch_id) REFERENCES ingestion_batches (batch_id)
);

CREATE TABLE ledger_entries (
    line_id TEXT PRIMARY KEY,
    journal_id TEXT NOT NULL,
    account_code TEXT NOT NULL,
    debit_cents BIGINT NOT NULL,
    credit_cents BIGINT NOT NULL,
    source_system TEXT NOT NULL,
    batch_id TEXT NOT NULL,
    source_created_at TIMESTAMPTZ NOT NULL,
    FOREIGN KEY (journal_id) REFERENCES ledger_journals (journal_id),
    FOREIGN KEY (account_code) REFERENCES chart_of_accounts (account_code),
    FOREIGN KEY (batch_id) REFERENCES ingestion_batches (batch_id),
    CHECK (debit_cents >= 0 AND credit_cents >= 0 AND ((debit_cents > 0 AND credit_cents = 0) OR (credit_cents > 0 AND debit_cents = 0)))
);

CREATE TABLE reconciliation_runs (
    run_id TEXT PRIMARY KEY,
    started_at TIMESTAMPTZ NOT NULL,
    as_of_date DATE NOT NULL,
    status TEXT NOT NULL,
    rule_version TEXT NOT NULL
);

CREATE TABLE match_groups (
    match_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    stage TEXT NOT NULL,
    rule_id TEXT NOT NULL,
    rule_version TEXT NOT NULL,
    status TEXT NOT NULL,
    currency TEXT NOT NULL,
    variance_cents BIGINT ,
    created_at TIMESTAMPTZ NOT NULL,
    FOREIGN KEY (run_id) REFERENCES reconciliation_runs (run_id)
);

CREATE TABLE match_members (
    member_id TEXT PRIMARY KEY,
    match_id TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_id TEXT NOT NULL,
    role TEXT NOT NULL,
    allocation_cents BIGINT NOT NULL,
    FOREIGN KEY (match_id) REFERENCES match_groups (match_id)
);

CREATE TABLE exceptions (
    exception_id TEXT PRIMARY KEY,
    match_id TEXT ,
    dedupe_key TEXT NOT NULL,
    type TEXT NOT NULL,
    amount_cents BIGINT ,
    currency TEXT NOT NULL,
    status TEXT NOT NULL,
    assigned_to TEXT ,
    opened_at TIMESTAMPTZ NOT NULL,
    FOREIGN KEY (match_id) REFERENCES match_groups (match_id),
    FOREIGN KEY (assigned_to) REFERENCES users (user_id),
    UNIQUE (dedupe_key)
);

CREATE TABLE case_history (
    event_id TEXT PRIMARY KEY,
    exception_id TEXT NOT NULL,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    note TEXT ,
    FOREIGN KEY (exception_id) REFERENCES exceptions (exception_id)
);

CREATE TABLE evidence_links (
    evidence_id TEXT PRIMARY KEY,
    exception_id TEXT NOT NULL,
    source_path TEXT NOT NULL,
    source_record_id TEXT ,
    added_at TIMESTAMPTZ NOT NULL,
    FOREIGN KEY (exception_id) REFERENCES exceptions (exception_id)
);
