import { useQuery } from '@tanstack/react-query'
import { storeGet, type CostHead, type DocStatus } from '@/api/store'

export type ControlKind = 'transfer' | 'count' | 'scrap'
export const KINDS: { key: ControlKind; label: string; plural: string; blurb: string }[] = [
  { key: 'transfer', label: 'Transfer', plural: 'Transfers', blurb: 'Stock sent from one store to another. It leaves the source when dispatched and arrives when the other store receives it.' },
  { key: 'count', label: 'Stock count', plural: 'Stock counts', blurb: 'A physical count freezes the store, then adjusts the books to what was found.' },
  { key: 'scrap', label: 'Wastage / scrap', plural: 'Wastage and scrap', blurb: 'Stock written off as wastage, or scrap that is sold or thrown away.' },
]
export const kindOf = (key: string | undefined) => KINDS.find((k) => k.key === key)

/** What the control routes send. Quantities, rates and values are strings. */
export interface DocLine {
  id: number
  item_id: number
  item_code: string
  item_name: string
  base_uom: string
  // transfer and scrap
  entry_uom?: string
  entry_qty?: string
  qty?: string
  rate?: string
  value?: string
  remarks?: string
  // count
  in_snapshot?: boolean
  counted_qty?: string | null
  reason?: string
  system_qty?: string | null
  avg_rate?: string | null
  variance_qty?: string | null
  variance_value?: string | null
  /** Delivered into the store since the count started - kept apart from the count. */
  arrived_since?: string | null
  // scrap
  disposal?: 'SCRAP' | 'WASTAGE'
  realised_value?: string
  cost_head?: CostHead | null
  writeoff_request_id?: number | null
}
export interface HistoryRow { action: string; from: string; to: string; by: string; at: string; note: string }
export interface Doc {
  kind: ControlKind
  id: number
  number: string
  status: DocStatus
  store_id: number
  store_code: string
  store_name: string
  date: string
  remarks: string
  cancel_reason: string
  created_by: string
  created_at: string
  posted_at: string
  line_count: number
  // transfer
  to_store_id?: number
  to_store_code?: string
  to_store_name?: string
  vehicle_no?: string
  receipt_status?: '' | 'IN_TRANSIT' | 'RECEIVED'
  received_at?: string
  received_by?: string
  inter_project?: boolean
  value?: string
  // count
  count_type?: 'FULL' | 'PARTIAL'
  started?: boolean
  started_at?: string
  started_by?: string
  counted?: number
  revealed?: boolean
  variance_value?: string | null
  frozen?: boolean
  /** Not started yet: transfers on their way to this store, which the count will not see. */
  in_transit?: { id: number; number: string; from_store: string; dispatched_on: string; value: string }[]
  // scrap
  project_id?: number | null
  project?: string
  buyer?: string
  reference?: string
  realised?: string
  lines?: DocLine[]
  history?: HistoryRow[]
}
export interface TransitRow { transfer_id: number; number: string; from_store: string; to_store: string; item_code: string; item_name: string; qty: string; value: string; dispatched_on: string; days: number; inter_project: boolean }
export interface VarianceRow { count_id: number; number: string; count_date: string; item_code: string; item_name: string; system_qty: string; counted_qty: string; variance_qty: string; variance_value: string }
export interface RealisationRow { scrap_doc_id: number; number: string; date: string; item_code: string; item_name: string; qty: string; book_value: string; realised_value: string; gain: string }
export interface OpenWriteoff { id: number; item_id: number; item_code: string; item_name: string; qty: string; reason: string }

export const qs = (params: Record<string, string | number | boolean | null | undefined>) => {
  const p = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) if (v !== '' && v !== 0 && v !== false && v != null) p.set(k, String(v))
  const s = p.toString()
  return s ? `?${s}` : ''
}

export const controlKeys = { all: ['store', 'control'] as const }
export const useDocs = (kind: ControlKind, f: { status: string; store_id: number; q: string }) =>
  useQuery({ queryKey: ['store', 'control', 'list', kind, f], queryFn: () => storeGet<{ total: number; items: Doc[] }>('control', `/${kind}${qs({ ...f, limit: 200 })}`) })
export const useDoc = (kind: ControlKind, id: number) =>
  useQuery({ queryKey: ['store', 'control', 'doc', kind, id], enabled: id > 0, queryFn: () => storeGet<Doc>('control', `/${kind}/${id}`) })
export const useInTransit = (projectId: number) =>
  useQuery({ queryKey: ['store', 'control', 'transit', projectId], queryFn: () => storeGet<{ total: number; total_value: string; items: TransitRow[] }>('control', `/in-transit${qs({ project_id: projectId })}`) })
export const useVariances = (storeId: number, from: string, to: string) =>
  useQuery({ queryKey: ['store', 'control', 'variances', storeId, from, to], enabled: storeId > 0, queryFn: () => storeGet<{ net_value: string; items: VarianceRow[] }>('control', `/count-variances${qs({ store_id: storeId, from_date: from, to_date: to })}`) })
export const useRealisation = (projectId: number, from: string, to: string) =>
  useQuery({ queryKey: ['store', 'control', 'realisation', projectId, from, to], queryFn: () => storeGet<{ book_value: string; realised_value: string; items: RealisationRow[] }>('control', `/scrap-realisation${qs({ project_id: projectId, from_date: from, to_date: to })}`) })
export const useAllStores = () =>
  useQuery({ queryKey: ['store', 'control', 'stores'], queryFn: async () => (await storeGet<{ items: { id: number; code: string; name: string; type: string; project_id: number | null }[] }>('control', '/pick/stores')).items })
export const useOpenWriteoffs = (storeId: number) =>
  useQuery({ queryKey: ['store', 'control', 'writeoffs', storeId], enabled: storeId > 0, queryFn: async () => (await storeGet<{ items: OpenWriteoff[] }>('control', `/pick/writeoffs?store_id=${storeId}`)).items })

export const num = (v: string | undefined | null) => Number(v ?? 0).toLocaleString('en-IN', { maximumFractionDigits: 3 })
export const money = (v: string | undefined | null) => Number(v ?? 0).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
export const dmy = (iso: string) => (iso ? new Date(iso.slice(0, 10) + 'T00:00').toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' }) : '-')
/** Today on this device's clock - the UTC date is still yesterday for the first hours of an Indian morning. */
export { today } from '@/lib/format'
export const headLabel = (h: string | null | undefined) => (h ? h.replace(/_/g, ' ').toLowerCase().replace(/^\w/, (c) => c.toUpperCase()) : '')
