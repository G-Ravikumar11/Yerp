import { useQuery } from '@tanstack/react-query'
import { del, get, post, put } from '@/lib/api'

/** Everything Equipment & Plant reads lives under the equipment keys, so any change refreshes every screen of it. */
export const plantKeys = { all: ['equipment'] as const }

export interface Person { id: number; code: string; name: string; mobile: string; designation: string; status: string; on_machines?: string[] }
export interface Allocation {
  id: number; asset_id: number; code: string; machine: string; availability: string; employee: Person | null; project: string; role: string; shift: string
  allocated_on: string; start_date: string; end_date: string; supervisor: Person | null; status: string; notes: string; ended_reason: string; created_by: string
}
export interface LogRow {
  id: number; log_date: string; asset_id: number; code: string; machine: string; employee: Person | { name: string; mobile: string } | null; project: string
  shift: string; start_time: string; end_time: string; break_minutes: number; opening_meter: number | null; closing_meter: number | null
  operating_hours: number; idle_hours: number; breakdown_hours: number; attendance_hours: number; regular_hours: number; overtime_hours: number
  work_done: string; fuel_litres: number; supervisor_remarks: string; approval_status: string; approved_by: string; recorded_by: string
}
export interface FuelRow { id: number; number: string; asset_id: number; code: string; machine: string; project: string; filled_at: string; fuel_type: string; litres: number; rate: number; amount: number; supplier: string; voucher_no: string; meter_reading: number | null; notes: string; recorded_by: string }
export interface Maint {
  id: number; number: string; asset_id: number; code: string; machine: string; availability: string; kind: string; priority: string; status: string
  reported_on: string; scheduled_on: string; completed_on: string; description: string; mechanic: string; parts_used: string; parts_cost: number
  labour_cost: number; total_cost: number; downtime_start: string; downtime_end: string; downtime_hours: number; work_performed: string; invoice_no: string
  next_service_on: string; next_service_meter: number | null; approval_status: string; approved_by: string; overdue: boolean
}
export interface Provider { id: number; name: string; contact_person: string; mobile: string; email: string; address: string; supplier_id: number | null }
export interface RentalInvoice { id: number; invoice_no: string; invoice_date: string; period_from: string; period_to: string; billed_hours: number; amount: number; paid: number; outstanding: number; paid_on: string; payment_ref: string }
export interface Rental {
  id: number; number: string; asset_id: number; code: string; machine: string; category: string; reg_no: string; provider: Provider | null; agreement_no: string
  start_date: string; expected_return: string; actual_return: string; rate: number; billing: string; min_billable_hours: number; overtime_rate: number
  transport_charges: number; deposit: number; advance: number; fuel_included: boolean; operator_included: boolean; notes: string; status: string; days_left: number | null
  extensions: { from: string; to: string; reason: string; by: string; at: string }[]; invoices: RentalInvoice[]
  billed: number; paid: number; outstanding: number; used_hours: number; billed_hours: number; hours_gap: number
}
export interface Expense {
  id: number; number: string; source: 'expense' | 'fuel' | 'maintenance' | 'rental'; asset_id: number; code: string; machine: string; project: string; category: string
  spent_on: string; description: string; quantity: number; unit_rate: number; amount: number; vendor: string; invoice_no: string; payment_status: string
  payment_ref: string; approval_status: string; approved_by: string; recorded_by: string
}
export interface CostRow {
  asset_id: number; code: string; name: string; ownership: string; operating_hours: number; idle_hours: number; breakdown_hours: number; fuel_litres: number
  fuel: number; maintenance: number; rental: number; rental_outstanding: number; expenses: Record<string, number>; other_expenses: number; labour_hours: number
  overtime_hours: number; labour_cost: number; total: number; fuel_per_hour: number; litres_per_hour: number; idle_share: number
}
export interface Dashboard {
  date_from: string; date_to: string
  cards: { total: number; owned: number; rented: number; leased: number; working: number; idle: number; maintenance: number; breakdown: number; operators: number; working_hours: number; fuel: number; maintenance_cost: number; operating_cost: number; upcoming: number; service?: { "Due soon": number; "Service due": number; Overdue: number } }
  status_distribution: { status: string; count: number }[]
  maintenance_reminders: { asset_id: number; code: string; name: string; due: boolean; status?: string; what: string; on: string }[]
  rental_returns: { rental_id: number; number: string; agreement_no: string; code: string; name: string; expected_return: string; overdue: boolean }[]
  excess_idle: { asset_id: number; code: string; name: string; idle_hours: number; operating_hours: number; idle_share: number }[]
  recent: { at: string; who: string; action: string; what: string; details: string }[]
  cost_summary: Record<string, number>
}

const qs = (o: Record<string, string | number | boolean | undefined>) => {
  const p = new URLSearchParams()
  for (const [k, v] of Object.entries(o)) if (v !== undefined && v !== '' && v !== 0 && v !== false) p.set(k, String(v))
  const s = p.toString()
  return s ? `?${s}` : ''
}
export type Range = { date_from?: string; date_to?: string; asset_id?: number; employee_id?: number; status?: string; category?: string; provider_id?: number }

export const useDashboard = (r: Range) => useQuery({ queryKey: ['equipment', 'dashboard', r], queryFn: () => get<Dashboard>(`/api/plant/dashboard${qs(r)}`) })
export const useCosts = (r: Range) => useQuery({ queryKey: ['equipment', 'costs', r], queryFn: () => get<{ machines: CostRow[]; totals: Record<string, number> }>(`/api/plant/costs${qs(r)}`) })
export const usePeople = () => useQuery({ queryKey: ['equipment', 'people'], queryFn: () => get<{ employees: Person[]; roles: string[]; shifts: string[] }>('/api/plant/employees') })
export const useAllocations = (r: Range) => useQuery({ queryKey: ['equipment', 'allocations', r], queryFn: () => get<{ allocations: Allocation[] }>(`/api/plant/allocations${qs(r)}`) })
export const useLogs = (r: Range) => useQuery({ queryKey: ['equipment', 'logs', r], queryFn: () => get<{ logs: LogRow[]; regular_hours: number }>(`/api/plant/logs${qs(r)}`) })
export const useFuel = (r: Range) => useQuery({ queryKey: ['equipment', 'fuel', r], queryFn: () => get<{ fuel: FuelRow[]; fuel_types: string[]; by_machine: { asset_id: number; code: string; name: string; litres: number; amount: number; operating_hours: number; litres_per_hour: number; cost_per_hour: number }[]; by_day: { day: string; litres: number; amount: number }[]; totals: { litres: number; amount: number } }>(`/api/plant/fuel${qs(r)}`) })
export const useMaintenance = (r: Range) => useQuery({ queryKey: ['equipment', 'maintenance', r], queryFn: () => get<{ maintenance: Maint[]; kinds: string[]; priorities: string[] }>(`/api/plant/maintenance${qs(r)}`) })
export const useProviders = () => useQuery({ queryKey: ['equipment', 'providers'], queryFn: () => get<{ providers: Provider[]; suppliers: { id: number; name: string }[] }>('/api/plant/rental-providers') })
export const useRentals = (r: Range) => useQuery({ queryKey: ['equipment', 'rentals', r], queryFn: () => get<{ rentals: Rental[]; billing: string[]; summary: Record<string, number> }>(`/api/plant/rentals${qs(r)}`) })
export const useExpenses = (r: Range) => useQuery({ queryKey: ['equipment', 'expenses', r], queryFn: () => get<{ expenses: Expense[]; categories: string[]; all_categories: string[]; by_category: Record<string, number>; total: number }>(`/api/plant/expenses${qs(r)}`) })

type Msg = { message: string; id?: number }
export const allocate = (b: Record<string, unknown>) => post<Msg>('/api/plant/allocations', b)
export const endAllocation = (id: number, reason: string) => post<Msg>(`/api/plant/allocations/${id}/end`, { reason })
export const reassign = (id: number, employee_id: number, on: string, reason: string) => post<Msg>(`/api/plant/allocations/${id}/reassign`, { employee_id, on, reason })
export const saveLog = (id: number | null, b: Record<string, unknown>) => (id ? put<Msg>(`/api/plant/logs/${id}`, b) : post<Msg>('/api/plant/logs', b))
export const decideLog = (id: number, decision: 'approve' | 'reject', remarks: string) => post<Msg>(`/api/plant/logs/${id}/decision`, { decision, remarks })
export const saveHoursRule = (regular_hours: number) => put<Msg>('/api/plant/settings', { regular_hours })
export const recordFuel = (b: Record<string, unknown>) => post<Msg>('/api/plant/fuel', b)
export const removeFuel = (id: number) => del<Msg>(`/api/plant/fuel/${id}`)
export const raiseMaint = (b: Record<string, unknown>) => post<Msg>('/api/plant/maintenance', b)
export const updateMaint = (id: number, b: Record<string, unknown>) => put<Msg>(`/api/plant/maintenance/${id}`, b)
export const completeMaint = (id: number, b: Record<string, unknown>) => post<Msg>(`/api/plant/maintenance/${id}/complete`, b)
export const approveMaint = (id: number) => post<Msg>(`/api/plant/maintenance/${id}/approve`)
export const saveProvider = (id: number | null, b: Record<string, unknown>) => (id ? put<Msg>(`/api/plant/rental-providers/${id}`, b) : post<Msg>('/api/plant/rental-providers', b))
export const createRental = (b: Record<string, unknown>) => post<Msg>('/api/plant/rentals', b)
export const extendRental = (id: number, to_date: string, reason: string) => post<Msg>(`/api/plant/rentals/${id}/extend`, { to_date, reason })
export const returnRental = (id: number, returned_on: string) => post<Msg>(`/api/plant/rentals/${id}/return`, { returned_on })
export const addRentalInvoice = (id: number, b: Record<string, unknown>) => post<Msg>(`/api/plant/rentals/${id}/invoices`, b)
export const payRentalInvoice = (id: number, amount: number, paid_on: string, payment_ref: string) => post<Msg>(`/api/plant/rental-invoices/${id}/payment`, { amount, paid_on, payment_ref })
export const saveExpense = (id: number | null, b: Record<string, unknown>) => (id ? put<Msg>(`/api/plant/expenses/${id}`, b) : post<Msg>('/api/plant/expenses', b))
export const decideExpense = (id: number, decision: 'approve' | 'reject', remarks: string) => post<Msg>(`/api/plant/expenses/${id}/decision`, { decision, remarks })
export const removeExpense = (id: number) => del<Msg>(`/api/plant/expenses/${id}`)
export const reportUrl = (kind: string, r: Range, pdf = false) => `/api/plant/reports/${kind}.${pdf ? 'pdf' : 'xlsx'}${qs(r)}`

/** The status as it is shown: what the register stores, in the words a site uses. */
export const STATUS_LABEL: Record<string, string> = { Deployed: 'Working', Available: 'Available', 'Under repair': 'Maintenance', Breakdown: 'Breakdown', Returned: 'Returned', Disposed: 'Disposed' }
export const statusTone = (s: string) => (s === 'Deployed' ? 'success' : s === 'Breakdown' ? 'danger' : s === 'Under repair' ? 'warning' : s === 'Returned' || s === 'Disposed' ? 'neutral' : 'info') as 'success' | 'danger' | 'warning' | 'neutral' | 'info'
