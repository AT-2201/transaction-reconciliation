import React from 'react';
import {TransactionTrail, RecordList, amount} from './TransactionTrail';
import {explainCase} from './case-explanation';

export function CaseExplanation({detail}) {
  const explanation = explainCase(detail);
  return <section className="case-explanation" aria-label="Case explanation">
    <h3>{explanation.title}</h3>
    <p>{explanation.summary}</p>
    <p className="explanation-next"><strong>What to check</strong>{explanation.next}</p>
  </section>;
}

export function CaseTrail({detail}) {
  const {check, evidence} = detail;
  const orderStage = check.stage === 'order_to_payment';
  const nodes = orderStage ? [
    {id:'order', title:'Order', value:amount(check.expected_cents), status:'source',
      caption:detail.case.entity_id,
      content:<RecordList rows={(evidence.orders || []).flatMap(row => [
        ['Order', row.order_id], ['Status', row.status], ['Total', amount(row.order_amount_cents)],
        ['Currency', row.currency], ['Ordered', row.ordered_at]
      ])}/>},
    {id:'captures', title:'Payment captures', value:amount(check.actual_cents), status:check.status,
      caption:(check.candidates || []).length + ' captures included in this check',
      content:<RecordList rows={(evidence.processor_transactions || []).filter(row =>
        (check.candidates || []).includes(row.txn_id)).flatMap(row => [
        ['Capture', row.txn_id], ['Amount', amount(row.amount_cents)], ['Currency', row.currency],
        ['Processed', row.processed_at]
      ])}/>}
  ] : [
    {id:'bank', title:'Bank deposit', value:amount(check.expected_cents), status:'source',
      caption:detail.case.entity_id,
      content:<RecordList rows={(evidence.bank_transactions || []).flatMap(row => [
        ['Bank record', row.bank_txn_id], ['Amount', amount(row.amount_cents)],
        ['Currency', row.currency], ['Value date', row.value_date], ['Reference', row.reference || 'Missing reference']
      ])}/>},
    {id:'ledger', title:'Ledger cash postings', value:amount(check.actual_cents), status:check.status,
      caption:(check.candidates || []).length + ' matching journals',
      content:<RecordList rows={(evidence.ledger_entries || []).flatMap(row => [
        ['Journal', row.journal_id], ['Account', row.account_code], ['Debit', amount(row.debit_cents)],
        ['Credit', amount(row.credit_cents)], ['Posting date', row.posting_date]
      ])}/>}
  ];
  return <TransactionTrail nodes={nodes}/>;
}
