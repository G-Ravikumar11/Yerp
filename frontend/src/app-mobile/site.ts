import { create } from 'zustand'
import { persist } from 'zustand/middleware'

/** The site the person is working on: Today, the + sheet and the diary all follow it. */
export const useSite = create<{ id: number; set: (id: number) => void }>()(
  persist((set) => ({ id: 0, set: (id) => set({ id }) }), { name: 'yerp.site' }),
)
