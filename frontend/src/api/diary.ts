import { useQuery } from '@tanstack/react-query'
import { get, post } from '@/lib/api'

export const diaryKeys = { all: ['diary'] as const }

export interface DiaryRow {
  id: number
  job_id: number
  diary_date: string
  weather: string
  rain_hours: number
  working_hours: number
  work_done: string
  holdups: string
  instructions: string
  visitors: string
  safety_note: string
  labour_cost: number
  plant_cost: number
  total_mandays: number
  status: string
  submitted_at: string
  /** Who signed the day off. */
  submitted_by_name?: string
  /** Each time the day was reopened after sign-off: when, by whom and why. */
  amendments?: string[]
  editable: boolean
  lost_to_weather: boolean
}
export interface LabourLine {
  trade: string; agency: string; headcount: number; hours: number; rate: number
  /** Set when this line was added "from Workers & Safety" rather than typed by hand: the headcount then always
   * matches how many are named here, and they are shown by name, not just counted. */
  worker_ids?: number[]
  workers?: { id: number; name: string; trade: string }[]
}
export interface PlantLine { plant: string; worked_hours: number; idle_hours: number; rate: number }
export interface DiaryDetail extends DiaryRow { labour: LabourLine[]; plant: PlantLine[] }
export interface DiarySummary { days_recorded: number; mandays: number; labour_cost: number; plant_cost: number; days_lost_to_weather: number; not_yet_submitted: number }
export interface DiaryInput {
  job_id: number
  diary_date: string
  weather: string
  rain_hours: number
  working_hours: number
  work_done: string
  holdups: string
  instructions: string
  visitors: string
  safety_note: string
  labour: LabourLine[]
  plant: PlantLine[]
  /** Planned work the day reports done: tasks ticked, activities now so far along. Applied to Planning & Progress on save. */
  work_updates?: WorkUpdate[]
}
export type WorkUpdate = { task_id: number; done: boolean } | { task_id: number; percent: number } | { activity_id: number; percent: number }
export interface LabourHistory { summary: { mandays: number; days_worked: number; average_crew: number; labour_cost: number; rain_hours: number }; by_trade: { trade: string; mandays: number; cost: number }[] }

export const useDiaries = (job: number) => useQuery({ queryKey: ['diary', 'list', job], enabled: job > 0, queryFn: () => get<{ diaries: DiaryRow[]; summary: DiarySummary }>(`/api/diary?job_id=${job}`) })
export const useDiary = (id: number | null) => useQuery({ queryKey: ['diary', 'one', id], enabled: !!id, queryFn: () => get<DiaryDetail>(`/api/diary/${id}`) })
export const useLabourHistory = (job: number) => useQuery({ queryKey: ['diary', 'labour', job], enabled: job > 0, queryFn: () => get<LabourHistory>(`/api/diary-labour/${job}`) })
export const signOffDiary = (id: number) => post<{ message: string }>(`/api/diary/${id}/submit`)
export const reopenDiary = (id: number, reason: string) => post<{ message: string }>(`/api/diary/${id}/reopen`, { reason })

export const TRADES = ['Mason', 'Helper', 'Carpenter', 'Bar bender', 'Fitter', 'Electrician', 'Plumber', 'Painter', 'Operator', 'Driver', 'Surveyor', 'Supervisor']
export const WEATHER = ['Clear', 'Cloudy', 'Rain', 'Heavy rain']
