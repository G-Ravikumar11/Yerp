import type { DocStatus } from '@/api/store'

export interface LogRow { from: string; to: string; user: string; at: string | null; note: string }
export interface TransferLine { id: number; item_id: number; item_code: string; item_name: string; qty: string; rate: string; value: string; received_qty: string | null; loss_qty: string; loss_reason: string; loss_remarks: string; on_hand: string; remarks: string }
export interface Transfer {
  id: number; number: string; store_id: number; store_code: string; store_name: string; to_store_id: number; to_store_code: string; to_store_name: string; trf_date: string
  inter_project: boolean; vehicle_no: string; driver_name: string; challan_no: string; challan_date: string | null; remarks: string; status: DocStatus; transit: '' | 'IN_TRANSIT' | 'RECEIVED'
  loss_status: '' | 'PENDING' | 'APPROVED'; loss_value: string; cancel_reason: string; created_by: string
  received_on: string | null; received_by: string; line_count: number; total_value: string; lines?: TransferLine[]; log?: LogRow[]
}
export interface CountLine { id: number; item_id: number; item_code: string; item_name: string; counted_qty: string | null; first_count_qty: string | null; recount: boolean; recounts: number; remarks: string; system_qty: string | null; variance_qty: string | null; variance_value: string | null }
export interface Count {
  id: number; number: string; store_id: number; store_code: string; store_name: string; count_date: string; remarks: string; status: DocStatus; cancel_reason: string
  created_by: string; line_count: number; counted_count: number; revealed: boolean; categories: string[]; bin_id: number | null; bin_code: string; recount_rounds: number; variance_value: string | null; lines?: CountLine[]; log?: LogRow[]
}
export interface AdjustmentLine { id: number; item_id: number; item_code: string; item_name: string; direction: 'IN' | 'OUT'; qty: string; rate: string; value: string; writeoff_request_id: number | null; remarks: string }
export interface Adjustment {
  id: number; number: string; store_id: number; store_code: string; store_name: string; adj_date: string; kind: 'STOCK' | 'WASTAGE' | 'WRITEOFF'; reason: string; reason_code: string; attachment_ref: string; project_id: number | null
  project_name: string; cost_head: string | null; high_value: boolean; status: DocStatus; cancel_reason: string; created_by: string; line_count: number; total_value: string
  lines?: AdjustmentLine[]; log?: LogRow[]
}
export interface ScrapLine { id: number; item_id: number; item_code: string; item_name: string; qty: string; scrap_class: string; book_value: string; realised_value: string; difference: string; remarks: string; on_hand: string }
export interface Scrap {
  id: number; number: string; store_id: number; store_code: string; store_name: string; scrap_date: string; project_id: number | null; project_name: string; buyer: string; gate_pass_no: string; reason: string
  status: DocStatus; cancel_reason: string; created_by: string; line_count: number; book_value: string; realised_value: string; difference: string; lines?: ScrapLine[]; log?: LogRow[]
}
export interface WriteoffReq { request_id: number; store_id: number; store_code: string; item_id: number; item_code: string; item_name: string; qty: string; reason: string }
export interface ControlMeta { adjustment_reasons: string[]; wastage_reasons: string[]; scrap_classes: string[]; high_value_limit: string }
export interface ReorderRow { store_id: number; store_code: string; item_id: number; item_code: string; item_name: string; uom: string; on_hand: string; reorder_level: string; min_qty: string; max_qty: string; pending_po: string; suggested: string; below_min: boolean }
export const label = (code: string | null) => (code ?? '').replace(/_/g, ' ').toLowerCase()
export const errText = (e: unknown) => (e as { detail?: string; message?: string })?.detail ?? (e as Error)?.message ?? 'Something went wrong'
export const money = (v: string | null) => Number(v ?? 0).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
export const num = (v: string | null) => Number(v ?? 0).toLocaleString('en-IN', { maximumFractionDigits: 3 })
