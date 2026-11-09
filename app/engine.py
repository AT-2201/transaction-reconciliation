"""Deterministic matching. This module never reads evaluation labels."""
import hashlib
import json
from collections import Counter, defaultdict
from datetime import date, timedelta
from .db import connect, now, uid, rows, audit

RULE_VERSION='1.0.0'
STAGES=['order_to_payment','payment_to_payout','payout_to_bank','bank_to_ledger']


def weekday_add(day,n):
    direction=1 if n>=0 else -1
    for _ in range(abs(n)):
        day+=timedelta(days=direction)
        while day.weekday()>4: day+=timedelta(days=direction)
    return day


def run(as_of='2026-11-05'):
    cutoff=date.fromisoformat(as_of)
    rid=uid('RUN')
    with connect(write=True) as c:
        fingerprint=hashlib.sha256('\n'.join(x['checksum'] for x in rows(c,'SELECT checksum FROM imports WHERE inserted>0 ORDER BY id')).encode()).hexdigest()
        c.execute('INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?)',(rid,now(),None,as_of,'running',RULE_VERSION,fingerprint,None,None))
    try:
        with connect(write=True) as c:
            # Stable snapshots under the same write transaction as results and case refreshes.
            tx=rows(c,'SELECT * FROM processor_transactions WHERE substr(processed_at,1,10)<=?',(as_of,))
            tx_index={x['txn_id']:x for x in tx}
            by_order=defaultdict(list)
            for t in tx:
                if t['type']=='capture' and t['status']=='succeeded': by_order[t['order_id']].append(t)
            items=defaultdict(list)
            for x in rows(c,'SELECT * FROM payout_items'):
                if x['txn_id'] in tx_index: items[x['payout_id']].append(x)
            banks=rows(c,"SELECT * FROM bank_transactions WHERE value_date<=? AND status='posted'",(as_of,))
            journal_groups=defaultdict(list)
            for j in rows(c,"SELECT j.*,SUM(CASE WHEN e.account_code='1000' THEN e.debit_cents-e.credit_cents ELSE 0 END) AS cash_cents, SUM(e.debit_cents-e.credit_cents) AS balance FROM ledger_journals j JOIN ledger_entries e ON e.journal_id=j.journal_id WHERE j.posting_date<=? AND j.status='posted' GROUP BY j.journal_id",(as_of,)):
                journal_groups[j['reference']].append(j)
            findings=[]
            used_bank=set()
            manual_bank_owners={r['bank_txn_id']:r['entity_id'] for r in rows(c,
                'SELECT d.bank_txn_id,x.entity_id FROM decisions d JOIN cases x ON x.id=d.case_id WHERE d.bank_txn_id IS NOT NULL AND d.active=1')}

            def emit(stage,entity,status,reason,expected=None,actual=None,candidates=None,members=None):
                cid=uid('CHK')
                variance=None if expected is None or actual is None else actual-expected
                candidates=candidates or []
                c.execute('INSERT INTO checks VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                    (cid,rid,stage,entity,status,reason,expected,actual,variance,'USD',json.dumps(candidates),f'{stage}/v1'))
                for table,key,side,amount in members or []:
                    c.execute('INSERT INTO allocations VALUES (?,?,?,?,?,?)',(uid('ALLOC'),cid,table,key,side,amount))
                findings.append(dict(id=cid,stage=stage,entity_id=entity,status=status,reason=reason,variance=variance))

            for o in rows(c,'SELECT * FROM orders WHERE substr(ordered_at,1,10)<=? ORDER BY order_id',(as_of,)):
                captures=[t for t in by_order[o['order_id']] if t['currency']==o['currency']]
                total=sum(t['amount_cents'] for t in captures)
                if o['status'] in ('cancelled','authorized','unpaid'):
                    status,reason=('exception','unexpected_capture') if total else ('not_eligible',f'{o["status"]}_order')
                elif total==o['order_amount_cents']:
                    status,reason='reconciled','split_capture' if len(captures)>1 else 'exact_capture'
                elif 0<total<o['order_amount_cents'] and o['status']=='partially_paid':
                    status,reason='partial','legitimate_partial_capture'
                else: status,reason='exception','paid_order_missing_capture' if not total else 'order_amount_mismatch'
                emit('order_to_payment',o['order_id'],status,reason,o['order_amount_cents'],total,
                     [t['txn_id'] for t in captures],
                     [('orders',o['order_id'],'expected',o['order_amount_cents'])]+[('processor_transactions',t['txn_id'],'actual',t['amount_cents']) for t in captures])

            for p in rows(c,'SELECT * FROM processor_payouts WHERE settlement_date<=? ORDER BY payout_id',(as_of,)):
                pi=items[p['payout_id']]
                total=sum(x['signed_contribution_cents'] for x in pi)
                valid=all(x['signed_contribution_cents']==tx_index[x['txn_id']]['amount_cents'] and tx_index[x['txn_id']]['currency']==p['currency'] for x in pi)
                status='reconciled' if valid and total==p['net_amount_cents'] else 'exception'
                emit('payment_to_payout',p['payout_id'],status,'signed_items_equal_header' if status=='reconciled' else 'payout_composition_mismatch',
                    p['net_amount_cents'],total,[x['txn_id'] for x in pi],
                    [('processor_payouts',p['payout_id'],'expected',p['net_amount_cents'])]+[('processor_transactions',x['txn_id'],'actual',x['signed_contribution_cents']) for x in pi])
                arrival=date.fromisoformat(p['expected_arrival'])
                lower,upper=str(weekday_add(arrival,-2)),str(weekday_add(arrival,2))
                eligible=[b for b in banks if b['account_id']==p['bank_account_id'] and b['currency']==p['currency'] and lower<=b['value_date']<=upper]
                exact=[b for b in eligible if b['reference']==p['bank_reference']]
                # An amount is a candidate only when no conflicting reference is present.
                candidates=exact or [b for b in eligible if not b['reference'] and b['amount_cents']==p['net_amount_cents']]
                actual=candidates[0]['amount_cents'] if candidates else None
                if p['status']=='in_transit':
                    status,reason=('exception','overdue_in_transit') if cutoff>weekday_add(arrival,2) else ('pending','not_yet_due' if arrival>cutoff else 'processor_in_transit')
                elif arrival>cutoff and not candidates:
                    status,reason='pending','not_yet_due'
                elif not candidates:
                    status,reason=('exception','missing_bank_deposit') if cutoff>weekday_add(arrival,2) else ('pending','within_arrival_grace')
                elif len(candidates)>1:
                    status,reason='review','ambiguous_bank_credit'
                elif candidates[0]['bank_txn_id'] in used_bank or manual_bank_owners.get(candidates[0]['bank_txn_id'],p['payout_id'])!=p['payout_id']:
                    status,reason='review','bank_amount_already_allocated'
                elif actual!=p['net_amount_cents']:
                    status,reason='exception','payout_bank_amount_mismatch'
                elif not exact:
                    status,reason='review','missing_bank_reference'
                else:
                    status,reason='reconciled','reference_account_currency_amount'
                    used_bank.add(candidates[0]['bank_txn_id'])
                members=[('processor_payouts',p['payout_id'],'expected',p['net_amount_cents'])]
                if len(candidates)==1:
                    members.append(('bank_transactions',candidates[0]['bank_txn_id'],'actual',actual))
                emit('payout_to_bank',p['payout_id'],status,reason,p['net_amount_cents'],actual,
                     [b['bank_txn_id'] for b in candidates],members)

            for b in banks:
                js=[j for j in journal_groups[b['bank_txn_id']] if j['currency']==b['currency']]
                amount=sum(j['cash_cents'] for j in js)
                good=amount==b['amount_cents'] and all(j['balance']==0 for j in js)
                emit('bank_to_ledger',b['bank_txn_id'],'reconciled' if good else 'exception',
                    'cash_line_matches_bank' if good else 'missing_ledger_journal' if not js else 'ledger_cash_mismatch',
                    b['amount_cents'],amount,[j['journal_id'] for j in js],
                    [('bank_transactions',b['bank_txn_id'],'expected',b['amount_cents'])]+[('ledger_journals',j['journal_id'],'actual',j['cash_cents']) for j in js])

            for f in findings:
                case=c.execute('SELECT * FROM cases WHERE stage=? AND entity_id=?',(f['stage'],f['entity_id'])).fetchone()
                active=f['status'] in ('exception','review')
                if active and not case:
                    caseid='CASE-'+hashlib.sha256(f'{f["stage"]}:{f["entity_id"]}'.encode()).hexdigest()[:12].upper()
                    c.execute('INSERT INTO cases (id,stage,entity_id,type,status,opened_at,updated_at,last_check_id) VALUES (?,?,?,?,?,?,?,?)',
                              (caseid,f['stage'],f['entity_id'],f['reason'],'open',now(),now(),f['id']))
                    audit(c,caseid,'system','opened',f['reason'])
                elif case:
                    old=c.execute('SELECT * FROM checks WHERE id=?',(case['last_check_id'],)).fetchone()
                    current=c.execute('SELECT * FROM checks WHERE id=?',(f['id'],)).fetchone()
                    changed=any(old[key]!=current[key] for key in ('status','reason','expected_cents','actual_cents','candidates'))
                    if active and changed and case['status'] in ('resolved','dismissed'):
                        c.execute("UPDATE cases SET status='open',resolution=NULL WHERE id=?",(case['id'],))
                        c.execute('UPDATE decisions SET active=0 WHERE case_id=?',(case['id'],))
                        audit(c,case['id'],'system','reopened','The source finding changed after the previous decision; renewed review required')
                    c.execute('UPDATE cases SET last_check_id=?,finding_active=?,updated_at=?,version=version+1 WHERE id=?',
                              (f['id'],int(active),now(),case['id']))
                    if case['finding_active']!=int(active):
                        audit(c,case['id'],'system','finding_changed','Finding persists' if active else 'Source difference cleared; reviewer closure required')
            summary=dict(Counter(f['status'] for f in findings))
            c.execute('UPDATE runs SET completed_at=?,status=?,summary=? WHERE id=?',(now(),'completed',json.dumps(summary),rid))
        return dict(id=rid,status='completed',summary=summary)
    except Exception as error:
        with connect(write=True) as c:
            c.execute('UPDATE runs SET completed_at=?,status=?,error=? WHERE id=?',(now(),'failed',str(error),rid))
        raise
