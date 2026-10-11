import { useQuery } from '@tanstack/react-query'
import { del, get, post } from '@/lib/api'
import type { MbDimension } from './mb'
import type { ClientOrder } from './clientOrders'

/** One line of a client order as the measurement book sees it. */
export interface ClientBookLine {
  line_id: number
  fg_code: string
  description: string
  uom: string
  ordered_qty: number
  rate: number
  measured_to_date: number
  billed_to_date: number
  unbilled: number
  balance_to_measure: number
  percent_measured: number
  over_measured: number
}

export interface ClientEntry {
  id: number
  line_id?: number
  fg_code: string
  measured_on: string
  quantity: number
  mb_ref: string
  location: string
  remarks: string
  recorded_by_name: string
  witnessed_by: string
  billed: boolean
  dimensions: MbDimension[]
}

export interface ClientBook {
  work_order: ClientOrder
  lines: ClientBookLine[]
  entries: ClientEntry[]
  summary: { ordered_value: number; measured_value: number; unbilled_value: number; lines_over_measured: number }
}

export const bookKeys = {
  all: ['client-book'] as const,
  book: (id: number) => ['client-book', 'book', id] as const,
  bills: (id: number) => ['client-book', 'bills', id] as const,
  variations: (id: number) => ['client-book', 'variations', id] as const,
  suggest: (id: number) => ['client-book', 'suggest', id] as const,
  statement: (id: number) => ['client-book', 'statement', id] as const,
}

export const useClientBook = (id: number) => useQuery({ queryKey: bookKeys.book(id), queryFn: () => get<ClientBook>(`/api/mb/${id}`), enabled: id > 0 })

export const clientEntriesUrl = (id: number) => `/api/mb/${id}/entries`
export const deleteClientEntry = (id: number) => del<{ message: string }>(`/api/mb/entries/${id}`)

/* --- The running account bills ---------------------------------------------------- */

export interface RaBill {
  id: number
  number: string
  sequence: number
  work_order_id: number
  work_order: string
  project: string
  customer: string
  status: 'DRAFT' | 'SUBMITTED' | 'CERTIFIED' | 'PAID' | 'CANCELLED' | string
  gross_to_date: number
  previously_billed: number
  this_bill: number
  retention_amount: number
  tds_amount: number
  net_payable: number
  tax_amount: number
  cgst_amount: number
  sgst_amount: number
  igst_amount: number
  cgst_percent: number
  sgst_percent: number
  igst_percent: number
  taxable_value: number
  created_at?: string
  certified_by_name: string
  actions: string[]
}

export interface RaSummary {
  bills: number
  awaiting_certification: number
  certified_unpaid: number
  claimed: number
  retention_held: number
  paid: number
}

export const useRaBills = (workOrderId: number) =>
  useQuery({ queryKey: bookKeys.bills(workOrderId), queryFn: () => get<{ bills: RaBill[]; summary: RaSummary }>(`/api/ra-bills?work_order_id=${workOrderId}`), enabled: workOrderId > 0 })

export const drawRaBill = (workOrderId: number) => post<{ message: string }>('/api/ra-bills', { work_order_id: workOrderId })
export const actOnRaBill = (id: number, action: 'submit' | 'certify' | 'reject' | 'cancel', comments: string) => post<{ message: string }>(`/api/ra-bills/${id}/${action}`, { comments })

/* --- Variations: what was built past the order, turned into a priced, approved change -- */

export interface Variation {
  id: number
  number: string
  origin: string
  reason: string
  value: number
  order_value_before: number
  order_value_after: number
  status: 'DRAFT' | 'SUBMITTED' | 'APPROVED' | 'REJECTED' | 'CANCELLED' | string
  rejection_reason: string
  actions: string[]
}

export interface VariationSummary {
  raised: number
  awaiting_approval: number
  approved_value: number
  pending_value: number
}

export const useVariations = (workOrderId: number) =>
  useQuery({ queryKey: bookKeys.variations(workOrderId), queryFn: () => get<{ variations: Variation[]; summary: VariationSummary }>(`/api/variations?work_order_id=${workOrderId}`), enabled: workOrderId > 0 })

export const useVariationSuggestion = (workOrderId: number) =>
  useQuery({ queryKey: bookKeys.suggest(workOrderId), queryFn: () => get<{ count: number; value: number }>(`/api/variations/suggest/${workOrderId}`), enabled: workOrderId > 0 })

export const raiseVariation = (workOrderId: number, reason: string) => post<{ message: string }>('/api/variations', { work_order_id: workOrderId, reason })
export const actOnVariation = (id: number, action: 'submit' | 'approve' | 'reject', comments: string) => post<{ message: string }>(`/api/variations/${id}/${action}`, { comments })

/* --- Where the order stands ------------------------------------------------------------------ */

export interface Statement {
  order: { original_value: number; variations_agreed: number; variations_pending: number; revised_value: number }
  progress: { measured_value: number; percent_complete: number; left_to_build: number; over_run_not_yet_varied: number }
  money: { claimed: number; certified: number; paid: number; awaiting_payment: number; measured_not_billed: number; retention_held: number; tds_deducted: number }
}

export const useStatement = (workOrderId: number) =>
  useQuery({ queryKey: bookKeys.statement(workOrderId), queryFn: () => get<Statement>(`/api/erp/work-orders/${workOrderId}/statement`), enabled: workOrderId > 0 })
