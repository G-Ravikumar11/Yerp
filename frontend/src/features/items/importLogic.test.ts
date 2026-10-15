import { describe, expect, it } from 'vitest'
import type { ImportPreviewRow } from '@/api/itemMasterImport'
import { canImport, chooseAction, editValue, entries, importCount, showing, skippedCsv, tally, willImport } from './importLogic'

const row = (line: number, status: ImportPreviewRow['status'], extra: Partial<ImportPreviewRow> = {}): ImportPreviewRow => ({
  line,
  status,
  reason: '',
  changes: [],
  action: status === 'New' || status === 'Update' ? 'import' : 'skip',
  values: { item_name: `Item ${line}` },
  kind_of_duplicate: '',
  ...extra,
})
const rows = [row(2, 'New'), row(3, 'Update'), row(4, 'Duplicate', { kind_of_duplicate: 'code_in_file' }), row(5, 'Duplicate', { kind_of_duplicate: 'same_name' }), row(6, 'Error')]

describe('import preview', () => {
  it('counts the rows by what will happen to them', () => {
    expect(tally(rows)).toEqual({ total: 5, new: 1, update: 1, duplicate: 2, error: 1 })
  })

  it('imports new and changed rows by default, and nothing that is a repeat or a mistake', () => {
    expect(rows.map(willImport)).toEqual([true, true, false, false, false])
    expect(importCount(rows)).toBe(2)
  })

  it('lets a same-name repeat be added anyway, but never a repeated code or a row with an error', () => {
    expect(rows.map(canImport)).toEqual([true, true, false, true, false])
    const next = chooseAction(chooseAction(chooseAction(rows, 5, 'import'), 4, 'import'), 6, 'import')
    expect(importCount(next)).toBe(3)
    expect(next.find((r) => r.line === 4)?.action).toBe('skip')
    expect(next.find((r) => r.line === 6)?.action).toBe('skip')
  })

  it('lets any row be skipped', () => {
    expect(importCount(chooseAction(rows, 2, 'skip'))).toBe(1)
  })

  it('filters by status and shows everything with no filter', () => {
    expect(showing(rows, 'Duplicate').map((r) => r.line)).toEqual([4, 5])
    expect(showing(rows, '')).toHaveLength(5)
  })

  it('sends the edited values, and a choice only where the person made one', () => {
    const edited = editValue(rows, 6, 'units_of_measure', 'cum')
    expect(edited.find((r) => r.line === 6)?.values.units_of_measure).toBe('cum')
    expect(edited.find((r) => r.line === 2)?.values.units_of_measure).toBeUndefined()
    const sent = entries(chooseAction(edited, 5, 'import'), new Set([5]))
    expect(sent.find((e) => e.line === 5)).toMatchObject({ action: 'import' })
    expect(sent.find((e) => e.line === 2)).not.toHaveProperty('action')
  })
})

describe('the list of rows that were left out', () => {
  it('is a csv with a heading, quoting what needs it', () => {
    const csv = skippedCsv([{ line: 7, code: 'A-1', name: 'Plywood, 19mm "BWP"', reason: 'The unit is missing.' }])
    expect(csv.split('\r\n')).toEqual(['"Line in your sheet","Item code","Item name","Why it was left out"', '"7","A-1","Plywood, 19mm ""BWP""","The unit is missing."'])
  })
})
