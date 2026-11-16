import { create } from 'zustand'

/** Whether the "New voucher" screen is open. Opened from the Accounts menu, the Finance Dashboard and the Alt+V shortcut. */
interface VoucherState {
  open: boolean
  show: () => void
  hide: () => void
}

export const useVoucher = create<VoucherState>((set) => ({
  open: false,
  show: () => set({ open: true }),
  hide: () => set({ open: false }),
}))
