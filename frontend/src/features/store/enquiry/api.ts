import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { storeGet, storeKeys, type MovementType, type StoreType } from '@/api/store'

/** Store > Stock enquiry: balances, the item card, and where an item is held. Read-only; quantities are strings. */

export type Group = 'store' | 'item' | 'project'
export interface BalanceFilter { group: Group; storeId: number; projectId: number; q: string; category: string; includeZero: boolean }

export interface StoreBalance {
  store_id: number; store_code: string; store_name: string; store_type: StoreType; project_id: number | null; project: string
  item_id: number; item_code: string; item_name: string; category: string | null; base_uom: string; qty: string; value: string
  avg_rate: string; reorder_level: string; below_reorder: boolean
}
export interface GroupedBalance {
  item_id: number; item_code: string; item_name: string; category: string | null; base_uom: string; qty: string; value: string
  avg_rate: string; stores: string[]; project_id?: number | null; project?: string
}
export interface BalanceSummary { lines: number; items: number; stores: number; total_value: string; below_reorder: number }
export interface Balances { group: Group; rows: (StoreBalance | GroupedBalance)[]; summary: BalanceSummary }

export interface CardRow {
  id: number; txn_date: string; movement_type: MovementType; label: string; direction: 'IN' | 'OUT'; qty_in: string; qty_out: string
  rate: string; value: string; signed_value: string; running_qty: string; running_value: string; avg_rate: string
  ref_doc_type: string; ref_doc_id: number; ref_line_id: number | null; doc_number: string; doc_path: string | null
  reversal_of_id: number | null; reversed_by_id: number | null; project: string; cost_head: string | null; user: string; remarks: string
}
export interface ItemCard {
  item: { id: number; code: string; name: string; base_uom: string }
  store: { id: number; code: string; name: string }
  from: string | null; to: string | null
  opening: { qty: string; value: string }; closing: { qty: string; value: string }
  totals: { qty_in: string; qty_out: string }; balance: { qty: string; value: string; avg_rate: string }
  rows: CardRow[]; truncated: boolean
}
export interface Availability {
  item: { id: number; code: string; name: string; base_uom: string }
  stores: { store_id: number; store_code: string; store_name: string; store_type: StoreType; project: string; qty: string; value: string; avg_rate: string }[]
  total: { qty: string; value: string; avg_rate: string }
}

const e = 'enquiry' as const
const key = (...parts: unknown[]) => [...storeKeys.slice('enquiry'), ...parts] as const

export function balancesPath(f: BalanceFilter) {
  const p = new URLSearchParams({ group: f.group })
  if (f.storeId) p.set('store_id', String(f.storeId))
  if (f.projectId) p.set('project_id', String(f.projectId))
  if (f.q) p.set('q', f.q)
  if (f.category) p.set('category', f.category)
  if (f.includeZero) p.set('include_zero', 'true')
  return `/balances?${p}`
}
export const useBalances = (f: BalanceFilter) =>
  useQuery({ queryKey: key('balances', f), placeholderData: keepPreviousData, queryFn: () => storeGet<Balances>(e, balancesPath(f)) })

export function cardPath(itemId: number, storeId: number, from = '', to = '', pdf = false) {
  const p = new URLSearchParams({ store_id: String(storeId) })
  if (from) p.set('date_from', from)
  if (to) p.set('date_to', to)
  return `/items/${itemId}/card${pdf ? '.pdf' : ''}?${p}`
}
export const useItemCard = (itemId: number, storeId: number, from: string, to: string) =>
  useQuery({ queryKey: key('card', itemId, storeId, from, to), enabled: itemId > 0 && storeId > 0, queryFn: () => storeGet<ItemCard>(e, cardPath(itemId, storeId, from, to)) })
export const useAvailability = (itemId: number) =>
  useQuery({ queryKey: key('availability', itemId), enabled: itemId > 0, queryFn: () => storeGet<Availability>(e, `/items/${itemId}/availability`) })
