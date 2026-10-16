import { useQuery, type QueryClient } from '@tanstack/react-query'
import { del, get, post, put } from '@/lib/api'

export interface Employee {
  id: number
  employee_id: string
  first_name: string
  last_name: string
  full_name: string
  email: string
  org_email?: string
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

interface OnboardingItem {
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
  /** The sites it was added to. One on no site is shown nowhere. */
  site_ids: number[]
}

interface Permission {
  key: string
  group: string
  label: string
  /** Held only by this access level (and the Master) - 'ho_qs' for opening vendor codes, work orders and BOQs. */
  only_role?: string
}

interface PermissionRole {
  code: string
  label: string
  rank: number
  description: string
  permissions: string[]
  retired?: boolean
  /** HO QS and HO Coordinator: they land on the HO portal. */
  head_office?: boolean
}

/** One card on the Access screen: a portal, set to No access, Read only or Read & write. `read` and `write` are the rights it sets. */
export interface Portal {
  code: string
  label: string
  blurb: string
  read: string[]
  write: string[]
  /** Set when the portal cannot be given to anybody but the Master, and why. */
  locked?: string
}

export interface HrCatalogue {
  portals: Portal[]
  levels: { code: string; label: string }[]
  roles: { code: string; label: string }[]
  permission_roles: PermissionRole[]
  permissions: Permission[]
}

export const peopleKeys = { all: ['people'] as const }
const k = (...p: unknown[]) => ['people', ...p] as const

export const useEmployees = (status: string) => useQuery({ queryKey: k('employees', status), queryFn: () => get<Employee[]>(`/api/employees${status ? `?status=${encodeURIComponent(status)}` : ''}`) })
export const useEmployee = (id: number) => useQuery({ queryKey: k('employee', id), queryFn: () => get<EmployeeDetail>(`/api/employees/${id}`), enabled: id > 0 })
/** Every site in the application, finished ones too: a department can be assigned to any of them. */
export const useAllSites = () => useQuery({ queryKey: ['jobs', 'all-sites'], queryFn: async () => (await get<{ jobs: { id: number; number: string; name: string }[] }>('/api/jobs?costing=false')).jobs ?? [], staleTime: 5 * 60_000 })
export const useDepartments = () => useQuery({ queryKey: k('departments'), queryFn: () => get<Department[]>('/api/departments') })
export const useHrCatalogue = () => useQuery({ queryKey: k('catalogue', 'v2'), queryFn: () => get<HrCatalogue>('/api/hr/levels'), staleTime: 60_000 })
export const useHrStats = () => useQuery({ queryKey: k('stats'), queryFn: () => get<{ total_employees: number; active: number; onboarding: number; offboarding: number; terminated: number; departments: number }>('/api/hr/stats') })
export const useSuggestedEmail = (first: string, last: string) =>
  useQuery({ queryKey: k('suggest', first, last), queryFn: async () => (await get<{ email?: string }>(`/api/hr/suggest-email?first_name=${encodeURIComponent(first)}&last_name=${encodeURIComponent(last)}`)).email ?? '', enabled: !!(first.trim() && last.trim()), staleTime: 60_000 })

export interface EmployeeInput {
  first_name: string
  last_name: string
  email: string
  org_email?: string
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
export const setAccess = (id: number, b: { permission_role: string; permissions: string[]; site_ids?: number[] }) => put<{ message: string }>(`/api/employees/${id}/permissions`, b)
/** Removes the person for good, with their payslips, attendance, leave and documents. The Master only. */
export const deleteEmployee = (id: number) => del<{ message: string }>(`/api/employees/${id}`)
export const setEmployeeStatus = (id: number, to: 'onboard' | 'offboard' | 'terminate') => post<{ message: string; status: string; end_date?: string }>(`/api/employees/${id}/${to}`)

export type DepartmentInput = { name: string; description: string; color: string; icon: string; site_ids?: number[] }
export const saveDepartment = (id: number | null, b: DepartmentInput) => (id ? put<Department>(`/api/departments/${id}`, b) : post<Department>('/api/departments', b))
/**
 * Shows a department change straight away from what the server sent back, then refreshes the rest
 * quietly behind it. Waiting for every People list to reload first held each click open for
 * several seconds on a far-away database.
 */
export function showDepartmentChange(qc: QueryClient, change: { saved?: Department; deletedId?: number }, { refresh = true } = {}) {
  const { saved, deletedId } = change
  const inSaved = new Set(saved?.employees.map((e) => e.id) ?? [])
  qc.setQueryData<Department[]>(k('departments'), (list) => {
    if (!list) return list
    let next = list.filter((d) => d.id !== deletedId)
    if (saved) {
      // Whoever is in this one now has left wherever they were.
      next = next.map((d) => {
        if (d.id === saved.id) return saved
        const kept = d.employees.filter((e) => !inSaved.has(e.id))
        return kept.length === d.employees.length ? d : { ...d, employees: kept, employee_count: kept.length }
      })
      if (!next.some((d) => d.id === saved.id)) next = [...next, saved].sort((a, b) => a.name.localeCompare(b.name))
    }
    return next
  })
  qc.setQueriesData<Employee[]>({ queryKey: k('employees') }, (list) =>
    list?.map((e) => {
      if (saved && inSaved.has(e.id)) return e.department_id === saved.id && e.department_name === saved.name ? e : { ...e, department_id: saved.id, department_name: saved.name }
      if ((saved && e.department_id === saved.id) || (deletedId && e.department_id === deletedId)) return { ...e, department_id: null, department_name: '' }
      return e
    }),
  )
  if (!refresh) return
  void qc.invalidateQueries({ queryKey: peopleKeys.all })
  void qc.invalidateQueries({ queryKey: ['orders', 'vocabulary'] })
}

/** Puts these people in the department, moving any already in another one. The Master only. */
export const addToDepartment = (id: number, employee_ids: number[]) => post<Department>(`/api/departments/${id}/employees`, { employee_ids })
export const removeFromDepartment = (id: number, employeeId: number) => del<Department>(`/api/departments/${id}/employees/${employeeId}`)
