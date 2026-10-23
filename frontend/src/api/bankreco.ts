import { useQuery } from '@tanstack/react-query'
import { api, get, post } from '@/lib/api'
import type { Entry } from '@/api/ledger'

/* Bank reconciliation (the bank's statement against the books) and the cheque register. */

export const recoKeys = { all: ['bank-reco'] as const }

export interface StatementLine {
  id: number
  txn_date: string
  narration: string
  reference: string
  debit: number
  credit: number
  balance: number | null
  status: 'UNMATCHED' | 'MATCHED' | 'IGNORED'
  entry_id: number | null
}

export interface OpenEntry { id: number; number: string; paid_on: string; party: string; mode: string; reference: string; amount: number }

export interface Brs {
  as_of: string
  books: number
  not_presented: OpenEntry[]
  not_credited: OpenEntry[]
  not_presented_total: number
  not_credited_total: number
  bank_should_show: number
  statement_balance: number | null
  statement_date: string
  difference: number | null
}

export interface Reco {
  brs: Brs
  lines: StatementLine[]
  suggestions: Record<string, { id: number; number: string; paid_on: string; party: string; reference: string }[]>
  counts: { matched: number; unmatched: number; ignored: number }
}

export const useReco = (accountId: number, asOf: string) =>
  useQuery({ queryKey: [...recoKeys.all, accountId, asOf], enabled: accountId > 0, queryFn: () => get<Reco>(`/api/bank-reco/${accountId}?as_of=${asOf}`) })

export function uploadStatement(accountId: number, file: File) {
  const form = new FormData()
  form.append('file', file)
  return api<{ message: string; added: number; matched: number }>(`/api/bank-reco/${accountId}/statement`, { method: 'POST', body: form })
}

export const matchLine = (lineId: number, entryId: number) => post<{ message: string }>(`/api/bank-reco/lines/${lineId}/match`, { entry_id: entryId })
export const ignoreLine = (lineId: number) => post<{ message: string }>(`/api/bank-reco/lines/${lineId}/ignore`, {})
export const bookLine = (lineId: number, head: string) => post<{ message: string }>(`/api/bank-reco/lines/${lineId}/book`, { head })
export const clearEntry = (entryId: number, clearedOn: string) => post<{ message: string }>(`/api/money/entries/${entryId}/clear`, { cleared_on: clearedOn })
export const brsUrl = (accountId: number, asOf: string) => `/api/bank-reco/${accountId}/brs.pdf?as_of=${asOf}`

export type ChequeStatus = 'PENDING' | 'CLEARED' | 'STALE' | 'BOUNCED' | 'CANCELLED'
export type Cheque = Entry & { status: ChequeStatus; cleared_on: string }

export const useCheques = (status = '') =>
  useQuery({ queryKey: [...recoKeys.all, 'cheques', status], queryFn: () => get<{ cheques: Cheque[]; summary: { issued_pending: number; received_pending: number; stale: number; bounced: number } }>(`/api/cheques${status ? `?status=${status}` : ''}`) })
