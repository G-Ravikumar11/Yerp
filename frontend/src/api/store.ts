import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { del, get, patch, post, put } from '@/lib/api'

/**
 * The Store module's API client. Every slice calls its own routes through storeGet / storePost / storePut / storePatch /
 * storeDelete so the /api/store/<slice> prefix is written once, and the pickers draw on the shared lookups below.
 * Quantities travel as strings ("12.500"): the server does the arithmetic, the screens only show and type them.
 */
export const STORE_SLICES = ['masters', 'enquiry', 'inward', 'outward', 'control', 'reports'] as const
export type StoreSlice = (typeof STORE_SLICES)[number]
export type StoreAction = 'view' | 'create' | 'approve' | 'post' | 'cancel'
/** The rights a screen asks `can()` for: store.<slice>.<action>. */
export const storePerm = (slice: StoreSlice, action: StoreAction = 'view') => `store.${slice}.${action}`

export type DocStatus = 'DRAFT' | 'SUBMITTED' | 'APPROVED' | 'POSTED' | 'CANCELLED'
export type StoreType = 'CENTRAL' | 'SITE' | 'YARD'
export type MovementType =
  | 'OPENING_IN' | 'GRN_IN' | 'CLIENT_SUPPLY_IN' | 'PURCHASE_RETURN_OUT' | 'ISSUE_OUT' | 'ISSUE_RETURN_IN' | 'SUBCON_ISSUE_OUT'
  | 'SUBCON_RETURN_IN' | 'TRANSFER_OUT' | 'TRANSFER_IN' | 'ADJUST_IN' | 'ADJUST_OUT' | 'WASTAGE_OUT' | 'SCRAP_OUT'
export type CostHead = 'SITE_ESTABLISHMENT' | 'P_AND_M_FUEL' | 'OVERHEAD' | 'SAFETY' | 'TEMPORARY_WORKS'

const base = (slice: StoreSlice, path: string) => `/api/store/${slice}${path}`
export const storeGet = <T>(slice: StoreSlice, path = '') => get<T>(base(slice, path))
export const storePost = <T>(slice: StoreSlice, path = '', body?: unknown) => post<T>(base(slice, path), body)
export const storePut = <T>(slice: StoreSlice, path = '', body?: unknown) => put<T>(base(slice, path), body)
export const storePatch = <T>(slice: StoreSlice, path = '', body?: unknown) => patch<T>(base(slice, path), body)
export const storeDelete = <T>(slice: StoreSlice, path = '') => del<T>(base(slice, path))

export const storeKeys = {
  all: ['store'] as const,
  slice: (slice: StoreSlice) => ['store', slice] as const,
  meta: ['store', 'lookup', 'meta'] as const,
  stores: (projectId = 0) => ['store', 'lookup', 'stores', projectId] as const,
  items: (q: string) => ['store', 'lookup', 'items', q] as const,
  uoms: (itemId: number | null) => ['store', 'lookup', 'uoms', itemId] as const,
}

export interface StoreOption { id: number; code: string; name: string; type: StoreType; project_id: number | null }
export interface UomOption { code: string; to_base_factor: number }
export interface StoreItemOption { id: number; code: string; name: string; base_uom: string; uoms: UomOption[]; category: string | null; batch_tracked?: boolean }
export interface StoreMeta {
  movement_types: MovementType[]; doc_statuses: DocStatus[]; cost_heads: CostHead[]; store_types: StoreType[]
  item_categories: string[]; slices: StoreSlice[]; actions: StoreAction[]
  /** The company uses QR and barcode scanning in the Store (Settings > Company > Store). Off unless turned on. */
  scanning?: boolean
}

export const useStoreMeta = () => useQuery({ queryKey: storeKeys.meta, staleTime: 60 * 60_000, queryFn: () => get<StoreMeta>('/api/store/lookup/meta') })
/** Whether to show the scan buttons, the maker's barcode and label printing. */
export const useScanning = () => !!useStoreMeta().data?.scanning
/** The stores this person may work in (optionally those of one project). */
export const useStoreOptions = (projectId = 0) =>
  useQuery({
    queryKey: storeKeys.stores(projectId),
    queryFn: async () => (await get<{ stores: StoreOption[] }>(`/api/store/lookup/stores${projectId ? `?project_id=${projectId}` : ''}`)).stores ?? [],
  })
export const useItemSearch = (q: string) =>
  useQuery({
    queryKey: storeKeys.items(q),
    placeholderData: keepPreviousData,
    queryFn: async () => (await get<{ items: StoreItemOption[] }>(`/api/store/lookup/items?q=${encodeURIComponent(q)}`)).items ?? [],
  })
export const useItemUoms = (itemId: number | null) =>
  useQuery({
    queryKey: storeKeys.uoms(itemId),
    enabled: !!itemId,
    staleTime: 5 * 60_000,
    queryFn: () => get<{ item_id: number; base_uom: string; uoms: UomOption[] }>(`/api/store/lookup/items/${itemId}/uoms`),
  })

/** What a scanned or typed code is: an item (its code or the maker's barcode on it), a rack or yard-bay tag, or a store document. */
export type ScanResult =
  | { kind: 'item'; item: StoreItemOption }
  | { kind: 'bin'; store: StoreOption; bin: { id: number; code: string } }
  | { kind: 'document'; doc: 'gate-pass' | 'issue' | 'grn'; id: number; number: string; status: string; path: string }
export const scanCode = (code: string) => get<ScanResult>(`/api/store/lookup/scan?code=${encodeURIComponent(code)}`)
/** A scan that found something other than what the box wanted, said plainly. */
export const scanWhat = (r: ScanResult) => (r.kind === 'item' ? `item ${r.item.code} ${r.item.name}` : r.kind === 'bin' ? `bin ${r.bin.code} in store ${r.store.code}` : `document ${r.number}`)
