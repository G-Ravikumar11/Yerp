import { useQuery } from '@tanstack/react-query'
import { get } from '@/lib/api'

export interface TdsRow {
  date: string
  year: string
  quarter: string
  bill: string
  amount_credited: number
  tds: number
  section: string
  rate: number
}

export interface Deducted extends TdsRow {
  deductee: string
  pan: string
  missing_pan: boolean
  paid_on: string
}

export interface Suffered extends TdsRow {
  deductor: string
  project: string
}

export interface TdsRegister {
  years: string[]
  deducted_by_quarter: { period: string; bills: number; amount_credited: number; tds: number }[]
  deducted: Deducted[]
  suffered: Suffered[]
  summary: { deducted: number; suffered: number; deductees_without_pan: number }
}

export interface Guarantee {
  contractor: string
  order_id: number
  order: string
  amount: number
  valid_until: string
  days_left: number | null
  completion_date: string
  defect_liability_months: number
  state: string
}

export interface Advance {
  contractor: string
  order_id: number
  order: string
  advance: number
  recovery_percent: number
  recovered: number
  percent_recovered: number
  outstanding: number
  secured_by_bg: boolean
}

export const useTdsRegister = (year: string, quarter: string) =>
  useQuery({ queryKey: ['registers', 'tds', year, quarter], queryFn: () => get<TdsRegister>(`/api/registers/tds?year=${encodeURIComponent(year)}&quarter=${encodeURIComponent(quarter)}`), placeholderData: (p) => p })

export const useGuarantees = () =>
  useQuery({ queryKey: ['registers', 'guarantees'], queryFn: () => get<{ guarantees: Guarantee[]; summary: { held: number; lapsing_soon: number; lapsed: number; no_expiry: number } }>('/api/registers/guarantees') })

export const useAdvances = () =>
  useQuery({ queryKey: ['registers', 'advances'], queryFn: () => get<{ advances: Advance[]; summary: { given: number; recovered: number; outstanding: number; unsecured: number } }>('/api/registers/advances') })
