import { useQuery } from '@tanstack/react-query'
import { api, get, post, put } from '@/lib/api'

/* A site's cash box (imprest): topped up by head office, spent on site with a photo of each bill, checked by accounts. */

export const siteCashKeys = { all: ['site-cash'] as const }

export interface CashBox {
  id: number
  name: string
  job_id: number | null
  project: string
  custodian_id: number | null
  custodian: string
  /** The float the box is topped back up to. */
  imprest_amount: number
  /** In the books. */
  balance: number
  /** Spent and not yet checked by accounts. */
  pending: number
  /** What should be in the box now: the balance less what is pending. */
  in_hand: number
  /** What brings the float back up, once what is pending is checked. */
  top_up: number
}

export type SiteExpenseStatus = 'SUBMITTED' | 'APPROVED' | 'REJECTED'

export interface SiteExpense {
  id: number
  number: string
  account_id: number
  job_id: number | null
  project: string
  spent_on: string
  head: string
  paid_to: string
  amount: number
  note: string
  bill_no: string
  status: SiteExpenseStatus
  submitted_by: number | null
  submitted_by_name: string
  submitted_at: string
  checked_by_name: string
  checked_at: string
  reject_reason: string
  entry_id: number | null
  photo: { id: number; name: string } | null
}

export interface SiteCash { boxes: CashBox[]; expenses: SiteExpense[]; manage: boolean; me: number | null }

export const useSiteCash = (status = '') =>
  useQuery({ queryKey: [...siteCashKeys.all, status], queryFn: () => get<SiteCash>(`/api/site-cash${status ? `?status=${status}` : ''}`) })

export const setCashBox = (id: number, b: { job_id: number | null; custodian_id: number | null; imprest_amount: number }) =>
  put<{ message: string }>(`/api/site-cash/boxes/${id}`, b)

export const spendSiteCash = (b: { account_id: number; amount: number; head: string; paid_to: string; spent_on: string; note: string; bill_no: string }) =>
  post<{ expense: SiteExpense; message: string }>('/api/site-cash/expenses', b)

/** The bill's photo, kept with the expense. */
export function attachBillPhoto(id: number, file: File) {
  const form = new FormData()
  form.append('file', file)
  return api<{ message: string }>(`/api/site-cash/expenses/${id}/photo`, { method: 'POST', body: form })
}

export const decideSiteExpense = (id: number, decision: 'approve' | 'reject', note = '') =>
  post<{ expense: SiteExpense; message: string }>(`/api/site-cash/expenses/${id}/decide`, { decision, note })

export const cashStatementUrl = (id: number) => `/api/site-cash/boxes/${id}/statement.pdf`
