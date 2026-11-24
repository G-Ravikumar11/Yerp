import { useQuery } from '@tanstack/react-query'
import { apiUrl, get, post, put } from '@/lib/api'

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
  /** The budget's own wastage % on a material, as typed. It is what the cost uses only where the store has no norm. */
  wastage_percent?: number
  base_quantity?: number
  wastage_quantity?: number
  final_quantity?: number
}

/** Which wastage % a material is costed at, as the server worked it out: the store's norm where one is set for the material on
 * the BOQ item, else the budget's own. The screens show this and never decide it themselves. */
export interface WastageAnswer {
  budgeting_wastage_percent: number
  store_norm_wastage_percent: number | null
  effective_wastage_percent: number
  wastage_source: 'STORE_NORM' | 'BUDGETING'
  has_wastage_mismatch: boolean
  mismatch_message: string | null
}
export type SavedBudgetItem = BudgetItem & Partial<WastageAnswer>

export interface BudgetRow {
  key: string
  /** Given to sub contractors on this project's work orders (sent or approved) against this line. */
  given_out?: number
  /** More given out than the budget's labour + plant & other for the line. */
  given_over?: boolean
  /** The key of the BOQ heading this line is under ('' before the first heading). */
  under: string
  item_no: string
  group_code: string
  description: string
  uom: string
  quantity: number
  rate: number
  revenue: number
  rate_only: boolean
  item_code: string
  /** The grade the BOQ names for the line, or its heading does (M10). */
  grade?: string
  budgeted: boolean
  items: SavedBudgetItem[]
  /** Materials of this line whose budget wastage % differs from the store's norm (the norm is the one used). */
  wastage_mismatches?: number
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
  given_out?: number
  lines_over_given?: number
  losing: number
  projected_profit: number | null
  wastage_mismatches?: number
}

export interface Budget {
  job: { id: number; number: string; name: string }
  boq: { id: number; number: string; revision: number } | null
  overhead_percent: number
  contingency_percent: number
  note: string
  updated_by_name: string
  rows: BudgetRow[]
  /** The BOQ's section headings, each standing above the priced line `before` ('' = after the last one). */
  headings: { key: string; item_no: string; description: string; before: string; level?: number; path?: string[] }[]
  total: BudgetTotal
  sections: { group: string; revenue: number; cost: number; profit: number; margin: number | null }[]
}

export interface MaterialOption { code: string; name: string; uom: string; rate: number }

export const budgetKey = (job: number) => ['budgeting', job] as const

// Always read again on opening: the BOQ it prices is changed on other screens, and a budget is looked at straight after.
export const useBudget = (job: number) => useQuery({ queryKey: budgetKey(job), queryFn: () => get<Budget>(`/api/jobs/${job}/budget`), enabled: job > 0, staleTime: 0 })

export const saveBudgetLine = (job: number, key: string, items: BudgetItem[]) =>
  put<Budget>(`/api/jobs/${job}/budget/lines/${encodeURIComponent(key)}`, { items })

/** Ask the server which wastage % each item in the editor would be costed at, before saving. One answer per item, in order. */
export const resolveBudgetWastage = async (job: number, key: string, items: { kind: CostKind; item_code: string; wastage_percent: number }[]) =>
  (await post<{ items: WastageAnswer[] }>(`/api/jobs/${job}/budget/lines/${encodeURIComponent(key)}/wastage`, { items })).items

export const saveBudgetSettings =(job: number, body: { overhead_percent: number; contingency_percent: number; note: string }) =>
  put<Budget>(`/api/jobs/${job}/budget`, body)

export const budgetMaterials = (q: string) => get<MaterialOption[]>(`/api/budget/materials?q=${encodeURIComponent(q)}`)

export const budgetFileUrl = (job: number) => apiUrl(`/api/jobs/${job}/budget.xlsx`)

/** A margin to one decimal; zero is a real answer here, not a blank. */
export const pct = (v: number) => `${Math.round(v * 10) / 10}%`
