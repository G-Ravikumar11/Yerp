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

export const useSafety = (job: number) => useQuery({ queryKey: ['safety', job], enabled: job >= 0, queryFn: () => get<SafetyData>(`/api/safety${job ? `?job_id=${job}` : ''}`) })

export interface IncidentInput { job_id: number; kind: string; happened_on: string; happened_at: string; location: string; description: string; injured_name: string; injury: string; treatment: string; lost_days: number; immediate_action: string }
export const reportIncident = (b: IncidentInput) => post<{ incident: { number: string } }>('/api/safety/incidents', b)
export const closeIncident = (id: number, b: { root_cause: string; corrective_action: string }) => post<{ incident: { number: string } }>(`/api/safety/incidents/${id}/close`, b)
export const recordTalk = (b: { job_id: number; topic: string; attendees: number; attendee_names: string }) => post<{ message?: string }>('/api/safety/talks', b)
export interface PermitInput { job_id: number; kind: string; location: string; description: string; receiver: string; valid_from: string; valid_to: string; precautions: { item: string; done: boolean }[] }
export const issuePermit = (b: PermitInput) => post<{ permit: { number: string; valid_to: string } }>('/api/safety/permits', b)
export const closePermit = (id: number, note: string) => post<{ permit: { number: string } }>(`/api/safety/permits/${id}/close`, { note })

// Workers screened before they start on site: name, age, address, trade, and a photo and medical certificate as files.
export const workerKeys = { all: ['workers'] as const }
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
  photo_url: string
  photo_full_url: string
  medical: { id: number; name: string; url: string }[]
}
export interface WorkerData { workers: Worker[]; trades: string[]; min_age: number; summary: { workers: number; by_trade: Record<string, number>; without_medical: number; without_photo: number } }
export const useWorkers = (job: number) => useQuery({ queryKey: ['workers', job], queryFn: () => get<WorkerData>(`/api/workers${job ? `?job_id=${job}` : ''}`) })
export const screenWorker = (b: { job_id: number; name: string; age: number; address: string; trade: string; screened_on: string }) => post<{ worker: Worker }>('/api/workers', b)
export const removeWorker = (id: number) => del<{ message: string }>(`/api/workers/${id}`)
