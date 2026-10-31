import { useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'
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
  /** Optional, and given by the employee in their own portal. Aadhaar comes back masked. */
  gender?: string
  /** YYYY-MM-DD. Colleagues see only the day and month, on the Celebrations page. */
  date_of_birth?: string
  pan_no?: string
  uan_no?: string
  esi_no?: string
  aadhaar_masked?: string
  /** Whether they have a password to sign in with. The password itself is never sent. */
  has_password: boolean
  /** How their login email went: empty if never sent, then sending, sent or failed. */
  credentials_email_status?: string
  credentials_email_at?: string
  permissions: string[]
  role_permissions: string[]
  extra_permissions: string[]
  denied_permissions: string[]
  site_ids: number[]
  site_names: string[]
  all_sites: boolean
  /** Only in the full record (without ?view=profile); the employee's page does not ask for them. */
  onboarding_items?: OnboardingItem[]
  payslips?: unknown[]
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
  /** A right broad enough to be ticked only knowingly (the Store administrator): shown where it is switched on. */
  warning?: string
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
  /** `rank` is higher for a more senior level: L1 is the top. */
  levels: { code: string; label: string; rank: number }[]
  /** `reports_to` is the role this one normally reports to; `level` is where it sits. */
  /** `access` is the access level the role normally carries, which the Add form gives them straight away. */
  roles: { code: string; label: string; level: string; reports_to: string | null; department: string; access?: string }[]
  permission_roles: PermissionRole[]
  permissions: Permission[]
}

export const peopleKeys = { all: ['people'] as const }

/** The cards HR keeps on file besides the numbers: what each is called, and the kind it is filed under. */
export const ID_DOCUMENTS = [
  { key: 'aadhaar', title: 'Aadhaar card', type: 'identity' },
  { key: 'pan', title: 'PAN card', type: 'identity' },
  { key: 'esi', title: 'ESI card', type: 'finance' },
] as const
export type IdDocumentKey = (typeof ID_DOCUMENTS)[number]['key']
/** What the server accepts: a photo (JPG, JPEG, PNG, WEBP) or a PDF, Word or text file, up to 5 MB. */
export const DOCUMENT_ACCEPT = '.pdf,.jpg,.jpeg,.png,.webp,.doc,.docx,.txt'

export interface EmployeeDoc { id: number; title: string; doc_type: string; file_name: string; file_size: number; uploaded_by: string; created_at: string }
export const useEmployeeDocuments = (id: number) => useQuery({ queryKey: [...peopleKeys.all, 'documents', id], queryFn: () => get<EmployeeDoc[]>(`/api/employees/${id}/documents`) })

const toBase64 = (file: File) => new Promise<string>((res, rej) => {
  const r = new FileReader()
  r.onerror = () => rej(new Error('Could not read that file. Try another copy of it.'))
  r.onload = () => res(String(r.result).split(',')[1] ?? '')
  r.readAsDataURL(file)
})

/** Keeps a file on somebody's record. The file travels as base64, as the staff portal's uploads do. */
export async function uploadEmployeeDocument(id: number, title: string, docType: string, file: File) {
  return post<{ message?: string; id?: number }>(`/api/employees/${id}/documents`, { title, doc_type: docType, file_name: file.name, file_type: file.type, file_data: await toBase64(file) })
}

/** The file comes back as base64 in JSON; hand it to the browser as a download. */
export async function downloadEmployeeDocument(id: number, docId: number) {
  const f = await get<{ file_name: string; file_type: string; file_data: string }>(`/api/employees/${id}/documents/${docId}/download`)
  const bytes = Uint8Array.from(atob(f.file_data), (c) => c.charCodeAt(0))
  const url = URL.createObjectURL(new Blob([bytes], { type: f.file_type || 'application/octet-stream' }))
  const a = document.createElement('a')
  a.href = url
  a.download = f.file_name
  a.click()
  setTimeout(() => URL.revokeObjectURL(url), 10_000)
}

export const deleteEmployeeDocument = (id: number, docId: number) => del<{ message?: string }>(`/api/employees/${id}/documents/${docId}`)
const k = (...p: unknown[]) => ['people', ...p] as const

export const employeesQuery = (status: string) => ({ queryKey: k('employees', status), queryFn: () => get<Employee[]>(`/api/employees${status ? `?status=${encodeURIComponent(status)}` : ''}`) })
export const useEmployees = (status: string) => useQuery(employeesQuery(status))
const employeeQuery = (id: number) => ({ queryKey: k('employee', id), queryFn: () => get<EmployeeDetail>(`/api/employees/${id}?view=profile`) })
/**
 * What the employee's page shows (profile, access, sites): three reads on the server rather than a dozen for everything
 * about them. Until it arrives the page is drawn from their row in the employee list, so opening somebody is instant;
 * `isPlaceholderData` says the access and actions are not loaded yet.
 */
export function useEmployee(id: number) {
  const qc = useQueryClient()
  return useQuery({
    ...employeeQuery(id), enabled: id > 0,
    placeholderData: () => {
      for (const [, list] of qc.getQueriesData<Employee[]>({ queryKey: k('employees') })) {
        const row = Array.isArray(list) ? list.find((e) => e.id === id) : undefined
        if (row) return { ...row, address: '', has_password: false, permissions: [], role_permissions: [], extra_permissions: [], denied_permissions: [], site_ids: [], site_names: [], all_sites: true } satisfies EmployeeDetail
      }
      return undefined
    },
  })
}
/** Starts reading somebody's page before they are clicked (the pointer is on their row); a fresh copy is not read twice. */
export const prefetchEmployee = (qc: QueryClient, id: number) => void qc.prefetchQuery({ ...employeeQuery(id), staleTime: 30_000 })
/** Every site in the application, finished ones too: a department can be assigned to any of them. */
export const allSitesQuery = () => ({ queryKey: ['jobs', 'all-sites'], queryFn: async () => (await get<{ jobs: { id: number; number: string; name: string }[] }>('/api/jobs?costing=false')).jobs ?? [], staleTime: 5 * 60_000 })
export const useAllSites = () => useQuery(allSitesQuery())
export const departmentsQuery = () => ({ queryKey: k('departments'), queryFn: () => get<Department[]>('/api/departments') })
export const useDepartments = () => useQuery(departmentsQuery())
/** Levels, roles, access levels and portals. They are fixed in the code, so they are read once and kept, and live outside the People keys: a save there does not read them again. */
export const hrCatalogueQuery = () => ({ queryKey: ['hr-catalogue', 'v3'], queryFn: () => get<HrCatalogue>('/api/hr/levels'), staleTime: Infinity, gcTime: Infinity })
export const useHrCatalogue = () => useQuery(hrCatalogueQuery())
export const hrStatsQuery = () => ({ queryKey: k('stats'), queryFn: () => get<{ total_employees: number; active: number; onboarding: number; offboarding: number; terminated: number; departments: number }>('/api/hr/stats') })
export const useHrStats = () => useQuery(hrStatsQuery())
export const useSuggestedEmail = (first: string, last: string) =>
  useQuery({ queryKey: k('suggest', first, last), queryFn: async () => (await get<{ email?: string }>(`/api/hr/suggest-email?first_name=${encodeURIComponent(first)}&last_name=${encodeURIComponent(last)}`)).email ?? '', enabled: !!(first.trim() && last.trim()), staleTime: 60_000 })

export interface EmployeeInput {
  first_name: string
  last_name: string
  email: string
  org_email?: string
  password?: string
  phone: string
  address?: string
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
  /** Optional: Male, Female, Other or Prefer not to say. */
  gender?: string
  date_of_birth?: string
  /** Optional statutory numbers. UAN is 12 digits, Aadhaar 12 digits, ESI 10 (17 for an employer code). */
  aadhaar_no?: string
  pan_no?: string
  uan_no?: string
  esi_no?: string
  /** The rights the Master ticked, saved with the employee in the same request. Left out, the access level's own apply. */
  permissions?: string[]
}

export const createEmployee = (b: EmployeeInput) => post<{ id: number; employee_id: string; first_name: string; site_names?: string[]; message: string }>('/api/employees', b)
/** Both answer with the saved profile, so the page shows it without asking again. */
export const updateEmployee = (id: number, b: Partial<EmployeeInput> & Record<string, unknown>) => put<EmployeeDetail & { message: string }>(`/api/employees/${id}`, b)
export const setAccess = (id: number, b: { permission_role: string; permissions: string[]; site_ids?: number[] }) => put<EmployeeDetail & { message: string }>(`/api/employees/${id}/permissions`, b)
/**
 * Shows a change to one employee straight away - their page from `saved` (the server's answer), or gone from every list
 * when `deletedId` - then reads the People lists again quietly behind it. Waiting for every list to reload first held
 * each save open for seconds on a far-away database; the record just saved is not read again at all.
 */
export function showEmployeeChange(qc: QueryClient, change: { saved?: EmployeeDetail; deletedId?: number; patch?: { id: number } & Partial<EmployeeDetail> }) {
  const { saved, deletedId, patch } = change
  const id = saved?.id ?? patch?.id ?? deletedId
  if (saved) qc.setQueryData<EmployeeDetail>(k('employee', saved.id), saved)
  if (patch) qc.setQueryData<EmployeeDetail>(k('employee', patch.id), (old) => old && { ...old, ...patch })
  if (deletedId) qc.removeQueries({ queryKey: k('employee', deletedId) })
  const row = saved ?? patch
  qc.setQueriesData<Employee[]>({ queryKey: k('employees') }, (list) => {
    if (!Array.isArray(list)) return list
    if (deletedId) return list.filter((e) => e.id !== deletedId)
    return row ? list.map((e) => (e.id === row.id ? { ...e, ...pickListFields(row) } : e)) : list
  })
  void qc.invalidateQueries({ queryKey: peopleKeys.all, predicate: (q) => !(q.queryKey[1] === 'employee' && q.queryKey[2] === id) })
}

const LIST_FIELDS = ['first_name', 'last_name', 'full_name', 'email', 'org_email', 'phone', 'department_id', 'department_name', 'reports_to', 'manager_name', 'job_title', 'role', 'level', 'permission_role', 'employment_type', 'pay_frequency', 'salary', 'tax_rate', 'emergency_contact', 'emergency_phone', 'start_date', 'end_date', 'status'] as const
function pickListFields(e: Partial<EmployeeDetail>): Partial<Employee> {
  const out: Partial<Employee> = {}
  for (const f of LIST_FIELDS) if (e[f] !== undefined) (out as Record<string, unknown>)[f] = e[f]
  if (e.site_ids !== undefined) out.site_count = e.all_sites ? 0 : e.site_ids.length
  return out
}

/** Removes the person for good, with their payslips, attendance, leave and documents. The Master only. */
export const deleteEmployee = (id: number) => del<{ message: string }>(`/api/employees/${id}`)
/** The Master gives somebody a password to sign in with (nothing is emailed). */
export const setEmployeePassword = (id: number, password: string) => put<{ message?: string }>(`/api/employees/${id}/set-password`, { password })
/** Their login email again, to the organization email, with a one-time link to set a password. */
export const sendLoginEmail = (id: number) => post<{ ok: boolean; message: string; credentials_email_status: string; credentials_email_at: string }>(`/api/employees/${id}/login-email`, {})
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

export interface SalaryRevision { id: number; old_salary: number; new_salary: number; percent: number; effective_date: string; valid_until: string; reason: string; changed_by: string; created_at: string }
export const useSalaryHistory = (id: number, enabled = true) => useQuery({ queryKey: [...peopleKeys.all, 'salary-history', id], queryFn: () => get<{ salary: number; revisions: SalaryRevision[] }>(`/api/employees/${id}/salary-history`), enabled })
export const giveIncrement = (id: number, body: { mode: 'percent' | 'amount'; value: number; effective_date: string; valid_until: string; reason: string }) =>
  post<{ message: string; salary: number; revision: SalaryRevision }>(`/api/employees/${id}/increment`, body)
