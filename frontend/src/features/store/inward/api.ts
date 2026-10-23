import { useQuery } from '@tanstack/react-query'
import { storeGet, type DocStatus } from '@/api/store'

/** The four inward documents. The key is the path under /api/store/inward and under /store/hub/inward. */
export type InwardKind = 'grn' | 'returns' | 'client-supply' | 'opening'
export const KINDS: { key: InwardKind; label: string; plural: string; blurb: string }[] = [
  { key: 'grn', label: 'Goods receipt', plural: 'Goods receipts', blurb: 'Deliveries received against purchase orders, with the quality check.' },
  { key: 'returns', label: 'Purchase return', plural: 'Purchase returns', blurb: 'Goods sent back to the supplier from a posted receipt.' },
  { key: 'client-supply', label: 'Client supply', plural: 'Client supplies', blurb: 'Material the client hands over for its own project.' },
  { key: 'opening', label: 'Opening stock', plural: 'Opening stock', blurb: 'Stock already held when a store starts being kept here.' },
]
export const kindOf = (key: string | undefined) => KINDS.find((k) => k.key === key)

/** What the inward routes send. Quantities, rates and values are strings. */
export interface DocLine {
  id: number
  item_id: number
  item_code: string
  item_name: string
  base_uom: string
  entry_uom: string
  entry_qty: string
  // goods receipt
  po_line_id?: number | null
  received_qty?: string
  accepted_qty?: string
  rejected_qty?: string
  rate?: string
  qc_status?: 'NOT_REQUIRED' | 'PENDING' | 'PASSED' | 'FAILED'
  qc_by?: string
  qc_note?: string
  reject_reason?: string
  batch_no?: string
  manufacturing_date?: string
  expiry_date?: string
  shelf_state?: '' | 'OK' | 'NEAR' | 'EXPIRED'
  remarks?: string
  /** This line's part of the receipt's charges, and the rate it goes (went) into stock at. */
  charges_share?: string
  landed_rate?: string
  // return
  grn_line_id?: number
  qty?: string
  reason?: string
  value?: string
  tax_pct?: string
  tax_value?: string
}
export type ChargeKind = 'FREIGHT' | 'LOADING' | 'GST' | 'INSURANCE' | 'OTHER'
export interface Charge { kind: ChargeKind; label: string; amount: string; basis: 'VALUE' | 'QTY' }
export const CHARGE_KINDS: Record<ChargeKind, string> = { FREIGHT: 'Freight', LOADING: 'Loading and unloading', GST: 'GST not claimable', INSURANCE: 'Transit insurance', OTHER: 'Other charges' }
export interface HistoryRow { action: string; from: string; to: string; by: string; at: string; note: string }
export interface Doc {
  kind: InwardKind
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
  value?: string
  po_id?: number | null
  po_number?: string
  supplier_name?: string
  challan_no?: string
  challan_date?: string
  vehicle_no?: string
  project_id?: number | null
  project?: string
  qc_pending?: number
  /** A delivery received before its purchase order, on its challan; linked to the order later. */
  gate_delivery?: boolean
  driver_remarks?: string
  linked_at?: string
  linked_by?: string
  /** Linked: what the order's rate comes to above (or below) the rate it was received at. */
  price_variance?: string
  /** Landed cost: freight, loading, GST not claimable - spread into the stock value. */
  charges?: Charge[]
  charges_total?: string
  landed_value?: string
  /** A purchase return's debit note. */
  debit_value?: string
  tax_value?: string
  debit_total?: string
  grn_id?: number
  grn_number?: string
  reason?: string
  work_order_id?: number | null
  client_ref?: string
  lines?: DocLine[]
  history?: HistoryRow[]
}
export interface PoOption {
  id: number
  number: string
  supplier_name: string
  project_id: number | null
  issue_date: string
  /** needs_item: the order line names no stock item yet - say which it is before receiving it. */
  lines: { po_line_id: number; item_id: number | null; needs_item?: boolean; item_code: string; item_name: string; description: string; po_uom: string; po_qty: string; price: string; base_uom: string; ordered: string; accepted: string; pending: string; category?: string | null; batch_tracked?: boolean }[]
}
export interface ReturnableLines {
  grn: { id: number; number: string; status: DocStatus; store_id: number; supplier_name: string }
  lines: { grn_line_id: number; item_id: number; item_code: string; item_name: string; base_uom: string; accepted: string; returnable: string }[]
}

export const qs = (params: Record<string, string | number | null | undefined>) => {
  const p = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) if (v !== '' && v !== 0 && v != null) p.set(k, String(v))
  const s = p.toString()
  return s ? `?${s}` : ''
}

export const inwardKeys = { all: ['store', 'inward'] as const }
export const useDocs = (kind: InwardKind, f: { status: string; store_id: number; q: string }) =>
  useQuery({ queryKey: ['store', 'inward', 'list', kind, f], queryFn: () => storeGet<{ total: number; items: Doc[] }>('inward', `/${kind}${qs({ ...f, limit: 200 })}`) })
export const useDoc = (kind: InwardKind, id: number) =>
  useQuery({ queryKey: ['store', 'inward', 'doc', kind, id], enabled: id > 0, queryFn: () => storeGet<Doc>('inward', `/${kind}/${id}`) })
export const usePoOptions = (q = '') =>
  useQuery({ queryKey: ['store', 'inward', 'po-options', q], queryFn: async () => (await storeGet<{ items: PoOption[] }>('inward', `/po-options${qs({ q })}`)).items })
export const useReturnable = (grnId: number) =>
  useQuery({ queryKey: ['store', 'inward', 'grn-lines', grnId], enabled: grnId > 0, queryFn: () => storeGet<ReturnableLines>('inward', `/grn-lines/${grnId}`) })

export const num = (v: string | undefined) => Number(v ?? 0).toLocaleString('en-IN', { maximumFractionDigits: 3 })
export const money = (v: string | undefined) => Number(v ?? 0).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
export const dmy = (iso: string) => (iso ? new Date(iso.slice(0, 10) + 'T00:00').toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' }) : '-')
/** Today on this device's clock - the UTC date is still yesterday for the first hours of an Indian morning. */
export { today } from '@/lib/format'
