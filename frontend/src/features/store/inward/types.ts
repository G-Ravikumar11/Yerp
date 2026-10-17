import type { DocStatus } from '@/api/store'

export interface LogRow { from: string; to: string; user: string; at: string | null; note: string }
export interface GrnLine {
  id: number; po_line_id: number | null; item_id: number; item_code: string; item_name: string; base_uom: string; qc_required: boolean
  uom: string; entered_qty: string; received_qty: string; accepted_qty: string; rejected_qty: string; rate: string
  bin_id: number | null; batch_no: string; qc_done: boolean; qc_remarks: string; remarks: string
}
export interface Grn {
  id: number; number: string; store_id: number; store_code: string; store_name: string; grn_date: string; po_id: number | null; po_number: string
  supplier_name: string; challan_no: string; challan_date: string | null; vehicle_no: string; remarks: string; status: DocStatus
  cancel_reason: string; created_by: string; created_at: string | null; line_count: number; total_value: string; lines?: GrnLine[]; log?: LogRow[]
}
export interface ReturnLine { id: number; grn_line_id: number | null; item_id: number; item_code: string; item_name: string; base_uom: string; qty: string; value: string; remarks: string }
export interface PurchaseReturn {
  id: number; number: string; store_id: number; store_code: string; store_name: string; return_date: string; grn_id: number | null; grn_number: string
  supplier_name: string; reason: string; remarks: string; status: DocStatus; cancel_reason: string; created_by: string; line_count: number
  total_value: string; lines?: ReturnLine[]; log?: LogRow[]
}
export interface PoLine { po_line_id: number; item_id: number | null; item_code: string; item_name: string; po_uom: string; base_uom: string; ordered_qty: string; received_qty: string; accepted_qty: string; pending_qty: string; price: string; in_item_master: boolean }
export const errText = (e: unknown) => (e as { detail?: string; message?: string })?.detail ?? (e as Error)?.message ?? 'Something went wrong'
export const money = (v: string) => Number(v).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
export const num = (v: string) => Number(v).toLocaleString('en-IN', { maximumFractionDigits: 3 })
