import { useQuery } from '@tanstack/react-query'
import { del, get, post, put } from '@/lib/api'

export const recurringKeys = { all: ['recurring'] as const }

export type RecurringStatus = 'Active' | 'Paused' | 'Ended'

/** A payment that falls due on the same day every month: rent, internet, hire, insurance. */
export interface Recurring {
  id: number
  payee: string
  head: string
  job_id: number | null
  project: string
  amount: number
  day_of_month: number
  start_date: string
  /** Blank: until stopped. */
  end_date: string
  /** The next day a request is raised for it; blank once it has ended. */
  next_due: string
  status: RecurringStatus
  is_active: boolean
  account_id: number | null
  account: string
  mode: string
  note: string
  /** As on an expense voucher: taxable or non_taxable, local or non_local from a state, the GST rate, and where a bank transfer goes. */
  tax?: string
  supply?: string
  supply_state?: string
  gst_rate?: number
  payee_bank?: string
  payee_account?: string
  payee_ifsc?: string
  raised_count: number
  last_raised_on: string
  /** Why the last attempt to raise it failed, until one works. */
  last_error: string
  /** The latest request it raised, and where it stands. */
  last_request: { number: string; status: string; due_on: string } | null
}

export interface RecurringInput {
  payee: string
  head: string
  amount: number
  day_of_month: number
  start_date: string
  end_date: string
  job_id: number | null
  account_id: number | null
  mode: string
  note: string
  tax?: string
  supply?: string
  supply_state?: string
  gst_rate?: number
  payee_bank?: string
  payee_account?: string
  payee_ifsc?: string
}

export interface RecurringList {
  payments: Recurring[]
  summary: { active: number; paused: number; ended: number; monthly: number; next_due: string; failing: number }
}

type Reply = { payment: Recurring; message: string }

export const useRecurring = () => useQuery({ queryKey: recurringKeys.all, queryFn: () => get<RecurringList>('/api/recurring-payments') })
export const saveRecurring = (id: number | null, b: RecurringInput) => (id ? put<Reply>(`/api/recurring-payments/${id}`, b) : post<Reply>('/api/recurring-payments', b))
export const pauseRecurring = (id: number) => post<Reply>(`/api/recurring-payments/${id}/pause`)
export const resumeRecurring = (id: number) => post<Reply>(`/api/recurring-payments/${id}/resume`)
export const deleteRecurring = (id: number) => del<{ message: string }>(`/api/recurring-payments/${id}`)
