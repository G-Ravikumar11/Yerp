import { useQuery } from '@tanstack/react-query'
import { api, get, del } from '@/lib/api'
import type { Order } from './orders'

export interface MbLine {
  item_id: number
  activity_no: string
  item_code?: string
  description: string
  is_header?: boolean
  uom?: string
  ordered_qty?: number
  rate?: number
  tolerance_percent?: number
  max_quantity?: number
  measured_to_date?: number
  billed_to_date?: number
  unbilled?: number
  balance_to_measure?: number
  percent_measured?: number
  over_measured?: number
}

export interface MbDimension {
  particulars: string
  nos: number | null
  nom: number | null
  length: number | null
  breadth: number | null
  depth: number | null
  deduct: boolean
  is_heading: boolean
  quantity?: number | null
}

export interface MbEntry {
  id: number
  item_id: number
  activity_no: string
  measured_on: string
  quantity: number
  multiplier: number
  mb_ref: string
  location: string
  remarks: string
  recorded_by_name: string
  billed: boolean
  dimensions: MbDimension[]
}

export interface MbBook {
  order: Order
  lines: MbLine[]
  entries: MbEntry[]
  summary: { ordered_value: number; measured_value: number; unbilled_value: number; lines_over_measured: number }
}

/** What is sent to record a measurement. Dimensions, when given, are the measurement. */
export interface MeasurementInput {
  item_id: number
  quantity?: number
  dimensions?: Omit<MbDimension, 'quantity'>[]
  multiplier?: number
  measured_on?: string
  mb_ref?: string
  location?: string
  remarks?: string
}

export const mbKeys = {
  all: ['mb'] as const,
  book: (orderId: number) => ['mb', orderId] as const,
}

export function useMeasurementBook(orderId: number) {
  return useQuery({ queryKey: mbKeys.book(orderId), queryFn: () => get<MbBook>(`/api/sub-mb/${orderId}`), enabled: orderId > 0 })
}

export const recordUrl = (orderId: number) => `/api/sub-mb/${orderId}/entries`
export const deleteEntry = (id: number) => del<{ message: string }>(`/api/sub-mb/entries/${id}`)

/* --- The book as the site keeps it in Excel ------------------------------ */

/** One line of a sheet's entry, as the server read it. */
export interface ImportDim {
  particulars: string
  is_heading: boolean
  nos: number | null
  nom: number | null
  length: number | null
  breadth: number | null
  depth: number | null
  deduct: boolean
}

export interface ImportSection {
  index: number
  description: string
  sno: string
  item_id: number | null
  item: string
  uom: string
  quantity: number
  entries: { location: string; multiplier: number; lines: number; one_block: number; quantity: number; stated: number | null; dims?: ImportDim[] }[]
}

export interface ImportPreview {
  ok: boolean
  committed: boolean
  sheet: string
  meta: { work_name?: string; contractor?: string; date?: string }
  sections: ImportSection[]
  warnings: string[]
  items: { id: number; label: string; uom: string }[]
  entries?: number
  message?: string
}

export function importBook(orderId: number, file: File, opts: { commit: boolean; mapping?: Record<number, number | null>; measuredOn?: string; includeDims?: boolean; entries?: [number, number][] }) {
  const form = new FormData()
  form.append('file', file)
  form.append('commit', opts.commit ? '1' : '0')
  if (opts.mapping) form.append('mapping', JSON.stringify(opts.mapping))
  if (opts.measuredOn) form.append('measured_on', opts.measuredOn)
  if (opts.includeDims) form.append('include_dims', '1')
  if (opts.entries) form.append('entries', JSON.stringify(opts.entries))
  return api<ImportPreview>(`/api/sub-mb/${orderId}/import`, { method: 'POST', body: form })
}
