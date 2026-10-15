import { useQuery } from '@tanstack/react-query'
import { api, apiUrl, get, post, put } from '@/lib/api'
import { Calendar, parsePredecessors, schedule, toDay, type ProgrammeRow } from '@/lib/programme'

/** One row of the programme, worked out by the server (backend/app/services/programme.py). */
export interface ProgrammeRowView {
  id: number
  parent_id: number | null
  order: number
  wbs: string
  level: number
  summary: boolean
  name: string
  description: string
  boq_ref: string
  boq_key: string
  uom: string
  quantity: number
  rate: number
  amount: number
  labour_required: number
  start: string | null
  end: string | null
  days: number | null
  /** What was typed, as opposed to what the rules make of it. */
  typed: { start: string; end: string; days: number | null }
  not_before: string
  predecessors: string
  milestone: boolean
  productivity: boolean
  output_per_day: number
  gangs: number
  qty_done: number
  percent: number
  planned_percent: number
  critical: boolean
  float_days: number | null
  problem: string
  baseline: { start: string | null; end: string | null; slip_days: number | null } | null
}

export interface ProgrammeLinkView {
  successor: number
  predecessor: number
  kind: string
  lag: number
}

export interface Holiday {
  id: number
  date: string
  name: string
}

export interface ProgrammeView {
  job: { id: number; number: string; name: string; location: string }
  company: string
  calendar: { calendar_days: boolean; weekly_off: number[]; holidays: Holiday[] }
  start: string | null
  finish: string | null
  duration: number
  as_of: string
  percent: number
  planned_percent: number
  baseline: { id: number; label: string; saved_at: string } | null
  errors: string[]
  broken_links: ProgrammeLinkView[]
  links: ProgrammeLinkView[]
  rows: ProgrammeRowView[]
  message?: string
  made?: number[]
  dropped_links?: string[]
}

export type EditableField =
  | 'name' | 'description' | 'boq_ref' | 'uom' | 'quantity' | 'rate' | 'amount' | 'labour_required' | 'start' | 'end'
  | 'days' | 'not_before' | 'predecessors' | 'milestone' | 'productivity' | 'output_per_day' | 'gangs' | 'qty_done'
export type RowChange = { id: number } & Partial<Record<EditableField, unknown>>

/** Under 'schedule', so anything that refreshes the schedule (an activity saved, a sheet imported) refreshes this too. */
export const programmeKeys = { one: (job: number) => ['schedule', 'programme', job] as const }

// Read afresh whenever it is opened, as the schedule is: someone else may have moved it since.
export const useProgramme = (job: number) =>
  useQuery({ queryKey: programmeKeys.one(job), enabled: job > 0, staleTime: 0, refetchOnMount: 'always', queryFn: () => get<ProgrammeView>(`/api/jobs/${job}/programme`) })

const base = (job: number) => `/api/jobs/${job}/programme`
export const loadProgramme = (job: number) => get<ProgrammeView>(base(job))

export const editRows = (job: number, changes: RowChange[]) => api<ProgrammeView>(`${base(job)}/rows`, { method: 'PATCH', body: { changes } })
export const addRows = (job: number, anchor_id: number | null, position: 'after' | 'child' | 'end', rows: Record<string, unknown>[] = [{}]) =>
  post<ProgrammeView>(`${base(job)}/rows`, { anchor_id, position, rows })
export const moveRow = (job: number, id: number, parent_id: number | null, before_id: number | null) =>
  post<ProgrammeView>(`${base(job)}/move`, { id, parent_id, before_id })
export const duplicateRow = (job: number, id: number) => post<ProgrammeView>(`${base(job)}/rows/${id}/duplicate`)
export const deleteRow = (job: number, id: number) => api<ProgrammeView>(`${base(job)}/rows/${id}`, { method: 'DELETE' })
export const copyUnits = (job: number, source_id: number, targets: { name: string; start?: string; offset?: number }[]) =>
  post<ProgrammeView>(`${base(job)}/copy`, { source_id, targets })
export const setCalendar = (job: number, calendar_days: boolean, weekly_off: number[]) =>
  put<ProgrammeView>(`${base(job)}/calendar`, { calendar_days, weekly_off })
export const addHoliday = (job: number, date: string, name: string) => post<ProgrammeView>(`${base(job)}/holidays`, { date, name })
export const addPublicHolidays = (job: number, year: number) => post<ProgrammeView>(`${base(job)}/holidays/public`, { year })
/** The programme as it stands, kept to measure against: planned % follows it, and each row's slip is from it. */
export const saveBaseline = (job: number, label: string) => post<ProgrammeView>(`${base(job)}/baseline`, { label })
export const removeHoliday = (job: number, id: number) => api<ProgrammeView>(`${base(job)}/holidays/${id}`, { method: 'DELETE' })

export interface Snapshot {
  rows: Record<string, unknown>[]
  links: ProgrammeLinkView[]
}
export const restoreProgramme = (job: number, snap: Snapshot) => post<ProgrammeView>(`${base(job)}/restore`, snap)

/** Everything needed to put the programme back as it is now (undo and redo). */
export function snapshotOf(v: ProgrammeView): Snapshot {
  return {
    rows: v.rows.map((r) => ({
      id: r.id, parent_id: r.parent_id, order: r.order, name: r.name, description: r.description, boq_ref: r.boq_ref,
      uom: r.uom, quantity: r.quantity, rate: r.rate, amount: r.amount, labour_required: r.labour_required,
      typed_start: r.typed.start, typed_end: r.typed.end, typed_days: r.typed.days, not_before: r.not_before,
      milestone: r.milestone, productivity: r.productivity, output_per_day: r.output_per_day, gangs: r.gangs, qty_done: r.qty_done,
    })),
    links: v.links,
  }
}

export const calendarOf = (v: ProgrammeView) =>
  new Calendar({ calendar_days: v.calendar.calendar_days, weekly_off: v.calendar.weekly_off, holidays: v.calendar.holidays.map((h) => h.date) })

/**
 * The view with a change applied here first, worked out by the same engine the server runs, so the grid answers as
 * the user types. The server's answer replaces it a moment later.
 */
export function recompute(v: ProgrammeView, change?: RowChange): ProgrammeView {
  const cal = calendarOf(v)
  let links = v.links
  const rows = v.rows.map((r) => {
    if (!change || r.id !== change.id) return r
    const next = { ...r, typed: { ...r.typed } }
    for (const [k, val] of Object.entries(change)) {
      if (k === 'id') continue
      if (k === 'start') next.typed.start = String(val ?? '')
      else if (k === 'end') {
        next.typed.end = String(val ?? '')
        if (next.typed.start && next.typed.end) next.typed.days = cal.span(cal.snap(toDay(next.typed.start)), toDay(next.typed.end))
      } else if (k === 'days') next.typed.days = val === '' || val === null || val === undefined ? null : Math.max(0, Math.trunc(Number(val)))
      else if (k === 'predecessors') {
        const wbs = Object.fromEntries(v.rows.map((x) => [x.wbs, x.id]))
        const { links: found } = parsePredecessors(String(val ?? ''), wbs)
        // its first predecessor: it follows it from now on and keeps its length (as the server does)
        if (found.length && !v.links.some((l) => l.successor === r.id) && !('start' in change) && !('end' in change) && next.typed.start) {
          if (next.typed.days === null && next.typed.end) next.typed.days = cal.span(cal.snap(toDay(next.typed.start)), toDay(next.typed.end))
          next.typed = { ...next.typed, start: '', end: '' }
        }
        links = [...links.filter((l) => l.successor !== r.id), ...found.map(([p, kind, lag]) => ({ successor: r.id, predecessor: p, kind, lag }))]
        next.predecessors = String(val ?? '')
      } else (next as Record<string, unknown>)[k] = val
    }
    return next
  })
  const input: ProgrammeRow[] = rows.map((r) => ({
    id: r.id, parent_id: r.parent_id, order: r.order, name: r.name, start: r.typed.start || null, end: r.typed.end || null,
    days: r.typed.days, not_before: r.not_before || null, milestone: r.milestone, quantity: r.quantity, rate: r.rate, amount: r.amount,
    qty_done: r.qty_done, percent: r.quantity > 0 ? null : r.percent, productivity: r.productivity, output_per_day: r.output_per_day, gangs: r.gangs,
  }))
  let prog
  try {
    prog = schedule(input, links, cal)
  } catch {
    return v
  }
  const order = new Map(prog.order.map((id, i) => [id, i]))
  return {
    ...v,
    links,
    start: prog.start,
    finish: prog.finish,
    duration: prog.duration,
    errors: prog.errors,
    rows: rows
      .map((r) => {
        const p = prog.rows.get(r.id)!
        return { ...r, wbs: p.wbs, level: p.level, summary: p.summary, start: p.start, end: p.end, days: p.days, critical: p.critical, float_days: p.float_days, percent: Math.round(p.percent * 100) / 100 }
      })
      .sort((a, b) => order.get(a.id)! - order.get(b.id)!),
  }
}

/** A line of the BOQ as the picker shows it (backend/app/services/programme_boq.py). */
export interface BoqNode {
  /** The BOQ line's key; "<key>#own" for an item's own work when it also has sub-items. */
  id: string
  key: string
  ref: string
  item_no: string
  parent: string | null
  level: number
  heading: boolean
  name: string
  description: string
  uom: string
  quantity: number
  rate: number
  amount: number
  rate_only: boolean
  drawn_rows: number
  drawn_quantity: number
}
export interface ProgrammeBoq {
  boq: { id: number; number: string; revision: string } | null
  items: BoqNode[]
  numbered: boolean
}
export interface BoqPick {
  id: string
  name?: string
  splits?: { label: string; quantity: number }[]
}

export const useProgrammeBoq = (job: number, enabled: boolean) =>
  useQuery({ queryKey: ['schedule', 'programme-boq', job], enabled: enabled && job > 0, staleTime: 0, queryFn: () => get<ProgrammeBoq>(`${base(job)}/boq`) })
export const drawProgrammeFromBoq = (job: number, body: { picks: BoqPick[]; anchor_id: number | null; position: 'after' | 'child' | 'end'; start: string }) =>
  post<ProgrammeView & { warnings?: string[] }>(`${base(job)}/from-boq`, body)

/** A row read from a schedule sheet, as the preview gives it and the confirm takes it back. */
export interface ImportNode {
  key: number
  parent: number | null
  name: string
  description: string
  boq_ref: string
  uom: string
  quantity: number
  labour: number
  start: string
  days: number | null
  percent: number | null
  heading: boolean
  links: { pred: number; kind: string; lag: number }[]
}
export interface ImportPreview { sheet: string; sheets: string[]; nodes: ImportNode[]; calendar: Record<string, unknown> | null; warnings: string[]; own: boolean }

export const readProgrammeSheet = (job: number, file: File, sheet = '') => {
  const form = new FormData()
  form.append('file', file)
  form.append('sheet', sheet)
  return api<ImportPreview>(`${base(job)}/import`, { method: 'POST', body: form })
}
export const importProgramme = (job: number, preview: ImportPreview) =>
  post<ProgrammeView>(`${base(job)}/import/confirm`, { nodes: preview.nodes, calendar: preview.calendar })
/** The programme as an Excel sheet with live formulas, or as an A3 PDF. */
export const programmeFileUrl = (job: number, kind: 'export' | 'pdf') => apiUrl(`${base(job)}/${kind}`)