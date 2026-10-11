import { useQuery } from '@tanstack/react-query'
import { del, get, post, put } from '@/lib/api'

export const grnKeys = { all: ['grn'] as const }

export interface GrnRow { id: number; number: string; challan_number: string; supplier_name: string; purchase_order: string; project: string; received_on: string; accepted_value: number; rejected_value: number; status: string; actions: string[] }
export interface GrnSummary { count: number; awaiting_posting: number; accepted_value: number; rejected_value: number }
export interface GrnLine { id: number; item_code: string; description: string; uom: string; ordered_qty: number; previously_received: number; received_qty: number; rejected_qty: number; accepted_qty: number; rejection_reason: string; amount: number; rate?: number; price?: number }
export interface Grn extends GrnRow { vehicle_number: string; received_by_name: string; editable: boolean; lines: GrnLine[]; received_value: number }
export interface OpenOrder { id: number; number: string; supplier_name: string; pending_value: number }
export interface MatchRow { purchase_order_id: number; number: string; supplier_name: string; project: string; ordered_value: number; received_value: number; billed_value: number; bill_count: number; receipt_count: number; verdict: string; note: string }
export interface MatchSummary { orders: number; matched: number; exceptions: number; over_billed: number; accrual_owed: number }

export const useReceipts = () => useQuery({ queryKey: ['grn', 'list'], queryFn: () => get<{ goods_receipts: GrnRow[]; summary: GrnSummary }>('/api/grn') })
export const useReceipt = (id: number | null) => useQuery({ queryKey: ['grn', 'one', id], enabled: !!id, queryFn: () => get<Grn>(`/api/grn/${id}`) })
export const useOpenOrders = () => useQuery({ queryKey: ['grn', 'open-orders'], queryFn: async () => (await get<{ orders: OpenOrder[] }>('/api/grn/open-orders')).orders ?? [] })
export const useMatch = (onlyExceptions: boolean) => useQuery({ queryKey: ['grn', 'match', onlyExceptions], queryFn: () => get<{ orders: MatchRow[]; summary: MatchSummary }>(`/api/match/three-way${onlyExceptions ? '?only_exceptions=true' : ''}`) })

export interface StartInput { purchase_order_id: number; received_on: string; challan_number: string; invoice_number: string; vehicle_number: string; store_location: string; inspected_by: string }
export const startReceipt = (b: StartInput) => post<Grn>('/api/grn', b)
export const saveReceipt = (id: number, lines: { id: number; received_qty: number; rejected_qty: number; rejection_reason: string }[]) => put<Grn>(`/api/grn/${id}`, { lines })
export const postReceipt = (id: number) => post<{ message: string; goods_receipt: Grn; over_received: unknown[] }>(`/api/grn/${id}/post`)
export const cancelReceipt = (id: number, comments: string) => post<{ message: string }>(`/api/grn/${id}/cancel`, { comments })
export const discardReceipt = (id: number) => del<{ message: string }>(`/api/grn/${id}`)
export const billReceipt = (id: number) => post<{ message: string }>(`/api/grn/${id}/bill`, {})

export const VERDICT: Record<string, { label: string; tone: 'danger' | 'warning' | 'neutral' | 'success' }> = {
  OVER_BILLED: { label: 'Billed over receipt', tone: 'danger' },
  AWAITING_RECEIPT: { label: 'Nothing received', tone: 'danger' },
  OVER_RECEIVED: { label: 'Over-received', tone: 'warning' },
  AWAITING_BILL: { label: 'To be billed', tone: 'warning' },
  PART_BILLED: { label: 'Part billed', tone: 'neutral' },
  AWAITING_DELIVERY: { label: 'Awaiting delivery', tone: 'neutral' },
  MATCHED: { label: 'Matched', tone: 'success' },
}
