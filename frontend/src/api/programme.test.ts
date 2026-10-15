import { describe, expect, it } from 'vitest'
import { recompute, snapshotOf, type ProgrammeRowView, type ProgrammeView } from './programme'
import { monthBands, scaleFor, ticks } from '@/features/schedule/programme/gantt'

const row = (id: number, over: Partial<ProgrammeRowView> = {}): ProgrammeRowView => ({
  id, parent_id: null, order: id, wbs: String(id), level: 0, summary: false, name: `Row ${id}`, description: '', boq_ref: '', boq_key: '',
  uom: '', quantity: 0, rate: 0, amount: 0, labour_required: 0, start: null, end: null, days: null, typed: { start: '', end: '', days: null },
  not_before: '', predecessors: '', milestone: false, productivity: false, output_per_day: 0, gangs: 0, qty_done: 0, percent: 0,
  planned_percent: 0, critical: false, float_days: null, problem: '', baseline: null, ...over,
})

// Mon 2 Nov 2026; Sundays off. A heading over tiling (5 days) and skirting (3 days, after tiling).
const view = (): ProgrammeView => recompute({
  job: { id: 1, number: 'JOB-1', name: 'Test', location: '' }, company: '', as_of: '2026-11-02', percent: 0, planned_percent: 0,
  calendar: { calendar_days: false, weekly_off: [7], holidays: [] }, start: null, finish: null, duration: 0, baseline: null, errors: [],
  broken_links: [], links: [{ successor: 3, predecessor: 2, kind: 'FS', lag: 0 }],
  rows: [
    row(1, { name: 'Flooring' }),
    row(2, { parent_id: 1, name: 'Floor tiling', typed: { start: '2026-11-02', end: '', days: 5 } }),
    row(3, { parent_id: 1, order: 4, name: 'Skirting', typed: { start: '', end: '', days: 3 } }),
  ],
})

describe('recompute: the grid answers before the server does', () => {
  it('works the programme out as the server would', () => {
    const v = view()
    const by = Object.fromEntries(v.rows.map((r) => [r.name, r]))
    expect(by['Floor tiling']).toMatchObject({ wbs: '1.1', start: '2026-11-02', end: '2026-11-06', days: 5 })
    expect(by.Skirting).toMatchObject({ wbs: '1.2', start: '2026-11-07', end: '2026-11-10', days: 3 })
    expect(by.Flooring).toMatchObject({ summary: true, start: '2026-11-02', end: '2026-11-10', days: 8 })
    expect(v.duration).toBe(9)                       // End - Start + 1, as the sheet's TIME DURATION IN DAYS
  })

  it('more Days on tiling moves skirting and the heading', () => {
    const v = recompute(view(), { id: 2, days: '7' })
    const by = Object.fromEntries(v.rows.map((r) => [r.name, r]))
    expect(by['Floor tiling'].end).toBe('2026-11-09')  // Sunday 8 Nov skipped
    expect(by.Skirting).toMatchObject({ start: '2026-11-10', end: '2026-11-12' })
    expect(by.Flooring.end).toBe('2026-11-12')
  })

  it('an End typed gives the Days', () => {
    const v = recompute(view(), { id: 2, end: '2026-11-04' })
    expect(v.rows.find((r) => r.id === 2)).toMatchObject({ days: 3, end: '2026-11-04' })
  })

  it('a predecessor typed as text links the rows; cleared, the row stands alone', () => {
    let v = recompute(view(), { id: 3, predecessors: '1.1SS+2' })
    expect(v.rows.find((r) => r.id === 3)?.start).toBe('2026-11-04')
    v = recompute(v, { id: 3, predecessors: '' })
    expect(v.links).toEqual([])
    expect(v.rows.find((r) => r.id === 3)?.start).toBeNull()
  })

  it('the snapshot for undo carries what was typed, not what was worked out', () => {
    const snap = snapshotOf(view())
    expect(snap.rows.find((r) => r.id === 3)).toMatchObject({ typed_start: '', typed_days: 3 })
    expect(snap.links).toHaveLength(1)
  })
})

describe('the chart scale', () => {
  it('week zoom starts on a Monday and keeps today in view', () => {
    const s = scaleFor('2026-11-04', '2026-11-20', '2026-10-15', 'week')
    expect(new Date(s.from * 86_400_000).getUTCDay()).toBe(1)
    expect(s.from * 86_400_000).toBeLessThanOrEqual(Date.UTC(2026, 9, 15))
    expect(ticks(s, 'week').every((t) => t.x % (7 * s.px) === 0)).toBe(true)
  })

  it('month bands cover the span without gaps', () => {
    const s = scaleFor('2026-11-04', '2027-01-20', '2026-11-04', 'month')
    const bands = monthBands(s)
    expect(bands[0].x).toBe(0)
    bands.slice(1).forEach((b, i) => expect(b.x).toBe(bands[i].x + bands[i].w))
    expect(bands.map((b) => b.label)).toContain('Dec 2026')
  })
})
