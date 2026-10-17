import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { storeGet, storeKeys, storePost, storePut, type DocStatus } from '@/api/store'

/** Store > Inward: gate entries, GRNs, quality checks, purchase returns, client supply rates. Quantities are strings. */

const s = 'inward' as const
export const inwardKeys = {
  all: storeKeys.slice('inward'),
  list: (...parts: unknown[]) => [...storeKeys.slice('inward'), ...parts] as const,
}

export type GrnKind = 'PO' | 'DIRECT' | 'CLIENT_SUPPLY'
export interface TrailRow { from: string | null; to: string; by: string; at: string; note: string }
export interface Gate {
  id: number; number: string; store_id: number; store_code: string; entry_date: string; time_in: string; vehicle_no: string
  supplier_id: number | null; vendor_name: string; po_id: number | null; po_number: string | null; challan_no: string; challan_date: string | null
  weighbridge_slip_no: string; gross_weight: string | null; tare_weight: string | null; net_weight: string | null; remarks: string
  status: 'OPEN' | 'GRN_MADE' | 'CANCELLED'; grns: { id: number; number: string; status: DocStatus }[]; created_by: string
}
export interface PoOption { id: number; number: string; vendor: string; project_id: number | null; issue_date: string; needed_by: string; lines: number; open_lines: number; fully_received: boolean }
export interface PoLine {
  po_line_id: number; description: string; item_code: string; po_uom: string; ordered_qty: string; po_rate: string; gst_pct: string
  item_id: number | null; item_name: string; base_uom: string; factor: string | null; problem: string | null
  ordered_base?: string; received_base?: string; accepted_base?: string; rejected_base?: string; in_hand_base?: string
  pending_base?: string; pending_qty?: string; tolerance_pct?: string; max_receivable_base?: string; base_rate?: string
}
export interface Steel { theoretical_kg: string; actual_kg: string | null; variance_kg: string | null; variance_pct: string | null }
export interface GrnLine {
  id: number; line_no: number; po_line_id: number | null; item_id: number; item_code: string; item_name: string; uom: string; factor: string
  base_uom: string; received_qty: string; accepted_qty: string; rejected_qty: string; shortage_qty: string; received_base: string
  accepted_base: string; rejected_base: string; base_rate: string; gst_pct: string; charges_share: string; landed_rate: string
  stock_value: string; qc_status: 'NOT_REQUIRED' | 'QC_PENDING' | 'DONE'; posted: boolean; batch_no: string; mtc_ref: string
  bundles: number | null; nos: number | null; dia_mm: string | null; bar_length_m: string | null; actual_weight: string | null
  steel: Steel | null; remarks: string
  qc: { accepted_qty: string; rejected_qty: string; test_type: string; test_ref: string; remarks: string; inspector: string; at: string } | null
}
export interface Grn {
  id: number; number: string; kind: GrnKind; doc_type: string; store_id: number; store_code: string; store_name: string; grn_date: string
  status: DocStatus; po_id: number | null; po_number: string | null; gate_entry_id: number | null; gate_number: string | null
  work_order_id: number | null; work_order: string | null; vendor_name: string; challan_no: string; challan_date: string | null
  invoice_no: string; invoice_date: string | null; freight: string; loading: string; other_charges: string; gst_recoverable: boolean
  reason: string; remarks: string; created_by: string; posted_at: string | null; cancel_reason: string; lines_count: number
  stock_value: string; qc_pending: number; unposted: number
  lines?: GrnLine[]; rejection_memo?: string | null; returns?: { id: number; number: string; status: DocStatus }[]; trail?: TrailRow[]; gate?: Gate | null
}
export interface GrnLineInput {
  po_line_id?: number | null; item_id?: number | null; uom: string; received_qty: string; accepted_qty: string; rejected_qty: string
  shortage_qty: string; rate?: string; gst_pct?: string; batch_no: string; mtc_ref: string; bundles?: number | null; nos?: number | null
  dia_mm?: string; bar_length_m?: string; actual_weight?: string; remarks: string
}
export interface GrnInput {
  store_id: number; kind: GrnKind; grn_date: string; po_id?: number | null; gate_entry_id?: number | null; work_order_id?: number | null
  vendor_name: string; challan_no: string; challan_date?: string | null; invoice_no: string; invoice_date?: string | null
  freight: string; loading: string; other_charges: string; gst_recoverable?: boolean | null; reason: string; remarks: string; lines: GrnLineInput[]
}
export interface DebitLine { item_code: string; item_name: string; source: 'REJECTED' | 'ACCEPTED'; qty: string; uom: string; qty_base: string; base_uom: string; rate: string; taxable_value: string; gst_pct: string; gst: string; total: string }
export interface DebitNote { number: string; date: string; grn_number: string; po_number: string | null; invoice_no: string; vendor: string; vendor_gstin: string; lines: DebitLine[]; taxable_value: string; gst: string; total: string }
export interface PurchaseReturn {
  id: number; number: string; grn_id: number; grn_number: string; store_id: number; return_date: string; status: DocStatus; reason: string
  vehicle_no: string; remarks: string; vendor: string; created_by: string; total: string; cancel_reason: string; debit_note?: DebitNote; trail?: TrailRow[]
}
export interface PendingLine { po_number: string; vendor: string; item_code: string; item_name: string; po_uom: string; ordered_qty: string; pending_qty: string; pending_base: string; base_uom: string; in_hand_base: string; pending_value: string }
export interface PendingGroup { po_id: number | null; po_number: string | null; vendor: string; lines: number; pending_value: string; orders: string[]; items: PendingLine[] }
export interface ClientRate { id: number; work_order_id: number; work_order: string; item_id: number; item_code: string; item_name: string; base_uom: string; rate: string; reference: string }

export const useGrns = (storeId = 0, status = '', kind = '') =>
  useQuery({ queryKey: inwardKeys.list('grns', storeId, status, kind), placeholderData: keepPreviousData, queryFn: async () => (await storeGet<{ grns: Grn[] }>(s, `/grn?store_id=${storeId}&status=${status}&kind=${kind}`)).grns })
export const useGrn = (id: number) => useQuery({ queryKey: inwardKeys.list('grn', id), enabled: id > 0, queryFn: () => storeGet<Grn>(s, `/grn/${id}`) })
export const createGrn = (b: GrnInput) => storePost<Grn>(s, '/grn', b)
export const grnAction = (id: number, action: string, reason?: string) => storePost<Grn>(s, `/grn/${id}/${action}`, { reason: reason ?? '' })
export const recordQc = (lineId: number, b: { accepted_qty: string; rejected_qty: string; test_type: string; test_ref: string; remarks: string }) => storePost<Grn>(s, `/grn/lines/${lineId}/qc`, b)

export const useGates = (storeId = 0, status = '') =>
  useQuery({ queryKey: inwardKeys.list('gates', storeId, status), queryFn: async () => (await storeGet<{ entries: Gate[] }>(s, `/gate?store_id=${storeId}&status=${status}`)).entries })
export const useGate = (id: number) => useQuery({ queryKey: inwardKeys.list('gate', id), enabled: id > 0, queryFn: () => storeGet<Gate>(s, `/gate/${id}`) })
export const saveGate = (id: number | null, b: Record<string, unknown>) => (id ? storePut<Gate>(s, `/gate/${id}`, b) : storePost<Gate>(s, '/gate', b))
export const cancelGate = (id: number) => storePost<Gate>(s, `/gate/${id}/cancel`, {})

export const usePos = (storeId: number) =>
  useQuery({ queryKey: inwardKeys.list('pos', storeId), enabled: storeId > 0, queryFn: async () => (await storeGet<{ orders: PoOption[] }>(s, `/pos?store_id=${storeId}`)).orders })
export const usePoLines = (poId: number, storeId: number) =>
  useQuery({ queryKey: inwardKeys.list('po-lines', poId, storeId), enabled: poId > 0, queryFn: async () => (await storeGet<{ lines: PoLine[] }>(s, `/pos/${poId}/lines?store_id=${storeId}`)).lines })
export const useWorkOrders = (storeId: number) =>
  useQuery({ queryKey: inwardKeys.list('work-orders', storeId), enabled: storeId > 0, queryFn: async () => (await storeGet<{ work_orders: { id: number; number: string }[] }>(s, `/work-orders?store_id=${storeId}`)).work_orders })
export const usePending = (group: 'po' | 'vendor') =>
  useQuery({ queryKey: inwardKeys.list('pending', group), queryFn: async () => (await storeGet<{ rows: PendingGroup[] }>(s, `/pending?group=${group}`)).rows })

export const useReturns = (grnId = 0) =>
  useQuery({ queryKey: inwardKeys.list('returns', grnId), queryFn: async () => (await storeGet<{ returns: PurchaseReturn[] }>(s, `/returns?grn_id=${grnId}`)).returns })
export const useReturn = (id: number) => useQuery({ queryKey: inwardKeys.list('return', id), enabled: id > 0, queryFn: () => storeGet<PurchaseReturn>(s, `/returns/${id}`) })
export const createReturn = (b: { grn_id: number; return_date: string; reason: string; vehicle_no: string; remarks: string; lines: { grn_line_id: number; source: string; qty: string }[] }) =>
  storePost<PurchaseReturn>(s, '/returns', b)
export const returnAction = (id: number, action: string, reason?: string) => storePost<PurchaseReturn>(s, `/returns/${id}/${action}`, { reason: reason ?? '' })

export const useClientRates = (woId = 0) =>
  useQuery({ queryKey: inwardKeys.list('client-rates', woId), queryFn: async () => (await storeGet<{ rates: ClientRate[] }>(s, `/client-rates?work_order_id=${woId}`)).rates })
export const saveClientRate = (b: { work_order_id: number; item_id: number; rate: string; reference: string }) => storePost<ClientRate>(s, '/client-rates', b)
export const useInwardSettings = () => useQuery({ queryKey: inwardKeys.list('settings'), queryFn: () => storeGet<{ gst_recoverable: boolean }>(s, '/settings') })
export const saveInwardSettings = (gst_recoverable: boolean) => storePut<{ gst_recoverable: boolean }>(s, '/settings', { gst_recoverable })

export const pdf = {
  grn: (id: number) => `/api/store/inward/grn/${id}/document.pdf`,
  qc: (id: number) => `/api/store/inward/grn/${id}/qc.pdf`,
  rejection: (id: number) => `/api/store/inward/grn/${id}/rejection.pdf`,
  ret: (id: number) => `/api/store/inward/returns/${id}/document.pdf`,
}
export const KIND_LABEL: Record<GrnKind, string> = { PO: 'Against PO', DIRECT: 'Direct (no PO)', CLIENT_SUPPLY: 'Client supply' }
