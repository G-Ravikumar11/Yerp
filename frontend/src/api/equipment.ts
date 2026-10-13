import { useQuery } from '@tanstack/react-query'
import { get, post, put } from '@/lib/api'

export const eqKeys = { all: ['equipment'] as const }

export interface Machine {
  id: number
  code: string
  name: string
  category: string
  ownership: string
  make: string
  model: string
  reg_no: string
  serial_no: string
  purchase_date: string
  purchase_value: number
  hired_from: string
  hire_rate: number
  hire_basis: string
  meter_unit: string
  meter_reading: number
  service_every: number
  service_every_days: number
  last_service_on: string
  last_service_meter: number | null
  service_interval_type: IntervalType
  reminder_meter: number | null
  reminder_days: number | null
  insurance_until: string
  fitness_until: string
  current_job_id: number | null
  current_job: string
  status: string
  notes: string
  service: { due: boolean; soon: boolean; reasons: string[]; status: ServiceStatus; schedule: Schedule }
  cost_to_date: number
  ownership_label?: string
  condition?: string
  is_archived?: boolean
}
export type IntervalType = 'Both' | 'Meter' | 'Days' | 'None'
export type ServiceStatus = 'Overdue' | 'Service due' | 'Due soon' | 'Upcoming' | 'Incomplete' | 'Not scheduled'
/** Where a machine stands on its schedule, as the server works it out - the register, the machine and the dashboard read the same. */
export interface Schedule {
  type: IntervalType; unit: string; every_meter: number; every_days: number
  reminder_meter: number; reminder_days: number; reminder_meter_set: boolean; reminder_days_set: boolean
  last_service_on: string; last_service_meter: number | null
  next_meter: number | null; next_on: string | null; meter_left: number | null; days_left: number | null
  status: ServiceStatus; reasons: string[]; missing: string[]
}
export interface Register { assets: Machine[]; categories: string[]; summary: { machines: number; deployed: number; idle_in_yard: number; service_due: number; service_soon: number; cost_to_date: number; service_status?: Record<ServiceStatus, number> } }
export interface MachineLog { log_date: string; job: string; hours_worked: number; idle_hours: number; fuel_litres: number; fuel_cost: number; hire_cost: number; operator: string; work_done: string }
export interface MachineService {
  id: number; number: string; service_on: string; kind: string; status: string; description: string; vendor: string; meter_at_service: number | null; downtime_hours: number
  work_performed: string; parts_used: string; parts_cost: number; labour_cost: number; total_cost: number; next_service_meter: number | null; next_service_on: string; by: string
}
export interface MachineMove { moved_on: string; from: string; to: string; note: string }
export interface ScheduleEvent { at: string; action: string; details: string; by: string }
export interface MachineDetail extends Machine { utilisation_percent: number; litres_per_hour: number; logs: MachineLog[]; services: MachineService[]; moves: MachineMove[]; schedule_history: ScheduleEvent[] }
export type MachineInput = Omit<Machine, 'id' | 'code' | 'current_job_id' | 'current_job' | 'status' | 'service' | 'cost_to_date' | 'ownership_label' | 'is_archived'> & { code: string }

export const useRegister = (status: string, archived = false) => useQuery({ queryKey: ['equipment', 'register', status, archived], queryFn: () => get<Register>(`/api/assets?archived=${archived}${status ? `&status=${encodeURIComponent(status)}` : ''}`) })
export const archiveMachine = (id: number, restore = false) => post<{ message: string }>(`/api/assets/${id}/archive`, { restore })
export const useMachine = (id: number | null) => useQuery({ queryKey: ['equipment', 'one', id], enabled: !!id, queryFn: () => get<MachineDetail>(`/api/assets/${id}`) })

export const saveMachine = (id: number | null, b: MachineInput) => (id ? put<{ code: string; name: string }>(`/api/assets/${id}`, b) : post<{ code: string; name: string }>('/api/assets', b))
export const moveMachine = (id: number, b: { to_job_id: number | null; moved_on: string; note: string }) => post<{ message: string }>(`/api/assets/${id}/move`, b)
export const logDay = (id: number, b: Record<string, unknown>) => post<{ message: string; cost: number; service?: { due: boolean } }>(`/api/assets/${id}/logs`, b)
export const serviceMachine = (id: number, b: Record<string, unknown>) => post<{ message: string }>(`/api/assets/${id}/services`, b)
export const completeService = (id: number, b: Record<string, unknown>) => post<{ message: string }>(`/api/assets/${id}/service-complete`, b)
export const backInService =(id: number) => post<{ message: string }>(`/api/assets/${id}/back-in-service`)
