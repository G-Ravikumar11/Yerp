import { create } from 'zustand'

/** A new version of the phone app, offered in a box in the middle of the screen rather than a message at its edge. */
export interface UpdateOffer {
  title: string
  message: string
  /** The button that takes the update ("Update"). */
  confirmLabel: string
  onConfirm: () => void | Promise<void>
}

interface UpdatePromptState {
  offer: UpdateOffer | null
  show: (offer: UpdateOffer) => void
  close: () => void
}

export const useUpdatePrompt = create<UpdatePromptState>((set) => ({
  offer: null,
  show: (offer) => set({ offer }),
  close: () => set({ offer: null }),
}))
