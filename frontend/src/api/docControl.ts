import { useQuery } from '@tanstack/react-query'
import { get, post } from '@/lib/api'

export type DocKind = 'TRANSMITTAL' | 'RFI' | 'SUBMITTAL'

/** One transmittal, RFI or submittal: who it went to, when it is due, and what came back. */
export interface DocItem {
  id: number; kind: DocKind; kind_label: string; number: string; subject: string; job_id: number | null; project: string
  to_party: string; to_email: string; details: string; purpose: string; revision: string; due_date: string; status: string
  response: string; responded_on: string; responded_by: string; created_by_name: string; created_at: string; closed_at: string
  reminders: number; reminded_on: string; overdue: boolean; replies: string[]
  items?: { id: number; drawing_id: number | null; number: string; revision: string; description: string }[]
}
export interface DocList { items: DocItem[]; summary: Record<DocKind, { open: number; overdue: number }>; purposes: string[] }
export interface DocInput {
  kind: DocKind; subject: string; to_party: string; to_email?: string; job_id?: number | null; details?: string; purpose?: string
  revision?: string; due_date?: string; items?: { drawing_id?: number | null; description?: string }[]
}

export const docKeys = { all: ['doc-control'] as const }
export const useDocs = (kind: DocKind, show: string) =>
  useQuery({ queryKey: [...docKeys.all, kind, show], queryFn: () => get<DocList>(`/api/doc-control?kind=${kind}&show=${show}`) })
export const useDoc = (id: number | null) =>
  useQuery({ queryKey: [...docKeys.all, 'one', id], enabled: !!id, queryFn: async () => (await get<{ item: DocItem }>(`/api/doc-control/${id}`)).item })

type Done = { message: string; item: DocItem }
export const raiseDoc = (b: DocInput) => post<Done>('/api/doc-control', b)
export const replyDoc = (id: number, reply: string, response: string) => post<Done>(`/api/doc-control/${id}/reply`, { reply, response })
export const resubmitDoc = (id: number) => post<Done>(`/api/doc-control/${id}/resubmit`)
export const closeDoc = (id: number, cancel = false, reason = '') => post<Done>(`/api/doc-control/${id}/close`, { cancel, reason })
export const remindDoc = (id: number) => post<Done>(`/api/doc-control/${id}/remind`)

/** A status in words. */
export const statusText = (s: string) => s.replace(/_/g, ' ').toLowerCase().replace('approved as noted', 'approved with comments')
