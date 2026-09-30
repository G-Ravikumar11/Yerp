import { useQuery } from '@tanstack/react-query'
import { get, post, put } from '@/lib/api'

/** A member of staff's own day: where they are clocked in, what waits for them, and the sites they work on. */
export interface Today {
  date: string
  name: string
  clock: { in: string; out: string; site: string }
  waiting?: { text: string; view: string; job_id: number }[]
  sites: { job_id: number; number: string; name: string; diary: { status: string } | null; permits_live: number; permits_overdue: number; incidents_open: number; inspections_open: number; unread: number }[]
}

export const staffKeys = { all: ['staff'] as const, clock: ['staff', 'clock'] as const, today: ['staff', 'today'] as const, dashboard: ['staff', 'dashboard'] as const }
const k = (...p: unknown[]) => ['staff', ...p] as const

export const useToday = () => useQuery({ queryKey: k('today'), queryFn: () => get<Today>('/api/employee/today') })

/** Clocked in where the phone is: the server matches the position to a site. */
export async function clock(which: 'in' | 'out') {
  const coords = await new Promise<GeolocationCoordinates | null>((res) => {
    if (!navigator.geolocation) return res(null)
    navigator.geolocation.getCurrentPosition((p) => res(p.coords), () => res(null), { timeout: 8000, enableHighAccuracy: true, maximumAge: 60000 })
  })
  const body: Record<string, unknown> = { device_info: navigator.userAgent.slice(0, 120) }
  if (coords) Object.assign(body, { latitude: coords.latitude, longitude: coords.longitude })
  return post<{ message?: string }>(`/api/employee/attendance/clock-${which}`, body)
}

export interface Attendance {
  date: string
  clock_in: string
  clock_out: string
  total_hours: number
  status: string
  check_type?: string
  break_minutes?: number
  overtime_hours?: number
  location_label?: string
}

export interface Payslip {
  number: string
  period_start: string
  period_end: string
  pay_date: string
  net_pay: number
  status: string
}

export const useMyDashboard = () => useQuery({ queryKey: k('dashboard'), queryFn: () => get<{ attendance: Attendance[]; payslips: Payslip[]; attendance_summary: { days_present: number; total_hours: number; avg_hours: number } }>('/api/employee/dashboard') })

/* --- Leave -------------------------------------------------------------------------------- */

export interface LeaveRequest {
  id: number
  leave_type: string
  start_date: string
  end_date: string
  days: number
  status: string
  reason: string
}

export interface LeaveBalance {
  annual_total: number
  annual_taken: number
  annual_pending: number
  annual_remaining: number
  sick_total: number
  sick_taken: number
  sick_remaining: number
}

export const useMyLeave = () => useQuery({ queryKey: k('leave'), queryFn: () => get<{ requests: LeaveRequest[]; balance: LeaveBalance }>('/api/employee/leave') })
export const requestLeave = (b: { leave_type: string; start_date: string; end_date: string; reason: string }) => post<{ message?: string }>('/api/employee/leave', b)

/* --- Costs: a bill a member of staff sends up for approval ------------------------------------ */

export interface MyCost {
  id: number
  number: string
  vendor_name: string
  job_id: number | null
  job_name: string
  issue_date: string
  amount: number
  tax_amount: number
  total: number
  category: string
  reference: string
  notes: string
  status: string
  approval_status: string
  rejection_reason: string
  purchase_order_id: number | null
  purchase_order_number?: string
  over_order?: boolean
}

export const useMyCosts = () => useQuery({ queryKey: k('costs'), queryFn: async () => (await get<{ bills: MyCost[] }>('/api/employee/bills')).bills ?? [] })

export type CostInput = { vendor_name: string; amount: number; tax_amount: number; issue_date: string; reference: string; category: string; notes: string; job_id: number | null; purchase_order_id: number | null }
export const sendCost = async (id: number | null, b: CostInput) => {
  if (!id) return post<{ message?: string }>('/api/employee/bills', b)
  await put(`/api/employee/bills/${id}`, b)
  return post<{ message?: string }>(`/api/employee/bills/${id}/submit`)
}

/* --- Documents ---------------------------------------------------------------------------------- */

export interface DocRequest {
  id: number
  name: string
  description: string
  doc_type: string
  is_mandatory: boolean
  status: string
  due_date: string
  is_overdue: boolean
  requires_expiry: boolean
  expires_on: string
  review_note: string
  file_name?: string
}

export interface MyFile { id: number; title: string; doc_type: string; file_name: string; uploaded_by: string; created_at: string }

export const useMyDocuments = () =>
  useQuery({
    queryKey: k('documents'),
    queryFn: async () => {
      const r = await get<{ requests: DocRequest[]; limits: { max_mb: number; allowed: string[] } }>('/api/employee/document-requests')
      return { requests: r.requests ?? [], limits: r.limits, files: await get<MyFile[]>('/api/employee/documents') }
    },
  })

/** Read a chosen file as base64 and send it against one request. */
export async function uploadDocument(id: number, file: File, expires_on: string) {
  const data = await new Promise<string>((res, rej) => {
    const r = new FileReader()
    r.onerror = () => rej(new Error('Could not read that file. Try another copy of it.'))
    r.onload = () => res(String(r.result).split(',')[1] ?? '')
    r.readAsDataURL(file)
  })
  return post<{ message?: string }>(`/api/employee/document-requests/${id}/upload`, { file_name: file.name, file_type: file.type, file_data: data, expires_on })
}

/** The file comes back as base64 in JSON; hand it to the browser as a download. */
export async function downloadMyFile(id: number) {
  const f = await get<{ file_name: string; file_type: string; file_data: string }>(`/api/employee/documents/${id}/download`)
  const bytes = Uint8Array.from(atob(f.file_data), (c) => c.charCodeAt(0))
  const url = URL.createObjectURL(new Blob([bytes], { type: f.file_type || 'application/octet-stream' }))
  const a = document.createElement('a')
  a.href = url
  a.download = f.file_name
  a.click()
  setTimeout(() => URL.revokeObjectURL(url), 10_000)
}

/* --- The clock ----------------------------------------------------------------------------------- */

export interface ClockState {
  clocked_in: boolean
  is_working_day?: boolean
  clock_in?: string
  clock_out?: string
  total_hours?: number
  is_on_break?: boolean
  break_minutes?: number
  overtime_hours?: number
  elapsed_hours?: number
  status?: string
}

export const useClock = () => useQuery({ queryKey: k('clock'), queryFn: () => get<ClockState>('/api/employee/attendance/today'), refetchInterval: 60_000 })
export const breakFor = (which: 'start' | 'stop') => post<{ message?: string }>(`/api/employee/attendance/break-${which}`)

export interface MyJob { id: number; number: string; name: string; customer_name: string; site_address: string }
export const useMyJobs = () => useQuery({ queryKey: k('jobs'), queryFn: async () => (await get<{ jobs: MyJob[] }>('/api/employee/jobs')).jobs ?? [] })
export const bookToJob = (job_id: number | null) => post<{ message?: string }>('/api/employee/attendance/job', { job_id })
