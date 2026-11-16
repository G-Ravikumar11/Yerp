import { useQuery } from '@tanstack/react-query'
import { del, get, post, put } from '@/lib/api'

export const loanKeys = { all: ['loans'] as const }

/** One instalment (EMI): the principal it repays and the interest it costs. */
export interface Instalment {
  id: number
  seq: number
  /** LN-0001 EMI 3/36: what the payment is entered against. */
  number: string
  due_on: string
  principal: number
  interest: number
  total: number
  status: 'DUE' | 'PAID'
  paid_on: string
  overdue: boolean
  days_late: number
}

export interface Loan {
  id: number
  number: string
  lender: string
  name: string
  kind: 'secured' | 'unsecured'
  /** The loan's own ledger in the books. */
  ledger: string
  principal: number
  annual_rate: number
  emi: number
  first_due: string
  /** Already running before these books began: entered with what was left of it. */
  existing: boolean
  taken_on: string
  note: string
  created_by_name: string
  instalments: number
  paid: number
  repaid: number
  /** What is still owed of the principal. */
  outstanding: number
  interest_paid: number
  interest_to_come: number
  status: 'ACTIVE' | 'CLOSED'
  received: boolean
  next: Instalment | null
  overdue: number
  /** Only on a single loan. */
  schedule?: Instalment[]
}

export interface LoanSummary {
  outstanding: number
  active: number
  closed: number
  emi_a_month: number
  due_week: number
  due_week_amount: number
  overdue: number
  overdue_amount: number
  interest_paid: number
  interest_to_come: number
  next_due: string
}

export interface LoanInput {
  lender: string
  name: string
  kind: string
  principal: number
  annual_rate: number
  months: number
  first_due: string
  /** The bank's own EMI; blank (0) to work it out. */
  emi: number
  existing: boolean
  taken_on: string
  account_id: number | null
  mode: string
  reference: string
  note: string
}

export const useLoans = () => useQuery({ queryKey: loanKeys.all, queryFn: () => get<{ loans: Loan[]; summary: LoanSummary }>('/api/loans') })
export const useLoan = (id: number) => useQuery({ queryKey: [...loanKeys.all, id], enabled: id > 0, queryFn: () => get<Loan>(`/api/loans/${id}`) })

export const addLoan = (b: LoanInput) => post<{ loan: Loan; message: string }>('/api/loans', b)
export const saveInstalment = (loan: number, id: number, b: { due_on: string; principal: number; interest: number }) =>
  put<{ instalment: Instalment; loan: Loan; message: string }>(`/api/loans/${loan}/instalments/${id}`, b)
export const deleteLoan = (id: number) => del<{ message: string }>(`/api/loans/${id}`)

/** About what the EMI will be, to show while the form is filled in. The server works out the real one. */
export function previewEmi(principal: number, annualRate: number, months: number) {
  if (principal <= 0 || months <= 0) return null
  const r = annualRate / 1200
  const emi = r === 0 ? principal / months : (principal * r * (1 + r) ** months) / ((1 + r) ** months - 1)
  return { emi, interest: Math.max(0, emi * months - principal) }
}
