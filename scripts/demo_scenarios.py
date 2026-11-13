"""Synthetic inputs for demonstrating the engine in an isolated database."""
import csv
import io

from app import db, engine, main


def import_rows(table, filename, records):
    with (db.DATASETS / 'source' / f'{table}.csv').open(newline='') as file:
        template = next(csv.DictReader(file))
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=list(template))
    writer.writeheader()
    for record in records:
        writer.writerow({**template, **record})
    result = db.import_csv(table, output.getvalue().encode(), filename)
    if result['inserted'] != len(records) or result['rejected']:
        raise RuntimeError(f'Scenario import failed for {table}: {result}')


def add_late_deposit():
    import_rows('bank_transactions', 'late-deposit.csv', [{
        'bank_txn_id': 'BTX-DEMO-LATE', 'amount_cents': 3301901,
        'reference': 'PO-0011', 'value_date': '2026-09-16',
        'source_created_at': '2026-11-05T10:00:00Z',
        'memo': 'Late-arriving bank statement record',
    }])


def add_grouped_payouts():
    payouts = []
    transactions = []
    items = []
    for label, amount in [('A', 60000), ('B', 40000)]:
        payout_id = f'PO-DEMO-{label}'
        txn_id = f'TXN-DEMO-{label}'
        payouts.append(dict(payout_id=payout_id, net_amount_cents=amount,
                            bank_reference='DEMO-BATCH-01', settlement_date='2026-10-27',
                            expected_arrival='2026-10-29', source_created_at='2026-10-27T18:00:00Z'))
        transactions.append(dict(txn_id=txn_id, order_id='', amount_cents=amount,
                                 processed_at='2026-10-27T10:00:00Z', source_created_at='2026-10-27T10:00:00Z'))
        items.append(dict(payout_item_id=f'PI-DEMO-{label}', payout_id=payout_id,
                          txn_id=txn_id, signed_contribution_cents=amount, source_created_at='2026-10-27T18:00:00Z'))
    import_rows('processor_payouts', 'grouped-payouts.csv', payouts)
    import_rows('processor_transactions', 'grouped-transactions.csv', transactions)
    import_rows('payout_items', 'grouped-items.csv', items)


def add_grouped_credit(credit_id):
    import_rows('bank_transactions', 'grouped-credit.csv', [{
        'bank_txn_id': credit_id, 'amount_cents': 100000,
        'reference': 'DEMO-BATCH-01', 'value_date': '2026-10-29',
        'source_created_at': '2026-10-29T13:00:00Z',
        'memo': 'Combined processor settlement',
    }])


def snapshots():
    before = main.payout_trace('PO-0011')
    case_id = next(case['id'] for case in main.exceptions(stage='payout_to_bank', offset=0, limit=1000)['items']
                   if case['entity_id']=='PO-0011')
    add_late_deposit()
    engine.run()
    after = main.payout_trace('PO-0011')
    case = main.case_detail(case_id)
    assert after['settlement']['status']=='reconciled' and not case['case']['finding_active']
    add_grouped_payouts()
    add_grouped_credit('BTX-DEMO-GROUP')
    engine.run()
    grouped = [main.payout_trace(f'PO-DEMO-{label}') for label in ('A', 'B')]
    assert all(t['settlement']['reason']=='grouped_bank_credit' for t in grouped)
    add_grouped_credit('BTX-DEMO-DUPLICATE')
    engine.run()
    ambiguous = [main.payout_trace(f'PO-DEMO-{label}') for label in ('A', 'B')]
    assert all(t['settlement']['status']=='review' for t in ambiguous)
    return dict(before=before, after=after, case=case, grouped=grouped, ambiguous=ambiguous)
