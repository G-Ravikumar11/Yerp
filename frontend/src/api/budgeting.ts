import { useQuery } from '@tanstack/react-query'
import { apiUrl, get, put } from '@/lib/api'

export type CostKind = 'MATERIAL' | 'LABOUR' | 'OTHER'

export const COST_KINDS: { value: CostKind; label: string }[] = [
  { value: 'MATERIAL', label: 'Material' },
  { value: 'LABOUR', label: 'Labour' },
  { value: 'OTHER', label: 'Plant & other' },
]

/** One thing that goes into one unit of a BOQ line: so much of it (quantity) at so much each (rate). */
export interface BudgetItem {
  id?: number
  kind: CostKind
  description: string
  uom: string
  coefficient: number
  rate: number
  item_code: string
  per_unit?: number
}

export interface BudgetRow {
  key: string
  item_no: string
  group_code: string
  description: string
  uom: string
  quantity: number
  rate: number
  revenue: number
  rate_only: boolean
  item_code: string
  budgeted: boolean
  items: BudgetItem[]
  unit_material: number
  unit_labour: number
  unit_other: number
  unit_cost: number
  material: number
  labour: number
  other: number
  direct: number
  overheads: number
  contingency: number
  cost: number
  profit: number | null
  margin: number | null
}

export interface BudgetTotal {
  boq_value: number
  budgeted_value: number
  unbudgeted_value: number
  material: number
  labour: number
  other: number
  direct: number
  overheads: number
  contingency: number
  cost: number
  profit: number
  margin: number | null
  lines: number
  lines_budgeted: number
  losing: number
  projected_profit: number | null
}

export interface Budget {
  job: { id: number; number: string; name: string }
  boq: { id: number; number: string; revision: number } | null
  overhead_percent: number
  contingency_percent: number
  note: string
  updated_by_name: string
  rows: BudgetRow[]
  total: BudgetTotal
  sections: { group: string; revenue: number; cost: number; profit: number; margin: number | null }[]
}

export interface MaterialOption { code: string; name: string; uom: string; rate: number }

export const budgetKey = (job: number) => ['budgeting', job] as const

// Always read again on opening: the BOQ it prices is changed on other screens, and a budget is looked at straight after.
export const useBudget = (job: number) => useQuery({ queryKey: budgetKey(job), queryFn: () => get<Budget>(`/api/jobs/${job}/budget`), enabled: job > 0, staleTime: 0 })

export const saveBudgetLine = (job: number, key: string, items: BudgetItem[]) =>
  put<Budget>(`/api/jobs/${job}/budget/lines/${encodeURIComponent(key)}`, { items })

export const saveBudgetSettings = (job: number, body: { overhead_percent: number; contingency_percent: number; note: string }) =>
  put<Budget>(`/api/jobs/${job}/budget`, body)

export const budgetMaterials = (q: string) => get<MaterialOption[]>(`/api/budget/materials?q=${encodeURIComponent(q)}`)

export const budgetFileUrl = (job: number) => apiUrl(`/api/jobs/${job}/budget.xlsx`)

/** A margin to one decimal; zero is a real answer here, not a blank. */
export const pct = (v: number) => `${Math.round(v * 10) / 10}%`
