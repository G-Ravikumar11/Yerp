import { useQuery } from '@tanstack/react-query'
import { get, post, put } from '@/lib/api'

export type PartyType = 'client' | 'supplier' | 'contractor' | 'other'
export const PARTY_LABEL: Record<string, string> = { client: 'Client', supplier: 'Supplier', contractor: 'Subcontractor', other: 'Other' }

export const ledgerKeys = { all: ['ledger'] as const }
const k = (...p: unknown[]) => ['ledger', ...p] as const

export interface Party {
  party_type: PartyType
  party: string
  billed: number
  moved: number
  last: string
  balance: number
}

export interface PartyList {
  parties: Party[]
  summary: { owed_to_us: number; we_owe: number; advances_out: number; advances_in: number; parties: number }
}

export const useParties = (type: string) => useQuery({ queryKey: k('parties', type), queryFn: () => get<PartyList>(`/api/ledger/parties${type ? `?party_type=${type}` : ''}`) })

export interface Entry {
  id: number
  number: string
  direction: 'IN' | 'OUT'
  party_type: PartyType
  party_name: string
  doc_number: string
  account: string
  amount: number
  paid_on: string
  mode: string
  reference: string
  voided: boolean
  void_reason: string
}

export const useEntries = () =>
  useQuery({ queryKey: k('entries'), queryFn: () => get<{ entries: Entry[]; summary: { received: number; paid: number; entries: number } }>('/api/money/entries') })

export const voidEntry = (id: number, reason: string) => post<{ message: string }>(`/api/money/entries/${id}/void`, { reason })

/** Money paid or received against no bill yet. It sits in the party's ledger until a bill arrives to set it against. */
export const recordOnAccount = (b: { direction: 'IN' | 'OUT'; party_type: string; party_name: string; amount: number; paid_on: string; mode: string; reference: string; note: string; account_id: number | null }) =>
  post<{ message: string }>('/api/money/entries', { ...b, doc_type: 'on_account', doc_id: null })

/* --- The bank book -------------------------------------------------------------------------- */

export interface Account {
  id: number
  name: string
  kind: string
  bank_name: string
  account_no: string
  ifsc: string
  opening_balance: number
  opening_date: string
  balance: number
}

export const useAccounts = () => useQuery({ queryKey: k('accounts'), queryFn: async () => (await get<{ accounts: Account[] }>('/api/bank-accounts')).accounts ?? [] })

export interface Book {
  opening: number
  rows: { date: string; number: string; party: string; against: string; mode: string; reference: string; received: number; paid: number; balance: number }[]
  received: number
  paid: number
  closing: number
}

export const useBook = (accountId: number) => useQuery({ queryKey: k('book', accountId), queryFn: () => get<Book>(`/api/money/book?account_id=${accountId}`), enabled: accountId > 0 })

export const createAccount = (b: { name: string; kind: string; bank_name: string; account_no: string; ifsc: string; opening_balance: number; opening_date: string }) => post<{ id: number; name: string }>('/api/bank-accounts', b)

/* --- Suppliers ------------------------------------------------------------------------------------ */

export interface Supplier {
  id: number
  code: string
  name: string
  contact_person: string
  phone: string
  email: string
  gstin: string
  pan: string
  address: string
  state: string
  bank_name: string
  bank_account: string
  bank_ifsc: string
  payment_days: number
  supplies: string
  is_active: boolean
}

export const useSuppliers = () => useQuery({ queryKey: k('suppliers'), queryFn: () => get<{ suppliers: Supplier[]; unregistered: string[] }>('/api/suppliers') })
export type SupplierInput = Omit<Supplier, 'id' | 'code' | 'state' | 'is_active'>
export const saveSupplier = (id: number | null, b: SupplierInput) => (id ? put<{ code: string; name: string }>(`/api/suppliers/${id}`, b) : post<{ code: string; name: string }>('/api/suppliers', b))
export const adoptSuppliers = () => post<{ message?: string }>('/api/suppliers/adopt', {})

/* --- A statement of account --------------------------------------------------------------------- */

export interface Statement {
  party: string
  party_type: PartyType
  master: { name?: string; gstin?: string; pan?: string; address?: string; phone?: string }
  opening: number
  closing: number
  billed: number
  moved: number
  closing_words?: string
  rows: { date: string; kind: string; number: string; against?: string; reference?: string; billed: number; moved: number; balance: number }[]
}

export const useStatementOfAccount = (type: string, party: string, enabled: boolean) =>
  useQuery({ queryKey: k('statement', type, party), queryFn: () => get<Statement>(`/api/ledger/statement?party_type=${encodeURIComponent(type)}&party=${encodeURIComponent(party)}`), enabled })
