import { create } from 'zustand'
import { persist } from 'zustand/middleware'

export type Theme = 'light' | 'dark' | 'system'

type UIState = {
  theme: Theme
  sidebarCollapsed: boolean
  mobileNavOpen: boolean
  /** Sidebar sections the user has left open, by group id. */
  openGroups: Record<string, boolean>
  setTheme: (t: Theme) => void
  toggleSidebar: () => void
  setMobileNav: (open: boolean) => void
  toggleGroup: (id: string) => void
  setGroup: (id: string, open: boolean) => void
}

export const useUI = create<UIState>()(
  persist(
    (set) => ({
      theme: 'dark',
      sidebarCollapsed: false,
      mobileNavOpen: false,
      openGroups: { projects: true },
      setTheme: (theme) => set({ theme }),
      toggleSidebar: () => set((s) => ({ sidebarCollapsed: !s.sidebarCollapsed })),
      setMobileNav: (mobileNavOpen) => set({ mobileNavOpen }),
      toggleGroup: (id) => set((s) => ({ openGroups: { ...s.openGroups, [id]: !s.openGroups[id] } })),
      setGroup: (id, open) => set((s) => ({ openGroups: { ...s.openGroups, [id]: open } })),
    }),
    {
      name: 'yerp-ui',
      partialize: (s) => ({ theme: s.theme, sidebarCollapsed: s.sidebarCollapsed, openGroups: s.openGroups }),
    },
  ),
)

export function applyTheme(theme: Theme) {
  const dark = theme === 'dark' || (theme === 'system' && matchMedia('(prefers-color-scheme: dark)').matches)
  document.documentElement.classList.toggle('dark', dark)
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', dark ? '#0b0b0e' : '#fbfaf8')
}
