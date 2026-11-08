import { useQuery } from '@tanstack/react-query'
import { get, post } from '@/lib/api'

export const journalKeys = { all: ['journals'] as const }

export type LineKind = 'party' | 'head' | 'account' | 'ledger'

export interface JournalLine {
  kind: LineKind
  party_type: string
  party_name: string
  head: string
  account_id: number | null
  ledger_key: string
  job_id: number | null
  debit: number
  credit: number
  note: string
  label?: string
}

export interface Journal {
  id: number
  number: string
  voucher_date: string
  narration: string
  status: 'PENDING' | 'APPROVED' | 'REJECTED' | 'CANCELLED'
  raised_by_name: string
  raised_at: string
  decided_by_name: string
  decided_at: string
  decision_note: string
  total: number
  lines: JournalLine[]
}

export interface JournalList {
  journals: Journal[]
  ledgers: { key: string; label: string }[]
  can_approve: boolean
}

export const useJournals = (jobId: number) =>
  useQuery({ queryKey: [...journalKeys.all, 'list', jobId], queryFn: () => get<JournalList>(`/api/journals${jobId ? `?job_id=${jobId}` : ''}`) })

export const raiseJournal = (b: { voucher_date: string; narration: string; lines: JournalLine[] }) => post<Journal>('/api/journals', b)
export const approveJournal = (id: number) => post<Journal>(`/api/journals/${id}/approve`, {})
export const rejectJournal = (id: number, note: string) => post<Journal>(`/api/journals/${id}/reject`, { note })
export const cancelJournal = (id: number, reason: string) => post<Journal>(`/api/journals/${id}/cancel`, { reason })
export const journalPdf = (id: number) => `/api/journals/${id}/voucher.pdf`

export interface DebitNote {
  id: number
  number: string
  note_date: string
  supplier_name: string
  bill_id: number | null
  bill_number: string
  purchase_return_id: number | null
  job_id: number | null
  project: string
  reason: string
  taxable: number
  tax: number
  total: number
  status: 'ISSUED' | 'CANCELLED'
  cancel_reason: string
  raised_by_name: string
  created_at: string
}

/** A purchase return posted in the store with no debit note raised for it yet. */
export interface OpenReturn {
  id: number
  number: string
  date: string
  supplier_name: string
  reason: string
  taxable: number
  tax: number
  total: number
  job_id: number | null
  bills: { id: number; number: string; total: number }[]
}

export const useDebitNotes = (jobId: number) =>
  useQuery({
    queryKey: [...journalKeys.all, 'debit-notes', jobId],
    queryFn: () => get<{ notes: DebitNote[]; returns: OpenReturn[] }>(`/api/supplier-debit-notes${jobId ? `?job_id=${jobId}` : ''}`),
  })

export const raiseDebitNote = (b: {
  note_date: string; supplier_name: string; bill_id: number | null; purchase_return_id: number | null; job_id: number | null
  reason: string; taxable: number; tax: number
}) => post<DebitNote>('/api/supplier-debit-notes', b)
export const cancelDebitNote = (id: number, reason: string) => post<DebitNote>(`/api/supplier-debit-notes/${id}/cancel`, { reason })
export const debitNotePdf = (id: number) => `/api/supplier-debit-notes/${id}/note.pdf`
