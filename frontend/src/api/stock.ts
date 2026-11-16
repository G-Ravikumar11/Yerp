import { useQuery } from '@tanstack/react-query'
import { get, post } from '@/lib/api'

export const stockKeys = { all: ['stock'] as const }

export interface StockRow { item_code: string; item_name: string; uom: string; received: number; issued: number; on_hand: number; rate: number; value: number; negative: boolean; below_level: boolean; reorder_level: number }
export interface StockSummary { items_held: number; value_on_hand: number; below_reorder: number; negative_lines: number }
interface Movement { moved_on: string; kind: string; quantity: number; rate: number; balance: number; source_ref: string; remarks: string }
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
/** A BOQ's budgeted materials against what the store issued to its project. */
export const useConsumption = (boq: number) => useQuery({ queryKey: ['stock', 'consumption', 'boq', boq], enabled: boq > 0, queryFn: () => get<Consumption>(`/api/stock/consumption/boq/${boq}`) })

export const countStock = (item_code: string, counted: number) => post<{ message: string; difference: number }>('/api/stock/adjustments', { item_code, counted, remarks: 'Physical count' })
