import { create } from 'zustand'
import { persist } from 'zustand/middleware'

type UIState = {
  sidebarCollapsed: boolean
  mobileNavOpen: boolean
  /** Sidebar sections the user has left open, by group id. */
  openGroups: Record<string, boolean>
  toggleSidebar: () => void
  setMobileNav: (open: boolean) => void
  toggleGroup: (id: string) => void
  setGroup: (id: string, open: boolean) => void
}

export const useUI = create<UIState>()(
  persist(
    (set) => ({
      sidebarCollapsed: false,
      mobileNavOpen: false,
      openGroups: { projects: true },
      toggleSidebar: () => set((s) => ({ sidebarCollapsed: !s.sidebarCollapsed })),
      setMobileNav: (mobileNavOpen) => set({ mobileNavOpen }),
      toggleGroup: (id) => set((s) => ({ openGroups: { ...s.openGroups, [id]: !s.openGroups[id] } })),
      setGroup: (id, open) => set((s) => ({ openGroups: { ...s.openGroups, [id]: open } })),
    }),
    {
      name: 'yerp-ui',
      partialize: (s) => ({ sidebarCollapsed: s.sidebarCollapsed, openGroups: s.openGroups }),
    },
  ),
)
