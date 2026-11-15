import { useQuery } from '@tanstack/react-query'
import { get } from '@/lib/api'

export const bookKeys = { all: ['books'] as const }

/** One ledger's line in the trial balance: where it stood, what the period did to it, where it stands now. A balance is on one side only. */
export interface TbLedger {
  ledger: string
  /** The Tally group it sits under. */
  group: string
  opening_dr: number
  opening_cr: number
  debit: number
  credit: number
  closing_dr: number
  closing_cr: number
}
type Columns = Pick<TbLedger, 'opening_dr' | 'opening_cr' | 'debit' | 'credit' | 'closing_dr' | 'closing_cr'>
export interface LeftOut { what: string; count: number; amount: number; why: string; where: string }
export interface TrialBalance {
  date_from: string
  date_to: string
  ledgers: TbLedger[]
  groups: (Columns & { group: string; ledgers: number })[]
  totals: Columns
  /** Vouchers in the period itself (not the opening). */
  vouchers: number
  balanced: boolean
  difference: number
  /** A voucher left out because it did not balance. */
  warnings: string[]
  /** Recorded in the period but not a voucher yet. */
  left_out: LeftOut[]
}

export interface DayVoucher {
  date: string
  type: string
  number: string
  narration: string
  project: string
  amount: number
  cancelled: boolean
  lines: { ledger: string; debit: number; credit: number }[]
}
export interface DayBook {
  date_from: string
  date_to: string
  vouchers: DayVoucher[]
  warnings: string[]
  summary: { count: number; cancelled: number; debit: number; credit: number; types: { type: string; count: number; amount: number }[] }
}

export const useTrialBalance = (from: string, to: string) =>
  useQuery({ queryKey: [...bookKeys.all, 'trial', from, to], queryFn: () => get<TrialBalance>(`/api/reports/trial-balance?date_from=${from}&date_to=${to}`) })

export const useDayBook = (day: string) =>
  useQuery({ queryKey: [...bookKeys.all, 'day', day], queryFn: () => get<DayBook>(`/api/reports/day-book?date=${day}`) })

export const trialBalanceXlsx = (from: string, to: string) => `/api/reports/trial-balance.xlsx?date_from=${from}&date_to=${to}`
export const dayBookXlsx = (day: string) => `/api/reports/day-book.xlsx?date=${day}`
