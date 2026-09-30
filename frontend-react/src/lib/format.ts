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

/** Today's date on this device's clock, as yyyy-mm-dd. (The UTC date is yesterday's for the first hours of an Indian morning.) */
export const today = () => {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

/** "1 item" / "3 items". */
export function plural(n: number, one: string, many = one + 's'): string {
  return `${n} ${n === 1 ? one : many}`
}
