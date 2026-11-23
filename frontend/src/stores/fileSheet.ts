import { create } from 'zustand'

/** A file the phone app has fetched and is holding, waiting for the person to say what to do with it. */
export interface HeldFile {
  /** What it is called ("registration.pdf"). */
  name: string
  /** Where it is kept on the phone for now (a file:// address in the app's cache). */
  uri: string
  /** Its contents, kept so it can be saved to the phone's own folders without fetching it again. */
  data: string
}

interface FileSheetState {
  /** The "File ready" box (save to the phone, or share). */
  file: HeldFile | null
  show: (file: HeldFile) => void
  close: () => void
  /** The file being looked at in the app (a PDF or an Excel sheet), read only. */
  viewing: HeldFile | null
  view: (file: HeldFile) => void
  closeView: () => void
}

export const useFileSheet = create<FileSheetState>((set) => ({
  file: null,
  show: (file) => set({ file }),
  close: () => set({ file: null }),
  viewing: null,
  view: (viewing) => set({ viewing }),
  closeView: () => set({ viewing: null }),
}))
