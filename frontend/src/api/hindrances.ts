import { useQuery } from '@tanstack/react-query'
import { del, get, post, put } from '@/lib/api'

export const hindranceKeys = { all: ['hindrances'] as const }

/** Something that held the work up: the cause, from when to when, whose risk it was, the days it cost, when the client was told. */
export interface Hindrance {
  id: number
  job_id: number
  number: string
  activity_id: number | null
  activity: string
  diary_id: number | null
  cause: string
  description: string
  from_date: string
  /** Blank while it is still holding the work up. */
  to_date: string
  ongoing: boolean
  /** Calendar days from its first day to its last (or to today while it goes on). */
  running_days: number
  responsibility: string
  /** Working days it cost the work. */
  impact_days: number
  notice_date: string
  status: string
  open: boolean
  /** The client's risk and not yet told in writing. */
  notice_due: boolean
  created_by_name: string
  created_at: string
}
export interface HindranceInput {
  activity_id?: number | null
  diary_id?: number | null
  cause: string
  description: string
  from_date: string
  to_date: string
  responsibility: string
  impact_days: number
  notice_date: string
  status: string
}
export interface Register {
  hindrances: Hindrance[]
  summary: { total: number; open: number; ongoing: number; impact_days: number; client_days: number; notice_due: number; by_party: Record<string, number> }
  choices: { causes: string[]; parties: string[]; statuses: string[] }
}
export interface DiaryDraft { draft: HindranceInput & { job_id: number }; has_cause: boolean; already: Hindrance[] }

export const useRegister = (job: number) => useQuery({ queryKey: [...hindranceKeys.all, job], enabled: job > 0, queryFn: () => get<Register>(`/api/jobs/${job}/hindrances`) })
export const useDiaryDraft = (diary: number) => useQuery({ queryKey: [...hindranceKeys.all, 'diary', diary], enabled: diary > 0, staleTime: 0, queryFn: () => get<DiaryDraft>(`/api/diary/${diary}/hindrance-draft`) })
export const registerXlsx = (job: number) => `/api/jobs/${job}/hindrances.xlsx`

type Reply = { hindrance: Hindrance; message?: string }
export const saveHindrance = (job: number, id: number | null, b: HindranceInput) => (id ? put<Reply>(`/api/hindrances/${id}`, b) : post<Reply>(`/api/jobs/${job}/hindrances`, b))
export const deleteHindrance = (id: number) => del<{ message?: string }>(`/api/hindrances/${id}`)

/** The same lists the server checks against (constants/projects.py). */
export const CAUSES = ['Rain / weather', 'Drawings or details awaited', 'Client decision awaited', 'Site or front not handed over', 'Payment held up', 'Material shortage', 'Labour shortage', 'Plant breakdown', 'Utility shifting', 'Change in scope', 'Statutory approval', 'Other'] as const
export const PARTIES = ['Client', 'Contractor', 'Subcontractor', 'Neither (force majeure)'] as const
export const STATUSES = ['Open', 'Notified', 'Agreed', 'Rejected', 'Closed'] as const
