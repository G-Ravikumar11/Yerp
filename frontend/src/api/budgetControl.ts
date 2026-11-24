import { useQuery } from '@tanstack/react-query'
import { get } from '@/lib/api'
import { budgetKey } from './budgeting'

/**
 * HO QS budget control, as the server works it out (services/budget_control.py): every figure here is the server's -
 * the screens only show them, so they cannot disagree with the check made when a work order is sent.
 */
export type LineStatus = 'Budgeted' | 'Partially budgeted' | 'Not budgeted'

export interface BudgetSummary {
  lines: number; budgeted: number; partial: number; unbudgeted: number
  approved_value: number; budgeted_value: number; remaining_value: number
  completion_percent: number; value_percent: number
  status: 'Complete' | 'Incomplete' | 'Not started' | 'No BOQ lines'
}
export interface BudgetControlLine {
  key: string; item_no: string; item_code: string; description: string; unit: string; status: LineStatus
  approved_qty: number; approved_value: number; budgeted_qty: number; budgeted_value: number; remaining_qty: number; remaining_value: number
  budget_per_unit: number; contractor_budget: number; committed_qty: number; committed_value: number; available_qty: number; available_value: number
}
export interface ProjectBudgetControl { job_id: number; code: string; name: string; live: boolean; summary: BudgetSummary; lines: BudgetControlLine[] }
export interface LiveProjectBudget { job_id: number; code: string; name: string; summary: BudgetSummary }

export interface OrderBudgetLine {
  key: string; item: string; unit: string; this_order_qty: number; this_order_value: number; available_qty: number; available_value: number; budget_per_unit: number
  short_qty?: number; short_value?: number
}
export interface OrderBudgetCheck {
  applies: boolean; can_send: boolean
  project: { job_id: number; code: string; name: string } | null
  /** The project's lines still to budget: while any is left, the order is neither sent nor approved. */
  missing: { key: string; item: string; status: LineStatus; unit: string; quantity: number; value: number | null }[]
  /** Past the BOQ quantity left: sent with a warning, approved only by the Master's override. */
  over_quantity: OrderBudgetLine[]
  /** Past the contractor budget left: sent only with a reason, and the Master signs it. */
  over_value: OrderBudgetLine[]
  lines: OrderBudgetLine[]
}

export const hoBudgetKey = ['budgeting', 'ho-control'] as const
/** With the order's own keys, so saving the order's schedule refreshes it too. */
export const woBudgetKey = (order: number) => ['orders', 'budget-check', order] as const

export const useHoBudgetControl = (enabled: boolean) =>
  useQuery({ queryKey: hoBudgetKey, enabled, staleTime: 0, queryFn: () => get<{ projects: LiveProjectBudget[] }>('/api/ho/budget-control') })
/** Under the Budgeting page's own key, so saving a line's budget refreshes it with the page. */
export const useProjectBudgetControl = (job: number) =>
  useQuery({ queryKey: [...budgetKey(job), 'control'], enabled: job > 0, staleTime: 0, queryFn: () => get<ProjectBudgetControl>(`/api/jobs/${job}/budget-control`) })
export const useOrderBudgetCheck = (order: number, enabled = true) =>
  useQuery({ queryKey: woBudgetKey(order), enabled: enabled && order > 0, staleTime: 0, queryFn: () => get<OrderBudgetCheck>(`/api/wo/orders/${order}/budget-check`) })

/** What else to refresh once a budget is saved: the HO list, the Setup Check and any work order's check. */
export const budgetControlKeys = [hoBudgetKey, ['setup-check'], ['orders', 'budget-check']] as const

export const STATUS_TONE: Record<string, 'success' | 'warning' | 'danger' | 'neutral'> = {
  Budgeted: 'success', 'Partially budgeted': 'warning', 'Not budgeted': 'danger',
  Complete: 'success', Incomplete: 'warning', 'Not started': 'danger', 'No BOQ lines': 'neutral',
}
