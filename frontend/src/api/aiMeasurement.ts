import { useQuery } from '@tanstack/react-query'
import { api, get, post } from '@/lib/api'
import type { Flag } from '@/api/aiSubcontracts'

export interface MeasurementAnalysis {
  order: string
  entries: number
  findings: Flag[]
  /** The findings about one entry, by entry id, for marking it in the table. */
  by_entry: Record<string, Flag[]>
  rows: { item_id: number; label: string; uom: string; ordered: number; measured: number; percent: number | null }[]
  measured_value: number
  ordered_value: number
  time_percent: number | null
  work_percent: number | null
  available: boolean
  summary: string
  message?: string
}

export interface ReadSheet {
  available: boolean
  message?: string
  reason?: string
  rows?: { item_id: number; location: string; quantity: number; measured_on: string; remarks: string }[]
  unmatched?: string[]
  low_confidence?: boolean
}

export interface ReadPaper {
  available: boolean
  message?: string
  reason?: string
  kind?: string
  number?: string
  holder_name?: string
  valid_from?: string
  valid_to?: string
  warnings?: string[]
  low_confidence?: boolean
}

function upload<T extends object>(url: string, input: { text?: string; file?: File | null }) {
  const form = new FormData()
  if (input.file) form.append('file', input.file)
  if (input.text) form.append('text', input.text)
  return api<T>(url, { method: 'POST', body: form })
}

/** The plain checks alone: free, no model, so the entries table can mark odd rows without being asked. */
export const useBookFlags = (orderId: number) =>
  useQuery({ queryKey: ['mb', 'flags', orderId], queryFn: () => get<MeasurementAnalysis>(`/api/ai/subcontracts/orders/${orderId}/measurement-analysis?ai=0`), enabled: orderId > 0, staleTime: 30_000 })

export interface BookAnswer { available: boolean; answer: string; message?: string }
export const askBook = (orderId: number, question: string) => post<BookAnswer>(`/api/ai/subcontracts/orders/${orderId}/ask-book`, { question })
export const analyseBook = (orderId: number) => get<MeasurementAnalysis>(`/api/ai/subcontracts/orders/${orderId}/measurement-analysis`)
export const readSheet = (orderId: number, input: { text?: string; file?: File | null }) => upload<ReadSheet>(`/api/ai/subcontracts/orders/${orderId}/read-measurements`, input)
export const readPaper = (contractorId: number, input: { text?: string; file?: File | null }) => upload<ReadPaper>(`/api/ai/subcontracts/contractors/${contractorId}/read-document`, input)
