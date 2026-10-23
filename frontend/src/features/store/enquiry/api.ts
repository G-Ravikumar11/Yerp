import { useQuery } from '@tanstack/react-query'
import { storeGet, type CostHead, type MovementType } from '@/api/store'

/** What the enquiry routes send. Quantities, rates and values are strings. */
export type StockStatus = 'NIL' | 'BELOW_MIN' | 'REORDER' | 'OVER_MAX' | 'OK'
export interface BalanceRow {
  store_id: number
  store_code: string
  store_name: string
  item_id: number
  item_code: string
  item_name: string
  category: string | null
  base_uom: string
  qty: string
  /** Promised to approved indents that are still to be issued, and what is left free. */
  reserved?: string
  available?: string
  avg_rate: string
  value: string
  status: StockStatus
  reorder_level: string
  min_qty: string
  max_qty: string
}
export interface Position { total: number; total_value: string; low: number; items: BalanceRow[] }
export interface LedgerRow {
  id: number
  txn_date: string
  store_id: number
  store_code: string
  item_id: number
  item_code: string
  item_name: string
  movement_type: MovementType
  qty_in: string
  qty_out: string
  rate: string
  value: string
  running_qty: string
  running_value: string
  avg_rate: string
  project_id: number | null
  project: string
  cost_head: CostHead | null
  ref_doc_type: string
  ref_doc_id: number
  is_reversal: boolean
  reversed: boolean
  user: string
  remarks: string
}
export interface Ledger { total: number; qty_in: string; qty_out: string; opening_qty?: string; closing_qty?: string; items: LedgerRow[] }
export interface ItemPosition {
  item: { id: number; code: string; name: string; base_uom: string; category: string | null }
  stores: BalanceRow[]
  total_qty: string
  total_value: string
  also_in: { uom: string; qty: string }[]
}

export const qs = (params: Record<string, string | number | boolean | null | undefined>) => {
  const p = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) if (v !== '' && v !== 0 && v !== false && v != null) p.set(k, String(v))
  const s = p.toString()
  return s ? `?${s}` : ''
}

export const usePosition = (f: { store_id: number; q: string; category: string; status: string; include_zero: boolean }) =>
  useQuery({ queryKey: ['store', 'enquiry', 'balances', f], queryFn: () => storeGet<Position>('enquiry', `/balances${qs({ ...f, limit: 1000 })}`) })
export const useItemPosition = (itemId: number) =>
  useQuery({ queryKey: ['store', 'enquiry', 'item', itemId], enabled: itemId > 0, queryFn: () => storeGet<ItemPosition>('enquiry', `/items/${itemId}`) })
export const useLedger = (f: { store_id: number; item_id: number; from_date: string; to_date: string; movement_type: string; project_id?: number; ref_doc_type?: string; ref_doc_id?: number }) =>
  useQuery({ queryKey: ['store', 'enquiry', 'ledger', f], queryFn: () => storeGet<Ledger>('enquiry', `/ledger${qs({ ...f, limit: 1000 })}`) })

export const STATUS_LABEL: Record<StockStatus, string> = { NIL: 'Nil', BELOW_MIN: 'Below minimum', REORDER: 'Reorder', OVER_MAX: 'Over maximum', OK: 'OK' }
export const STATUS_TONE = { NIL: 'neutral', BELOW_MIN: 'danger', REORDER: 'warning', OVER_MAX: 'info', OK: 'success' } as const
export const qty = (v: string) => Number(v).toLocaleString('en-IN', { maximumFractionDigits: 3 })
export const money = (v: string) => Number(v).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
