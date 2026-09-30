export interface LedgerEntry {
  direction: 'IN' | 'OUT' | string
  amount: number
  paid_on: string
  voided?: boolean
}

export interface MonthFlow {
  /** 2026-10 */
  month: string
  /** Oct 26 */
  label: string
  received: number
  paid: number
  net: number
  /** Net summed from the first month shown. */
  running: number
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

/**
 * Money in and money out, month by month, from the ledger.
 *
 * Voided entries never happened and are left out. The last `months` months up
 * to and including `today`'s are always all shown, empty ones as nought, so
 * the chart's time axis is even rather than jumping over a quiet month.
 */
export function cashFlow(entries: readonly LedgerEntry[], months = 12, today = new Date()): MonthFlow[] {
  const out: MonthFlow[] = []
  const at = new Map<string, MonthFlow>()
  for (let i = months - 1; i >= 0; i--) {
    const d = new Date(today.getFullYear(), today.getMonth() - i, 1)
    const month = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
    const row: MonthFlow = { month, label: `${MONTHS[d.getMonth()]} ${String(d.getFullYear()).slice(2)}`, received: 0, paid: 0, net: 0, running: 0 }
    at.set(month, row)
    out.push(row)
  }
  for (const e of entries) {
    if (e.voided) continue
    const row = at.get((e.paid_on ?? '').slice(0, 7))
    if (!row) continue
    if (e.direction === 'IN') row.received += e.amount
    else if (e.direction === 'OUT') row.paid += e.amount
  }
  let running = 0
  for (const row of out) {
    row.received = Math.round(row.received * 100) / 100
    row.paid = Math.round(row.paid * 100) / 100
    row.net = Math.round((row.received - row.paid) * 100) / 100
    running = Math.round((running + row.net) * 100) / 100
    row.running = running
  }
  return out
}

export const AGE_BUCKETS = ['Not due', '0-30', '31-60', '61-90', '90+'] as const

/** Owed to us and owed by us, side by side for each age. */
export function ageing(receivable: Record<string, number> | undefined, payable: Record<string, number> | undefined) {
  return AGE_BUCKETS.map((b) => ({ bucket: b === 'Not due' ? 'Not yet due' : `${b} days`, receivable: receivable?.[b] ?? 0, payable: payable?.[b] ?? 0 }))
}
