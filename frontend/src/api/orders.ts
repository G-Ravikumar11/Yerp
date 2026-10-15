import { useQuery } from '@tanstack/react-query'
import { api, get, post, put } from '@/lib/api'

export type OrderStatus = 'DRAFT' | 'PROVISIONAL' | 'APPROVED' | 'EXECUTED' | 'AMENDED' | 'CANCELLED' | 'CLOSED'
export type OrderAction = 'SUBMIT' | 'APPROVE' | 'REJECT' | 'EXECUTE' | 'AMEND' | 'CANCEL' | 'CLOSE'

export interface OrderItem {
  id?: number
  activity_no: string
  item_code: string
  item_description: string
  technical_spec: string
  uom: string
  quantity: number
  unit_rate: number
  total_amount: number
  budget_id: number | null
  cost_centre: string
  display_order: number
  is_header: boolean
  tolerance_percent: number
  /** The line of the project BOQ this is part of. */
  boq_key?: string
  /** Ordered plus its tolerance: the most that may be measured. */
  max_quantity: number
}

export interface OrderTerm {
  id?: number
  clause_category: string
  clause_text: string
}

export interface OrderHistory {
  action: string
  actor: string
  from_status: string
  to_status: string
  comments: string
  at: string
}

export interface RouteStep {
  step: number
  name: string
  owner: boolean
  status: 'waiting' | 'pending' | 'approved' | 'skipped' | 'cancelled' | 'rejected' | string
  notes: string
  decided_at: string
}

export interface BudgetRow {
  id: number
  code: string
  name: string
  department: string
  allocated: number
  committed: number
  this_order: number
  available: number
  over: boolean
  notes?: string
  set_by?: string
  /** False when set or raised by somebody who cannot approve orders, until an approver signs an order that spends it. */
  confirmed?: boolean
  confirmed_by?: string
}

export interface BillingHead {
  head: string
  rate: number | null
  amount: number
  kind: 'base' | 'add' | 'total' | 'info' | 'hold' | 'less' | 'net' | string
  note?: string
}

export interface BillingSchedule {
  rows: BillingHead[]
  intra_state: boolean
  place_of_supply: string
  contractor_state: string
}

export interface Order {
  id: number
  /** The member of staff who made it; blank for the owner. */
  submitted_by?: number | null
  wo_number: string
  status: OrderStatus
  amendment_no: number
  supersedes_id: number | null
  business_unit_id: number | null
  business_unit: string
  contractor_id: number | null
  contractor: string
  vendor_code: string
  job_id: number | null
  project: string
  work_type: string
  department: string
  subject: string
  scope_of_work: string
  commencement_date: string
  completion_date: string
  duration_months: number
  defect_liability_months: number
  bank_guarantee_applicable: boolean
  bank_guarantee_amount: number
  bank_guarantee_validity: string
  bank_guarantee_number: string
  bank_guarantee_bank: string
  bank_guarantee_returned_at: string
  /** returned | expired | expiring | valid | undated, or blank when the order carries none. */
  bank_guarantee_state: string
  ld_percent_per_week: number
  ld_cap_percent: number
  /** Recorded when the order is closed: the defects period runs from here. */
  actual_completion_date: string
  closed_at: string
  closed_by_name: string
  close_reason: string
  gross_amount: number
  gst_rate: number
  gst_amount: number
  tds_rate: number
  tds_amount: number
  net_order_value: number
  retention_percent: number
  retention_amount: number
  mobilization_advance_percent: number
  mobilization_advance_amount: number
  advance_recovery_percent: number
  labour_cess_percent: number
  labour_cess_amount: number
  billing_cycle: string
  payment_days: number
  copied_from_id: number | null
  rejection_reason: string
  approved_at: string
  executed_at: string
  created_at: string
  editable: boolean
  actions: OrderAction[]
  provisional: boolean
  item_count: number
  files?: { files: number; drawings: number; photos: number }
  // detail only
  items?: OrderItem[]
  terms?: OrderTerm[]
  history?: OrderHistory[]
  billing_schedule?: BillingSchedule
  advance_paid?: number
  pending_with?: string[]
  approval_route?: RouteStep[]
  copied_from?: string
  budgets?: BudgetRow[]
  budget_warnings?: string[]
  /** What would stop this revision being approved now: a bill still open on the order it replaces, lines it drops. */
  revision_blockers?: string[]
  /** What approving it would run into: past the client's BOQ, TDS below the statutory rate, the contractor's papers. */
  boq_warnings?: string[]
  tds_warning?: string
  compliance_warnings?: string[]
  unconfirmed_budgets?: string[]
  /** What stands between a live order and closing it. */
  close_blockers?: string[]
  advance_outstanding?: number
  /** A closed order: the work billed on it, which is all it now holds of the budget. */
  billed_value?: number
  statutory_tds?: { rate: number; why: string } | null
}

export interface OrderSummary {
  total: number
  draft: number
  awaiting: number
  approved: number
  executed: number
  value: number
}

/** What the order header form sends - the whole of it, every time. */
export interface OrderHead {
  business_unit_id: number | null
  contractor_id: number | null
  job_id: number | null
  department: string
  work_type: string
  subject: string
  scope_of_work: string
  commencement_date: string
  completion_date: string
  duration_months: number
  defect_liability_months: number
  bank_guarantee_applicable: boolean
  bank_guarantee_amount: number
  bank_guarantee_validity: string
  bank_guarantee_number: string
  bank_guarantee_bank: string
  gst_rate: number
  tds_rate: number
  retention_percent: number
  mobilization_advance_percent: number
  advance_recovery_percent: number
  labour_cess_percent: number
  billing_cycle: string
  payment_days: number
  ld_percent_per_week: number
  ld_cap_percent: number
}

export const orderKeys = {
  all: ['orders'] as const,
  list: ['orders', 'list'] as const,
  one: (id: number) => ['orders', 'one', id] as const,
  budgets: (jobId: number, orderId: number) => ['orders', 'budgets', jobId, orderId] as const,
}

/** Screens that pick an order to work on ask for the list afresh each time: one approved or amended a minute ago must be there. */
export function useOrders() {
  return useQuery({ queryKey: orderKeys.list, queryFn: () => get<{ orders: Order[]; summary: OrderSummary }>('/api/wo/orders'), refetchOnMount: 'always' })
}

export function useOrder(id: number) {
  return useQuery({ queryKey: orderKeys.one(id), queryFn: async () => (await get<{ order: Order }>(`/api/wo/orders/${id}`)).order, enabled: id > 0 })
}

/* --- What the pickers need ------------------------------------------------ */

export interface WorkType {
  id: number
  code: string
  name: string
  department: string
}

export interface Vocabulary {
  departments: string[]
  /** The sites each department was added to, by name; one missing here is on no site. */
  department_sites?: Record<string, number[]>
  uoms: string[]
  clause_categories: string[]
  jobs: { id: number; number: string; name: string }[]
  work_types: WorkType[]
  gst_rates: number[]
  tds_options: { rate: number; label: string }[]
  may_administer: boolean
}

export interface BusinessUnit {
  id: number
  name: string
  code: string
  gstin: string
}

export interface Contractor {
  id: number
  company_name: string
  vendor_code: string
  registration_status: string
  pan: string
  gst_number: string
  nature_of_work: string
  /** The TDS the law sets for paying them: 1% a person or HUF, 2% anybody else, 20% with no PAN. */
  tds_rate?: number | null
  tds_basis?: string
}

export function useOrderVocabulary() {
  return useQuery({ queryKey: ['orders', 'vocabulary'], queryFn: () => get<Vocabulary>('/api/wo/vocabulary'), staleTime: 10 * 60_000 })
}

export function useBusinessUnits() {
  return useQuery({ queryKey: ['orders', 'units'], queryFn: async () => (await get<{ business_units: BusinessUnit[] }>('/api/wo/business-units')).business_units, staleTime: 10 * 60_000 })
}

export function useContractors() {
  return useQuery({ queryKey: ['contractors'], queryFn: () => get<{ contractors: Contractor[]; summary: { registered: number; pending: number; sent_back: number } }>('/api/wo/contractors') })
}

export function useProjectBudgets(jobId: number | null, orderId: number) {
  return useQuery({
    queryKey: orderKeys.budgets(jobId ?? 0, orderId),
    queryFn: () => get<{ project: string; job_budget: number; budgets: BudgetRow[]; totals: { allocated: number; committed: number; available: number } }>(`/api/wo/projects/${jobId}/budgets?order_id=${orderId}`),
    enabled: !!jobId,
  })
}

export const termsLibrary = () => get<{ library: OrderTerm[] }>('/api/wo/terms/library')

/* --- Changing an order ---------------------------------------------------- */

type OrderReply = { order: Order; message: string }

export const createOrder = (head: Partial<OrderHead>) => post<OrderReply>('/api/wo/orders', head)
export const saveHead = (id: number, head: OrderHead) => put<OrderReply>(`/api/wo/orders/${id}`, head)
export const saveSchedule = (id: number, lines: Partial<OrderItem>[]) => put<OrderReply>(`/api/wo/orders/${id}/boq`, { lines })
export const saveTerms = (id: number, terms: OrderTerm[]) => put<OrderReply>(`/api/wo/orders/${id}/terms`, { terms })
export const copyOrder = (id: number) => post<OrderReply>(`/api/wo/orders/${id}/copy`)
export const chargeBudget = (id: number, budgetId: number, onlyBlank: boolean) => post<OrderReply>(`/api/wo/orders/${id}/charge-budget`, { budget_id: budgetId, only_blank: onlyBlank })
export const createBudget = (jobId: number, b: { name: string; code?: string; allocated_amount: number; order_id?: number }) => post<{ id: number; message: string; confirmed?: boolean }>(`/api/wo/projects/${jobId}/budgets`, b)
export const updateBudget = (budgetId: number, b: { name: string; code?: string; allocated_amount: number; order_id?: number; notes?: string }) =>
  put<{ id: number; message: string; confirmed?: boolean }>(`/api/wo/projects/budgets/${budgetId}`, b)

/** The work is over: closed with the date it actually finished. */
export const closeOrder = (id: number, b: { actual_completion_date: string; comments: string }) => post<OrderReply>(`/api/wo/orders/${id}/close`, b)
export const returnGuarantee = (id: number, comments: string) => post<OrderReply>(`/api/wo/orders/${id}/bank-guarantee/return`, { comments })

export interface Guarantee {
  order_id: number
  wo_number: string
  status: string
  contractor: string
  project: string
  number: string
  bank: string
  amount: number
  valid_to: string
  days_left: number | null
  returned_at: string
  state: 'returned' | 'expired' | 'expiring' | 'valid' | 'undated'
}

export function useGuarantees() {
  return useQuery({
    queryKey: ['orders', 'guarantees'],
    queryFn: () => get<{ guarantees: Guarantee[]; summary: { count: number; held: number; expiring: number; expired: number } }>('/api/wo/bank-guarantees'),
  })
}

/* --- The kinds of work, which an administrator keeps ---------------------- */

export interface WorkTypeRow extends WorkType {
  status?: string
  requested_by_name?: string
  request_reason?: string
}

export function useWorkTypes() {
  return useQuery({ queryKey: ['orders', 'work-types'], queryFn: () => get<{ work_types: WorkTypeRow[]; requested: WorkTypeRow[]; may_administer: boolean }>('/api/wo/work-types') })
}
export const requestWorkType = (b: { name: string; department: string; code?: string; request_reason?: string }) => post<{ message: string }>('/api/wo/work-types', b)
export const decideWorkType = (id: number, approve: boolean) => post<{ message: string }>(`/api/wo/work-types/${id}/decide?approve=${approve ? 'true' : 'false'}`)

export interface Move {
  action: 'submit' | 'approve' | 'reject' | 'execute' | 'cancel' | 'amend' | 'self-approve'
  comments?: string
  override?: boolean
}

/** One state change. The server decides whether it is allowed and says why not. */
export const moveOrder = (id: number, { action, comments, override }: Move) => post<OrderReply>(`/api/wo/orders/${id}/${action}`, { comments: comments ?? '', override: !!override })

export interface ScheduleImport {
  lines: Partial<OrderItem>[]
  skipped_rows: number
  gross_amount: number
  message: string
}

/** Reads a workbook into schedule lines and hands them back - nothing is saved until the schedule is. */
export function importSchedule(id: number, file: File) {
  const form = new FormData()
  form.append('file', file)
  return api<ScheduleImport>(`/api/wo/orders/${id}/boq/import`, { method: 'POST', body: form })
}

/** The departments added to this site. With no site chosen, every one that is on any site; a department already on the order stays listed. */
export function departmentsForSite(v: Vocabulary | undefined, jobId: number | null | undefined, keep = ''): string[] {
  const all = v?.departments ?? []
  if (!jobId) return all
  return all.filter((d) => d === keep || v?.department_sites?.[d]?.includes(jobId))
}
