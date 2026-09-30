import { useQuery } from '@tanstack/react-query'
import { del, get, post } from '@/lib/api'

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
}

export interface PayslipDetail {
  id: number
  number: string
  employee: { full_name: string; employee_id: string; email: string; job_title: string; department_name: string; bank_name: string; bank_account: string; tax_id: string }
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
  total_deductions: number
  net_pay: number
  status: string
  sent: boolean
  notes: string
  company: { name: string; address: string; email: string; phone: string }
}

export interface PayDetails {
  salary: number
  hours_worked: number
  overtime_hours: number
  overtime_rate: number
  bonus: number
  allowances: number
  tax_rate: number
  deductions: number
  is_hourly?: boolean
}

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

export const usePayslips = () => useQuery({ queryKey: k('list'), queryFn: () => get<PayslipRow[]>('/api/payslips') })
export const usePayslip = (id: number | null) => useQuery({ queryKey: k('one', id), queryFn: () => get<PayslipDetail>(`/api/payslips/${id}`), enabled: !!id })
export const usePayDetails = (emp: number | null, start: string, end: string) =>
  useQuery({ queryKey: k('pay-details', emp, start, end), queryFn: () => get<PayDetails>(`/api/employees/${emp}/pay-details?period_start=${start}&period_end=${end}`), enabled: !!emp && !!start && !!end })
export const useAnomalies = () => useQuery({ queryKey: k('anomalies'), queryFn: () => get<{ anomalies: Anomaly[]; total_checked: number }>('/api/ai/payroll-anomalies'), enabled: false })

export const createPayslip = (b: PayslipInput, allowOverlap: boolean) => post<{ message?: string }>(`/api/payslips${allowOverlap ? '?allow_overlap=true' : ''}`, b)
export const runPayroll = (b: { period_start: string; period_end: string; pay_date: string }) => post<RunResult>('/api/payroll/run', { ...b, include_attendance_hours: true, skip_existing: true })
export const markPaid = (id: number) => post<{ message?: string }>(`/api/payslips/${id}/mark-paid`)
export const reopenPayslip = (id: number) => post<{ message?: string }>(`/api/payslips/${id}/unmark-paid`)
export const deletePayslip = (id: number, force: boolean) => del<{ message?: string }>(`/api/payslips/${id}${force ? '?force=true' : ''}`)
export const emailPayslip = (id: number) => post<{ message?: string }>(`/api/payslips/${id}/send`)
