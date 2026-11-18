import { useQuery } from '@tanstack/react-query'
import { del, get, post, put } from '@/lib/api'

export type PartyType = 'client' | 'supplier' | 'contractor' | 'other'
export const PARTY_LABEL: Record<string, string> = { client: 'Client', supplier: 'Supplier', contractor: 'Subcontractor', staff: 'Staff', other: 'Other' }

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

/** Every party's ledger, or, with a project, only what was billed or moved for that project. */
export const useParties = (type: string, job = 0) =>
  useQuery({ queryKey: k('parties', type, job), queryFn: () => get<PartyList>(`/api/ledger/parties?${new URLSearchParams({ ...(type ? { party_type: type } : {}), ...(job ? { job_id: String(job) } : {}) })}`) })

export interface Entry {
  id: number
  /** An expense: taxable or non_taxable, and for a taxable one local or non_local. */
  tax?: string
  supply?: string
  supply_state?: string
  /** The rate in percent, and the tax worked out inside the amount. */
  gst_rate?: number
  gst?: { base: number; tax: number; igst: number; cgst: number; sgst: number } | null
  /** A bank transfer on an expense: the bank, account number and IFSC the money went to. */
  payee_bank?: string
  payee_account?: string
  payee_ifsc?: string
  number: string
  direction: 'IN' | 'OUT'
  party_type: PartyType
  party_name: string
  doc_type: string
  doc_number: string
  account: string
  amount: number
  paid_on: string
  mode: string
  reference: string
  note: string
  voided: boolean
  void_reason: string
  /** An expense voucher's or a sundry receipt's head. */
  head: string
  job_id: number | null
}

export interface EntrySummary { received: number; paid: number; expenses: number; transferred: number; entries: number }
export const useEntries = () =>
  useQuery({ queryKey: k('entries'), queryFn: () => get<{ entries: Entry[]; summary: EntrySummary }>('/api/money/entries') })

/** The voucher for an entry, on the letterhead: a receipt, a payment, an expense or a transfer. */
export const voucherUrl = (id: number) => `/api/money/entries/${id}/voucher.pdf`

/** What an entry was for, in a word: the bill, the expense head, a transfer, or on account. */
export const entryAgainst = (e: Pick<Entry, 'doc_type' | 'doc_number' | 'head'>) =>
  e.doc_type === 'contra' ? 'Transfer' : e.head || e.doc_number || 'on account'

/** The heads an expense voucher or a sundry receipt is booked under. */
export const useMoneyHeads = () => useQuery({ queryKey: k('heads', 'v2'), staleTime: 60 * 60_000, queryFn: () => get<{ expense: string[]; income: string[]; states?: { value: string; label: string }[] }>('/api/money/heads') })

/** Money out with no bill behind it (diesel, transport, site sundries), or in (scrap sold, interest). */
export const recordVoucher = (b: { doc_type: 'expense' | 'income'; head: string; tax?: string; supply?: string; supply_state?: string; gst_rate?: number; payee_bank?: string; payee_account?: string; payee_ifsc?: string; party_name: string; amount: number; paid_on: string; mode: string; reference: string; note: string; account_id: number | null; job_id: number | null }) =>
  post<{ message: string; entry: Entry }>('/api/money/entries', { ...b, doc_id: null })

/** Cash drawn from the bank for a site, paid back in, or moved between banks: one contra voucher, both books. */
export const transferMoney = (b: { from_account_id: number; to_account_id: number; amount: number; paid_on: string; mode: string; reference: string; note: string }) =>
  post<{ message: string; entry: Entry }>('/api/money/transfer', b)

export const voidEntry = (id: number, reason: string) => post<{ message: string }>(`/api/money/entries/${id}/void`, { reason })

/** Money paid or received against no bill yet. It sits in the party's ledger until a bill arrives to set it against. */
export const recordOnAccount = (b: { direction: 'IN' | 'OUT'; party_type: string; party_name: string; amount: number; paid_on: string; mode: string; reference: string; note: string; account_id: number | null; job_id?: number | null }) =>
  post<{ message: string }>('/api/money/entries', { ...b, doc_type: 'on_account', doc_id: null })

/* --- Opening balances ------------------------------------------------------------------------- */

export type OpeningSide = 'owed' | 'advance'
export interface Opening {
  id: number
  /** OB-0001 */
  number: string
  party_type: PartyType
  party: string
  side: OpeningSide
  /** What it means for this party, in words: They owe us, We owe them, ... */
  means: string
  amount: number
  /** Its effect on the party's balance: up when owed, down when it is an advance. */
  balance: number
  as_on: string
  job_id: number | null
  project: string
  note: string
  created_by_name: string
  created_at: string
}
export interface OpeningInput { party_type: string; party_name: string; side: OpeningSide; amount: number; as_on: string; job_id: number | null; note: string }

export const useOpenings = () => useQuery({ queryKey: k('openings'), queryFn: () => get<{ openings: Opening[]; summary: { count: number; owed_to_us: number; we_owe: number } }>('/api/ledger/openings') })
export const saveOpening = (id: number | null, b: OpeningInput) => (id ? put<{ opening: Opening; message: string }>(`/api/ledger/openings/${id}`, b) : post<{ opening: Opening; message: string }>('/api/ledger/openings', b))
export const deleteOpening = (id: number) => del<{ message: string }>(`/api/ledger/openings/${id}`)

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
  is_active: boolean
  balance: number
}

export const useAccounts = () => useQuery({ queryKey: k('accounts'), queryFn: async () => (await get<{ accounts: Account[] }>('/api/bank-accounts')).accounts ?? [] })

export interface Book {
  opening: number
  rows: { id: number; date: string; number: string; party: string; against: string; mode: string; reference: string; received: number; paid: number; balance: number }[]
  received: number
  paid: number
  closing: number
}

export const useBook = (accountId: number) => useQuery({ queryKey: k('book', accountId), queryFn: () => get<Book>(`/api/money/book?account_id=${accountId}`), enabled: accountId > 0 })

export const createAccount = (b: { name: string; kind: string; bank_name: string; account_no: string; ifsc: string; opening_balance: number; opening_date: string }) => post<{ id: number; name: string }>('/api/bank-accounts', b)

/** Correct an account's details or opening balance, or close it. */
export const updateAccount = (id: number, b: { name: string; bank_name: string; account_no: string; ifsc: string; opening_balance: number; opening_date: string; is_active: boolean }) =>
  put<{ id: number; name: string }>(`/api/bank-accounts/${id}`, b)

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
  /** Udyam registration: micro and small enterprises are paid within 45 days (43B(h)). */
  msme_type: '' | 'micro' | 'small' | 'medium'
  udyam_no: string
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
