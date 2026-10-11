import { useQuery } from '@tanstack/react-query'
import { get, post } from '@/lib/api'

export interface ApprovalItem {
  key: string
  kind: string
  kind_label: string
  id: number
  number: string
  amount: number
  party: string
  project: string
  raised_by: string
  since: string
  what: string
  view: string
  pdf: string
  approve_label: string
  reject_label: string
  note_to_approve: boolean
  mine: boolean
  waiting_on: string
  warnings: string[]
  /** For a variation to the BOQ: the BOQ it belongs to. */
  doc_id?: number
  /** For a contractor's RA bill: the hard copy of it, as it came on paper. */
  scan?: string
  overrun?: boolean
  budget?: string[]
}

export interface Inbox {
  items: ApprovalItem[]
  mine: number
  count: number
  owner: boolean
}

export const approvalKeys = { inbox: ['approvals', 'inbox'] as const }

export function useInbox() {
  return useQuery({ queryKey: approvalKeys.inbox, queryFn: () => get<Inbox>('/api/approvals/inbox'), refetchInterval: 60_000 })
}

export interface Decision {
  kind: string
  id: number
  decision: 'approve' | 'reject'
  note?: string
  override?: boolean
}

export const decide = (d: Decision) => post<{ message: string }>('/api/approvals/decide', { ...d, note: d.note ?? '', override: !!d.override })

/** Where the document lives in the app. A kind without a page of its own opens the approvals inbox. */
export function hrefFor(i: ApprovalItem): { to: string; external: boolean } {
  switch (i.kind) {
    case 'subcontract_order':
      return { to: `/subcontractors/work-orders/${i.id}`, external: false }
    case 'sub_bill':
      return { to: `/subcontractors/ra-bills/${i.id}`, external: false }
    case 'contractor':
      return { to: '/subcontractors/vendors', external: false }
    case 'boq_variation':
      return { to: `/projects/boq/${i.doc_id ?? ''}?tab=variations`, external: false }
    case 'ra_bill':
      return { to: `/clients/measurement?bill=${i.id}`, external: false }
    default:
      return { to: '/approvals', external: false }
  }
}
