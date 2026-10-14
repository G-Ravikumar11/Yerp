import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import { useProjects } from '@/api/projects'

/** The site the person is working on, as they last chose it: Today and the + sheet follow it. */
export const useSite = create<{ id: number; set: (id: number) => void }>()(
  persist((set) => ({ id: 0, set: (id) => set({ id }) }), { name: 'yerp.site' }),
)

/** The site in use: the one chosen, or - until one is chosen, or if it has finished - the first live one. */
export function useCurrentSite() {
  const projects = useProjects()
  const chosen = useSite((s) => s.id)
  const live = (projects.data ?? []).filter((p) => !['complete', 'cancelled'].includes(p.status))
  return { site: live.find((p) => p.id === chosen) ?? live[0], sites: live, isPending: projects.isPending }
}
