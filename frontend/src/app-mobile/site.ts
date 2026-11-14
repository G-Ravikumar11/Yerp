import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import { useProjects } from '@/api/projects'

/** The site the person is working on, as they last chose it: Today and the + sheet follow it. */
export const useSite = create<{ id: number; set: (id: number) => void }>()(
  persist((set) => ({ id: 0, set: (id) => set({ id }) }), { name: 'yerp.site' }),
)

/** A site's two letters for its circle: the first letters of its first two words, or the first two of a single word. */
export const letters = (name: string) => {
  const w = name.trim().split(/\s+/).filter(Boolean)
  return ((w.length > 1 ? w[0][0] + w[1][0] : (w[0] ?? '?').slice(0, 2)) || '?').toUpperCase()
}

/** The site in use: the one chosen, or - until one is chosen, or if it has finished - the first live one. */
export function useCurrentSite() {
  const projects = useProjects()
  const chosen = useSite((s) => s.id)
  const live = (projects.data ?? []).filter((p) => !['complete', 'cancelled'].includes(p.status))
  return { site: live.find((p) => p.id === chosen) ?? live[0], sites: live, isPending: projects.isPending }
}
