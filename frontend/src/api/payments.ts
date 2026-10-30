import { useQuery } from '@tanstack/react-query'
import { get, post, put } from '@/lib/api'
import type { Entry } from '@/api/ledger'

/* Payments approved before they are made: accounts ask, the accounts head checks, the MD releases over a limit. */

export const paymentKeys = { all: ['payments'] as const }

export interface PaymentRules {
  on: boolean
  /** Up to this amount a payment needs no approval. */
  free_below: number
  /** Above this the MD releases it as well. */
  md_above: number
  can_check: boolean
  can_release: boolean
  master: boolean
  me: number | null
}

export type RequestStatus = 'PENDING' | 'AWAITING_MD' | 'APPROVED' | 'PAID' | 'REJECTED' | 'CANCELLED'

export interface PaymentRequest {
  id: number
  number: string
  doc_type: string
  doc_id: number | null
  doc_number: string
  party_type: string
  party_name: string
  job_id: number | null
  project: string
  head: string
  amount: number
  account_id: number | null
  account: string
  mode: string
  note: string
  status: RequestStatus
  status_label: string
  requested_by: number | null
  requested_by_name: string
  requested_at: string
  checked_by_name: string
  checked_at: string
  approved_by_name: string
  approved_at: string
  rejected_by_name: string
  reject_reason: string
  entry_id: number | null
  /** Approved, but not paid in time: it can no longer be paid. */
  expired?: boolean
}

export const usePaymentRules = () => useQuery({ queryKey: [...paymentKeys.all, 'rules'], staleTime: 60_000, queryFn: () => get<PaymentRules>('/api/payment-requests/rules') })
export const savePaymentRules = (b: { on: boolean; free_below: number; md_above: number }) => put<PaymentRules & { message: string }>('/api/payment-requests/rules', b)

/** Whether this payment has to be sent for approval rather than paid now. The Master never does. */
export const mustAsk = (rules: PaymentRules | undefined, amount: number) => !!rules?.on && !rules.master && amount > rules.free_below

export const usePaymentRequests = (status = '') =>
  useQuery({ queryKey: [...paymentKeys.all, 'list', status], queryFn: () => get<{ requests: PaymentRequest[]; summary: { with_accounts: number; with_md: number; to_pay: number; open: number } }>(`/api/payment-requests${status ? `?status=${status}` : ''}`) })

export interface RequestInput {
  doc_type: string
  doc_id?: number | null
  amount: number
  account_id?: number | null
  mode?: string
  note?: string
  party_type?: string
  party_name?: string
  head?: string
  job_id?: number | null
}
export const raisePaymentRequest = (b: RequestInput) => post<{ request: PaymentRequest; message: string }>('/api/payment-requests', b)
export const decidePaymentRequest = (id: number, decision: 'approve' | 'reject', note = '') =>
  post<{ request: PaymentRequest; message: string }>(`/api/payment-requests/${id}/decide`, { decision, note })
export const payPaymentRequest = (id: number, b: { paid_on: string; mode: string; reference: string; account_id: number | null; amount?: number }) =>
  post<{ entry: Entry; message: string }>(`/api/payment-requests/${id}/pay`, b)
export const cancelPaymentRequest = (id: number) => post<{ message: string }>(`/api/payment-requests/${id}/cancel`, {})
