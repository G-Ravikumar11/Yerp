import { useQuery } from '@tanstack/react-query'
import { get, post, put } from '@/lib/api'

export type BillStatus = 'DRAFT' | 'SUBMITTED' | 'CERTIFIED' | 'PAID' | 'CANCELLED'
export type BillAction = 'SUBMIT' | 'CERTIFY' | 'REJECT' | 'PAY' | 'CANCEL'

export interface BillLine {
  id: number
  item_id: number
  activity_no: string
  description: string
  uom: string
  ordered_qty: number
  measured_to_date: number
  previously_billed_qty: number
  this_bill_qty: number
  rate: number
  amount: number
  upto_date_amount: number
}

export interface BillStep {
  step: number
  name: string
  owner: boolean
  approver_id: number | null
  status: string
  notes: string
  decided_at: string
}

export interface SubBill {
  id: number
  number: string
  sequence: number
  order_id: number
  order: string
  contractor: string
  vendor_code: string
  job_id: number | null
  project: string
  status: BillStatus
  period_from: string
  period_to: string
  bill_date: string
  work_type: string
  work_name: string
  hsn_sac: string
  gross_to_date: number
  previously_billed: number
  this_bill: number
  debit_notes: number
  gross_value: number
  retention_percent: number
  retention_amount: number
  advance_recovery: number
  other_deductions: number
  deduction_notes: string
  gst_percent: number
  gst_amount: number
  cgst_amount: number
  sgst_amount: number
  igst_amount: number
  place_of_supply: string
  tds_percent: number
  tds_amount: number
  labour_cess_percent: number
  labour_cess_amount: number
  net_payable: number
  certified_by_name: string
  certified_at: string
  approved_by_name: string
  submitted_by_name: string
  submitted_at: string
  accepted_by_name: string
  accepted_at: string
  paid_at: string
  paid_reference: string
  remarks: string
  editable: boolean
  actions: BillAction[]
  created_at: string
  route: BillStep[]
  waiting_on: string
  // detail only
  lines?: BillLine[]
  amount_in_words?: string
  place_of_supply_name?: string
  material_recovered?: number
  site?: string
  /** 'chosen' when the bill was drawn from entries picked for it; the entries it carries (detail only). */
  entry_mode?: '' | 'chosen'
  entries?: { id: number; code: string; kind: string; quantity: number; activity_no: string; location: string; measured_on: string }[]
  order_detail?: { number: string; subject: string; value: number; retention_percent: number; commencement_date: string; completion_date: string }
}

export interface BillSummary {
  claimed: number
  awaiting_certification: number
  certified_unpaid: number
  retention_held: number
  paid: number
}

/** The certificate's own boxes, put right on a draft. */
export interface BillEdit {
  period_from: string
  period_to: string
  bill_date: string
  work_type: string
  work_name: string
  hsn_sac: string
  debit_notes: number
  advance_recovery: number
  other_deductions: number
  deduction_notes: string
}

export const billKeys = {
  all: ['subbills'] as const,
  list: (orderId: number) => ['subbills', 'list', orderId] as const,
  one: (id: number) => ['subbills', 'one', id] as const,
}

export function useSubBills(orderId: number) {
  return useQuery({ queryKey: billKeys.list(orderId), queryFn: () => get<{ bills: SubBill[]; summary: BillSummary }>(`/api/sub-bills${orderId ? `?order_id=${orderId}` : ''}`) })
}

export function useSubBill(id: number) {
  return useQuery({ queryKey: billKeys.one(id), queryFn: () => get<SubBill>(`/api/sub-bills/${id}`), enabled: id > 0 })
}

/** Draw up a bill: everything measured and not yet billed, or only the entries of the measurement book given. */
export const drawBill = (orderId: number, entryIds?: number[]) => post<{ bill: SubBill; message: string }>('/api/sub-bills', { order_id: orderId, ...(entryIds ? { entry_ids: entryIds } : {}) })
export const editBill = (id: number, edit: Partial<BillEdit>) => put<{ bill: SubBill; message: string }>(`/api/sub-bills/${id}`, edit)

export interface BillMove {
  action: 'submit' | 'certify' | 'reject' | 'cancel' | 'accept'
  comments?: string
  name?: string
}

export const moveBill = (id: number, { action, comments, name }: BillMove) => post<{ bill: SubBill; message: string }>(`/api/sub-bills/${id}/${action}`, { comments: comments ?? '', name })

/** Bills climbing their signatures: previous + this bill, and the running total of what is payable. */
export function withRunningTotals(bills: SubBill[]): Map<number, number> {
  const out = new Map<number, number>()
  const perOrder = new Map<number, SubBill[]>()
  for (const b of bills) perOrder.set(b.order_id, [...(perOrder.get(b.order_id) ?? []), b])
  for (const list of perOrder.values()) {
    let running = 0
    list
      .slice()
      .sort((a, b) => a.sequence - b.sequence || a.id - b.id)
      .forEach((b) => {
        if (b.status !== 'CANCELLED') running += b.net_payable
        out.set(b.id, running)
      })
  }
  return out
}
