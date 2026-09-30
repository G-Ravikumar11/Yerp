import { useQuery } from '@tanstack/react-query'
import { get } from '@/lib/api'
import { cashFlow, type LedgerEntry } from '@/lib/cashflow'

export interface AttentionItem {
  kind: string
  severity: 'money' | 'wrong' | 'action' | 'notice' | string
  value: number
  count: number
  view: string
  title: string
  detail: string
}

export interface ProjectPnl {
  job_id: number
  number: string
  name: string
  customer_name: string
  status: string
  order_value: number
  revenue: number
  incurred: number
  committed: number
  margin: number
  margin_percent: number
  over_budget: boolean
  outstanding: number
}

type Buckets = Record<string, number>

/** These are read separately, so one that is refused or slow leaves the rest of the dashboard alone. */
const opts = { retry: false, staleTime: 60_000 } as const

export const useAttention = () =>
  useQuery({
    queryKey: ['dashboard', 'attention'],
    queryFn: () => get<{ items: AttentionItem[]; summary: { items: number; money_at_stake: number; needs_a_decision: number; looks_wrong: number } }>('/api/attention'),
    ...opts,
  })

export const useReceivables = (enabled: boolean) =>
  useQuery({ queryKey: ['dashboard', 'receivables'], queryFn: () => get<{ buckets: Buckets; summary: { owed: number; overdue: number; invoices: number; over_90: number } }>('/api/money/receivables'), enabled, ...opts })

export const usePayables = (enabled: boolean) =>
  useQuery({ queryKey: ['dashboard', 'payables'], queryFn: () => get<{ buckets: Buckets; summary: { owed: number; overdue: number; bills: number; awaiting_approval: number; over_90: number } }>('/api/money/payables'), enabled, ...opts })

export const useRetention = (enabled: boolean) =>
  useQuery({ queryKey: ['dashboard', 'retention'], queryFn: () => get<{ summary: { held: number; released: number; on_finished_jobs: number; projects: number } }>('/api/money/retention'), enabled, ...opts })

export const useProjectPnl = (enabled: boolean) =>
  useQuery({
    queryKey: ['dashboard', 'pnl'],
    queryFn: () => get<{ projects: ProjectPnl[]; summary: { projects: number; order_value: number; revenue: number; incurred: number; margin: number; losing_money: number; owed_to_us: number } }>('/api/jobs-pnl'),
    enabled,
    ...opts,
  })

/** The last twelve months of money in and out, from the ledger. */
export const useCashFlow = (enabled: boolean) =>
  useQuery({
    queryKey: ['dashboard', 'cashflow'],
    queryFn: async () => cashFlow((await get<{ entries: LedgerEntry[] }>('/api/money/entries')).entries, 12),
    enabled,
    ...opts,
  })

/** Where an attention item lives now. What has not been ported still opens in the current app. */
export function attentionHref(view: string): { to: string; external: boolean } {
  const ported: Record<string, string> = {
    'subcontracts-view': '/subcontractors/work-orders',
    'subbills-view': '/subcontractors/ra-bills',
    'vendors-view': '/subcontractors/vendors',
    'approvals-view': '/approvals',
    'items-view': '/store/items',
    'measurement-view': '/clients/measurement',
  }
  return ported[view] ? { to: ported[view], external: false } : { to: '/app.html', external: true }
}
