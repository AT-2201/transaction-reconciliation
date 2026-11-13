import argparse
import csv
import json
from collections import Counter
from . import db,engine


def evaluate():
    with db.connect() as c:
        latest=c.execute("SELECT id FROM runs WHERE status='completed' ORDER BY started_at DESC LIMIT 1").fetchone()
        if not latest: raise SystemExit('Run reconciliation first')
        actual={(r['stage'],r['entity_id']):dict(r) for r in c.execute('SELECT * FROM checks WHERE run_id=?',(latest['id'],))}
        allocations = {}
        for row in c.execute("""SELECT a.*, ch.stage, ch.entity_id FROM allocations a
            JOIN checks ch ON ch.id=a.check_id
            WHERE ch.run_id=? AND ch.status='reconciled' AND a.side='actual'""", (latest['id'],)):
            allocations.setdefault((row['stage'], row['entity_id']), set()).add((row['source_id'], row['amount_cents']))
    with (db.DATASETS/'evaluation/expected_checks.csv').open() as f: labels=list(csv.DictReader(f))
    links = {}
    with (db.DATASETS/'evaluation/true_links.csv').open() as f:
        for row in csv.DictReader(f):
            left, right = row['left_id'], row['right_id']
            if row['stage']=='payment_to_payout':
                left, right = right, left
            links.setdefault((row['stage'], left), set()).add((right, int(row['allocation_cents'])))
    metrics = {}
    mismatches=[]; splits=Counter()
    expected_keys=set()
    for label in labels:
        key=(label['stage'],label['entity_id']); expected_keys.add(key)
        found=actual.get(key)
        counts = metrics.setdefault(label['evaluation_split'], dict(checks=0, auto_matches=0,
            false_matches=0, link_checks=0, review_findings=0))
        counts['checks'] += 1
        if found and found['status'] in ('exception', 'review'):
            counts['review_findings'] += 1
        if found and found['status']=='reconciled':
            counts['auto_matches'] += 1
            if key in links:
                counts['link_checks'] += 1
            if label['expected_status']!='reconciled' or (key in links and allocations.get(key,set())!=links[key]):
                counts['false_matches'] += 1
        problems=[]
        if not found: problems=['missing check']
        else:
            if found['status']!=label['expected_status']: problems.append('status')
            for field in ['expected_cents','actual_cents','variance_cents']:
                name={'expected_cents':'expected_amount_cents','actual_cents':'actual_amount_cents'}.get(field,field)
                target=int(label[name]) if label[name] else None
                if found[field]!=target: problems.append(field)
        if problems: mismatches.append({'stage':key[0],'entity':key[1],'fields':problems})
        else: splits[label['evaluation_split']]+=1
    extras=set(actual)-expected_keys
    return dict(expected_checks=len(labels),actual_checks=len(actual),passed=len(labels)-len(mismatches),
                split_passes=dict(splits),metrics=metrics,unexpected_checks=len(extras),mismatches=mismatches[:30],
                all_passed=not mismatches and not extras and not any(row['false_matches'] for row in metrics.values()))


def main():
    p=argparse.ArgumentParser(description='Reconciliation project tools')
    p.add_argument('command',choices=['init','seed','run','evaluate'])
    p.add_argument('--as-of',default='2026-11-05')
    args=p.parse_args()
    if args.command=='init': db.initialize(); result={'initialized':True}
    elif args.command=='seed': result=db.seed()
    elif args.command=='run': result=engine.run(args.as_of)
    else: result=evaluate()
    print(json.dumps(result,indent=2))
    if args.command=='evaluate' and not result['all_passed']: raise SystemExit(1)


if __name__=='__main__': main()
