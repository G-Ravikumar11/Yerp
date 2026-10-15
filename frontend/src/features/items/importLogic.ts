import type { ImportEntry, ImportPreviewRow, ImportResult, ImportStatus } from '@/api/itemMasterImport'

export interface Tally {
  total: number
  new: number
  update: number
  duplicate: number
  error: number
}

export function tally(rows: readonly ImportPreviewRow[]): Tally {
  const t: Tally = { total: rows.length, new: 0, update: 0, duplicate: 0, error: 0 }
  for (const r of rows) t[r.status.toLowerCase() as keyof Omit<Tally, 'total'>] += 1
  return t
}

/** Only a new or changed item can be switched on; a row with a problem cannot be imported, and a repeat of the same code never is.
 *  A repeat that only shares a name can be added anyway: the person is saying it is a different item. */
export function canImport(r: ImportPreviewRow): boolean {
  if (r.status === 'New' || r.status === 'Update') return true
  return r.status === 'Duplicate' && r.kind_of_duplicate === 'same_name'
}

/** Will this row be saved when the person presses Import? */
export const willImport = (r: ImportPreviewRow) => r.action === 'import' && canImport(r)

export const importCount = (rows: readonly ImportPreviewRow[]) => rows.filter(willImport).length

export function showing(rows: readonly ImportPreviewRow[], status: ImportStatus | ''): ImportPreviewRow[] {
  return status ? rows.filter((r) => r.status === status) : [...rows]
}

export function chooseAction(rows: readonly ImportPreviewRow[], line: number, action: 'import' | 'skip'): ImportPreviewRow[] {
  return rows.map((r) => (r.line === line && (action === 'skip' || canImport(r)) ? { ...r, action } : r))
}

export function editValue(rows: readonly ImportPreviewRow[], line: number, field: string, value: string): ImportPreviewRow[] {
  return rows.map((r) => (r.line === line ? { ...r, values: { ...r.values, [field]: value } } : r))
}

/** What is sent to be checked or saved: the values as they now stand, and the choice only where the person made one. */
export function entries(rows: readonly ImportPreviewRow[], chosen: ReadonlySet<number>): ImportEntry[] {
  return rows.map((r) => ({ line: r.line, values: r.values, ...(chosen.has(r.line) ? { action: r.action } : {}) }))
}

const quote = (v: string | number) => `"${String(v ?? '').replace(/"/g, '""')}"`

/** The rows that were left out and why, as a file to open in Excel and put right. */
export function skippedCsv(errors: ImportResult['errors']): string {
  const head = ['Line in your sheet', 'Item code', 'Item name', 'Why it was left out']
  return [head, ...errors.map((e) => [e.line, e.code, e.name, e.reason])].map((r) => r.map(quote).join(',')).join('\r\n')
}

export const STATUS_HELP: Record<ImportStatus, string> = {
  New: 'Will be added to the item master.',
  Update: 'Already in the master. Only the cells you filled in will change it.',
  Duplicate: 'Looks like something already there, or repeated in your sheet.',
  Error: 'Cannot be imported until it is fixed.',
}
