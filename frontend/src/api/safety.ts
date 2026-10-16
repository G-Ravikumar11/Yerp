import { useQuery } from '@tanstack/react-query'
import { del, get, post } from '@/lib/api'

export const safetyKeys = { all: ['safety'] as const }

export interface Incident {
  id: number
  number: string
  happened_on: string
  happened_at: string
  kind: string
  serious: boolean
  location: string
  description: string
  injured_name: string
  injury: string
  lost_days: number
  root_cause: string
  corrective_action: string
  status: string
}
export interface Talk { id: number; held_on: string; topic: string; notes: string; conducted_by: string; attendees: number; attendee_names: string }
export interface Permit { id: number; number: string; kind: string; location: string; valid_from: string; valid_to: string; receiver: string; status: string; expired: boolean }
export interface SafetySummary { days_without_lti: number | null; incidents_this_month: number; near_misses: number; open: number; talks_this_week: number; active_permits: number; expired_open: number }
export interface SafetyData { incidents: Incident[]; talks: Talk[]; permits: Permit[]; summary: SafetySummary; kinds: string[]; permit_kinds: Record<string, string[]> }

export type HseGo = 'workers' | 'incidents' | 'talks' | 'permits'
export interface HseCheckItem { key: string; rule: string; label: string; status: 'ok' | 'warn' | 'bad' | 'info'; count: number; detail: string; go: HseGo }
export const useHseCheck = (job: number) => useQuery({ queryKey: ['safety', 'hse', job], queryFn: () => get<{ items: HseCheckItem[]; ok: number; total: number }>(`/api/safety/hse-check${job ? `?job_id=${job}` : ''}`) })

export const useSafety = (job: number) => useQuery({ queryKey: ['safety', job], enabled: job >= 0, queryFn: () => get<SafetyData>(`/api/safety${job ? `?job_id=${job}` : ''}`) })

export interface IncidentInput { job_id: number; kind: string; happened_on: string; happened_at: string; location: string; description: string; injured_name: string; injury: string; treatment: string; lost_days: number; immediate_action: string }
export const reportIncident = (b: IncidentInput) => post<{ incident: { number: string } }>('/api/safety/incidents', b)
export const closeIncident = (id: number, b: { root_cause: string; corrective_action: string }) => post<{ incident: { number: string } }>(`/api/safety/incidents/${id}/close`, b)
export const recordTalk = (b: { job_id: number; topic: string; attendees: number; attendee_names: string }) => post<{ message?: string }>('/api/safety/talks', b)
export interface PermitInput { job_id: number; kind: string; location: string; description: string; receiver: string; valid_from: string; valid_to: string; precautions: { item: string; done: boolean }[] }
export const issuePermit = (b: PermitInput) => post<{ permit: { number: string; valid_to: string } }>('/api/safety/permits', b)
export const closePermit = (id: number, note: string) => post<{ permit: { number: string } }>(`/api/safety/permits/${id}/close`, { note })

// Workers screened before they start on site, after the company's own paper "Screening Of Worker" form: who they
// are, their trade, their physical and education details, previous work, and a photo and medical certificate as files.
export const workerKeys = { all: ['workers'] as const }
export interface EducationRow { exam: string; year: string; school: string }
export interface ExperienceRow { organization: string; project_site: string; category: string; period: string; salary: string }
export interface WorkerPaper { id: number; name: string; url: string; image: boolean }
export interface Worker {
  id: number
  job_id: number
  number: string
  name: string
  age: number
  address: string
  trade: string
  screened_on: string
  screened_by: string
  contractor_name: string
  father_name: string
  dob: string
  sex: string
  marital_status: string
  children: number
  mother_tongue: string
  other_languages: string
  emergency_contact: string
  phone: string
  identification_mark: string
  vision_normal: boolean
  vision_problem: string
  health_normal: boolean
  health_problem: string
  weight_kg: number
  height_cm: number
  blood_group: string
  education: EducationRow[]
  experience: ExperienceRow[]
  certificates_verified: boolean
  trial_briefed: boolean
  safety_officer_name: string
  pan: string
  /** Never the whole number: XXXX XXXX and the last four digits. */
  aadhaar_masked: string
  pan_card: WorkerPaper[]
  aadhaar_card: WorkerPaper[]
  photo_url: string
  photo_full_url: string
  medical: { id: number; name: string; url: string }[]
}
export interface WorkerData { workers: Worker[]; trades: string[]; min_age: number; sexes: string[]; marital_statuses: string[]; summary: { workers: number; by_trade: Record<string, number>; without_medical: number; without_photo: number } }
export const useWorkers = (job: number) => useQuery({ queryKey: ['workers', job], queryFn: () => get<WorkerData>(`/api/workers${job ? `?job_id=${job}` : ''}`) })
export interface WorkerInput {
  job_id: number; name: string; age: number; address: string; trade: string; screened_on: string
  contractor_name?: string; father_name?: string; dob?: string; sex?: string; marital_status?: string
  children?: number; mother_tongue?: string; other_languages?: string; emergency_contact?: string; phone?: string
  identification_mark?: string; vision_normal?: boolean; vision_problem?: string; health_normal?: boolean
  health_problem?: string; weight_kg?: number; height_cm?: number; blood_group?: string
  education?: EducationRow[]; experience?: ExperienceRow[]
  certificates_verified?: boolean; trial_briefed?: boolean; safety_officer_name?: string
  pan?: string; aadhaar?: string
}
export const screenWorker = (b: WorkerInput) => post<{ worker: Worker }>('/api/workers', b)
export const removeWorker = (id: number) => del<{ message: string }>(`/api/workers/${id}`)

// Equipment checks: the company's inspection checklists - portable grinder, breaking machine, hammer drill, fire
// extinguisher and electrical board - each answered item by item, with photos, readings and sign-offs.
export interface CheckFormItem { key: string; label: string; section?: string; bad_if_yes: boolean; optional: boolean }
export interface CheckForm {
  key: string
  label: string
  title: string
  doc_ref: string
  equipment_label: string
  specs_label: string
  fields: string[]
  extinguisher_types?: string[]
  default_interval_days?: number
  items: CheckFormItem[]
  readings: { key: string; label: string; unit: string }[]
  signoffs: { role: string; label: string }[]
  review: { label: string; signoff_label: string } | null
}
export interface CheckPhoto { id: number; url: string; thumb_url: string }
export interface CheckItem extends CheckFormItem { answer: string; remarks: string; photos: CheckPhoto[] }
export interface Check {
  id: number
  job_id: number
  project: string
  number: string
  form_type: string
  form_label: string
  doc_ref: string
  equipment_no: string
  specs: string
  location: string
  extinguisher_type: string
  board_type: string
  contractor_name: string
  inspection_date: string
  next_inspection_date: string
  items: CheckItem[]
  readings: Record<string, number>
  signoffs: Record<string, { name: string; date: string }>
  has_review: boolean
  decision: '' | 'accepted' | 'rejected'
  decision_by: string
  decision_on: string
  recorded_by: string
  result: 'pass' | 'fail'
  failed: string[]
  rpm_wrong: boolean
  photo_count: number
  current: boolean
  due_in_days: number | null
  due_state: '' | 'ok' | 'soon' | 'overdue'
}
export interface CheckSummary { total: number; equipment: number; failed: number; overdue: number; due_soon: number; awaiting_review: number }
export interface CheckData { checks: Check[]; forms: CheckForm[]; summary: CheckSummary }
export const useChecks = (job: number, form = '') => useQuery({
  queryKey: ['safety', 'checks', job, form],
  queryFn: () => get<CheckData>(`/api/safety/checks?${new URLSearchParams({ ...(job ? { job_id: String(job) } : {}), ...(form ? { form_type: form } : {}) })}`),
})
export interface CheckInput {
  job_id: number; form_type: string; equipment_no: string; specs: string; location: string; extinguisher_type: string
  board_type: string; contractor_name: string; inspection_date: string; next_inspection_date: string
  items: { key: string; answer: string; remarks: string }[]
  readings: Record<string, number>
  signoffs: Record<string, { name: string; date: string }>
}
export const recordCheck = (b: CheckInput) => post<{ check: Check }>('/api/safety/checks', b)
export const signCheck = (id: number, b: { role: string; name: string; date: string; decision?: string }) => post<{ check: Check }>(`/api/safety/checks/${id}/signoff`, b)
export const removeCheck = (id: number) => del<{ message: string }>(`/api/safety/checks/${id}`)
/** A fault is a No on an item worded the good way, or a Yes on one worded the faulty way (is it corroded?). */
export const isFault = (i: { answer: string; bad_if_yes: boolean }) => (i.answer === 'yes' || i.answer === 'no') && (i.answer === 'yes') === i.bad_if_yes
