/** Figures and ordering shared by the project money screens (Project Profit, Cost by Project). */

/** Whole rupees, the Indian way (12,34,567): the paise are noise in a table of projects. */
export const rupees = (n: number | null | undefined) => {
  const v = Math.round(n ?? 0)
  return `${v < 0 ? '-' : ''}₹${Math.abs(v).toLocaleString('en-IN')}`
}

export const percent = (part: number, whole: number) => (whole > 0 ? Math.round((part / whole) * 100) : 0)

/** A to Z by project name, then by number, ignoring case and reading "Block 2" before "Block 10". */
export const alphabetical = (a: { name: string; number: string }, b: { name: string; number: string }) =>
  a.name.localeCompare(b.name, undefined, { sensitivity: 'base', numeric: true }) || a.number.localeCompare(b.number, undefined, { numeric: true })
