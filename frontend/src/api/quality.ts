import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { del, get, post, put } from '@/lib/api'

export const qcKeys = { all: ['quality'] as const }

/* ---- shapes ---- */

export interface CheckItem { item: string; criteria?: string; result: string; measured?: string; remark: string }
export interface Inspection {
  id: number; job_id: number; project: string; site: string; number: string; checklist: string; location: string
  building: string; floor_area: string; work_activity: string; assigned_to: string; measurements: string
  inspected_on: string; inspected_by: string; witnessed_by: string; remarks: string
  result: string; result_label: string; failed_items: number; checked: number; items: CheckItem[]
  approval_status: string; submitted_by: string; submitted_on: string; approved_by: string; approved_on: string; return_note: string
  reinspection_of: number | null; editable: boolean
  reinspection_number?: string; reinspection_result?: string; reinspection_of_number?: string
  ncrs?: { id: number; number: string; status: string }[]
}
export interface CubeResult {
  id: number; age_days: number; tested_on: string; strengths: number[]; average: number; evaluation: 'meets' | 'below' | 'no_criteria'
  ok: boolean; failed: boolean; spread_ok: boolean; verdict: string; criteria_min: number; criteria_single: number; criteria_ref: string
  lab: string; remarks: string; flagged: boolean; actual_age: number | null; recorded_by: string
}
export interface CubeDue { age_days: number; due_on: string; overdue: boolean; today: boolean }
export interface CubeSchedule { age_days: number; due_on: string; state: 'tested' | 'due' | 'overdue' | 'upcoming' }
export interface CubeSet {
  id: number; job_id: number; project?: string; number: string; cast_on: string; location: string; pour_ref: string; cube_ids: string
  supplier: string; docket: string; grade: string; fck: number; slump_mm: number; remarks: string; cast_by: string
  test_ages: number[]; schedule: CubeSchedule[]; results: CubeResult[]; due: CubeDue[]
  status: string; needs_review: boolean; review_reasons: string[]; counted_below: number
  acceptance: string; acceptance_note: string; accepted_by: string; accepted_on: string
  ncrs?: { id: number; number: string; status: string; source_ref: string }[]
}
export interface Ncr {
  id: number; job_id: number; project: string; number: string; severity: string; raised_on: string; raised_by: string; location: string; description: string
  responsible: string; target_date: string; corrective_action: string; root_cause: string; status: string; status_label: string; overdue: boolean
  source_type: string; source_id: number | null; source_ref: string; source_number?: string
  assigned_by: string; assigned_on: string; corrective_done: string; corrective_on: string
  verification_result: string; verification_note: string; verified_by: string; verified_on: string; reinspection_ref: string
  closed_on: string; closed_by: string; closure_note: string; needs_root_cause: boolean; evidence?: number
}
export interface HistoryLine { at: string; who: string; action: string; details: string }
export interface Template { id: number | null; name: string; work_type: string; builtin: boolean; job_id: number | null; spec_ref: string; is_active: boolean; items: { item: string; criteria: string }[] }
export interface Criteria { id: number; job_id: number; project?: string; grade: string; age_days: number; min_mean: number; min_single: number; standard: string; approved_by: string; approved_on: string }
export interface Summary {
  inspections_failed: number; inspections_awaiting_approval: number; cubes_to_crush: number; cubes_overdue: number
  below_grade: number; cubes_for_review: number; ncrs_open: number; ncrs_overdue: number
}

/** What narrows and orders a list. The server does it, so a page is always the page of what was asked for. */
export interface ListQuery { job: number; q: string; status: string; from: string; to: string; sort: string; dir: 'asc' | 'desc'; page: number; size: number; severity?: string }
export const emptyQuery = (job = 0): ListQuery => ({ job, q: '', status: '', from: '', to: '', sort: '', dir: 'desc', page: 1, size: 25 })

const qs = (f: ListQuery) => {
  const p = new URLSearchParams()
  if (f.job) p.set('job_id', String(f.job))
  if (f.q.trim()) p.set('q', f.q.trim())
  if (f.status) p.set('status', f.status)
  if (f.from) p.set('date_from', f.from)
  if (f.to) p.set('date_to', f.to)
  if (f.severity) p.set('severity', f.severity)
  if (f.sort) { p.set('sort', f.sort); p.set('dir', f.dir) }
  p.set('page', String(f.page))
  p.set('page_size', String(f.size))
  return p.toString()
}
export const exportUrl = (kind: 'inspections' | 'cubes' | 'ncrs', f: ListQuery) => `/api/qc/${kind}.xlsx?${qs({ ...f, page: 1, size: 0 })}`

interface Page<T> { rows: T[]; total: number }

/* ---- reads ---- */

export const useSummary = (job: number) => useQuery({ queryKey: [...qcKeys.all, 'summary', job], queryFn: () => get<Summary>(`/api/qc/summary${job ? `?job_id=${job}` : ''}`) })

export const useInspections = (f: ListQuery) =>
  useQuery({
    queryKey: [...qcKeys.all, 'inspections', f],
    placeholderData: keepPreviousData,
    queryFn: async (): Promise<Page<Inspection>> => {
      const d = await get<{ inspections: Inspection[]; total: number }>(`/api/qc/inspections?${qs(f)}`)
      return { rows: d.inspections ?? [], total: d.total ?? 0 }
    },
  })

export const useCubes = (f: ListQuery) =>
  useQuery({
    queryKey: [...qcKeys.all, 'cubes', f],
    placeholderData: keepPreviousData,
    queryFn: async (): Promise<Page<CubeSet>> => {
      const d = await get<{ cubes: CubeSet[]; total: number }>(`/api/qc/cubes?${qs(f)}`)
      return { rows: d.cubes ?? [], total: d.total ?? 0 }
    },
  })

export const useNcrs = (f: ListQuery) =>
  useQuery({
    queryKey: [...qcKeys.all, 'ncrs', f],
    placeholderData: keepPreviousData,
    queryFn: async (): Promise<Page<Ncr>> => {
      const d = await get<{ ncrs: Ncr[]; total: number }>(`/api/qc/ncrs?${qs(f)}`)
      return { rows: d.ncrs ?? [], total: d.total ?? 0 }
    },
  })

export const useInspection = (id: number | null) => useQuery({ queryKey: [...qcKeys.all, 'inspection', id], enabled: !!id, staleTime: 0, refetchOnMount: 'always', queryFn: () => get<{ inspection: Inspection; history: HistoryLine[] }>(`/api/qc/inspections/${id}`) })
export const useCube = (id: number | null) => useQuery({ queryKey: [...qcKeys.all, 'cube', id], enabled: !!id, staleTime: 0, refetchOnMount: 'always', queryFn: () => get<{ cube_set: CubeSet; history: HistoryLine[] }>(`/api/qc/cubes/${id}`) })
export const useNcr = (id: number | null) => useQuery({ queryKey: [...qcKeys.all, 'ncr', id], enabled: !!id, staleTime: 0, refetchOnMount: 'always', queryFn: () => get<{ ncr: Ncr; history: HistoryLine[] }>(`/api/qc/ncrs/${id}`) })

export const useTemplates = (job: number, manage = false) =>
  useQuery({ queryKey: [...qcKeys.all, 'checklists', job, manage], staleTime: 60_000, queryFn: async () => (await get<{ templates: Template[] }>(`/api/qc/checklists?job_id=${job}${manage ? '&manage=true' : ''}`)).templates })
export const useCriteria = (job: number) => useQuery({ queryKey: [...qcKeys.all, 'criteria', job], queryFn: async () => (await get<{ criteria: Criteria[] }>(`/api/qc/criteria${job ? `?job_id=${job}` : ''}`)).criteria })

/* ---- inspections ---- */

export interface InspectionForm {
  job_id: number; checklist: string; location: string; building: string; floor_area: string; work_activity: string
  assigned_to: string; inspected_on: string; witnessed_by: string; measurements: string; remarks: string
}
export const startInspection = (b: InspectionForm) => post<{ inspection: Inspection }>('/api/qc/inspections', b)
export const saveInspection = (i: Pick<Inspection, 'id' | 'job_id'> & Partial<Inspection>) =>
  put<{ inspection: Inspection }>(`/api/qc/inspections/${i.id}`, { job_id: i.job_id, items: i.items, remarks: i.remarks, measurements: i.measurements, location: i.location, building: i.building, floor_area: i.floor_area, work_activity: i.work_activity, assigned_to: i.assigned_to, witnessed_by: i.witnessed_by, inspected_on: i.inspected_on })
export const submitInspection = (id: number) => post<{ inspection: Inspection }>(`/api/qc/inspections/${id}/submit`)
export const returnInspection = (id: number, note: string) => post<{ inspection: Inspection }>(`/api/qc/inspections/${id}/return`, { note })
export const closeInspection = (id: number) => post<{ inspection: Inspection }>(`/api/qc/inspections/${id}/close`)
export const reinspect = (id: number) => post<{ inspection: Inspection }>(`/api/qc/inspections/${id}/reinspect`)

/* ---- checklists and criteria ---- */

export interface TemplateForm { name: string; work_type: string; job_id: number | null; spec_ref: string; items: { item: string; criteria: string }[]; is_active: boolean }
export const saveTemplate = (id: number | null, b: TemplateForm) => (id ? put<{ message?: string }>(`/api/qc/checklists/${id}`, b) : post<{ message?: string }>('/api/qc/checklists', b))
export const deleteTemplate = (id: number) => del<{ message: string }>(`/api/qc/checklists/${id}`)
export interface CriteriaForm { job_id: number; grade: string; age_days: number; min_mean: number; min_single: number; standard: string }
export const saveCriteria = (id: number | null, b: CriteriaForm) => (id ? put<{ message?: string }>(`/api/qc/criteria/${id}`, b) : post<{ message?: string }>('/api/qc/criteria', b))
export const deleteCriteria = (id: number) => del<{ message: string }>(`/api/qc/criteria/${id}`)

/* ---- cubes ---- */

export interface CubeForm { job_id: number; grade: string; cast_on: string; location: string; pour_ref: string; cube_ids: string; supplier: string; docket: string; slump_mm: number; test_ages: string; remarks: string }
export const logCubes = (b: CubeForm) => post<{ cube_set: CubeSet }>('/api/qc/cubes', b)
export const cubeResult = (id: number, b: { age_days: number; strengths: string; tested_on: string; lab: string; remarks: string; flag_review: boolean }) => post<{ cube_set: CubeSet }>(`/api/qc/cubes/${id}/results`, b)
export const flagCube = (id: number, note: string) => post<{ cube_set: CubeSet }>(`/api/qc/cubes/${id}/flag`, { note })
export const decideCube = (id: number, decision: string, note: string) => post<{ cube_set: CubeSet }>(`/api/qc/cubes/${id}/decision`, { decision, note })

/* ---- non-conformances ---- */

export const raiseNcr = (b: Record<string, unknown>) => post<{ ncr: Ncr }>('/api/qc/ncrs', b)
export const assignNcr = (id: number, b: { responsible: string; target_date: string; corrective_action: string; root_cause: string; severity: string }) => post<{ ncr: Ncr }>(`/api/qc/ncrs/${id}/assign`, b)
export const recordWork = (id: number, b: { corrective_done: string; root_cause: string }) => post<{ ncr: Ncr }>(`/api/qc/ncrs/${id}/work`, b)
export const requestVerification = (id: number) => post<{ ncr: Ncr }>(`/api/qc/ncrs/${id}/request-verification`)
export const verifyNcr = (id: number, result: 'verified' | 'rejected', note: string) => post<{ ncr: Ncr }>(`/api/qc/ncrs/${id}/verify`, { result, note })
export const closeNcr = (id: number, closure_note: string) => post<{ ncr: Ncr }>(`/api/qc/ncrs/${id}/close`, { closure_note })
