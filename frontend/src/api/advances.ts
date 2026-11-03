import { useQuery } from '@tanstack/react-query'
import { get } from '@/lib/api'

/** A mobilisation advance given to a contractor on a work order, and what their RA bills have taken back of it. */
export interface MobilisationAdvance {
  order_id: number
  order: string
  contractor: string
  project: string
  job_id: number | null
  agreed: number
  not_yet_paid: number
  advance: number
  recovery_percent: number
  recovered: number
  outstanding: number
  percent_recovered: number
  security: string
  unsecured: number
  /** Taken back by the bills beyond what was paid: a mistake to look at. */
  over_recovered: number
}

/** Paid to a party on account, ahead of their bills, and not yet set against one. */
export interface OnAccountAdvance {
  party_type: string
  party: string
  outstanding: number
  last_paid: string
  projects: string[]
}

/** Cash a member of staff holds in a site cash box, to spend for the site. */
export interface CashWithStaff {
  box: string
  custodian: string
  project: string
  job_id: number | null
  in_hand: number
  pending: number
}

export interface Advances {
  mobilisation: MobilisationAdvance[]
  on_account: OnAccountAdvance[]
  staff: OnAccountAdvance[]
  site_cash: CashWithStaff[]
  summary: { contractors: number; unsecured: number; suppliers: number; on_account_contractors: number; staff: number; other: number }
}

export const advanceKeys = { all: ['advances'] as const }
export const useAdvances = (jobId: number) =>
  useQuery({ queryKey: [...advanceKeys.all, jobId], queryFn: () => get<Advances>(`/api/advances${jobId ? `?job_id=${jobId}` : ''}`) })
export const useAdvanceStaff = (enabled: boolean) =>
  useQuery({ queryKey: [...advanceKeys.all, 'staff'], enabled, queryFn: () => get<{ staff: { id: number; name: string }[] }>('/api/advances/staff') })
