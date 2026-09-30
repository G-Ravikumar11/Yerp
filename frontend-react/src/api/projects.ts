import { useQuery } from '@tanstack/react-query'
import { get } from '@/lib/api'
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
