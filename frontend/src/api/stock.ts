import { useQuery } from '@tanstack/react-query'
import { get, post } from '@/lib/api'

export const stockKeys = { all: ['stock'] as const }

export interface StockRow { item_code: string; item_name: string; uom: string; received: number; issued: number; on_hand: number; rate: number; value: number; negative: boolean; below_level: boolean; reorder_level: number }
export interface StockSummary { items_held: number; value_on_hand: number; below_reorder: number; negative_lines: number }
export interface Movement { moved_on: string; kind: string; quantity: number; rate: number; balance: number; source_ref: string; remarks: string }
export interface Ledger { item_name: string; uom: string; on_hand: number; rate: number; value: number; movements: Movement[] }
export interface Issue { id: number; number: string; work_order: string; purpose: string; issued_to: string; issued_on: string; total_value: number; status: string }
export interface IssueSummary { notes: number; not_yet_posted: number; issued_value: number }
export interface Consumption {
  summary: { planned_value: number; issued_value: number; variance_value: number; lines_over_consumed: number; unplanned_items: number }
  lines: { item_code: string; item_name: string; planned_qty: number; issued_qty: number; variance_qty: number; variance_value: number; percent_used: number; over_consumed: boolean; unplanned: boolean }[]
}

export const useStock = (lowOnly: boolean, store = '') => useQuery({ queryKey: ['stock', 'held', lowOnly, store], queryFn: () => get<{ stock: StockRow[]; summary: StockSummary }>(`/api/stock?${lowOnly ? 'low_only=true&' : ''}${store ? `store=${encodeURIComponent(store)}` : ''}`) })
export const useLedger = (code: string | null) => useQuery({ queryKey: ['stock', 'ledger', code], enabled: !!code, queryFn: () => get<Ledger>(`/api/stock/${encodeURIComponent(code as string)}/ledger`) })
export const useIssues = () => useQuery({ queryKey: ['stock', 'issues'], queryFn: () => get<{ issues: Issue[]; summary: IssueSummary }>('/api/stock-issues') })
export const useStores = () => useQuery({ queryKey: ['stock', 'stores'], queryFn: async () => (await get<{ stores: { store: string; value: number }[] }>('/api/stock/stores')).stores ?? [] })
export const useConsumption = (wo: number) => useQuery({ queryKey: ['stock', 'consumption', wo], enabled: wo > 0, queryFn: () => get<Consumption>(`/api/stock/consumption/${wo}`) })
export const usePlacedOrders = () => useQuery({ queryKey: ['stock', 'placed-orders'], queryFn: async () => ((await get<{ work_orders: { id: number; number: string; job_name: string; status: string }[] }>('/api/erp/work-orders')).work_orders ?? []).filter((w) => w.status !== 'Draft') })
export const useGangOrders = () => useQuery({ queryKey: ['stock', 'gang-orders'], queryFn: async () => ((await get<{ orders: { id: number; wo_number: string; contractor: string; status: string }[] }>('/api/wo/orders')).orders ?? []).filter((o) => o.status === 'APPROVED' || o.status === 'EXECUTED') })

export const countStock = (item_code: string, counted: number) => post<{ message: string; difference: number }>('/api/stock/adjustments', { item_code, counted, remarks: 'Physical count' })
export interface IssueInput { work_order_id: number | null; job_id: number | null; store: string; issued_on: string; issued_to: string; purpose: string; lines: { item_code: string; quantity: number; rate: number }[] }
export const openIssue = (b: IssueInput) => post<{ issue: { id: number }; message: string }>('/api/stock-issues', b)
export const postIssue = (id: number, b: { recover_from_order_id?: number | null; markup_percent?: number; allow_negative?: boolean } = {}) => post<{ message: string }>(`/api/stock-issues/${id}/post`, b)
export const cancelIssue = (id: number) => post<{ message: string }>(`/api/stock-issues/${id}/cancel`, {})
export const sendStock = (b: { from_store: string; to_store: string; moved_on: string; note: string; lines: { item_code: string; qty: number }[] }) => post<{ message: string }>('/api/stock/transfers', b)
