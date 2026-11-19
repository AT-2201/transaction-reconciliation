const money = value => value == null ? 'an unavailable amount' : new Intl.NumberFormat('en-US', {
  style: 'currency', currency: 'USD'
}).format(value / 100);

export function explainCase({check, evidence, case: caseRecord}) {
  const expected = money(check.expected_cents);
  const actual = money(check.actual_cents);
  const gap = check.variance_cents == null ? '' : money(Math.abs(check.variance_cents));
  const comparison = check.expected_cents == null || check.actual_cents == null
    ? 'The run does not contain both amounts needed to calculate a difference.'
    : check.variance_cents === 0
      ? 'The amounts agree, but the matching rule still requires review.'
      : `The observed amount is ${gap} ${check.variance_cents > 0 ? 'higher' : 'lower'} than expected.`;
  const explanations = {
    paid_order_missing_capture: [
      `The order is marked paid for ${expected}, but this run found no matching capture amount in the processor records.`,
      'Check the processor export for the order reference, capture date, and currency.'
    ],
    order_amount_mismatch: [
      `The order total is ${expected} and matching processor captures total ${actual}. ${comparison}`,
      'Compare the capture records with the order total and confirm any split payments.'
    ],
    unexpected_capture: [
      `The order is marked ${evidence.orders?.[0]?.status || 'ineligible'}, but matching captures total ${actual}.`,
      'Confirm the order status and check whether the capture should have been reversed.'
    ],
    payout_composition_mismatch: [
      `The processor reports a payout of ${expected}. Its linked signed payment items total ${actual}. ${check.variance_cents === 0 ? 'The totals agree, but at least one item has a contribution or currency inconsistency.' : comparison}`,
      'Compare captures, refunds, fees, and adjustments with the payout items and confirm their currencies.'
    ],
    missing_bank_deposit: [
      `The processor reports a payout of ${expected}, but no eligible bank deposit was found within the matching window after the arrival grace period.`,
      'Check the expected arrival date and the bank statement for the payout reference.'
    ],
    payout_bank_amount_mismatch: [
      `The processor reports ${expected} and the candidate bank deposit is ${actual}. ${comparison}`,
      'Compare the deposit reference and any documented fees or adjustments with the payout statement.'
    ],
    ambiguous_bank_credit: [
      `The run found ${check.candidates?.length || 0} candidate bank deposits for a payout of ${expected}. A reviewer must identify the correct deposit.`,
      'Compare each candidate’s account, date, currency, and settlement reference before approving a match.'
    ],
    ambiguous_grouped_bank_credit: [
      'Several payouts share a settlement reference, but the available bank credits do not establish one safe allocation.',
      'Compare the complete payout group with the bank credits and check for duplicate deposits.'
    ],
    bank_amount_already_allocated: [
      `A candidate deposit was found for ${expected}, but its amount is already allocated to another payout.`,
      'Review the existing allocation and confirm which payout the deposit belongs to.'
    ],
    missing_bank_reference: [
      `A candidate deposit has the same amount as the ${expected} payout, but its bank reference is missing. Amount alone does not confirm the match.`,
      'Confirm the account, currency, value date, and supporting settlement evidence.'
    ],
    missing_ledger_journal: [
      `The bank reports ${expected}, but this run found no matching ledger journal in the same currency. The checked ledger cash amount is ${actual}.`,
      'Check whether the journal was posted under another reference or is absent from the ledger export.'
    ],
    ledger_cash_mismatch: [
      `The bank reports ${expected} and matching ledger cash postings total ${actual}. ${check.variance_cents === 0 ? 'The cash totals agree, but at least one linked journal is unbalanced.' : comparison}`,
      'Review the cash lines, journal balance, currency, and bank reference.'
    ],
    overdue_in_transit: [
      `The processor still marks the ${expected} payout in transit after the arrival grace period.`,
      'Confirm the processor’s settlement status and check the latest bank statement.'
    ]
  };
  if (!caseRecord.finding_active) return {
    title: 'The source difference has cleared',
    summary: 'The latest check no longer reports an active finding. The case retains the investigation history.',
    next: 'Review the updated evidence and record the closure decision.'
  };
  const [summary, next] = explanations[check.reason] || [
    `This check was flagged for ${(check.reason || 'review').replaceAll('_', ' ')}. ${comparison}`,
    'Compare the linked source records and matching rule before recording a decision.'
  ];
  return {title: 'Why this was flagged', summary, next};
}
