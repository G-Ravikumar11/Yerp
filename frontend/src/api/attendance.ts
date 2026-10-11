import { useQuery } from '@tanstack/react-query'
import { get, post, put } from '@/lib/api'

export const attKeys = { all: ['attendance'] as const }
const k = (...p: unknown[]) => ['attendance', ...p] as const

export interface AttStats { total_employees: number; present: number; absent: number; avg_hours: number; date: string }
export interface LivePerson {
  id: number
  employee_id: string
  full_name: string
  job_title: string
  department: string
  clock_in: string
  clock_out: string
  total_hours: number
  attendance_status: string
  location_label: string
  check_type: string
}
export interface AttRecord {
  id: number
  employee_id: number
  employee_name: string
  employee_email: string
  date: string
  clock_in: string
  clock_out: string
  total_hours: number
  status: string
  check_type?: string
  location_label?: string
}
export interface BySite {
  fenced_sites: number
  sites: { project: string; people: { employee: string; job_title: string; clock_in: string }[] }[]
  elsewhere: { employee: string; job_title: string; clock_in: string }[]
  summary: { on_site: number; elsewhere: number }
}
export interface Analytics { avg_daily_hours: number; late_arrivals: number; overtime_sessions: number; remote_sessions: number; avg_attendance_rate: number; daily: Record<string, { present: number; absent: number; hours: number }> }
export interface AttSettings {
  office_name: string
  office_lat: number
  office_lng: number
  geofence_radius: number
  work_start: string
  work_end: string
  grace_minutes: number
  auto_clockout_hours: number
  max_overtime_hours: number
  allow_remote: boolean
  require_location: boolean
  working_days: string
  auto_clock_in: boolean
}
export interface OvertimeLog { id?: number; employee_id: number; employee_name: string; date: string; hours: number; reason: string; announced_by: string; status: string }

export const useAttStats = () => useQuery({ queryKey: k('stats'), queryFn: () => get<AttStats>('/api/attendance/stats') })
export const useLive = () => useQuery({ queryKey: k('live'), queryFn: () => get<LivePerson[]>('/api/attendance/live'), refetchInterval: 60_000 })
export const useBySite = () => useQuery({ queryKey: k('by-site'), queryFn: () => get<BySite>('/api/attendance/by-site') })
export const useAttRecords = (date: string) => useQuery({ queryKey: k('records', date), queryFn: () => get<AttRecord[]>(`/api/attendance${date ? `?date=${encodeURIComponent(date)}` : ''}`) })
export const useAnalytics = (days = 30) => useQuery({ queryKey: k('analytics', days), queryFn: () => get<Analytics>(`/api/attendance/analytics?days=${days}`) })
export const useAttSettings = () => useQuery({ queryKey: k('settings'), queryFn: () => get<AttSettings>('/api/attendance/settings') })
export const useOvertime = () => useQuery({ queryKey: k('overtime'), queryFn: () => get<OvertimeLog[]>('/api/attendance/overtime/logs') })

export const clockFor = (employee_id: number, which: 'in' | 'out') => post<{ message: string; total_hours?: number }>(`/api/attendance/clock-${which}`, { employee_id })
export const saveAttSettings = (b: AttSettings) => put<{ message?: string }>('/api/attendance/settings', b)
export const announceOvertime = (b: { employee_id: number; date: string; hours: number; reason: string }) => post<{ message: string }>('/api/attendance/overtime/announce', b)
export const exportAttendance = (date: string) => get<Record<string, unknown>[]>(`/api/attendance/export${date ? `?start_date=${date}&end_date=${date}` : ''}`)
