import { useQuery } from '@tanstack/react-query'
import { storeGet } from '@/api/store'
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
