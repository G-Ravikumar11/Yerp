import { useQuery } from '@tanstack/react-query'
import { del, get, post, put } from '@/lib/api'

export const schKeys = { all: ['schedule'] as const }

export interface Activity {
  id: number
  code: string
  name: string
  planned_start: string
  planned_finish: string
  forecast_finish: string
  weight: number
  is_milestone: boolean
  depends_on: string
  depends_on_id: number | null
  work_order_line_id: number | null
  progress_from: string
  actual_percent: number
  planned_percent: number
  state: string
  slip_days: number
}
export interface CurvePoint { week: string; planned: number | null; actual: number | null }
export interface Schedule {
  activities: Activity[]
  curve: CurvePoint[]
  summary: { activities: number; planned_percent: number; actual_percent: number; variance: number; late: number; behind: number; done: number; planned_finish: string; forecast_finish: string; slip_days: number }
}
export interface ActivityInput { name: string; code: string; planned_start: string; planned_finish: string; weight: number; depends_on_id: number | null; work_order_line_id: number | null; is_milestone: boolean }
export interface WoLite { id: number; number: string; job_id: number; status: string }
export interface WoLine { id: number; label: string }

export const useSchedule = (job: number) => useQuery({ queryKey: ['schedule', job], enabled: job > 0, queryFn: () => get<Schedule>(`/api/jobs/${job}/schedule`) })

/** The placed work orders of a project - each of their lines can carry an activity's progress. */
export const useWorkOrdersOf = (job: number) =>
  useQuery({ queryKey: ['schedule', 'work-orders', job], enabled: job > 0, queryFn: async () => ((await get<{ work_orders: WoLite[] }>('/api/erp/work-orders')).work_orders ?? []).filter((w) => w.job_id === job && w.status !== 'Draft') })

export const useWorkOrderLines = (orders: WoLite[]) =>
  useQuery({
    queryKey: ['schedule', 'lines', orders.map((o) => o.id).join(',')],
    enabled: orders.length > 0,
    queryFn: async (): Promise<WoLine[]> => {
      const out: WoLine[] = []
      for (const o of orders) {
        const full = await get<{ lines?: { id: number; fg_code?: string; description?: string; item_name?: string }[] }>(`/api/erp/work-orders/${o.id}`)
        for (const l of full.lines ?? []) out.push({ id: l.id, label: `${o.number} - ${l.fg_code ?? ''} ${(l.description || l.item_name || '').split('\n')[0]}`.trim() })
      }
      return out
    },
  })

type Reply = { schedule: Schedule; message?: string }
export const saveActivity = (job: number, id: number | null, b: ActivityInput) => (id ? put<Reply>(`/api/schedule/activities/${id}`, b) : post<Reply>(`/api/jobs/${job}/schedule/activities`, b))
export const deleteActivity = (id: number) => del<Reply>(`/api/schedule/activities/${id}`)
export const setProgress = (id: number, percent: number) => post<Reply>(`/api/schedule/activities/${id}/progress`, { percent })
export const drawFromOrder = (job: number, wo: number, start: string, finish: string) => post<Reply>(`/api/jobs/${job}/schedule/from-work-order/${wo}`, { start, finish })
