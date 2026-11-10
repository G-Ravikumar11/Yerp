import { useQuery } from '@tanstack/react-query'
import { del, get, post, put } from '@/lib/api'

/** The payslip as a file, every column of the sheet: a PDF or an Excel workbook. */
export const payslipFile = (id: number, kind: 'pdf' | 'xlsx') => `/api/payslips/${id}/${kind}`

/** Many payslips in one Excel sheet, a row each with every column. */
export const payrollRegister = (ids: number[]) => `/api/payslips/register.xlsx?ids=${ids.join(',')}`

/** One month's payslips as a register, or (with `last`) every month from `first` to `last` in one file. */
export const payrollMonthFile = (first: string, last?: string) =>
  last && last !== first ? `/api/payslips/register.xlsx?from_month=${first}&to_month=${last}` : `/api/payslips/register.xlsx?month=${first}`

/** The payslips paid between two dates (either may be left out), in one file. */
export const payrollDatesFile = (from: string, to: string) => `/api/payslips/register.xlsx?from_date=${from}&to_date=${to}`

export const payKeys = { all: ['payroll'] as const }
const k = (...p: unknown[]) => ['payroll', ...p] as const

export interface PayslipRow {
  id: number
  number: string
  employee_id: number
  employee_name: string
  employee_email: string
  period_start: string
  period_end: string
  pay_date: string
  gross_pay: number
  tax_amount: number
  total_deductions: number
  net_pay: number
  status: string
  sent: boolean
  /** The statutory breakdown: PF and ESI from the person and from the company, professional tax, and the days paid. */
  employee_pf?: number
  employer_pf?: number
  employer_epf?: number
  employer_eps?: number
  employee_esi?: number
  employer_esi?: number
  professional_tax?: number
  working_days?: number
  lop_days?: number
  paid_days?: number
  /** The YYYY-MM it belongs to, and where that month's payroll stands. */
  month?: string
  month_status?: MonthStatus
}

export type MonthStatus = 'Draft' | 'Approved' | 'Paid' | 'Locked'
export interface PayrollMonth {
  month: string
  status: MonthStatus
  payslips?: number
  net_pay?: number
  approved_at: string
  approved_by: string
  paid_at: string
  locked_at: string
  locked_by: string
  reopened_at: string
  reopened_by: string
  reopen_reason: string
}

/** A payslip's status as a badge colour, whatever case the server sends it in: paid is green, sent blue, void red. */
export function payslipTone(status: string | undefined): 'success' | 'info' | 'danger' | 'neutral' {
  switch ((status ?? '').toLowerCase()) {
    case 'paid': return 'success'
    case 'sent': return 'info'
    case 'void': return 'danger'
    default: return 'neutral'
  }
}

/** A month's payroll status as a badge colour. */
export const monthTone = (status: MonthStatus | undefined) =>
  status === 'Locked' ? 'neutral' : status === 'Paid' ? 'success' : status === 'Approved' ? 'info' : 'warning'

export interface PayslipDetail {
  id: number
  number: string
  employee: { full_name: string; employee_id: string; email: string; job_title: string; department_name: string; bank_name: string; bank_account: string; tax_id: string; start_date: string; work_location: string; uan_no?: string; esi_no?: string; aadhaar_masked?: string }
  days: { total: number; work: number; balance_leaves: number }
  period_start: string
  period_end: string
  pay_date: string
  hours_worked: number
  overtime_hours: number
  overtime_rate: number
  basic_salary: number
  overtime_pay: number
  bonus: number
  allowances: number
  gross_pay: number
  tax_amount: number
  insurance: number
  retirement: number
  other_deductions: number
  standing_deduction: number
  professional_tax?: number
  /** Paid days: the period's working days, the loss of pay in them, and the days paid. */
  working_days?: number
  lop_days?: number
  paid_days?: number
  /** What the company pays on top, not taken from the employee. */
  employer_pf?: number
  employer_epf?: number
  employer_eps?: number
  employer_esi?: number
  total_deductions: number
  net_pay: number
  status: string
  sent: boolean
  notes: string
  /** The monthly salary the structure was worked from, and the pay line by line; no lines for a payslip made without one. */
  monthly_salary?: number
  lines?: PayLine[]
  company: { name: string; address: string; email: string; phone: string; logo_url?: string }
}

export interface PayDetails {
  salary: number
  /** The month's tax as the payslip will deduct it: new-regime TDS for anybody without a flat rate. */
  tax_amount?: number
  hours_worked: number
  overtime_hours: number
  overtime_rate: number
  bonus: number
  allowances: number
  tax_rate: number
  deductions: number
  is_hourly?: boolean
  /** The month's statutory deductions as the server works them out (PF on the basic to 15,000, ESI to a 21,000 gross, PT by state slab). */
  provident_fund?: number
  state_insurance?: number
  professional_tax?: number
  /** Paid days of the period (joining, leaving, unpaid leave, absences, late penalty); null when the pay is not a monthly salary. */
  days?: { working_days: number; active_days: number; unpaid_leave: number; excess_leave: number; absent: number; late_count: number; late_penalty: number; lop_days: number; paid_days: number; factor: number } | null
  /** What the company's salary structure would make of this person's pay; null when it does not apply to them. */
  structure?: { name: string; kind: 'earning' | 'deduction'; amount: number; basis: 'percent' | 'manual'; percent: number }[] | null
}

/** One line of a payslip made from the salary structure. */
export interface PayLine { id: number; name: string; kind: 'earning' | 'deduction'; basis: 'percent' | 'manual'; percent: number; counts_as: string; amount: number }
/** One component of the company's salary structure. */
export interface SalaryComponent { id: number; name: string; kind: 'earning' | 'deduction'; basis: 'percent' | 'manual'; percent: number; counts_as: string; is_active: boolean; sort_order: number }
export type ComponentInput = Partial<Pick<SalaryComponent, 'name' | 'kind' | 'basis' | 'percent' | 'counts_as' | 'is_active'>>

export interface PayslipInput {
  employee_id: number
  period_start: string
  period_end: string
  pay_date: string
  hours_worked: number
  basic_salary: number
  overtime_hours: number
  overtime_rate: number
  bonus: number
  allowances: number
  insurance: number
  retirement: number
  other_deductions: number
  notes: string
}

export interface RunResult { created: { number: string }[]; skipped: unknown[]; total_net: number; warnings?: { name: string; number: string; reason: string }[] }
export interface Anomaly { employee_name: string; previous_net: number; current_net: number; change_pct: number; direction: string }

export const payslipsQuery = () => ({ queryKey: k('list'), queryFn: () => get<PayslipRow[]>('/api/payslips') })
export const usePayslips = () => useQuery(payslipsQuery())
export const usePayslip = (id: number | null) => useQuery({ queryKey: k('one', id), queryFn: () => get<PayslipDetail>(`/api/payslips/${id}`), enabled: !!id })
export const usePayDetails = (emp: number | null, start: string, end: string) =>
  useQuery({ queryKey: k('pay-details', emp, start, end), queryFn: () => get<PayDetails>(`/api/employees/${emp}/pay-details?period_start=${start}&period_end=${end}`), enabled: !!emp && !!start && !!end })
export const useAnomalies = () => useQuery({ queryKey: k('anomalies'), queryFn: () => get<{ anomalies: Anomaly[]; total_checked: number }>('/api/ai/payroll-anomalies'), enabled: false })

export const useSalaryStructure = (enabled = true) => useQuery({ queryKey: k('structure'), queryFn: () => get<{ components: SalaryComponent[] }>('/api/salary-structure'), enabled })
export const addComponent = (b: ComponentInput) => post<{ message?: string }>('/api/salary-structure', b)
export const saveComponent = (id: number, b: ComponentInput) => put<{ message?: string }>(`/api/salary-structure/${id}`, b)
export const removeComponent = (id: number) => del<{ message?: string }>(`/api/salary-structure/${id}`)
export const reorderComponents = (ids: number[]) => post<{ message?: string }>('/api/salary-structure/reorder', { ids })
/** HR types an amount on a payslip's own line (HRA, say), or brings the payslip up to date with the structure. */
export const savePayslipLines = (id: number, lines: { id: number; amount: number }[]) => put<{ message?: string }>(`/api/payslips/${id}`, { lines })
export const reapplyStructure = (id: number) => put<{ message?: string }>(`/api/payslips/${id}`, { reapply_structure: true })

export const createPayslip = (b: PayslipInput, allowOverlap: boolean) => post<{ message?: string }>(`/api/payslips${allowOverlap ? '?allow_overlap=true' : ''}`, b)
export type RunPeriod = { period_start: string; period_end: string; pay_date: string }
/** Figures HR may type over a previewed row; the rest follow from them and the salary structure. */
export type RunOverride = Partial<Record<'bonus' | 'overtime_hours' | 'hours_worked' | 'tax_amount', number>>
export interface PreviewRow {
  employee_id: number; name: string; hours_worked: number; overtime_hours: number; bonus: number; tax_amount: number
  basic_salary: number; allowances: number; gross_pay: number; total_deductions: number; net_pay: number
  working_days: number | null; paid_days: number | null; lop_days: number | null
}
export interface PayrollPreview { rows: PreviewRow[]; skipped: { name: string; reason: string }[]; warnings: { name: string; reason: string }[]; total_gross: number; total_net: number }
const runBody = (b: RunPeriod, employeeIds?: number[], overrides?: Record<number, RunOverride>) => ({ ...b, include_attendance_hours: true, skip_existing: true, employee_ids: employeeIds, overrides })
/** What the run would pay each person, worked out and thrown away. Master or HR only, on the server. */
export const previewPayroll = (b: RunPeriod, employeeIds?: number[], overrides?: Record<number, RunOverride>) => post<PayrollPreview>('/api/payroll/preview', runBody(b, employeeIds, overrides))
export const runPayroll = (b: RunPeriod, employeeIds?: number[], overrides?: Record<number, RunOverride>) => post<RunResult>('/api/payroll/run', runBody(b, employeeIds, overrides))
export const markPaid = (id: number) => post<{ message?: string }>(`/api/payslips/${id}/mark-paid`)
export const reopenPayslip = (id: number) => post<{ message?: string }>(`/api/payslips/${id}/unmark-paid`)
export const deletePayslip = (id: number, force: boolean) => del<{ message?: string }>(`/api/payslips/${id}${force ? '?force=true' : ''}`)
export const usePayrollMonths = () => useQuery({ queryKey: k('months'), queryFn: () => get<PayrollMonth[]>('/api/payroll/months') })
type MonthAnswer = PayrollMonth & { message?: string; emails?: { enabled: boolean; queued: number; skipped: string[]; message: string } }
/** Draft -> Approved -> Paid -> Locked; reopening a locked month is the Master's, with a reason. */
export const moveMonth = (action: 'approve' | 'pay' | 'lock', month: string) => post<MonthAnswer>(`/api/payroll/month/${action}`, { month })
export const reopenMonth = (month: string, reason: string) => post<MonthAnswer>('/api/payroll/month/reopen', { month, reopen_reason: reason })

export type ExportKind = 'neft' | 'ecr' | 'esic'
export const EXPORTS: { kind: ExportKind; label: string }[] = [
  { kind: 'neft', label: 'NEFT bank file' },
  { kind: 'ecr', label: 'EPFO ECR 2.0' },
  { kind: 'esic', label: 'ESIC sheet' },
]
export const exportUrl = (kind: ExportKind, month: string, allowIncomplete = false) =>
  `/api/payroll/exports/${kind}?month=${month}${allowIncomplete ? '&allow_incomplete=true' : ''}`

export const emailPayslip = (id: number) => post<{ message?: string }>(`/api/payslips/${id}/send`)

export const autoPayrollQuery = () => ({ queryKey: k('auto'), queryFn: () => get<{ enabled: boolean }>('/api/payroll/auto') })
export const useAutoPayroll = () => useQuery(autoPayrollQuery())
export const setAutoPayroll = (enabled: boolean) => put<{ enabled: boolean; message: string }>('/api/payroll/auto', { enabled })

/* --- Leaving, tax and leave: full and final, Form 16, the leave ledger -------------------------------------------- */

export interface SettlementPart { item: string; amount: number; note: string }
export interface Settlement {
  last_day: string
  start_date: string
  monthly_salary: number
  last_basic: number
  service: { completed_years: number; years_counted: number }
  gratuity: { eligible: boolean; amount: number; reason: string; years_counted: number }
  leave: { unused_days: number; day_pay: number; amount: number }
  arrears: { rows: { payslip: string; period_end: string; paid_on_salary: number; salary_now: number; amount: number }[]; total: number }
  parts: SettlementPart[]
  total: number
}
/** What is owed to somebody leaving. A calculation: nothing is saved or paid by asking. */
export const useSettlement = (id: number, lastDay: string) =>
  useQuery({ queryKey: k('settlement', id, lastDay), queryFn: () => get<Settlement>(`/api/employees/${id}/full-and-final?last_day=${lastDay}`), enabled: !!lastDay })
export const settlementPdf = (id: number, lastDay: string) => `/api/employees/${id}/full-and-final.pdf?last_day=${lastDay}`
export const form16Pdf = (id: number, fy: string) => `/api/employees/${id}/form16?fy=${fy}`
export const myForm16Pdf = (fy: string) => `/api/employee/form16?fy=${fy}`

/** The financial years to offer, newest first: the last completed one and the two before it, then the current one. */
export function financialYears(today = new Date()): string[] {
  const start = today.getMonth() >= 3 ? today.getFullYear() : today.getFullYear() - 1
  return [start - 1, start - 2, start - 3, start].map((y) => `${y}-${String((y + 1) % 100).padStart(2, '0')}`)
}

export interface LedgerEntry { id: number; leave_type: 'annual' | 'sick'; kind: string; date: string; days: number; note: string; by: string }
export interface LeaveLedger { year: number; enabled: boolean; entries: LedgerEntry[]; balance: Record<string, number> }
export const useLeaveLedger = (id: number, year: number) => useQuery({ queryKey: k('ledger', id, year), queryFn: () => get<LeaveLedger>(`/api/employees/${id}/leave-ledger?year=${year}`) })
export const adjustLeave = (id: number, b: { leave_type: string; days: number; note: string }) => post<{ message?: string }>(`/api/employees/${id}/leave-ledger`, b)
export const useLeaveAccrual = (enabled = true) => useQuery({ queryKey: k('accrual'), queryFn: () => get<{ enabled: boolean; carry_max: { annual: number; sick: number } }>('/api/leave/accrual'), enabled })
export const setLeaveAccrual = (b: { enabled?: boolean; carry_max?: { annual?: number; sick?: number } }) => put<{ message?: string; credited: number }>('/api/leave/accrual', b)
