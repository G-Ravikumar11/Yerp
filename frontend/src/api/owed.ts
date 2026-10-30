import { useQuery } from '@tanstack/react-query'
import { get, post } from '@/lib/api'

export const BUCKETS = ['Not due', '0-30', '31-60', '61-90', '90+'] as const
export type Buckets = Record<(typeof BUCKETS)[number], number>

interface Aged {
  id: number
  number: string
  project: string
  due_date: string
  outstanding: number
  bucket: string
  days_overdue: number
  doc_type?: string
  kind: string
}

export interface Receivable extends Aged {
  customer: string
  total: number
  paid: number
}

export interface Payable extends Aged {
  party: string
  approved?: boolean
}

/** A bill a credit note took past what was owed on it: the balance is now in the party's favour. */
export interface CreditBalance {
  id: number
  number: string
  doc_type: string
  party: string
  project: string
  amount: number
}

/** Per party: owed on open documents, in their favour after credit notes, on account, and the net. */
export interface PartyPosition {
  party: string
  owed: number
  credit: number
  on_account: number
  net: number
}

export interface Ledger<T> {
  rows: T[]
  buckets: Buckets
  summary: Record<string, number>
  credits: CreditBalance[]
  parties: PartyPosition[]
}

export const owedKeys = { all: ['owed'] as const, receivables: ['owed', 'receivables'] as const, payables: ['owed', 'payables'] as const, retention: ['owed', 'retention'] as const }

export const useOwedReceivables = () =>
  useQuery({ queryKey: owedKeys.receivables, queryFn: async (): Promise<Ledger<Receivable>> => { const d = await get<{ invoices: Receivable[]; buckets: Buckets; summary: Record<string, number>; credits?: CreditBalance[]; parties?: PartyPosition[] }>('/api/money/receivables'); return { rows: d.invoices ?? [], buckets: d.buckets, summary: d.summary ?? {}, credits: d.credits ?? [], parties: d.parties ?? [] } } })

export const useOwedPayables = () =>
  useQuery({ queryKey: owedKeys.payables, queryFn: async (): Promise<Ledger<Payable>> => { const d = await get<{ bills: Payable[]; buckets: Buckets; summary: Record<string, number>; credits?: CreditBalance[]; parties?: PartyPosition[] }>('/api/money/payables'); return { rows: d.bills ?? [], buckets: d.buckets, summary: d.summary ?? {}, credits: d.credits ?? [], parties: d.parties ?? [] } } })

/* --- Retention: money held back on a bill until the work is proved ---------------------- */

export interface Position {
  side: 'client' | 'contractor'
  order_id: number
  order_number: string
  project: string
  job_status: string
  finished: boolean
  party: string
  bills: number
  claimed: number
  held: number
  released: number
  balance: number
  gst_percent: number
  suggest?: { stage: string; amount: number }
  dlp_ends: string
  dlp_over: boolean
  /** Released (or taken back by credit notes) past what was held - an error to put right. */
  over_released?: number
  /** What would stop the release suggested next: the defects period still running, a back-charge open... */
  holds?: string[]
  actual_completion_date?: string
}

export interface Release {
  id: number
  number: string
  release_on: string
  stage: string
  side: 'client' | 'contractor'
  party: string
  order_number: string
  amount: number
  net_amount: number
  gst_amount: number
  outstanding: number
  /** SUBMITTED: raised by staff, waiting for somebody else to certify it before it is owed. */
  status: 'SUBMITTED' | 'CERTIFIED' | 'PAID' | 'CANCELLED' | string
  settled?: boolean
  created_by_name?: string
  certified_by_name?: string
  override_note?: string
  can_certify?: boolean
}

export interface Retention {
  positions: Position[]
  releases: Release[]
  stages: string[]
  summary: { client_held: number; client_on_finished: number; client_to_receive: number; contractor_held: number; contractor_dlp_over: number }
}

export const useRetentionPage = () => useQuery({ queryKey: owedKeys.retention, queryFn: () => get<Retention>('/api/retention') })

export const raiseRelease = (b: { side: string; order_id: number; stage: string; amount: number; release_on: string; notes: string; override?: boolean; dlp_ends?: string }) => post<{ message: string }>('/api/retention/releases', b)
export const certifyRelease = (id: number, comments: string) => post<{ message: string }>(`/api/retention/releases/${id}/certify`, { comments })
export const cancelRelease = (id: number, reason: string) => post<{ message: string }>(`/api/retention/releases/${id}/cancel`, { reason })
