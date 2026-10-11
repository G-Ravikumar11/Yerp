import { useQuery } from '@tanstack/react-query'
import { get, post } from '@/lib/api'
import type { ApprovalItem } from './approvals'

/** Who is looking at the HO portal, and which of head office's own work they may open. */
export interface HoPerson {
  role: string
  role_label: string
  name: string
  may_create: { vendors: boolean; work_orders: boolean; boq: boolean }
}

/** An order opened and not yet sent for approval. */
export interface HoDraft {
  kind: 'subcontract_order' | 'work_order'
  kind_label: string
  id: number
  number: string
  party: string
  project: string
  subject: string
  amount: number
  raised_by: string
  since: string
  href: string
}

export interface HoProject {
  id: number
  number: string
  name: string
  status: string
}

export interface HoOverview {
  person: HoPerson
  company: string
  reserved: string[]
  vendors: { registered: number; pending: number; sent_back: number; total: number }
  subcontract_orders: { draft: number; awaiting: number; approved: number; total: number; value: number }
  client_orders: { draft: number; awaiting: number; placed: number; total: number; value: number }
  boqs: { count: number; being_priced: number; projects_without: number }
  sub_bills: { draft: number; awaiting: number; certified: number; claimed: number }
  projects_without_boq: HoProject[]
  waiting: ApprovalItem[]
  drafts: HoDraft[]
}

export const hoKeys = { overview: ['head-office', 'overview'] as const }

/** The HO portal's front page: every site at once. Kept fresh while it is open - it is a list to chase. */
export const useHoOverview = () => useQuery({ queryKey: hoKeys.overview, queryFn: () => get<HoOverview>('/api/ho/overview'), refetchInterval: 60_000 })

/** HO QS draws up the client's work order from a tender somebody else marked won. */
export const workOrderFromTender = (estimateId: number) =>
  post<{ message: string; work_order: { id: number; number: string } }>(`/api/estimates/${estimateId}/work-order`)
