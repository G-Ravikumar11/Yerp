import { useQuery } from '@tanstack/react-query'
import { get } from '@/lib/api'

export interface BudgetMaterial {
  rm_code: string
  rm_name: string
  description: string
  qty: number
  uom: string
  rate: number
  wo_qty: number
  amount: number
}
export interface BudgetGroup {
  fg_code: string
  item_name: string
  value: number
  cost: number
  margin: number
  budgeted: boolean
  lines: BudgetMaterial[]
}
export interface BudgetReport {
  title: string
  company: string
  printed_at: string
  fiscal_year: string
  sale_order_no: string
  work_order_no: string
  project: string
  customer: string
  status: string
  groups: BudgetGroup[]
  totals: { ordered_lines: number; material_lines: number; unbudgeted_lines: number; value: number; cost: number; margin: number; margin_percent: number }
}

export const useBudgetReport = (id: number) => useQuery({ queryKey: ['orders', 'budget-report', id], queryFn: () => get<BudgetReport>(`/api/erp/work-orders/${id}/budget-report`), enabled: id > 0 })
