import { useQuery } from '@tanstack/react-query'
import { apiUrl, get } from '@/lib/api'

/** Figures shared by a line, a heading and the project: budget, planned value, earned value, actual cost. */
interface Figures {
  budget: number
  pv: number
  ev: number
  ac: number
  /** EV - AC: positive is under budget for the work done. */
  variance: number
  /** EV / AC (null with nothing spent) and EV / PV (null with nothing planned yet). */
  cpi: number | null
  spi: number | null
  planned_percent: number
  done_percent: number
}
export interface EvLine extends Figures {
  key: string
  item_no: string
  description: string
  uom: string
  budgeted: boolean
  path: string[]
  /** Where its % done came from: its own activity, a heading's, or '' (no activity drawn on it). */
  progress_from: '' | 'line' | 'heading'
  material: number
  subcontract: number
  overrun: boolean
}
export interface EvHeading extends Figures {
  key: string
  item_no: string
  description: string
  level: number
  path: string[]
  lines: number
  overrun: boolean
  over_by: number
}
export interface EarnedValue {
  job: { id: number; number: string; name: string }
  boq: { id: number; number: string; revision: number } | null
  as_of: string
  lines: EvLine[]
  headings: EvHeading[]
  not_against_a_line: { material: number; subcontract: number }
  total: Figures & { ac_on_lines: number; eac: number | null; vac: number | null; lines_with_progress: number; lines: number; overruns: number }
}

export const useEarnedValue = (job: number) => useQuery({ queryKey: ['budgeting', 'ev', job], enabled: job > 0, staleTime: 0, queryFn: () => get<EarnedValue>(`/api/jobs/${job}/budget/earned-value`) })
export const earnedValueFileUrl = (job: number) => apiUrl(`/api/jobs/${job}/budget/earned-value.xlsx`)
