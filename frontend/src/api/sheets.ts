import { api, post } from '@/lib/api'

/** A sheet read into rows, with what is wrong with each. Nothing is saved until the rows are brought in. */
export interface SheetColumn {
  key: string
  label: string
  number: boolean
}

export type SheetRow = Record<string, string | number | null>

export interface SheetRead {
  kind: string
  columns: SheetColumn[]
  rows: SheetRow[]
  problems: Record<string, string[]>
  skipped: number
  read_as?: unknown
  message: string
}

export const sheetTemplateUrl = (kind: string) => `/api/sheets/${kind}/template.xlsx`

export function readSheet(kind: string, file: File) {
  const form = new FormData()
  form.append('file', file)
  return api<SheetRead>(`/api/sheets/${kind}/read`, { method: 'POST', body: form })
}

export const checkSheet = (kind: string, rows: SheetRow[]) => post<{ problems: Record<string, string[]> }>(`/api/sheets/${kind}/check`, { rows })
export const importSheet = (kind: string, rows: SheetRow[]) => post<{ count: number; message: string }>(`/api/sheets/${kind}/import`, { rows })
