# Synthetic transaction reconciliation datasets

Start with `source/`. These are fictional, standardized source exports for NovaCommerce. The separate `demo_context.json` adds fictional customer names, markets, sales channels, and bank and processor labels for the interface. The matching engine uses the source exports.

## Scope

- Seed: 20261105. Synthetic snapshot: 2026-11-05 at 23:59:59 UTC; processor event dates 2026-09-06 through 2026-11-04.
- One merchant, one processor, one bank account, one illustrative ledger; USD only.
- 10,000 orders; 20,590 processor events; 120 payouts.
- Integer cents throughout: 43500 means USD 435.00. CSV is UTF-8 with a header. Blank optional values mean NULL.
- ISO dates; timestamps use UTC with Z. There is no personal information or payment card data.
- Fees are separate negative processor events. Never subtract fees again from payout item sums.
- Two weekdays to expected arrival plus two weekdays grace; weekends modeled, holidays omitted. Treat future arrivals as pending.

## Folders

| Folder | Purpose |
|---|---|
| source | Baseline files to import into the project |
| evaluation | Expected checks, true links, scenario labels; keep out of production matching inputs |
| fixtures/replay | 100 repeated events to test idempotent ingestion |
| fixtures/invalid | Four malformed/unsupported rows to test quarantine; never import as baseline |
| fixtures/late_evidence | Two missing payout membership rows; apply only after baseline checks |
| runtime_templates | Header-only application output tables; your engine generates their rows |
| documentation | Data dictionary, SQL schema, load commands, rules, validation report, and model |

## Baseline source files

| File | Rows | Meaning |
|---|---:|---|
| ingestion_batches.csv | 4 | Completed synthetic export metadata; application import state is separate. |
| customers.csv | 2,500 | Fictional customers without names, emails, or personal data. |
| bank_accounts.csv | 1 | One fictional merchant bank account. |
| chart_of_accounts.csv | 9 | Simplified illustrative ledger accounts. |
| users.csv | 2 | Fictional reviewers for application development. |
| orders.csv | 10,000 | One commerce order. Gross order value is independent of later refunds. |
| processor_transactions.csv | 20,590 | One signed processor event. Fees are separate events. |
| processor_payouts.csv | 120 | One settlement header reported by the processor. |
| payout_items.csv | 20,538 | Processor-supplied membership; one signed event contributes to one payout. |
| bank_transactions.csv | 120 | Observed bank movements; includes unrelated credits and fees. |
| ledger_journals.csv | 20,658 | One posted journal header; references bank movement where applicable. |
| ledger_entries.csv | 41,316 | One debit or credit line; every supplied journal balances. |

## How to start

1. Read `documentation/data_dictionary.csv` and `documentation/rules.json`.
2. Create a database and run `documentation/schema.sql`. Then, from this datasets directory, run `psql YOUR_DATABASE -f documentation/load_source.psql`. This loads only baseline source data. Use a fresh schema; creation/load scripts are not migrations or idempotent loaders.
3. Reconcile orders to captures, processor events to payouts, payouts to bank, then bank cash movements to ledger journals.
4. Generate your own match groups, members, exceptions, and case history. The supplied runtime templates intentionally contain no fake results.
5. Compare against `evaluation/expected_checks.csv`; use `evaluation/true_links.csv` only to score linkage correctness.
6. Test replay and invalid files separately. Then apply late evidence and confirm reruns preserve case history.

## Scenarios and expected behavior

- Normal settlements aggregate many captures and fees. Some also contain refunds, chargebacks, reserve holds, or releases; these are legitimate signed activity.
- First 200 orders use two captures. Another 50 are partially captured and retain an open balance. There are 50 paid storefront orders without processor captures: exceptions.
- Unpaid, authorization-only, and cancelled orders are not eligible for automatic paid-order matching. Authorizations contribute zero to settlement.
- Two examples each of bank short-payment, missing bank deposit, ambiguous same-amount bank credit, missing bank reference, missing ledger journal, incorrect ledger amount, missing payout item, and incorrect payout header are injected.
- Missing references require review even when amount/date identify a unique candidate. Equal-amount ambiguous credits must not be force-matched.
- Missing membership and incorrect header cases intentionally violate payout totals. An incorrect header also causes a payout-to-bank variance. Check each stage independently.
- Every supplied journal balances, including deliberately incorrect cash amounts. Balanced journals alone do not establish reconciliation correctness.
- Two unrelated extra credits create ambiguity, plus two explicit bank-only movements are included. Bank-only does not automatically mean erroneous.
- Pending payout counts depend on the fixed snapshot and rule policy. They are not missing-deposit exceptions.
- Late-evidence membership rows correct only missing-item cases. Other anomalies remain unresolved until you implement an appropriate review/correction workflow.

## Evaluation conventions

`expected_checks.csv` has one row per order check, two per payout, and one per observed bank-to-ledger check. `variance_cents = actual - expected`. Missing observations use blank actual/variance, not a fabricated zero. Ledger absence uses zero observed cash allocation. For ambiguous bank candidates, actual is the primary true credit amount, not the sum of alternative candidates. `candidate_ids` is semicolon-delimited. `true_links.csv` records economic linkage, including links requiring review or carrying a variance; it is not a list of approved auto-matches.

Development and holdout labels use the first 48 versus last 12 settlement days. Order labels use order date. Related refunds and orders can cross the date boundary: this is a temporal test split, not an entity-disjoint machine-learning split. Both payout splits contain all eight anomaly types. Keep holdout labels hidden while tuning rules.

## Deliberate limits

Source files are standardized exports rather than authentic Stripe/Shopify/bank payloads. Tax, inventory, invoice-to-cash, FX, disputes lifecycle, holiday calendars, reissued payouts, and full financial statements are outside this V1. The ledger demonstrates captures, processing expenses, refunds, reserves, and bank settlement with simplified accounting. These files do not constitute provider-specific accounting guidance.

Foreign keys validate supplied source links. Polymorphic match member links and cross-row allocation limits require application-level validation. Reserve and adjustment events may have no order. `ingestion_batches` records export readiness, not proof of import into your application. `manifest.json` carries actual per-file hashes and row counts.

The generator uses a fixed seed and no wall-clock-dependent values. Source files and expected answers were checked by importing the CSVs into SQLite, enforcing foreign keys, checking balanced journals, and independently recomputing amounts. PostgreSQL execution has not been performed.
