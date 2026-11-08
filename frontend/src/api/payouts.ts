import { useQuery } from '@tanstack/react-query'
import { api, get, post } from '@/lib/api'

export const payoutKeys = { all: ['payouts'] as const }

/* --- bank payment files --------------------------------------------------------------------------- */

export interface Candidate {
  doc_type: string
  doc_id: number | null
  doc_number: string
  request_id: number | null
  request_number: string
  party_type: string
  party_name: string
  amount: number
  account: string
  ifsc: string
  bank: string
  problem: string
  in_a_file: boolean
}

export interface BatchLine {
  id: number
  doc_type: string
  doc_number: string
  party_name: string
  amount: number
  account: string
  ifsc: string
  mode: string
  status: 'READY' | 'PAID' | 'FAILED'
  error: string
}

export interface Batch {
  id: number
  number: string
  account: string
  bank_format: string
  format_label: string
  pay_on: string
  status: 'DRAFT' | 'PAID' | 'CANCELLED'
  made_by_name: string
  paid_by_name: string
  total: number
  count: number
  lines: BatchLine[]
}

export const useBatches = () =>
  useQuery({
    queryKey: [...payoutKeys.all, 'batches'],
    queryFn: () => get<{ batches: Batch[]; formats: { key: string; label: string }[]; accounts: { id: number; name: string; has_number: boolean; ifsc: string }[] }>('/api/payment-batches'),
  })
export const useCandidates = (enabled: boolean) =>
  useQuery({ queryKey: [...payoutKeys.all, 'candidates'], enabled, queryFn: () => get<{ items: Candidate[]; approval_on: boolean }>('/api/payment-batches/candidates') })
export const makeBatch = (b: { account_id: number; bank_format: string; pay_on: string; items: (Candidate & { amount: number })[] }) =>
  post<Batch & { message: string }>('/api/payment-batches', b)
export const batchFileUrl = (id: number) => `/api/payment-batches/${id}/file`
export const batchPaid = (id: number, paid_on: string, reference: string) => post<Batch & { message: string }>(`/api/payment-batches/${id}/paid`, { paid_on, reference })
export const batchCancel = (id: number) => post<Batch & { message: string }>(`/api/payment-batches/${id}/cancel`, {})

/* --- cheque books and post-dated cheques ---------------------------------------------------------- */

export interface ChequeBook { id: number; account: string; account_id: number; first_no: number; last_no: number; received_on: string; leaves: number; blank: number; next_leaf: number | null; spoilt: number }
export interface Leaf { number: number; status: string; party: string; amount: number; date: string; ref: string }

export const useChequeBooks = () => useQuery({ queryKey: [...payoutKeys.all, 'books'], queryFn: async () => (await get<{ books: ChequeBook[] }>('/api/cheque-books')).books })
export const useLeaves = (id: number) => useQuery({ queryKey: [...payoutKeys.all, 'leaves', id], enabled: id > 0, queryFn: async () => (await get<{ leaves: Leaf[] }>(`/api/cheque-books/${id}/leaves`)).leaves })
export const addBook = (b: { account_id: number; first_no: number; last_no: number; received_on: string }) => post<ChequeBook>('/api/cheque-books', b)
export const spoilLeaf = (id: number, number: number, reason: string) => post<{ message: string }>(`/api/cheque-books/${id}/spoil`, { number, reason })

export interface Pdc {
  id: number
  direction: 'IN' | 'OUT'
  cheque_no: string
  cheque_date: string
  drawn_on: string
  account_id: number | null
  account: string
  party_type: string
  party_name: string
  doc_number: string
  project: string
  amount: number
  note: string
  status: 'HELD' | 'BANKED' | 'RETURNED' | 'CANCELLED'
  closed_reason: string
  days_to_go: number | null
  due: boolean
}

export const usePdcs = () =>
  useQuery({ queryKey: [...payoutKeys.all, 'pdcs'], queryFn: () => get<{ cheques: Pdc[]; summary: { given: number; held: number; due: number; this_week: number } }>('/api/pdcs') })
export const addPdc = (b: Record<string, unknown>) => post<Pdc & { message: string }>('/api/pdcs', b)
export const bankPdc = (id: number, on: string, account_id: number | null) => post<Pdc & { message: string }>(`/api/pdcs/${id}/bank`, { on, account_id })
export const closePdc = (id: number, status: 'RETURNED' | 'CANCELLED', reason: string) => post<Pdc & { message: string }>(`/api/pdcs/${id}/close`, { status, reason })

/* --- staff expense claims ------------------------------------------------------------------------- */

export interface Claim {
  id: number
  number: string
  employee_id: number
  employee_name: string
  spent_on: string
  head: string
  job_id: number | null
  project: string
  amount: number
  description: string
  bill_no: string
  status: 'SUBMITTED' | 'APPROVED' | 'REJECTED' | 'SETTLED' | 'CANCELLED'
  decided_by_name: string
  decision_note: string
  against_advance: number
  left: number
  photos: { id: number; name: string }[]
}

export const useClaims = (mine = false) =>
  useQuery({ queryKey: [...payoutKeys.all, 'claims', mine], queryFn: () => get<{ claims: Claim[]; can_decide: boolean; me: number | null }>(`/api/expense-claims${mine ? '?mine=true' : ''}`) })
export const submitClaim = (b: { spent_on: string; head: string; job_id: number | null; amount: number; description: string; bill_no: string; employee_id?: number }) =>
  post<Claim & { message: string }>('/api/expense-claims', b)
export const decideClaim = (id: number, decision: 'approve' | 'reject', note = '') => post<Claim & { message: string }>(`/api/expense-claims/${id}/decide`, { decision, note })
export const claimAgainstAdvance = (id: number) => post<Claim & { message: string }>(`/api/expense-claims/${id}/against-advance`, {})
export const cancelClaim = (id: number) => post<Claim & { message: string }>(`/api/expense-claims/${id}/cancel`, {})
/** The bill's photo, kept with the claim. */
export function attachClaimPhoto(id: number, file: File) {
  const form = new FormData()
  form.append('file', file)
  return api<{ message: string }>(`/api/expense-claims/${id}/photo`, { method: 'POST', body: form })
}
