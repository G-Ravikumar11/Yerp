import { get, post } from '@/lib/api'
import type { Flag } from '@/api/aiSubcontracts'
import type { Schedule } from '@/api/schedule'

interface Off { available: boolean; message?: string; reason?: string }

export interface DraftActivity { line_id: number; name: string; weight: number; start: string; finish: string; after_line_id: number | null }
export interface PlanDraft extends Off { work_order_id?: number | null; boq_id?: number | null; activities: DraftActivity[] }
/** What a programme is drafted from: the project's BOQ, or one of its placed work orders. */
export type DraftSource = { boq: true } | { work_order_id: number }
interface DayTaskIdea { text: string; activity_id: number | null; activity: string }
export interface DayIdeas extends Off { date: string; tasks: DayTaskIdea[] }
interface PlanFinding extends Flag { activity_id: number | null }
export interface PlanReview extends Off {
  summary: string
  findings: PlanFinding[]
  progress: { actual_percent: number; planned_percent: number; variance: number; slip_days: number; forecast_finish: string; planned_finish: string }
}
export interface PlanAnswer extends Off { answer: string }

const base = (job: number) => `/api/ai/planning/jobs/${job}`

/** A proposed programme from the BOQ or a work order. Nothing is saved. */
export const draftProgramme = (job: number, source: DraftSource, start: string, finish: string) => post<PlanDraft>(`${base(job)}/draft`, { ...source, start, finish })
/** Saves the programme a person has checked. */
export const applyDraft = (job: number, source: DraftSource, activities: DraftActivity[]) => post<{ schedule: Schedule; message?: string }>(`${base(job)}/draft/apply`, { ...source, activities })
/** Tasks suggested for a day. Nothing is saved. */
export const suggestDay = (job: number, on: string) => post<DayIdeas>(`${base(job)}/day-plan`, { on })
export const reviewPlan = (job: number) => get<PlanReview>(`${base(job)}/review`)
export const askPlan = (job: number, question: string) => post<PlanAnswer>(`${base(job)}/ask`, { question })
