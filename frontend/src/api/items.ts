import { useQuery } from '@tanstack/react-query'
import { api, get, post, put, del } from '@/lib/api'

export type ItemKind = 'RM' | 'FG'

export interface Item {
  id: number
  kind: ItemKind
  item_code: string
  item_name: string
  description: string
  category: string
  item_type: string
  units_of_measure: string
  hsn_code: string
  item_tax_type: string
  last_rate: number
  reorder_level: number
}

export interface ItemList {
  items: Item[]
  counts: Record<ItemKind, number>
}

export interface ItemVocabulary {
  kinds: ItemKind[]
  item_types: string[]
  units: string[]
  tax_rates: string[]
}

/** What is sent to make or change an item. A blank code means "issue the next". */
export interface ItemInput {
  kind: ItemKind
  item_code?: string
  item_name: string
  description?: string
  item_type?: string
  units_of_measure?: string
  hsn_code?: string
  item_tax_type?: string
  reorder_level?: number | null
}

export const itemKeys = {
  all: ['items'] as const,
  list: (kind: string, q: string) => ['items', 'list', kind, q] as const,
  vocabulary: ['items', 'vocabulary'] as const,
}

export function useItems(kind: string, q: string) {
  return useQuery({
    queryKey: itemKeys.list(kind, q),
    queryFn: () => get<ItemList>(`/api/erp/items?kind=${encodeURIComponent(kind)}&q=${encodeURIComponent(q)}`),
    placeholderData: (prev) => prev,
  })
}

export function useItemVocabulary() {
  return useQuery({ queryKey: itemKeys.vocabulary, queryFn: () => get<ItemVocabulary>('/api/erp/vocabulary'), staleTime: 60 * 60_000 })
}

export const createItems = (items: ItemInput[]) => post<{ created: number; codes: string[]; message: string }>('/api/erp/items/bulk', { items })
export const updateItem = (id: number, item: ItemInput) => put<{ message: string }>(`/api/erp/items/${id}`, item)
export const deleteItem = (id: number) => del<{ ok: boolean }>(`/api/erp/items/${id}`)

/* --- Bringing them in from a workbook ------------------------------------ */

export interface ImportProblem {
  field: string
  message: string
  fix: string | null
}

export interface ImportRow {
  _line: number
  _kind: ItemKind | ''
  _problems?: ImportProblem[]
  _repairs?: { line: number; field: string; from: string; to: string }[]
  item_code?: string
  item_name?: string
  item_type?: string
  units_of_measure?: string
  hsn_code?: string
  item_tax_type?: string
  description?: string
  segment?: string
  make?: string
  [key: string]: unknown
}

export interface ImportAnalysis {
  ok: boolean
  mapping: { header: string; field: string | null }[] | Record<string, string>
  unmapped_headers: string[]
  detected: Partial<Record<ItemKind, number>>
  unknown_kind: number
  rows: ImportRow[]
  repairs: unknown[]
  summary: { total: number; ready: number; blocked: number; repaired: number }
}

export function analyseItemFile(file: File, kind: string) {
  const form = new FormData()
  form.append('file', file)
  form.append('kind', kind)
  return api<ImportAnalysis>('/api/erp/items/analyse', { method: 'POST', body: form })
}

export interface CommitResult {
  ok: boolean
  created: number
  reused?: number
  errors: { line: number; field: string; message: string }[]
  message: string
}

export const commitItems = (rows: ImportRow[]) => post<CommitResult>('/api/erp/items/commit', { rows })
