import { api, post } from '@/lib/api'

/* Importing items from a sheet: read it and say what each row would do, let the person fix or skip rows, then save. */

export type ImportStatus = 'New' | 'Update' | 'Duplicate' | 'Error'

export interface ImportPreviewRow {
  line: number
  status: ImportStatus
  reason: string
  changes: string[]
  action: 'import' | 'skip'
  values: Record<string, string>
  kind_of_duplicate: string
}

export interface ImportPreview {
  rows: ImportPreviewRow[]
  summary: { total: number; new: number; update: number; duplicate: number; error: number }
  read_as?: Record<string, string>
  unused_columns?: string[]
}

export interface ImportResult {
  created: number
  updated: number
  skipped: number
  errors: { line: number; code: string; name: string; reason: string }[]
  message: string
}

export type ImportEntry = { line: number; action?: 'import' | 'skip'; values: Record<string, string> }

export function previewImport(file: File) {
  const form = new FormData()
  form.append('file', file)
  return api<ImportPreview>('/api/items/import/preview', { method: 'POST', body: form })
}

export const checkImport = (rows: ImportEntry[]) => post<ImportPreview>('/api/items/import/check', { rows })
export const commitImport = (rows: ImportEntry[]) => post<ImportResult>('/api/items/import/commit', { rows })
export const TEMPLATE_URL = '/api/items/import/template'
