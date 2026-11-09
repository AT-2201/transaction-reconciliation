"""Build deterministic synthetic reconciliation fixtures using only the standard library."""
import csv
import hashlib
import json
import random
import sqlite3
import zipfile
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'datasets'
SEED = 20261105
ASOF = date(2026, 11, 5)
START = date(2026, 9, 6)
rng = random.Random(SEED)
tables = {}
schemas = {}
descriptions = {}


def define(name, description, columns):
    descriptions[name] = description
    schemas[name] = columns
    tables[name] = []


def add(name, **row):
    assert set(row) == {c[0] for c in schemas[name]}, (name, row)
    tables[name].append(row)
    return row


def stamp(day, hour=12):
    return f'{day.isoformat()}T{hour:02}:00:00Z'


def business_add(day, count):
    while count:
        day += timedelta(days=1)
        if day.weekday() < 5:
            count -= 1
    return day


# Columns: name, type, requirement, meaning. Monetary values are always integer USD cents.
define('customers', 'Fictional customers without names, emails, or personal data.', [
    ('customer_id','TEXT','PK','Synthetic customer identifier'),
    ('created_at','TIMESTAMPTZ','NOT NULL','Customer creation time')])
define('bank_accounts', 'One fictional merchant bank account.', [
    ('account_id','TEXT','PK','Synthetic account token; not a real account number'),
    ('merchant_id','TEXT','NOT NULL','Fictional merchant identifier'),
    ('currency','TEXT','NOT NULL','ISO currency code')])
define('chart_of_accounts', 'Simplified illustrative ledger accounts.', [
    ('account_code','TEXT','PK','Ledger account code'),
    ('account_name','TEXT','NOT NULL','Account label')])
define('users', 'Fictional reviewers for application development.', [
    ('user_id','TEXT','PK','Synthetic user identifier'),
    ('display_name','TEXT','NOT NULL','Fictional role label'),
    ('role','TEXT','NOT NULL','reviewer or approver')])
common = [('source_system','TEXT','NOT NULL','Stable external identifier namespace'),
          ('batch_id','TEXT','NOT NULL','Import batch identifier'),
          ('source_created_at','TIMESTAMPTZ','NOT NULL','Time recorded by the source')]
define('orders', 'One commerce order. Gross order value is independent of later refunds.', [
    ('order_id','TEXT','PK','Source order identifier'),
    ('customer_id','TEXT','NOT NULL','Reference to customers'),
    ('order_amount_cents','BIGINT','NOT NULL','Original positive order value in cents'),
    ('currency','TEXT','NOT NULL','USD'),
    ('status','TEXT','NOT NULL','paid, partially_paid, unpaid, authorized, or cancelled'),
    ('ordered_at','TIMESTAMPTZ','NOT NULL','Order creation time')] + common)
define('processor_transactions', 'One signed processor event. Fees are separate events.', [
    ('txn_id','TEXT','PK','Stable processor event identifier'),
    ('order_id','TEXT','','Related order; blank for processor-level reserve activity'),
    ('related_txn_id','TEXT','','Original capture related to fee/refund/chargeback, or reserve hold'),
    ('type','TEXT','NOT NULL','capture, fee, refund, chargeback, reserve_hold, reserve_release, authorization'),
    ('amount_cents','BIGINT','NOT NULL','Signed settlement effect; authorization is zero'),
    ('authorized_amount_cents','BIGINT','','Positive authorized amount only for authorization events'),
    ('currency','TEXT','NOT NULL','USD'),
    ('status','TEXT','NOT NULL','succeeded for settled events; authorized for noncaptured authorization'),
    ('processed_at','TIMESTAMPTZ','NOT NULL','Processor event time')] + common)
define('processor_payouts', 'One settlement header reported by the processor.', [
    ('payout_id','TEXT','PK','Stable processor payout identifier'),
    ('bank_account_id','TEXT','NOT NULL','Destination bank account token'),
    ('net_amount_cents','BIGINT','NOT NULL','Reported net payout in cents'),
    ('currency','TEXT','NOT NULL','USD'),
    ('status','TEXT','NOT NULL','paid or in_transit'),
    ('settlement_date','DATE','NOT NULL','Date settlement was assembled'),
    ('expected_arrival','DATE','NOT NULL','Expected bank value date'),
    ('bank_reference','TEXT','NOT NULL','Processor-provided payout reference')] + common)
define('payout_items', 'Processor-supplied membership; one signed event contributes to one payout.', [
    ('payout_item_id','TEXT','PK','Membership row identifier'),
    ('payout_id','TEXT','NOT NULL','Reference to processor_payouts'),
    ('txn_id','TEXT','NOT NULL','Reference to processor_transactions'),
    ('signed_contribution_cents','BIGINT','NOT NULL','Signed event contribution; do not deduct fees again')] + common)
define('bank_transactions', 'Observed bank movements; includes unrelated credits and fees.', [
    ('bank_txn_id','TEXT','PK','Stable bank transaction identifier'),
    ('account_id','TEXT','NOT NULL','Reference to bank_accounts'),
    ('value_date','DATE','NOT NULL','Bank value date'),
    ('amount_cents','BIGINT','NOT NULL','Credit positive; debit negative'),
    ('currency','TEXT','NOT NULL','USD'),
    ('status','TEXT','NOT NULL','posted'),
    ('reference','TEXT','','Bank-supplied reference; can be blank'),
    ('memo','TEXT','NOT NULL','Bank description')] + common)
define('ledger_journals', 'One posted journal header; references bank movement where applicable.', [
    ('journal_id','TEXT','PK','Journal identifier'),
    ('posting_date','DATE','NOT NULL','Accounting posting date'),
    ('status','TEXT','NOT NULL','posted'),
    ('reference','TEXT','NOT NULL','Source event or bank transaction identifier'),
    ('currency','TEXT','NOT NULL','USD')] + common)
define('ledger_entries', 'One debit or credit line; every supplied journal balances.', [
    ('line_id','TEXT','PK','Journal line identifier'),
    ('journal_id','TEXT','NOT NULL','Reference to ledger_journals'),
    ('account_code','TEXT','NOT NULL','Reference to chart_of_accounts'),
    ('debit_cents','BIGINT','NOT NULL','Nonnegative debit amount'),
    ('credit_cents','BIGINT','NOT NULL','Nonnegative credit amount')] + common)

def source(system, when):
    return dict(source_system=system, batch_id=f'BATCH-{system}-001', source_created_at=when)

for i in range(1,2501):
    add('customers',customer_id=f'CUST-{i:05}',created_at='2026-09-01T00:00:00Z')
add('bank_accounts',account_id='BANK-ACCT-01',merchant_id='NOVA-001',currency='USD')
for code,name in [('1000','Bank cash'),('1100','Processor clearing'),('1200','Processor reserve'),
                  ('4000','Sales'),('4010','Refunds'),('6100','Processing fees'),('6200','Chargebacks'),
                  ('6300','Bank fees'),('2990','Unclassified bank credits')]:
    add('chart_of_accounts',account_code=code,account_name=name)
for i,role in enumerate(['reviewer','approver'],1):
    add('users',user_id=f'USER-{i:02}',display_name=f'Demo {role}',role=role)

truth = []
links = []
scenarios = []

def expected(stage, entity, status, reason, expected_amount=None, actual_amount=None, candidates='', split='development'):
    truth.append(dict(check_id=f'CHECK-{len(truth)+1:06}',stage=stage,entity_id=entity,
        expected_status=status,reason=reason,expected_amount_cents=expected_amount,
        actual_amount_cents=actual_amount,variance_cents=None if expected_amount is None or actual_amount is None else actual_amount-expected_amount,
        candidate_ids=candidates,evaluation_split=split))

def split_for(day):
    return 'holdout' if day >= START+timedelta(days=48) else 'development'

event_payout = {}
by_payout = defaultdict(list)
captures = []
order_captures = defaultdict(list)

def event(kind, amount, day, slot, order='', related='', authorized=None):
    tx=f'TXN-{len(tables["processor_transactions"])+1:07}'
    row=add('processor_transactions',txn_id=tx,order_id=order,related_txn_id=related,type=kind,
        amount_cents=amount,authorized_amount_cents=authorized,currency='USD',
        status='authorized' if kind=='authorization' else 'succeeded',processed_at=stamp(day,10+slot),
        **source('processor',stamp(day,10+slot)))
    if kind!='authorization':
        payout=f'PO-{(day-START).days*2+slot+1:04}'
        by_payout[payout].append(row)
        event_payout[tx]=payout
    return row

for i in range(1,10001):
    day=START+timedelta(days=(i-1)%60)
    slot=(i//60)%2
    oid=f'ORD-{i:06}'
    amount=rng.randrange(1500,85001)
    status='paid' if i<=9800 else 'unpaid' if i<=9900 else 'authorized' if i<=9950 else 'cancelled'
    if 201<=i<=250: status='partially_paid'
    add('orders',order_id=oid,customer_id=f'CUST-{rng.randrange(1,2501):05}',order_amount_cents=amount,
        currency='USD',status=status,ordered_at=stamp(day,8),**source('storefront',stamp(day,8)))
    captured=0
    if i<=9800 and not 251<=i<=300:
        amounts=[amount//2,amount-amount//2] if i<=200 else [amount//2] if i<=250 else [amount]
        for value in amounts:
            c=event('capture',value,day,slot,oid)
            captures.append(c)
            order_captures[oid].append(c)
            fee=(value*29+500)//1000+30
            event('fee',-fee,day,slot,oid,c['txn_id'])
            captured+=value
            links.append(dict(stage='order_to_payment',left_id=oid,right_id=c['txn_id'],allocation_cents=value))
    elif status=='authorized':
        event('authorization',0,day,slot,oid,authorized=amount)
    if 251<=i<=300:
        outcome,reason='exception','paid_order_missing_capture'
    elif status=='partially_paid':
        outcome,reason='partial','legitimate_partial_capture'
    elif status in ('unpaid','authorized','cancelled'):
        outcome,reason='not_eligible',f'{status}_order'
    else:
        outcome,reason='reconciled','split_capture' if i<=200 else 'exact_capture'
    expected('order_to_payment',oid,outcome,reason,amount,captured,
             ';'.join(x['txn_id'] for x in order_captures[oid]),split_for(day))

eligible=[c for c in captures if (date.fromisoformat(c['processed_at'][:10])-START).days<=43]
rng.shuffle(eligible)
for i,c in enumerate(eligible[:600]):
    original_day=date.fromisoformat(c['processed_at'][:10])
    day=original_day+timedelta(days=rng.randrange(1,16))
    kind='refund' if i<500 else 'chargeback'
    amount=c['amount_cents'] if kind=='chargeback' or i%2==0 else c['amount_cents']//2
    event(kind,-amount,day,i%2,c['order_id'],c['txn_id'])
for i in range(20):
    day=START+timedelta(days=i*2)
    hold=event('reserve_hold',-10000,day,0)
    event('reserve_release',10000,day+timedelta(days=10),1,related=hold['txn_id'])

def journal(reference, day, debit_account, credit_account, amount):
    jid=f'JRN-{len(tables["ledger_journals"])+1:07}'
    add('ledger_journals',journal_id=jid,posting_date=str(day),status='posted',reference=reference,
        currency='USD',**source('ledger',stamp(day,15)))
    for side,account in [('debit',debit_account),('credit',credit_account)]:
        add('ledger_entries',line_id=f'{jid}-{1 if side=="debit" else 2}',journal_id=jid,account_code=account,
            debit_cents=amount if side=='debit' else 0,credit_cents=amount if side=='credit' else 0,
            **source('ledger',stamp(day,15)))
    return jid

accounts={'capture':('1100','4000'),'fee':('6100','1100'),'refund':('4010','1100'),
          'chargeback':('6200','1100'),'reserve_hold':('1200','1100'),'reserve_release':('1100','1200')}
for tx in tables['processor_transactions']:
    if tx['type']!='authorization':
        debit,credit=accounts[tx['type']]
        journal(tx['txn_id'],date.fromisoformat(tx['processed_at'][:10]),debit,credit,abs(tx['amount_cents']))

anomalies={}
names=['bank_short_payment','missing_bank_deposit','ambiguous_bank_credit','missing_bank_reference',
       'missing_ledger_journal','incorrect_ledger_amount','missing_payout_item','incorrect_payout_header']
for cycle,offset in enumerate([10,98]):
    for n,name in enumerate(names): anomalies[offset+n]=name
omitted=[]

def bank(day, amount, reference, memo='Processor settlement'):
    bid=f'BTX-{len(tables["bank_transactions"])+1:05}'
    return add('bank_transactions',bank_txn_id=bid,account_id='BANK-ACCT-01',value_date=str(day),
        amount_cents=amount,currency='USD',status='posted',reference=reference,memo=memo,
        **source('bank',stamp(day,13)))

for n in range(1,121):
    pid=f'PO-{n:04}'
    day=START+timedelta(days=(n-1)//2)
    arrival=business_add(day,2)
    due=business_add(arrival,2) # Grace policy counts weekdays, not bank holidays.
    evs=by_payout[pid]
    true_total=sum(x['amount_cents'] for x in evs)
    assert true_total>0
    issue=anomalies.get(n,'normal')
    pending=arrival>ASOF
    if pending: issue='pending_settlement'
    header=true_total+(2000 if issue=='incorrect_payout_header' else 0)
    add('processor_payouts',payout_id=pid,bank_account_id='BANK-ACCT-01',net_amount_cents=header,
        currency='USD',status='in_transit' if pending else 'paid',settlement_date=str(day),
        expected_arrival=str(arrival),bank_reference=pid,**source('processor',stamp(day,18)))
    dropped=next((x for x in evs if x['type']=='fee'),None) if issue=='missing_payout_item' else None
    item_sum=0
    for tx in evs:
        item=dict(payout_item_id=f'PI-{tx["txn_id"][4:]}',payout_id=pid,txn_id=tx['txn_id'],
            signed_contribution_cents=tx['amount_cents'],**source('processor',stamp(day,18)))
        if tx is dropped:
            omitted.append(item)
            continue
        add('payout_items',**item)
        item_sum+=tx['amount_cents']
        links.append(dict(stage='payment_to_payout',left_id=tx['txn_id'],right_id=pid,allocation_cents=tx['amount_cents']))
    expected('payment_to_payout',pid,'exception' if item_sum!=header else 'reconciled',
        issue if item_sum!=header else 'signed_items_equal_header',header,item_sum,split=split_for(day))
    bids=[]
    bank_total=None
    if not pending and issue!='missing_bank_deposit':
        amount=true_total-(2000 if issue=='bank_short_payment' else 0)
        ref='' if issue in ('ambiguous_bank_credit','missing_bank_reference') else pid
        b=bank(arrival,amount,ref)
        bids.append(b['bank_txn_id'])
        bank_total=amount
        links.append(dict(stage='payout_to_bank',left_id=pid,right_id=b['bank_txn_id'],allocation_cents=amount))
        if issue=='ambiguous_bank_credit':
            extra=bank(arrival,amount,'',memo='Incoming credit')
            bids.append(extra['bank_txn_id'])
            j=journal(extra['bank_txn_id'],arrival,'1000','2990',amount)
            expected('bank_to_ledger',extra['bank_txn_id'],'reconciled','unrelated_credit_recorded',amount,amount,j,split_for(day))
        if issue=='missing_ledger_journal':
            expected('bank_to_ledger',b['bank_txn_id'],'exception',issue,amount,0,split=split_for(day))
        else:
            ledger_amount=amount+(1500 if issue=='incorrect_ledger_amount' else 0)
            jid=journal(b['bank_txn_id'],arrival,'1000','1100',ledger_amount)
            expected('bank_to_ledger',b['bank_txn_id'],'exception' if ledger_amount!=amount else 'reconciled',
                issue if ledger_amount!=amount else 'cash_line_matches_bank',amount,ledger_amount,jid,split_for(day))
            links.append(dict(stage='bank_to_ledger',left_id=b['bank_txn_id'],right_id=jid,allocation_cents=ledger_amount))
    if pending:
        status,reason='pending','not_yet_due'
    elif not bids:
        status,reason=('exception','missing_bank_deposit') if ASOF>due else ('pending','within_arrival_grace')
    elif issue=='ambiguous_bank_credit': status,reason='review',issue
    elif issue=='missing_bank_reference': status,reason='review',issue
    elif bank_total!=header: status,reason='exception',issue
    else: status,reason='reconciled','reference_account_currency_amount'
    expected('payout_to_bank',pid,status,reason,header,bank_total,';'.join(bids),split_for(day))
    scenarios.append(dict(scenario_id=f'SCN-{n:04}',payout_id=pid,scenario_type=issue,
        settlement_date=str(day),arrival_deadline=str(due),evaluation_split=split_for(day),
        true_payout_cents=true_total,reported_payout_cents=header,
        bank_candidate_ids=';'.join(bids),withheld_item_id=dropped['txn_id'] if dropped else ''))

for day,amount,reference in [(START+timedelta(days=20),-2500,'BANK-FEE-01'),
                            (START+timedelta(days=40),50000,'OTHER-CREDIT-01')]:
    b=bank(day,amount,reference,memo='Account fee' if amount<0 else 'Other incoming transfer')
    jid=journal(b['bank_txn_id'],day,'6300' if amount<0 else '1000','1000' if amount<0 else '2990',abs(amount))
    expected('bank_to_ledger',b['bank_txn_id'],'reconciled','bank_only_movement_recorded',amount,amount,jid)

# Runtime outputs start empty. Expected answers are isolated in evaluation/.
runtime={
 'reconciliation_runs':[('run_id','TEXT','PK','Run identifier'),('started_at','TIMESTAMPTZ','NOT NULL','Run start'),('as_of_date','DATE','NOT NULL','Evaluation cutoff'),('status','TEXT','NOT NULL','Run state'),('rule_version','TEXT','NOT NULL','Rule set version')],
 'match_groups':[('match_id','TEXT','PK','Reconciliation group'),('run_id','TEXT','NOT NULL','Reference to reconciliation_runs'),('stage','TEXT','NOT NULL','Reconciliation stage'),('rule_id','TEXT','NOT NULL','Rule identifier'),('rule_version','TEXT','NOT NULL','Rule version'),('status','TEXT','NOT NULL','Group status'),('currency','TEXT','NOT NULL','Group currency'),('variance_cents','BIGINT','','Actual less expected'),('created_at','TIMESTAMPTZ','NOT NULL','Creation time')],
 'match_members':[('member_id','TEXT','PK','Member identifier'),('match_id','TEXT','NOT NULL','Reference to match_groups'),('source_type','TEXT','NOT NULL','Source table'),('source_id','TEXT','NOT NULL','Source record identifier'),('role','TEXT','NOT NULL','expected or actual'),('allocation_cents','BIGINT','NOT NULL','Signed allocated amount')],
 'exceptions':[('exception_id','TEXT','PK','Case identifier'),('match_id','TEXT','','Optional match group'),('dedupe_key','TEXT','NOT NULL','Unique stable stage/entity/type case key'),('type','TEXT','NOT NULL','Exception classification'),('amount_cents','BIGINT','','Signed variance when quantifiable'),('currency','TEXT','NOT NULL','Case currency'),('status','TEXT','NOT NULL','Workflow state'),('assigned_to','TEXT','','Reference to users'),('opened_at','TIMESTAMPTZ','NOT NULL','Creation time')],
 'case_history':[('event_id','TEXT','PK','Audit event identifier'),('exception_id','TEXT','NOT NULL','Reference to exceptions'),('actor','TEXT','NOT NULL','User or system actor'),('action','TEXT','NOT NULL','Recorded action'),('timestamp','TIMESTAMPTZ','NOT NULL','Event time'),('note','TEXT','','Reviewer explanation')],
 'evidence_links':[('evidence_id','TEXT','PK','Evidence identifier'),('exception_id','TEXT','NOT NULL','Reference to exceptions'),('source_path','TEXT','NOT NULL','Relative immutable file location'),('source_record_id','TEXT','','Identifier inside evidence'),('added_at','TIMESTAMPTZ','NOT NULL','Evidence attachment time')]
}
for name,cols in runtime.items(): define(name,'Empty application output template; populate from your engine.',cols)

define('ingestion_batches','Completed synthetic export metadata; application import state is separate.',[
    ('batch_id','TEXT','PK','Logical source export batch'),('source','TEXT','NOT NULL','Source namespace'),
    ('exported_at','TIMESTAMPTZ','NOT NULL','Synthetic export cutoff'),('state','TEXT','NOT NULL','export_ready; not imported into an application')])
for system in ['storefront','processor','bank','ledger']:
    add('ingestion_batches',batch_id=f'BATCH-{system}-001',source=system,exported_at='2026-11-05T23:59:59Z',state='export_ready')

def write_csv(path, rows, fields=None):
    path.parent.mkdir(parents=True,exist_ok=True)
    fields=fields or list(rows[0])
    with path.open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

for name,rows in tables.items():
    folder='runtime_templates' if name in runtime else 'source'
    write_csv(OUT/folder/f'{name}.csv',rows,[c[0] for c in schemas[name]])
write_csv(OUT/'evaluation/expected_checks.csv',truth)
write_csv(OUT/'evaluation/true_links.csv',links)
write_csv(OUT/'evaluation/scenario_catalog.csv',scenarios)
write_csv(OUT/'fixtures/replay/processor_transactions_replay.csv',tables['processor_transactions'][:100])
write_csv(OUT/'fixtures/late_evidence/missing_payout_items.csv',omitted,[c[0] for c in schemas['payout_items']])
bad=[]
for i,(field,value,reason) in enumerate([('currency','EUR','unsupported_currency'),('txn_id','','missing_identifier'),('amount_cents','not_a_number','invalid_integer'),('status','unknown','invalid_status')]):
    row=dict(tables['processor_transactions'][i])
    row['txn_id']=f'INVALID-{i+1}'
    row[field]=value
    bad.append(row)
write_csv(OUT/'fixtures/invalid/processor_transactions_invalid.csv',bad)
write_csv(OUT/'evaluation/fixture_expectations.csv',[
    dict(fixture='fixtures/replay/processor_transactions_replay.csv',expected_action='deduplicate',expected_count=100,note='Import after source file; zero new canonical events'),
    dict(fixture='fixtures/invalid/processor_transactions_invalid.csv',expected_action='quarantine',expected_count=4,note='One invalid field per row; do not import into canonical tables'),
    dict(fixture='fixtures/late_evidence/missing_payout_items.csv',expected_action='controlled_amendment',expected_count=2,note='After baseline evaluation, add missing membership rows and rerun; retain case history')])

dictionary=[]
for name,cols in schemas.items():
    for field,typ,requirement,meaning in cols:
        dictionary.append(dict(table=name,column=field,data_type=typ,requirement=requirement or 'nullable',description=meaning))
write_csv(OUT/'documentation/data_dictionary.csv',dictionary)

fks={
 'orders':[('customer_id','customers','customer_id')],
 'processor_transactions':[('order_id','orders','order_id'),('related_txn_id','processor_transactions','txn_id')],
 'processor_payouts':[('bank_account_id','bank_accounts','account_id')],
 'payout_items':[('payout_id','processor_payouts','payout_id'),('txn_id','processor_transactions','txn_id')],
 'bank_transactions':[('account_id','bank_accounts','account_id')],
 'ledger_entries':[('journal_id','ledger_journals','journal_id'),('account_code','chart_of_accounts','account_code')],
 'match_groups':[('run_id','reconciliation_runs','run_id')],
 'match_members':[('match_id','match_groups','match_id')],
 'exceptions':[('match_id','match_groups','match_id'),('assigned_to','users','user_id')],
 'case_history':[('exception_id','exceptions','exception_id')],
 'evidence_links':[('exception_id','exceptions','exception_id')]}
ddl=[]
for name,cols in schemas.items():
    lines=[f'    {field} {typ} '+('PRIMARY KEY' if req=='PK' else req) for field,typ,req,_ in cols]
    for field,target,key in fks.get(name,[]):
        lines.append(f'    FOREIGN KEY ({field}) REFERENCES {target} ({key})')
    for field,_,_,_ in cols:
        if field=='batch_id' and name!='ingestion_batches':
            lines.append(f'    FOREIGN KEY (batch_id) REFERENCES ingestion_batches (batch_id)')
    if name=='payout_items': lines.append('    UNIQUE (txn_id)')
    if name=='exceptions': lines.append('    UNIQUE (dedupe_key)')
    if name=='ledger_entries':
        lines.append('    CHECK (debit_cents >= 0 AND credit_cents >= 0 AND ((debit_cents > 0 AND credit_cents = 0) OR (credit_cents > 0 AND debit_cents = 0)))')
    ddl.append('CREATE TABLE '+name+' (\n'+',\n'.join(lines)+'\n);')
# Metadata must exist before referencing it in PostgreSQL.
ddl=[ddl[-1]]+ddl[:-1]
(OUT/'documentation/schema.sql').write_text('-- PostgreSQL starting schema. Blank optional CSV fields load as NULL.\n\n'+'\n\n'.join(ddl)+'\n',encoding='utf-8')
load_order=['ingestion_batches','customers','bank_accounts','chart_of_accounts','users','orders','processor_transactions','processor_payouts','payout_items','bank_transactions','ledger_journals','ledger_entries']
sql=['-- Run psql from the datasets directory after creating tables with documentation/schema.sql.']
for name in load_order:
    sql.append(f"\\copy {name} FROM 'source/{name}.csv' WITH (FORMAT csv, HEADER true, NULL '')")
(OUT/'documentation/load_source.psql').write_text('\n'.join(sql)+'\n',encoding='utf-8')

rules=dict(as_of_date=str(ASOF),currency='USD',money_unit='integer_cents',seed=SEED,
    settlement_lag_weekdays=2,arrival_grace_weekdays=2,holidays_modeled=False,amount_tolerance_cents=0,
    auto_match_requires=['stable reference','same account','same currency','exact amount','unique eligible candidate','compatible status'],
    bank_candidate_date_window_weekdays=2,missing_reference_policy='review_even_if_unique_amount_date_candidate',
    order_capture_policy='sum succeeded captures only; exclude authorizations and later refunds',
    item_sign_policy='capture/reserve_release positive; fee/refund/chargeback/reserve_hold negative',
    split_policy='payout settlement days 1-48 development, 49-60 holdout; order split by order day; linked records may span splits',
    snapshot_policy='No bank records later than as_of_date. Future expected arrivals are pending.',
    stage_policy='Evaluate each stage independently. A clean bank link does not resolve an upstream payout composition failure.')
(OUT/'documentation/rules.json').write_text(json.dumps(rules,indent=2)+'\n')

# Independent validation against CSV round trips and SQL-loaded tables.
checks=[]
def check(label, condition):
    checks.append(dict(check=label,passed=bool(condition)))
    if not condition: raise AssertionError(label)

conn=sqlite3.connect(':memory:')
conn.execute('PRAGMA foreign_keys=ON')
conn.executescript('\n'.join(ddl))
for name in load_order:
    with (OUT/'source'/f'{name}.csv').open(newline='') as f: rows=list(csv.DictReader(f))
    check(f'{name}: CSV row count',len(rows)==len(tables[name]))
    for row in rows:
        values=[]
        for field,typ,req,_ in schemas[name]:
            v=row[field]
            values.append(None if v=='' else int(v) if typ=='BIGINT' else v)
        conn.execute(f'INSERT INTO {name} VALUES ({",".join("?" for _ in values)})',values)
check('Source foreign keys valid',not conn.execute('PRAGMA foreign_key_check').fetchall())
check('Every journal balances',not conn.execute('SELECT journal_id FROM ledger_entries GROUP BY journal_id HAVING SUM(debit_cents) != SUM(credit_cents)').fetchall())
check('No future bank records',all(x['value_date']<=str(ASOF) for x in tables['bank_transactions']))
check('All source timestamps precede export cutoff',all(row['source_created_at']<='2026-11-05T23:59:59Z' for rows in tables.values() for row in rows if 'source_created_at' in row))
check('Each event is assigned at most once',len({x['txn_id'] for x in tables['payout_items']})==len(tables['payout_items']))
check('Only two intentional missing membership rows',len(tables['payout_items'])+len(omitted)==sum(x['type']!='authorization' for x in tables['processor_transactions']))
check('Replay IDs already exist',all(x['txn_id'] in event_payout for x in tables['processor_transactions'][:100]))
check('Holdout includes each anomaly class',set(names)<=set(x['scenario_type'] for x in scenarios if x['evaluation_split']=='holdout'))
tx_index={x['txn_id']:x for x in tables['processor_transactions']}
check('Membership contributions equal source event amounts',all(x['signed_contribution_cents']==tx_index[x['txn_id']]['amount_cents'] for x in tables['payout_items']))
check('All adjustments occur after related events',all(x['processed_at']>=tx_index[x['related_txn_id']]['processed_at'] for x in tables['processor_transactions'] if x['related_txn_id']))
check('Refunds and chargebacks do not exceed original capture',all(abs(x['amount_cents'])<=tx_index[x['related_txn_id']]['amount_cents'] for x in tables['processor_transactions'] if x['type'] in ('refund','chargeback')))
for row in truth:
    stage=row['stage']; key=row['entity_id']
    if stage=='order_to_payment':
        actual=conn.execute("SELECT COALESCE(SUM(amount_cents),0) FROM processor_transactions WHERE order_id=? AND type='capture' AND status='succeeded'",(key,)).fetchone()[0]
    elif stage=='payment_to_payout':
        actual=conn.execute('SELECT SUM(signed_contribution_cents) FROM payout_items WHERE payout_id=?',(key,)).fetchone()[0]
    elif stage=='bank_to_ledger':
        actual=conn.execute("SELECT COALESCE(SUM(e.debit_cents-e.credit_cents),0) FROM ledger_journals j JOIN ledger_entries e ON e.journal_id=j.journal_id WHERE j.reference=? AND e.account_code='1000'",(key,)).fetchone()[0]
    else:
        candidates=row['candidate_ids'].split(';') if row['candidate_ids'] else []
        actual=conn.execute('SELECT amount_cents FROM bank_transactions WHERE bank_txn_id=?',(candidates[0],)).fetchone()[0] if candidates else None
    if actual!=row['actual_amount_cents']: raise AssertionError((row,actual))
check('All expected amounts independently recomputed from imported CSVs',True)
totals=Counter((x['stage'],x['expected_status']) for x in truth)
report=dict(seed=SEED,as_of_date=str(ASOF),validation_engine='SQLite load of supplied schema and CSV files; PostgreSQL itself not executed',
    checks=checks,all_passed=all(x['passed'] for x in checks),
    source_row_counts={name:len(tables[name]) for name in load_order},
    expected_results={f'{stage}/{status}':count for (stage,status),count in sorted(totals.items())})
(OUT/'documentation/validation_report.json').write_text(json.dumps(report,indent=2)+'\n')

readme=f'''# Synthetic transaction reconciliation datasets

Start with `source/`. These are fictional, standardized source exports for NovaCommerce, not real provider exports or customer records.

## Scope

- Seed: {SEED}. Synthetic snapshot: {ASOF} at 23:59:59 UTC; processor event dates {START} through {START+timedelta(days=59)}.
- One merchant, one processor, one bank account, one illustrative ledger; USD only.
- 10,000 orders; {len(tables['processor_transactions']):,} processor events; 120 payouts.
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
'''
for name in load_order:
    readme+=f'| {name}.csv | {len(tables[name]):,} | {descriptions[name]} |\n'
readme+='''
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
'''
(OUT/'README.md').write_text(readme,encoding='utf-8')
(OUT/'documentation/data_model.md').write_text('''# Data model

```mermaid
erDiagram
    customers ||--o{ orders : places
    orders ||--o{ processor_transactions : has
    processor_transactions ||--o| payout_items : contributes
    processor_payouts ||--o{ payout_items : contains
    bank_accounts ||--o{ processor_payouts : receives
    bank_accounts ||--o{ bank_transactions : records
    ledger_journals ||--|{ ledger_entries : contains
    chart_of_accounts ||--o{ ledger_entries : classifies
    reconciliation_runs ||--o{ match_groups : produces
    match_groups ||--o{ match_members : includes
    match_groups |o--o{ exceptions : raises
    exceptions ||--o{ case_history : records
    exceptions ||--o{ evidence_links : supports
```

Source ownership: storefront supplies orders; processor supplies events, payout headers, and payout membership; bank supplies movements; ledger supplies journals and lines. Source namespace plus identifier defines external identity. This V1 has one source instance of each kind.

Payout-to-bank is inferred by the engine, not stored as a source foreign key. Journal reference identifies the processor event or bank movement recorded; use match groups to record validated links. Payment fees are separate events. Captures can be split across an order; refunds retain their original capture reference and settle in a later payout.

Match member role distinguishes expected and actual sides. Stage lives on the group. A source amount may participate across stages but must not be overallocated within the same stage and side. Polymorphic source links need explicit validation in your engine. The supplied SQL is a starting schema, not a complete production control implementation.
''',encoding='utf-8')

manifest=[]
for p in sorted(OUT.rglob('*')):
    if p.is_file() and p.name!='manifest.json':
        entry=dict(path=p.relative_to(OUT).as_posix(),bytes=p.stat().st_size,sha256=hashlib.sha256(p.read_bytes()).hexdigest())
        if p.suffix=='.csv':
            with p.open(newline='') as f: entry['rows']=sum(1 for _ in csv.reader(f))-1
        manifest.append(entry)
(OUT/'manifest.json').write_text(json.dumps(dict(dataset_version='1.0.0',seed=SEED,files=manifest),indent=2)+'\n')
archive=ROOT/'transaction_reconciliation_datasets.zip'
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
    for p in sorted(OUT.rglob('*')):
        if p.is_file(): z.write(p,Path('datasets')/p.relative_to(OUT))
print(json.dumps(dict(archive=str(archive),source_rows=report['source_row_counts'],checks_passed=len(checks),expected_results=report['expected_results']),indent=2))
