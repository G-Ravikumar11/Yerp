import { useQuery } from '@tanstack/react-query'
import { get, post } from '@/lib/api'

export interface Outstanding {
  number: string
  worth: number
  settled: number
  outstanding: number
  entries: { paid_on: string; number: string; amount: number; mode: string; reference: string; voided: boolean }[]
}

export interface BankAccount {
  id: number
  name: string
  kind: string
  balance: number
}

/** Which way the money goes for each kind of document a payment can be against. */
export type PayDoc = 'sub_bill' | 'supplier_bill' | 'ra_bill' | 'invoice' | string

export const PAY_MODES = ['Bank transfer', 'Cheque', 'UPI', 'Cash', 'Adjustment']

export function useOutstanding(docType: string, docId: number, enabled: boolean) {
  return useQuery({ queryKey: ['money', 'outstanding', docType, docId], queryFn: () => get<Outstanding>(`/api/money/outstanding/${docType}/${docId}`), enabled })
}

export function useBankAccounts() {
  return useQuery({ queryKey: ['money', 'accounts'], queryFn: async () => (await get<{ accounts: BankAccount[] }>('/api/bank-accounts')).accounts, staleTime: 60_000 })
}

export interface PaymentInput {
  doc_type: string
  doc_id: number
  amount: number
  paid_on: string
  mode: string
  reference: string
  note: string
  account_id: number | null
}

export const recordPayment = (p: PaymentInput) => post<{ message: string }>('/api/money/entries', p)
