import { useQuery } from '@tanstack/react-query'
import { storeGet, storeKeys, type StoreType } from '@/api/store'

/** What the masters routes send. Quantities are strings ("12.500"): the server does the arithmetic. */
export interface StoreRow {
  id: number
  code: string
  name: string
  type: StoreType
  project_id: number | null
  project_name: string
  address: string
  is_active: boolean
  bins: number
  staff: number
  items_held: number
  stock_value: string
  frozen: boolean
  frozen_reason: string
}
export interface BinRow { id: number; store_id: number; code: string; description: string; is_active: boolean }
export interface AssignRow { id: number; store_id: number; employee_id: number; name: string; email: string; job_title: string; role: string; is_active: boolean }
export interface EmployeeOption { id: number; name: string; email: string; job_title: string }
export interface ItemSettings {
  item_id: number
  category: string
  base_uom: string
  reorder_level: string
  min_qty: string
  max_qty: string
  qc_required: boolean
  over_receipt_tolerance_pct: string
  is_batch_tracked: boolean
  /** The maker's barcode on packaged goods, scanned to find the item. */
  barcode?: string
}
export interface Conversion { uom: string; to_base_factor: string }
export interface ItemRow {
  id: number
  code: string
  name: string
  item_uom: string
  is_active: boolean
  configured: boolean
  settings: ItemSettings
  conversions: Conversion[]
  on_hand: string
}

export const mastersKeys = {
  stores: ['store', 'masters', 'stores'] as const,
  bins: (id: number) => ['store', 'masters', 'bins', id] as const,
  assignments: (id: number) => ['store', 'masters', 'assignments', id] as const,
  items: (q: string, category: string, configured: string) => ['store', 'masters', 'items', q, category, configured] as const,
  employees: (q: string) => ['store', 'masters', 'employees', q] as const,
}

export const useStores = (status: string, q: string) =>
  useQuery({
    queryKey: [...mastersKeys.stores, status, q],
    queryFn: async () => (await storeGet<{ items: StoreRow[] }>('masters', `/stores?status=${status}&q=${encodeURIComponent(q)}`)).items,
  })
export const useBins = (storeId: number) =>
  useQuery({ queryKey: mastersKeys.bins(storeId), enabled: storeId > 0, queryFn: async () => (await storeGet<{ items: BinRow[] }>('masters', `/stores/${storeId}/bins`)).items })
export const useAssignments = (storeId: number) =>
  useQuery({ queryKey: mastersKeys.assignments(storeId), enabled: storeId > 0, queryFn: async () => (await storeGet<{ items: AssignRow[] }>('masters', `/stores/${storeId}/assignments`)).items })
export const useEmployeeOptions = (q: string) =>
  useQuery({ queryKey: mastersKeys.employees(q), queryFn: async () => (await storeGet<{ items: EmployeeOption[] }>('masters', `/employees?q=${encodeURIComponent(q)}`)).items })
export const useMasterItems = (q: string, category: string, configured: string) =>
  useQuery({
    queryKey: mastersKeys.items(q, category, configured),
    queryFn: () => storeGet<{ total: number; items: ItemRow[] }>('masters', `/items?q=${encodeURIComponent(q)}&category=${category}&configured=${configured}&limit=200`),
  })

/** After a change to the masters, the pickers every other part of the Store module draws on are stale too. */
export const mastersInvalidate = [['store', 'masters'], [...storeKeys.all, 'lookup']] as const
