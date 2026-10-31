export interface MonthFlow {
  /** 2026-10 */
  month: string
  /** Oct 26 */
  label: string
  received: number
  paid: number
  net: number
  /** The balance of every account together at the month's end, from their opening balances. */
  running: number
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

/** "2026-10" as "Oct 26". */
export function monthLabel(month: string) {
  const [y, m] = month.split('-').map(Number)
  return `${MONTHS[(m || 1) - 1]} ${String(y).slice(2)}`
}

/**
 * Money in and money out, month by month, as the server totals it (GET /api/money/cash-flow): over every entry, a
 * transfer between our own accounts neither in nor out, a voided entry nothing, the balance from the opening balances.
 */
export const withLabels = (months: Omit<MonthFlow, 'label'>[]): MonthFlow[] => months.map((m) => ({ ...m, label: monthLabel(m.month) }))

const AGE_BUCKETS = ['Not due', '0-30', '31-60', '61-90', '90+'] as const

/** Owed to us and owed by us, side by side for each age. */
export function ageing(receivable: Record<string, number> | undefined, payable: Record<string, number> | undefined) {
  return AGE_BUCKETS.map((b) => ({ bucket: b === 'Not due' ? 'Not yet due' : `${b} days`, receivable: receivable?.[b] ?? 0, payable: payable?.[b] ?? 0 }))
}
