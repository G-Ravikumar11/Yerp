import { useQuery } from '@tanstack/react-query'
import { api, get, patch, post, put } from '@/lib/api'

export interface MasterItem {
  id: number
  kind: 'RM' | 'FG'
  item_code: string
  item_name: string
  description: string
  item_category: string
  item_subcategory: string
  item_type: string
  units_of_measure: string
  specification: string
  purchase_rate: number
  selling_rate: number
  /** What it was last bought or sold at, from before purchase rates were kept here. 0 when never. */
  last_rate: number
  /** The selling rate when one is kept, else null. A default only: a site's finalised rate never follows it. */
  default_rate: number | null
  hsn_code: string
  item_tax_type: string
  preferred_supplier: string
  reorder_level: number
  remarks: string
  is_active: boolean
  /** The brand: UltraTech, Tata Tiscon, Finolex. */
  make: string
  shelf_life_applicable?: boolean
  shelf_life_days?: number | null
  expiry_tracking?: boolean
  /** The company or division the item belongs to, as the old ERP's sheet has it. */
  segment: string
  sites: number
  /** The store's running total for the item, or null when none is kept. */
  stock: number | null
  created_by: string
  updated_by: string
  created_at: string
  updated_at: string
}

export interface MasterItemInput {
  kind?: 'RM' | 'FG'
  item_code?: string
  item_name: string
  description?: string
  item_category?: string
  item_subcategory?: string
  item_type?: string
  units_of_measure?: string
  specification?: string
  purchase_rate?: number | null
  selling_rate?: number | null
  hsn_code?: string
  gst_percent?: number | null
  preferred_supplier?: string
  reorder_level?: number | null
  remarks?: string
  is_active?: boolean
  make?: string
  shelf_life_applicable?: boolean
  shelf_life_days?: number | null
  expiry_tracking?: boolean
  segment?: string
}

/** What an item can be missing: the master's gaps. */
export type Gap = 'category' | 'gst' | 'hsn' | 'rate' | 'make'

export interface ItemFilters {
  q: string
  category: string
  subcategory: string
  item_type: string
  uom: string
  status: string
  site_id: string
  /** RM (materials), FG (work items), or '' for both. */
  kind: string
  /** Only the items missing this detail. */
  missing: Gap | ''
  sort: string
  direction: 'asc' | 'desc'
  page: number
  page_size: number
}

export interface ItemPage {
  items: MasterItem[]
  total: number
  page: number
  page_size: number
  /** How many materials and work items the same filters find. */
  counts: { RM: number; FG: number }
}

export interface Category {
  id: number
  name: string
  is_active: boolean
  /** How many items are filed under it, subcategories included. */
  items: number
  subcategories: { id: number; name: string; is_active: boolean; items: number }[]
}

export const masterKeys = {
  all: ['item-master'] as const,
  list: (f: ItemFilters) => ['item-master', 'list', f] as const,
  categories: ['item-master', 'categories'] as const,
  sites: (id: number | null) => ['item-master', 'sites', id] as const,
}

function queryString(f: object) {
  const p = new URLSearchParams()
  Object.entries(f).forEach(([k, v]) => v !== '' && v !== undefined && v !== null && p.set(k, String(v)))
  return p.toString()
}

export function useMasterItems(f: ItemFilters) {
  return useQuery({ queryKey: masterKeys.list(f), queryFn: () => get<ItemPage>(`/api/items?${queryString(f)}`), placeholderData: (prev) => prev })
}

/** How many items are missing each detail. */
export function useItemGaps(f: Pick<ItemFilters, 'status' | 'kind'>) {
  return useQuery({ queryKey: ['item-master', 'gaps', f.status, f.kind], queryFn: () => get<Record<Gap, number> & { total: number }>(`/api/items/gaps?${queryString({ status: f.status, kind: f.kind })}`) })
}

export function useCategories() {
  return useQuery({ queryKey: masterKeys.categories, queryFn: async () => (await get<{ categories: Category[] }>('/api/item-categories')).categories })
}

export function useItemSites(itemId: number | null) {
  return useQuery({
    queryKey: masterKeys.sites(itemId),
    enabled: itemId !== null,
    queryFn: () =>
      get<{ sites: { site_id: number; site_code: string; site_name: string; boq_number: string; quantity: number; site_rate: number | null; status: string }[] }>(
        `/api/items/${itemId}/sites`,
      ),
  })
}

export interface SimilarItem {
  id: number
  item_code: string
  item_name: string
  units_of_measure: string
  item_category: string
  is_active: boolean
  /** Why it is shown: "Same code", "Same name" or "Looks similar". */
  reason: string
}

export const fetchNextCode = async () => (await get<{ code: string }>('/api/items/next-code')).code
export const fetchSimilar = async (name: string, code: string, excludeId?: number) =>
  (await get<{ similar: SimilarItem[] }>(`/api/items/similar?${queryString({ name, code, exclude_id: excludeId })}`)).similar
export const fetchItem = async (id: number) => (await get<{ item: MasterItem }>(`/api/items/${id}`)).item

export interface UsageGroup {
  key: string
  label: string
  count: number
  rows: { label: string; detail: string; path: string }[]
  more: number
}

export function useWhereUsed(itemId: number | null) {
  return useQuery({
    queryKey: ['item-master', 'where-used', itemId],
    enabled: itemId !== null,
    queryFn: () => get<{ item: MasterItem; total: number; groups: UsageGroup[] }>(`/api/items/${itemId}/where-used`),
  })
}

export const createMasterItem = (body: MasterItemInput) => post<{ item: MasterItem; message: string }>('/api/items', body)
export const updateMasterItem = (id: number, body: MasterItemInput) => put<{ item: MasterItem; message: string }>(`/api/items/${id}`, body)
export const setItemActive = (id: number, is_active: boolean, confirm = false) => patch<{ item: MasterItem; message: string }>(`/api/items/${id}/status`, { is_active, confirm })
export const addCategory = (name: string, parent_id?: number) => post<{ message: string }>('/api/item-categories', { name, parent_id })
export const patchCategory = (id: number, body: { name?: string; is_active?: boolean }) => patch<{ message: string }>(`/api/item-categories/${id}`, body)
export const exportUrl = (f: Partial<ItemFilters>, ids: number[] = []) =>
  `/api/items/export.xlsx?${queryString({ ...f, page: undefined, page_size: undefined, sort: undefined, direction: undefined, ids: ids.join(',') })}`
export const bulkStatus = (ids: number[], is_active: boolean, confirm = false) => post<{ changed: number; message: string }>('/api/items/bulk-status', { ids, is_active, confirm })
/** The details to change on every item ticked; anything left out stays as it is on each. */
export interface BulkChange { kind?: 'RM' | 'FG'; item_category?: string; item_subcategory?: string; item_type?: string; units_of_measure?: string; gst_percent?: number; hsn_code?: string; make?: string }
export const bulkUpdate = (ids: number[], change: BulkChange) => post<{ changed: number; message: string }>('/api/items/bulk-update', { ids, ...change })

export const mergeCategory = (id: number, into_id: number) => post<{ moved: number; message: string }>(`/api/item-categories/${id}/merge`, { into_id })
export const deleteCategory = (id: number) => api<{ message: string }>(`/api/item-categories/${id}`, { method: 'DELETE' })
