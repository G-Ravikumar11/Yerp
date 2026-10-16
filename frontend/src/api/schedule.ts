import { useQuery } from '@tanstack/react-query'
import { del, get, post, put } from '@/lib/api'

export const schKeys = { all: ['schedule'] as const }

/** Where a row sits in the programme and what it is in the BOQ: shown beside its name, and what progress is read in. */
export interface Placing {
  /** 1.2.3, the programme's own numbering */
  wbs?: string
  /** The headings above it: "A-16 > Internal Painting" */
  path?: string
  boq_ref?: string
  /** With a quantity, progress is recorded as how much is done so far. */
  quantity?: number
  uom?: string
  qty_done?: number
}

export interface Activity extends Placing {
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
  assigned_to_id?: number | null
  assigned_to?: string
  overdue?: boolean
  days_late?: number
  delayed?: boolean
  predecessor_code?: string
  status?: string
  stored_status?: string
  notes?: string
}
export interface Employee { id: number; name: string }
export interface CurvePoint { week: string; planned: number | null; actual: number | null }
export interface Schedule {
  job?: { id: number; number: string; name: string; customer_name?: string; site_address?: string; status?: string }
  activities: Activity[]
  curve: CurvePoint[]
  employees?: Employee[]
  team_scope?: string
  summary: { start?: string; end?: string; duration_days?: number; overdue?: number; milestones?: number; milestones_done?: number; activities: number; planned_percent: number; actual_percent: number; variance: number; late: number; behind: number; done: number; planned_finish: string; forecast_finish: string; slip_days: number }
}
export interface ActivityInput { name: string; code: string; planned_start: string; planned_finish: string; weight: number; depends_on_id: number | null; work_order_line_id: number | null; is_milestone: boolean; assigned_to_id?: number | null; status?: string; notes?: string }
export interface WoLite { id: number; number: string; job_id: number; status: string }
export interface WoLine { id: number; label: string }

/** One row of a day's plan: an activity, how far along it is, and what the plan asks of it that day. */
export interface DayRow extends Placing {
  id: number
  code: string
  name: string
  bucket: 'today' | 'overdue' | 'soon' | 'later' | 'done'
  planned_start: string
  planned_finish: string
  is_milestone: boolean
  progress_from: string
  /** Where the plan has it by the end of the day, and where the work actually is. */
  planned_percent: number
  actual_percent: number
  /** The share of the activity the plan puts on this one day. */
  target_today: number
  /** What it would take to be back on plan by the end of the day. */
  to_catch_up: number
  remaining: number
  days_left: number | null
  starts_in: number | null
  days_late: number | null
  /** The last progress report on it: when, and who made it. */
  updated_on: string
  updated_by: string
  /** False when its progress comes from the measurement book. */
  editable: boolean
  /** Its tasks, all days: progress follows how many are done. */
  tasks_total: number
  tasks_done: number
  tasks: DayTask[]
}

/** Something to be done on a day, optionally under an activity. */
export interface DayTask {
  id: number
  activity_id: number | null
  activity: string
  date: string
  text: string
  done: boolean
  /** How much of the task is done: 100 when it is done, the part reported when it is only part done. */
  percent: number
  done_by_name: string
  done_at: string
  created_by_name: string
}
export interface DayPlan {
  job: { id: number; number: string; name: string }
  date: string
  today: DayRow[]
  overdue: DayRow[]
  soon: DayRow[]
  /** Every other activity on the site: finished, or starting further off. */
  others: DayRow[]
  tasks: DayTask[]
  summary: { working: number; overdue: number; starting_soon: number; done_percent: number; planned_percent: number; variance: number }
}

export const useDayPlan = (job: number, on: string) => useQuery({ queryKey: ['schedule', 'day', job, on], enabled: job > 0, queryFn: () => get<DayPlan>(`/api/jobs/${job}/schedule/day?on=${on}`) })
export interface ActivityDetail {
  job: { id: number; number: string; name: string }
  activity: Activity & Pick<DayRow, 'editable' | 'tasks_total' | 'tasks_done' | 'tasks' | 'updated_on' | 'updated_by'> & { planned_start: string; planned_finish: string }
  /** qty_done: the quantity done so far when it was reported that way */
  history: { on: string; percent: number; qty_done?: number | null; uom?: string; note: string; by: string }[]
}
export const useActivity = (id: number) => useQuery({ queryKey: ['schedule', 'activity', id], enabled: id > 0, queryFn: () => get<ActivityDetail>(`/api/schedule/activities/${id}`) })
export const useSchedule = (job: number) => useQuery({ queryKey: ['schedule', job], enabled: job > 0, staleTime: 0, refetchOnMount: 'always', queryFn: () => get<Schedule>(`/api/jobs/${job}/schedule`) })

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
export const setProgress = (id: number, percent: number, qty_done?: number) =>
  post<Reply>(`/api/schedule/activities/${id}/progress`, qty_done === undefined ? { percent } : { percent, qty_done })
export const addTask = (job: number, b: { text: string; date: string; activity_id: number | null }) => post<{ task: DayTask }>(`/api/jobs/${job}/schedule/tasks`, b)
export const editTask = (id: number, b: { text?: string; date?: string; activity_id?: number | null; done?: boolean; percent?: number }) => put<{ task: DayTask }>(`/api/schedule/tasks/${id}`, b)
export const deleteTask = (id: number) => del<{ ok: boolean }>(`/api/schedule/tasks/${id}`)
