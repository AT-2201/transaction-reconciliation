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
    with (db.DATASETS/'evaluation/expected_checks.csv').open() as f: labels=list(csv.DictReader(f))
    mismatches=[]; splits=Counter()
    expected_keys=set()
    for label in labels:
        key=(label['stage'],label['entity_id']); expected_keys.add(key)
        found=actual.get(key)
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
                split_passes=dict(splits),unexpected_checks=len(extras),mismatches=mismatches[:30],
                all_passed=not mismatches and not extras)


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
