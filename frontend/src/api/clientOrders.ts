import { useQuery } from '@tanstack/react-query'
import { api, get, post } from '@/lib/api'

/** An order received from a client: what we are paid for. Its budget and bills hang off it. */
export interface ClientOrderLine {
  id: number
  fg_code: string
  item_name: string
  description: string
  qty: number
  uom: string
  rate: number
  amount: number
}

export interface BudgetLine {
  fg_code: string
  rm_code: string
  rm_name?: string
  qty: number
  uom?: string
  rate: number
  amount?: number
}

export type Approval = 'none' | 'pending' | 'approved' | 'rejected'

export interface ClientOrder {
  id: number
  number: string
  job_id: number
  job_name: string
  customer_name: string
  order_date: string
  reference: string
  notes: string
  status: string
  total_value: number
  budget_cost: number
  margin: number
  margin_percent: number
  budgeted: boolean
  approval_status: Approval
  current_step: number
  waiting_on: string
  waiting_step?: number | string
  rejection_reason: string
  line_count: number
  files?: { files: number; drawings: number; photos: number }
  // detail only
  lines?: ClientOrderLine[]
  bom?: BudgetLine[]
  approval_history?: { step?: number; decision?: string; by?: string; note?: string; at?: string }[]
}

export interface ClientOrderList {
  work_orders: ClientOrder[]
  summary: { count: number; awaiting_approval: number; total_value: number; total_margin: number }
}

export const clientOrderKeys = {
  all: ['client-orders'] as const,
  list: ['client-orders', 'list'] as const,
  one: (id: number) => ['client-orders', id] as const,
  requisition: (id: number) => ['client-orders', 'requisition', id] as const,
}

export const useClientOrders = () => useQuery({ queryKey: clientOrderKeys.list, queryFn: () => get<ClientOrderList>('/api/erp/work-orders') })

export const useClientOrder = (id: number) =>
  useQuery({ queryKey: clientOrderKeys.one(id), queryFn: () => get<ClientOrder>(`/api/erp/work-orders/${id}`), enabled: id > 0 })

/** The jobs an order can be booked against. Staff see the jobs they work on. */
export interface JobOption {
  id: number
  number: string
  name: string
}
export const useJobOptions = (staff: boolean) =>
  useQuery({
    queryKey: ['jobs', 'options', staff],
    queryFn: async () => (await get<{ jobs: JobOption[] }>(staff ? '/api/employee/jobs' : '/api/jobs?open_only=true&costing=false')).jobs ?? [],
    staleTime: 5 * 60_000,
  })

/* --- Building an order from codes already in the item master ------------------ */

export interface BuildLine {
  code: string
  qty: number
  rate: number
  description?: string
}

export const buildClientOrder = (b: { job_id: number; reference: string; lines: BuildLine[] }) =>
  post<{ ok: boolean; message: string; work_order: ClientOrder }>('/api/erp/work-orders/build', b)

export const saveBudget = (workOrderId: number, lines: Pick<BudgetLine, 'fg_code' | 'rm_code' | 'qty' | 'rate'>[]) =>
  post<{ ok: boolean; message: string; total_cost: number; work_order: ClientOrder }>('/api/erp/bom/build', { work_order_id: workOrderId, lines })

/* --- Moving it along -------------------------------------------------------------- */

export const placeClientOrder = (id: number) => post<{ message: string; work_order: ClientOrder }>(`/api/erp/work-orders/${id}/place-order`)

export const decideClientOrder = (id: number, decision: 'approve' | 'reject', note: string) =>
  post<{ message?: string; status?: string; work_order?: ClientOrder }>(`/api/erp/work-orders/${id}/decide`, { decision, note })

/* --- From the budget to a purchase order -------------------------------------------- */

export interface RequisitionLine {
  item_code: string
  item_name: string
  uom: string
  needed: number
  in_store: number
  on_order: number
  to_buy: number
  covered: boolean
  rate: number
  budget_rate?: number
  amount: number
}

export interface Requisition {
  work_order: ClientOrder
  lines: RequisitionLine[]
  summary: { items: number; to_buy: number; value: number; already_covered: number }
}

export const useRequisition = (id: number) =>
  useQuery({ queryKey: clientOrderKeys.requisition(id), queryFn: () => get<Requisition>(`/api/erp/work-orders/${id}/requisition`), enabled: id > 0, staleTime: 0 })

export const raisePurchaseOrder = (id: number, b: { supplier_name: string; needed_by: string; item_codes: string[] }) =>
  post<{ message: string }>(`/api/erp/work-orders/${id}/raise-po`, b)

/* --- Bringing an order in from a sheet ---------------------------------------------------- */

export interface SheetIssue {
  line: number
  field: string
  message: string
}

export interface SheetResult {
  ok: boolean
  errors?: SheetIssue[]
  warnings?: { line: number; message: string }[]
  total_value?: number
  lines?: unknown[]
  message?: string
  work_order?: ClientOrder | null
}

function sheetForm(file: File, extra: Record<string, string>) {
  const form = new FormData()
  form.append('file', file)
  Object.entries(extra).forEach(([k, v]) => form.append(k, v))
  return form
}

export const validateOrderSheet = (file: File) => api<SheetResult>('/api/erp/work-orders/validate', { method: 'POST', body: sheetForm(file, { sheet: '' }) })

export const uploadOrderSheet = (file: File, jobId: number) => api<SheetResult>('/api/erp/work-orders', { method: 'POST', body: sheetForm(file, { job_id: String(jobId), sheet: '' }) })
