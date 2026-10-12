import { get, post } from '@/lib/api'
import type { Flag } from '@/api/aiSubcontracts'
import type { Schedule } from '@/api/schedule'

interface Off { available: boolean; message?: string; reason?: string }

export interface DraftActivity { line_id: number; name: string; weight: number; start: string; finish: string; after_line_id: number | null }
export interface PlanDraft extends Off { work_order_id?: number; activities: DraftActivity[] }
export interface DayTaskIdea { text: string; activity_id: number | null; activity: string }
export interface DayIdeas extends Off { date: string; tasks: DayTaskIdea[] }
export interface PlanFinding extends Flag { activity_id: number | null }
export interface PlanReview extends Off {
  summary: string
  findings: PlanFinding[]
  progress: { actual_percent: number; planned_percent: number; variance: number; slip_days: number; forecast_finish: string; planned_finish: string }
}
export interface PlanAnswer extends Off { answer: string }

const base = (job: number) => `/api/ai/planning/jobs/${job}`

/** A proposed programme from a work order. Nothing is saved. */
export const draftProgramme = (job: number, work_order_id: number, start: string, finish: string) => post<PlanDraft>(`${base(job)}/draft`, { work_order_id, start, finish })
/** Saves the programme a person has checked. */
export const applyDraft = (job: number, work_order_id: number, activities: DraftActivity[]) => post<{ schedule: Schedule; message?: string }>(`${base(job)}/draft/apply`, { work_order_id, activities })
/** Tasks suggested for a day. Nothing is saved. */
export const suggestDay = (job: number, on: string) => post<DayIdeas>(`${base(job)}/day-plan`, { on })
export const reviewPlan = (job: number) => get<PlanReview>(`${base(job)}/review`)
export const askPlan = (job: number, question: string) => post<PlanAnswer>(`${base(job)}/ask`, { question })
