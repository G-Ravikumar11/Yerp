const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

/** 2026-10-01 (or a datetime) as "01 Oct 2026". Blank stays blank. */
export function formatDate(value: string | null | undefined): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(value ?? '')
  if (!m) return value ?? ''
  return `${m[3]} ${MONTHS[+m[2] - 1] ?? m[2]} ${m[1]}`
}

/** A quantity as a person reads it: no trailing noughts, Indian grouping. */
export function formatQty(value: number | null | undefined, max = 3): string {
  if (value === null || value === undefined) return ''
  return value.toLocaleString('en-IN', { maximumFractionDigits: max })
}

export function formatPercent(value: number | null | undefined): string {
  return value ? `${value}%` : '-'
}

export const today = () => new Date().toISOString().slice(0, 10)

/** "1 item" / "3 items". */
export function plural(n: number, one: string, many = one + 's'): string {
  return `${n} ${n === 1 ? one : many}`
}
