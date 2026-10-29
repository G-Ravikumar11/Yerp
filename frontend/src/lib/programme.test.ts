import { describe, expect, it } from 'vitest'
import { Calendar, formatPredecessors, parsePredecessors, plannedPercent, schedule, type ProgrammeLink, type ProgrammeRow } from './programme'
// The same cases the server's engine is tested with (backend/tests/test_programme_engine.py): both must answer alike.
import CASES from '../../../backend/tests/data/programme_cases.json'

interface Case {
  name: string
  calendar?: { calendar_days?: boolean; weekly_off?: number[]; holidays?: string[] }
  rows: ProgrammeRow[]
  links?: ProgrammeLink[]
  expect?: Record<string, Record<string, unknown>>
  expect_project?: { start: string; finish: string; duration: number }
  expect_errors?: string[]
  expect_broken_links?: number
  planned?: { as_of: string; expect: Record<string, number> }[]
}
interface Parse { text: string; wbs: Record<string, number>; links: [number, string, number][]; problems: number }
interface Format { links: [number, string, number][]; wbs: Record<string, string>; text: string }
const DATA = CASES as unknown as { cases: Case[]; parse: Parse[]; format: Format[] }

describe('the programme engine answers as the server does', () => {
  for (const c of DATA.cases) {
    it(c.name, () => {
      const cal = new Calendar(c.calendar ?? {})
      const prog = schedule(c.rows, c.links ?? [], cal)
      for (const [rid, want] of Object.entries(c.expect ?? {})) {
        const got = prog.rows.get(Number(rid))! as unknown as Record<string, unknown>
        for (const [k, v] of Object.entries(want)) {
          if (k === 'percent') expect(got[k] as number, `${rid}.${k}`).toBeCloseTo(v as number, 2)
          else expect(got[k], `${rid}.${k}`).toEqual(v)
        }
      }
      if (c.expect_project) {
        expect([prog.start, prog.finish, prog.duration]).toEqual([c.expect_project.start, c.expect_project.finish, c.expect_project.duration])
      }
      for (const text of c.expect_errors ?? []) expect(prog.errors.some((e) => e.includes(text))).toBe(true)
      if (!c.expect_errors?.length) expect(prog.errors).toEqual([])
      if (c.expect_broken_links !== undefined) expect(prog.broken_links.length).toBe(c.expect_broken_links)
      for (const check of c.planned ?? []) {
        const pct = plannedPercent(prog, cal, check.as_of)
        for (const [rid, v] of Object.entries(check.expect)) {
          expect(pct.get(rid === 'project' ? 'project' : Number(rid))!, `${check.as_of} ${rid}`).toBeCloseTo(v, 2)
        }
      }
    })
  }
})

describe('predecessors as text', () => {
  for (const c of DATA.parse) {
    it(`reads "${c.text}"`, () => {
      const { links, problems } = parsePredecessors(c.text, c.wbs)
      expect(links).toEqual(c.links)
      expect(problems.length).toBe(c.problems)
    })
  }
  for (const c of DATA.format) {
    it(`writes "${c.text}"`, () => {
      const wbs = Object.fromEntries(Object.entries(c.wbs).map(([k, v]) => [Number(k), v]))
      expect(formatPredecessors(c.links, wbs)).toBe(c.text)
    })
  }
})

describe('size', () => {
  it('works out 1,800 rows in well under a second', () => {
    const rows: ProgrammeRow[] = []
    const links: ProgrammeLink[] = []
    let id = 0
    for (let b = 0; b < 20; b++) {
      const block = ++id
      rows.push({ id: block, name: `Block ${b}`, order: b })
      for (let u = 0; u < 10; u++) {
        const unit = ++id
        rows.push({ id: unit, parent_id: block, order: u, name: `Unit ${u}` })
        let prev: number | null = null
        for (let a = 0; a < 8; a++) {
          const act = ++id
          rows.push({ id: act, parent_id: unit, order: a, name: `Activity ${a}`, start: prev === null ? '2026-11-02' : null, days: 3 })
          if (prev !== null) links.push({ successor: act, predecessor: prev, kind: 'FS', lag: 0 })
          prev = act
        }
      }
    }
    const t = performance.now()
    const prog = schedule(rows, links)
    expect(performance.now() - t).toBeLessThan(1000)
    expect(prog.errors).toEqual([])
    expect(prog.finish).toBe('2026-11-28')
  })
})
