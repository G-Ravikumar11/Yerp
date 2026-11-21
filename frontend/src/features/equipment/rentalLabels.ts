/**
 * How a rental bill reads on screen. The server keeps its own words (Matched, Mismatch, Duplicate, Missing, Incomplete,
 * In progress, and finance's Approved or Disputed); these are only the labels people see.
 */
type Tone = 'danger' | 'warning' | 'success' | 'neutral' | 'info'

const CHECK_LABEL: Record<string, string> = {
  Matched: 'Received', Mismatch: 'Difference Found', Duplicate: 'Duplicate', Missing: 'Missing', Incomplete: 'Incomplete', 'In progress': 'In Progress',
}
const TONE: Record<string, Tone> = {
  Verified: 'success', Received: 'info', 'Difference Found': 'danger', Duplicate: 'danger', Disputed: 'danger', Missing: 'danger', Incomplete: 'warning', 'In Progress': 'neutral',
}

/** Finance's decision comes first: an approved bill is Verified, a disputed one Disputed; otherwise what the check found. */
export function billLabel(check: string, verification = ''): string {
  if (verification === 'Approved') return 'Verified'
  if (verification === 'Disputed') return 'Disputed'
  return CHECK_LABEL[check] ?? check ?? ''
}
export const billTone = (label: string): Tone => TONE[label] ?? 'neutral'

export const PAYMENT_TONE: Record<string, Tone> = { Paid: 'success', 'Partially paid': 'warning', Unpaid: 'danger', 'No bills': 'neutral' }
