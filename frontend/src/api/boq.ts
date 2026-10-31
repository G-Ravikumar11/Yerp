import { useQuery } from '@tanstack/react-query'
import { api, get, post, put } from '@/lib/api'

export type BoqKind = 'section' | 'item' | 'sub' | 'note'

export interface BoqHead {
  id: number
  number: string
  title: string
  job_id: number
  project: string
  customer: string
  current_rev: number
  revision: string
  status: 'OPEN' | 'ISSUED'
  items: number
  total: number
  created_at: string
}

export interface BoqLine {
  id?: number
  key: string
  kind: BoqKind
  /** The client's own numbering: I, 2, 2.1, 2.1.1. The programme's tree is drawn from it. */
  item_no?: string
  group_code: string
  description: string
  uom: string
  quantity: number
  rate: number
  amount: number
  item_code: string
  remarks: string
  /** The grade or material: M40, Fe550/550D, Ply wood. */
  material?: string
  /** Rate agreed, quantity not yet known ("R/o"): carries a rate, comes to nothing, and is in no total. */
  rate_only?: boolean
  /** Sections only: what the items under it come to. */
  subtotal?: number
}

export interface BoqSummarySection {
  key: string
  group_code: string
  title: string
  items: number
  rate_only: number
  amount: number
}

/** The BOQ on one page: section totals, then the total, the GST on it, and the total with GST. */
export interface BoqSummary {
  boq: BoqHead
  sections: BoqSummarySection[]
  total: number
  gst_percent: number
  gst: number
  total_with_gst: number
  by_material: { material: string; items: number; amount: number }[]
  rate_only_items: number
}

interface BoqRevision {
  rev_no: number
  label: string
  note: string
  status: 'OPEN' | 'ISSUED'
  created_by_name: string
  created_at: string
  issued_at: string
}

export interface BoqBook {
  boq: BoqHead
  revisions: BoqRevision[]
  lines: BoqLine[]
  total: number
  editable: boolean
}

export interface BoqChanges {
  from: string
  to: string
  difference: number
  changes: { change: 'added' | 'removed' | 'changed'; line: string; detail?: string; amount: number }[]
}

export interface BoqImport {
  lines: BoqLine[]
  read_as: Record<string, string>
  ignored_columns: string[]
  skipped_rows: number
  warnings: string[]
  total: number
  message: string
}

export type BoqFlag = 'no_contractor' | 'over_allotted' | 'loss' | 'over_executed'

export interface TrackerRow {
  kind: BoqKind
  key?: string
  group_code: string
  description: string
  uom?: string
  item_code?: string
  quantity?: number
  rate?: number
  amount?: number
  given?: number
  contractor_rate?: number
  contractor_cost?: number
  orders?: string[]
  left_to_give?: number
  executed?: number
  contractor_billed?: number
  client_executed?: number
  client_billed?: number
  margin_percent?: number | null
  percent_done?: number
  flags?: BoqFlag[]
}

export interface Tracker {
  boq: BoqHead
  rows: TrackerRow[]
  flags: Record<BoqFlag, number>
  totals: { value: number; given_cost: number; client_billed: number; contractor_billed: number }
}

export interface AvailableLine {
  kind: BoqKind
  key?: string
  item_no?: string
  group_code: string
  description: string
  /** A heading: how deep it sits (0 a main heading, 1 the sub-heading under it ...). */
  level?: number
  /** The headings above it, outermost first. */
  path?: string[]
  /** A heading: the text written under it on the sheet. */
  notes?: string
  uom?: string
  material?: string
  remarks?: string
  item_code?: string
  quantity?: number
  rate?: number
  given?: number
  left?: number
  /** A contractor rate to start from: the budget's labour and plant per unit, else the rate last given. */
  suggested_rate?: number
  rate_from?: '' | 'budget' | 'last given'
}

/** A schedule line as the server lays it out (the screen's own line, from the BOQ or typed in). */
export interface ScheduleRow {
  activity_no: string
  item_code: string
  item_description: string
  technical_spec: string
  uom: string
  quantity: number
  unit_rate: number
  tolerance_percent: number
  budget_id: number | string | null
  is_header: boolean
  boq_key: string
  boq_parts: { key: string; qty: number }[]
  material: string
  heading_level: number
  rate_from?: string
}

export const boqKeys = {
  all: ['boq'] as const,
  list: ['boq', 'list'] as const,
  one: (id: number, rev?: number) => ['boq', 'one', id, rev ?? 'current'] as const,
  tracker: (id: number) => ['boq', 'tracker', id] as const,
  summary: (id: number, gst: number, rev?: number) => ['boq', 'summary', id, gst, rev ?? 'current'] as const,
  available: (id: number) => ['boq', 'available', id] as const,
}

export const useBoqs = () => useQuery({ queryKey: boqKeys.list, queryFn: () => get<{ boqs: BoqHead[] }>('/api/boqs') })
export const useBoq = (id: number, rev?: number) =>
  useQuery({ queryKey: boqKeys.one(id, rev), enabled: id > 0, queryFn: () => get<BoqBook>(`/api/boqs/${id}${rev === undefined ? '' : `?rev=${rev}`}`) })
export const useTracker = (id: number, enabled: boolean) => useQuery({ queryKey: boqKeys.tracker(id), enabled: enabled && id > 0, queryFn: () => get<Tracker>(`/api/boqs/${id}/tracker`) })
export const useBoqSummary = (id: number, gst: number, enabled: boolean, rev?: number) =>
  useQuery({
    queryKey: boqKeys.summary(id, gst, rev),
    enabled: enabled && id > 0,
    queryFn: () => get<BoqSummary>(`/api/boqs/${id}/summary?gst=${gst}${rev === undefined ? '' : `&rev=${rev}`}`),
  })
/** Every material or grade already put on a BOQ line: what the Material dropdown offers besides its standard list. */
export const useBoqMaterials = () => useQuery({ queryKey: ['boq', 'materials'], queryFn: () => get<{ materials: string[] }>('/api/boqs/materials') })
// Read afresh each time the picker opens: the BOQ, what other orders have taken and the budget all change elsewhere.
export const useAvailable = (id: number) =>
  useQuery({ queryKey: boqKeys.available(id), enabled: id > 0, staleTime: 0, gcTime: 0, queryFn: () => get<{ boq: BoqHead; lines: AvailableLine[] }>(`/api/boqs/${id}/available`) })
export const useBoqChanges = (id: number, from: number, enabled: boolean) => useQuery({ queryKey: ['boq', 'changes', id, from], enabled: enabled && id > 0, queryFn: () => get<BoqChanges>(`/api/boqs/${id}/changes?frm=${from}`) })

export const createBoq = (jobId: number, title: string) => post<{ boq: BoqHead; message: string }>('/api/boqs', { job_id: jobId, title })
export const saveBoqLines = (id: number, lines: Partial<BoqLine>[], issueCodes: boolean) => put<{ boq: BoqHead; lines: BoqLine[]; total: number; message: string }>(`/api/boqs/${id}/lines`, { lines, issue_codes: issueCodes })
export const newRevision = (id: number, label: string, note: string) => post<{ boq: BoqHead; message: string }>(`/api/boqs/${id}/revisions`, { label, note })
export const makeClientOrder = (id: number, reference: string) => post<{ work_order: { id: number; number: string }; message: string }>(`/api/boqs/${id}/client-order`, { reference })
export function importBoq(id: number, file: File) {
  const form = new FormData()
  form.append('file', file)
  return api<BoqImport>(`/api/boqs/${id}/import`, { method: 'POST', body: form })
}
export interface BoqGroupPick {
  /** The heading it stands for: the line goes where that heading is, under the headings above it. */
  heading_key: string
  description: string
  group_code: string
  /** Left out, the rate the budget (or the last order) suggests, weighted by quantity. */
  rate?: number
  parts: { key: string; quantity: number }[]
}

/**
 * `lines` are BOQ lines taken one by one; `groups` are headings taken as one line each (their quantities added up at one
 * rate). With `current` (the schedule on screen), `rows` is the whole schedule with them in it, laid out like the sheet.
 */
export const pullBoqLines = (
  orderId: number,
  lines: { key: string; quantity: number; rate?: number }[],
  groups: BoqGroupPick[] = [],
  current?: Partial<ScheduleRow>[],
) =>
  post<{ lines: ScheduleRow[]; headings: ScheduleRow[]; rows?: ScheduleRow[]; warnings: string[] }>(`/api/wo/orders/${orderId}/boq-lines`, {
    lines,
    groups,
    ...(current ? { current } : {}),
  })

/**
 * The schedule on screen made cumulative: its BOQ lines added up into one line per heading at `level` (0 the main
 * headings, 1 the sub-headings), per unit and, with `keep_grades`, per grade - or with `split` put back as BOQ lines.
 * The order's value does not move; each line keeps the BOQ lines it adds up.
 */
export const cumulativeSchedule = (orderId: number, rows: Partial<ScheduleRow>[], opts: { level?: number; keep_grades?: boolean; split?: boolean }) =>
  post<{ rows: ScheduleRow[] }>(`/api/wo/orders/${orderId}/schedule/cumulative`, { rows, ...opts })

/** The schedule on screen in the BOQ's order, under its headings, numbered (the blank numbers, or all with `renumber`). */
export const arrangeSchedule = (orderId: number, rows: Partial<ScheduleRow>[], renumber: boolean) =>
  post<{ rows: ScheduleRow[] }>(`/api/wo/orders/${orderId}/schedule/arrange`, { rows, renumber })

/* --- Variations to the BOQ -------------------------------------------------------------------- */

type VariationStatus = 'DRAFT' | 'SUBMITTED' | 'APPROVED' | 'CANCELLED'

export interface VariationLine {
  id?: number
  kind: 'quantity' | 'extra'
  boq_key: string
  section_key: string
  description: string
  uom: string
  old_qty: number
  change_qty: number
  new_qty?: number
  rate: number
  amount: number
  remarks: string
}

export interface BoqVariation {
  id: number
  number: string
  boq_id: number
  boq: string
  project: string
  status: VariationStatus
  reason: string
  value: number
  basis_rev: string
  applied_rev: string
  raised_by_name: string
  approved_by_name: string
  approved_at: string
  rejection_reason: string
  actions: ('SUBMIT' | 'APPROVE' | 'REJECT' | 'CANCEL')[]
  editable: boolean
  created_at: string
  route: { step: number; name: string; owner: boolean; status: string; notes: string; decided_at: string }[]
  waiting_on: string
  lines?: VariationLine[]
}

export interface VariationInput {
  kind: 'quantity' | 'extra'
  boq_key: string
  section_key: string
  description: string
  uom: string
  change_qty: number
  rate: number | null
  remarks: string
}

export const variationKeys = { all: ['boq-variations'] as const, list: (boqId: number) => ['boq-variations', 'list', boqId] as const, one: (id: number) => ['boq-variations', 'one', id] as const }

export const useBoqVariations = (boqId: number) =>
  useQuery({
    queryKey: variationKeys.list(boqId),
    enabled: boqId > 0,
    queryFn: () => get<{ variations: BoqVariation[]; summary: { raised: number; awaiting_approval: number; approved_value: number; pending_value: number } }>(`/api/boq-variations?boq_id=${boqId}`),
  })
export const useBoqVariation = (id: number) => useQuery({ queryKey: variationKeys.one(id), enabled: id > 0, queryFn: () => get<BoqVariation>(`/api/boq-variations/${id}`) })
export const suggestVariation = (boqId: number) => get<{ lines: VariationLine[]; value: number }>(`/api/boq-variations/suggest/${boqId}`)
export const createVariation = (boqId: number, reason: string, lines: VariationInput[]) => post<{ variation: BoqVariation; message: string }>('/api/boq-variations', { boq_id: boqId, reason, lines })
export const updateVariation = (id: number, reason: string, lines: VariationInput[]) => put<{ variation: BoqVariation; message: string }>(`/api/boq-variations/${id}`, { reason, lines })
export const moveVariation = (id: number, action: 'submit' | 'approve' | 'reject' | 'cancel', comments = '') => post<{ variation: BoqVariation; message: string }>(`/api/boq-variations/${id}/${action}`, { comments })
export const deleteVariation = (id: number) => api<{ message: string }>(`/api/boq-variations/${id}`, { method: 'DELETE' })
