import { useQuery } from '@tanstack/react-query'
import { del, get, post, put } from '@/lib/api'
import { useSession } from '@/lib/session'

export interface Project {
  id: number
  number: string
  name: string
  customer_name: string
  status: string
  site_address?: string
  quoted_value?: number
  budget?: number
  start_date?: string
  target_end_date?: string
}

/** The projects this person works on: every live one for the office, the sites they are assigned to for staff. */
export function useProjects() {
  const { user } = useSession()
  const staff = user?.type === 'employee'
  return useQuery({
    queryKey: ['projects', 'mine', staff],
    enabled: !!user,
    queryFn: async () => {
      const d = await get<{ jobs?: Project[] } | Project[]>(staff ? '/api/employee/jobs' : '/api/jobs')
      return Array.isArray(d) ? d : (d.jobs ?? [])
    },
  })
}

export const projectLabel = (p: Pick<Project, 'number' | 'name'>) => `${p.number ? p.number + ' - ' : ''}${p.name}`

/* --- The projects board ---------------------------------------------------------------------- */


export const projectKeys = { all: ['projects'] as const }
export const JOB_STATUS: Record<string, string> = { quoting: 'Quoting', won: 'Won', in_progress: 'In progress', on_hold: 'On hold', complete: 'Complete', cancelled: 'Cancelled' }

export interface Costing {
  quoted: number
  budget: number
  invoiced: number
  received: number
  outstanding: number
  total_cost: number
  committed: number
  labour_cost: number
  labour_hours: number
  profit: number
  margin_percent: number
  over_budget: boolean
}
export interface BoardProject extends Project { customer_name: string; state_code?: string; description?: string; retention_percent?: number; costing: Costing }
export interface Board { jobs: BoardProject[]; totals: { invoiced: number; cost: number; committed: number; profit: number } }
export interface ProjectDoc { id: number; number: string; total: number; status: string; issue_date: string; to_contact?: string; supplier_name?: string; vendor_name?: string; over_order?: boolean }
export interface ProjectDetail extends BoardProject { invoices: ProjectDoc[]; bills: ProjectDoc[]; purchase_orders: ProjectDoc[]; quotes: ProjectDoc[] }
export interface SiteLocation { set: boolean; lat?: number; lng?: number; radius_m?: number }
export interface ProjectInput { name: string; customer_name: string; status: string; site_address: string; state_code: string; quoted_value: number; budget: number; retention_percent: number; start_date: string; target_end_date: string; description: string }

export const useBoard = () => useQuery({ queryKey: ['projects', 'board'], queryFn: () => get<Board>('/api/jobs-summary') })
export const useProject = (id: number) => useQuery({ queryKey: ['projects', 'one', id], enabled: id > 0, queryFn: () => get<ProjectDetail>(`/api/jobs/${id}`) })
export const useSiteLocation = (id: number | null) => useQuery({ queryKey: ['projects', 'location', id], enabled: !!id, queryFn: () => get<SiteLocation>(`/api/jobs/${id}/site-location`) })
export const useGstStates = () => useQuery({ queryKey: ['projects', 'states'], staleTime: 60 * 60_000, queryFn: async () => (await get<{ states?: Record<string, string> }>('/api/gst/settings')).states ?? {} })

export const saveProject = (id: number | null, b: ProjectInput) => (id ? put<{ id?: number }>(`/api/jobs/${id}`, b) : post<{ id: number }>('/api/jobs', b))
export const setSiteLocation = (id: number, position: string, radius_m: number) => put<unknown>(`/api/jobs/${id}/site-location`, { position, radius_m })
export const clearSiteLocation = (id: number) => del<unknown>(`/api/jobs/${id}/site-location`)
