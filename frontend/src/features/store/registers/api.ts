import { useQuery } from '@tanstack/react-query'
import { storeGet } from '@/api/store'
import { get, post } from '@/lib/api'
import { qs, type BalanceRow, type Position } from '../enquiry/api'

/** The lists pull fresh figures by themselves this often, and whenever the window is come back to. */
const REFRESH = 60_000

export interface ReceiptLine {
  id: number
  grn_id: number
  number: string
  item_id: number
  item_code: string
  item_name: string
  qty: string
  uom: string
  supplier: string
  po_number: string
  date: string
  received_by: string
  status: string
  store_code: string
  store_name: string
}

export interface IssueLine {
  id: number
  issue_id: number
  number: string
  item_id: number
  item_code: string
  item_name: string
  qty: string
  uom: string
  used_for: string
  subcontractor: string
  received_by: string
  project: string
  date: string
  issued_by: string
  status: string
  store_code: string
}

export type StockRow = BalanceRow & { last_received?: string }

export const useStock = (f: { store_id: number; category: string; include_zero?: boolean }) =>
  useQuery({ queryKey: ['store', 'enquiry', 'balances', 'register', f], refetchOnMount: 'always', refetchInterval: REFRESH, refetchOnWindowFocus: true, queryFn: () => storeGet<Position & { items: StockRow[] }>('enquiry', `/balances${qs({ ...f, limit: 1000 })}`) })
export const useReceipts = (storeId: number) =>
  useQuery({ queryKey: ['store', 'enquiry', 'receipts', storeId], refetchOnMount: 'always', refetchInterval: REFRESH, refetchOnWindowFocus: true, queryFn: () => storeGet<{ items: ReceiptLine[] }>('enquiry', `/receipts${qs({ store_id: storeId, limit: 1000 })}`) })
export const useIssues = (storeId: number) =>
  useQuery({ queryKey: ['store', 'enquiry', 'issues', storeId], refetchOnMount: 'always', refetchInterval: REFRESH, refetchOnWindowFocus: true, queryFn: () => storeGet<{ items: IssueLine[] }>('enquiry', `/issues${qs({ store_id: storeId, limit: 1000 })}`) })

/** The level an item is reordered at in this store: the reorder level where one is set, else the minimum. */
export const levelOf = (r: BalanceRow) => Math.max(Number(r.reorder_level) || 0, Number(r.min_qty) || 0)
/** Low: at or under its level, or none left of an item that has one. */
export const isLow = (r: BalanceRow) => levelOf(r) > 0 && Number(r.qty) <= levelOf(r)

/** Rupees as the register shows them: lakhs and crores past a lakh. */
export function inLakhs(v: number) {
  if (Math.abs(v) >= 1e7) return `₹${(v / 1e7).toFixed(2)} Cr`
  if (Math.abs(v) >= 1e5) return `₹${(v / 1e5).toFixed(1)} L`
  return `₹${Math.round(v).toLocaleString('en-IN')}`
}

/** Rows whose words contain what was typed, in any of the given fields. */
export function matching<T>(rows: T[], q: string, fields: (r: T) => (string | null | undefined)[]) {
  const term = q.trim().toLowerCase()
  return term ? rows.filter((r) => fields(r).some((v) => (v ?? '').toLowerCase().includes(term))) : rows
}

/** One item that is low now, as the server worked it out: what is available (not just on hand), its level, how much to order, and the
 * store's alert with the indent or enquiry raised for it. The screen shows these and never works them out itself. */
export type LowStatus = 'LOW_STOCK' | 'INDENT_RAISED' | 'ENQUIRY_RAISED'
export type LowStage = 'ALERT ACTIVE' | 'INDENT RAISED' | 'ENQUIRY RAISED' | 'PO CREATED' | 'GOODS RECEIVED' | 'QUALITY ACCEPTED' | 'STOCK UPDATED' | 'LOW STOCK'
export interface LowRow {
  key: string
  alert_id: number | null
  store_id: number
  store_code: string
  store_name: string
  project_id: number | null
  project: string
  item_id: number
  item_code: string
  item_name: string
  category: string | null
  base_uom: string
  on_hand: string
  unusable: string
  reserved: string
  available: string
  reorder_level: string
  min_qty: string
  max_qty: string
  target_level: string | null
  suggest_basis: string
  suggested_qty: string
  on_order: string
  to_order: string
  alerted_at: string
  last_checked_at: string
  times_raised: number
  status: LowStatus
  /** How far the alert has got toward replenishment, as the server works it out (store_low_stock._stage). */
  stage: LowStage
  /** Reorder level less what is available: how far under the level it stands. */
  shortage: string
  action: '' | 'INDENT' | 'ENQUIRY'
  action_ref: string
  action_doc_id: number | null
  action_doc_status: string
  action_live: boolean
  action_qty: string | null
  action_by: string
  action_at: string
}
export interface LowHistoryRow {
  alert_id: number
  store_code: string
  item_code: string
  item_name: string
  status: 'RESOLVED' | 'CLOSED'
  alerted_at: string | null
  resolved_at: string | null
  available: string | null
  reorder_level: string | null
  suggested_qty: string | null
  resolved_qty: string | null
  action: string | null
  action_ref: string | null
  action_qty: string | null
  action_by: string | null
}
export interface LowStock { items: LowRow[]; can_indent: boolean; can_enquire: boolean }

export const lowKeys = { all: ['store', 'low-stock'] as const }
export const useLowStock = (storeId: number) =>
  useQuery({ queryKey: [...lowKeys.all, 'active', storeId], refetchOnMount: 'always', refetchInterval: REFRESH, refetchOnWindowFocus: true,
    queryFn: () => get<LowStock>(`/api/store/levels/low-stock${qs({ store_id: storeId })}`) })
export const useLowHistory = (storeId: number, enabled: boolean) =>
  useQuery({ queryKey: [...lowKeys.all, 'history', storeId], enabled, queryFn: async () => (await get<{ items: LowHistoryRow[] }>(`/api/store/levels/low-stock${qs({ store_id: storeId, view: 'history' })}`)).items })

export interface RaiseLine { store_id: number; item_id: number; qty: string; alert_id: number | null }
export interface RaiseResult {
  store_id: number
  item_id: number
  ok: boolean
  message: string
  ref?: string
  doc_id?: number
  repeat?: boolean
  status?: string
}
export interface RaiseAnswer { ok: boolean; action: 'INDENT' | 'ENQUIRY'; created: { type: string; id: number; number: string; lines: number; store_code?: string; status: string }[]; results: RaiseResult[]; raised: number; failed: number; message: string }
export const raiseLow = (body: { action: 'INDENT' | 'ENQUIRY'; lines: RaiseLine[]; request_key: string; project_id?: number; required_by?: string; title?: string }) =>
  post<RaiseAnswer>('/api/store/levels/low-stock/raise', body)