import type { DocStatus } from '@/api/store'

export interface LogRow { from: string; to: string; user: string; at: string | null; note: string }
interface Where { project_id: number | null; project_name: string; work_order_id: number | null; work_order_number: string; boq_item_id: number | null; cost_head: string | null }
export interface ReqLine { id: number; item_id: number; item_code: string; item_name: string; base_uom: string; uom: string; entered_qty: string; qty: string; issued_qty: string; remarks: string }
export interface Requisition extends Where { id: number; number: string; store_id: number; store_code: string; store_name: string; req_date: string; required_by: string | null; purpose: string; status: DocStatus; cancel_reason: string; created_by: string; line_count: number; lines?: ReqLine[]; log?: LogRow[] }
export interface IssueLine { id: number; requisition_line_id: number | null; item_id: number; item_code: string; item_name: string; base_uom: string; uom: string; entered_qty: string; qty: string; rate: string; value: string; returnable: boolean; chargeable: boolean; recovery_rate: string; returned_qty: string; lost_qty: string; outstanding_qty: string; remarks: string }
export interface Issue extends Where {
  id: number; number: string; store_id: number; store_code: string; store_name: string; issue_date: string; issue_type: 'SITE' | 'SUBCONTRACTOR'; requisition_id: number | null; requisition_number: string; direct: boolean
  subcontractor_id: number | null; subcontractor_name: string; holder_type: string | null; holder_id: number | null; holder_name: string; expected_return_date: string | null; purpose: string
  status: DocStatus; cancel_reason: string; created_by: string; line_count: number; total_value: string; lines?: IssueLine[]; log?: LogRow[]
}
export interface ReturnLine { id: number; issue_line_id: number; item_id: number; item_code: string; item_name: string; base_uom: string; qty: string; lost_qty: string; rate: string; value: string; remarks: string }
export interface IssueReturn { id: number; number: string; store_id: number; store_code: string; issue_id: number; issue_number: string; return_date: string; remarks: string; status: DocStatus; cancel_reason: string; created_by: string; line_count: number; holder_name: string; total_value: string; lines?: ReturnLine[]; log?: LogRow[] }
export interface Options {
  projects: { id: number; name: string; number: string }[]; work_orders: { id: number; number: string; project_id: number }[]
  subcontractors: { id: number; name: string }[]; employees: { id: number; name: string }[]; cost_heads: string[]
}
export const errText = (e: unknown) => (e as { detail?: string; message?: string })?.detail ?? (e as Error)?.message ?? 'Something went wrong'
export const money = (v: string) => Number(v).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
export const num = (v: string) => Number(v).toLocaleString('en-IN', { maximumFractionDigits: 3 })
