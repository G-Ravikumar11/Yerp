import { useQuery } from '@tanstack/react-query'
import { del, get, post, put } from '@/lib/api'

export interface Employee {
  id: number
  employee_id: string
  first_name: string
  last_name: string
  full_name: string
  email: string
  phone: string
  department_id: number | null
  department_name: string
  reports_to: number | null
  manager_name: string
  job_title: string
  role: string
  level: string
  permission_role: string
  employment_type: string
  pay_frequency: string
  salary: number
  tax_rate: number
  emergency_contact: string
  emergency_phone: string
  start_date: string
  end_date: string
  status: string
  site_count?: number
}

export interface OnboardingItem {
  id: number
  title: string
  category: string
  is_completed: boolean
  assigned_to: string
}

export interface EmployeeDetail extends Employee {
  address: string
  permissions: string[]
  role_permissions: string[]
  extra_permissions: string[]
  denied_permissions: string[]
  site_ids: number[]
  site_names: string[]
  all_sites: boolean
  onboarding_items: OnboardingItem[]
  payslips: unknown[]
}

export interface Department {
  id: number
  name: string
  description: string
  color: string
  icon: string
  employee_count: number
  employees: { id: number; name: string; job_title: string; email: string; status?: string }[]
}

export interface Permission {
  key: string
  group: string
  label: string
}

export interface PermissionRole {
  code: string
  label: string
  rank: number
  description: string
  permissions: string[]
  retired?: boolean
}

export interface HrCatalogue {
  levels: { code: string; label: string }[]
  roles: { code: string; label: string }[]
  permission_roles: PermissionRole[]
  permissions: Permission[]
}

export const peopleKeys = { all: ['people'] as const }
const k = (...p: unknown[]) => ['people', ...p] as const

export const useEmployees = (status: string) => useQuery({ queryKey: k('employees', status), queryFn: () => get<Employee[]>(`/api/employees${status ? `?status=${encodeURIComponent(status)}` : ''}`) })
export const useEmployee = (id: number) => useQuery({ queryKey: k('employee', id), queryFn: () => get<EmployeeDetail>(`/api/employees/${id}`), enabled: id > 0 })
export const useDepartments = () => useQuery({ queryKey: k('departments'), queryFn: () => get<Department[]>('/api/departments') })
export const useHrCatalogue = () => useQuery({ queryKey: k('catalogue'), queryFn: () => get<HrCatalogue>('/api/hr/levels'), staleTime: 10 * 60_000 })
export const useHrStats = () => useQuery({ queryKey: k('stats'), queryFn: () => get<{ total_employees: number; active: number; onboarding: number; offboarding: number; terminated: number; departments: number }>('/api/hr/stats') })
export const useSuggestedEmail = (first: string, last: string) =>
  useQuery({ queryKey: k('suggest', first, last), queryFn: async () => (await get<{ email?: string }>(`/api/hr/suggest-email?first_name=${encodeURIComponent(first)}&last_name=${encodeURIComponent(last)}`)).email ?? '', enabled: !!(first.trim() && last.trim()), staleTime: 60_000 })

export interface EmployeeInput {
  first_name: string
  last_name: string
  email: string
  password?: string
  phone: string
  job_title: string
  department_id: number | null
  reports_to: number | null
  level: string
  role: string
  permission_role: string
  site_ids: number[]
  employee_id?: string
  employment_type: string
  pay_frequency: string
  salary: number
  tax_rate: number
  start_date: string
  emergency_contact: string
  emergency_phone: string
}

export const createEmployee = (b: EmployeeInput) => post<{ id: number; employee_id: string; first_name: string; site_names?: string[]; message: string }>('/api/employees', b)
export const updateEmployee = (id: number, b: Partial<EmployeeInput> & Record<string, unknown>) => put<{ message?: string }>(`/api/employees/${id}`, b)
export const setAccess = (id: number, b: { permission_role: string; permissions: string[] }) => put<{ message: string }>(`/api/employees/${id}/permissions`, b)
export const resetPassword = (id: number, password: string) => post<{ message: string }>(`/api/employees/${id}/reset-password`, { password })
export const startOffboarding = (id: number) => post<{ message: string }>(`/api/employees/${id}/offboard`)

export type DepartmentInput = { name: string; description: string; color: string; icon: string }
export const saveDepartment = (id: number | null, b: DepartmentInput) => (id ? put<{ id: number }>(`/api/departments/${id}`, b) : post<{ id: number }>('/api/departments', b))
export const deleteDepartment = (id: number) => del<{ message: string }>(`/api/departments/${id}`)
