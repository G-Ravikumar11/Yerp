import { useQuery } from '@tanstack/react-query'
import { get } from '@/lib/api'

export interface CostMix { key: string; label: string; amount: number }
export interface CostRow {
  job_id: number
  number: string
  name: string
  customer_name: string
  contract_value: number
  percent_complete: number
  incurred: number
  commitment: number
  forecast_cost: number
  over_budget: number
  margin: number
  margin_percent: number
  invoiced: number
  over_billed: number
  unpaid: number
  bills_awaiting_approval: number
}
export interface CostSummary { sold: number; incurred: number; commitment: number; forecast_cost: number; margin: number; retention_held: number; outstanding: number; over_budget: number; categories: CostMix[] }
export interface ProjectCosts extends CostRow {
  estimate: number
  labour: number
  labour_hours: number
  cost_to_complete: number
  earned: number
  outstanding: number
  retention_held: number
  retention_percent: number
  billed: number
  paid: number
  categories: CostMix[]
  work_order_list: { number: string; status: string; approval: string; value: number }[]
  purchase_order_list: { number: string; supplier: string; status: string; total: number }[]
  subcontract_list: { number: string; status: string; net: number }[]
  bill_list: { number: string; supplier: string; status: string; approval: string; total: number }[]
}
export interface PnlRow { job_id: number; number: string; name: string; customer_name: string; order_value: number; revenue: number; incurred: number; committed: number; margin: number; margin_percent: number; mandays: number; losing: boolean; over_budget: boolean; status: string }
export interface Pnl { summary: { projects: number; order_value: number; revenue: number; incurred: number; margin: number; owed_to_us: number }; projects: PnlRow[] }

export const useCosts = () => useQuery({ queryKey: ['costs', 'list'], queryFn: () => get<{ projects: CostRow[]; summary: CostSummary }>('/api/costs/by-project') })
export const useProjectCosts = (id: number) => useQuery({ queryKey: ['costs', 'one', id], enabled: id > 0, queryFn: () => get<ProjectCosts>(`/api/costs/by-project/${id}`) })
export const usePnl = () => useQuery({ queryKey: ['costs', 'pnl'], queryFn: () => get<Pnl>('/api/jobs-pnl') })
