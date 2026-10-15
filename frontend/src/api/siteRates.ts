import { useQuery } from '@tanstack/react-query'
import { get, post, put } from '@/lib/api'
import type { MasterItem } from '@/api/itemMaster'

export type PriceStatus = 'Pending' | 'Draft' | 'Finalized' | 'Changed'

export interface Site {
  id: number
  site_code: string
  site_name: string
  customer: string
  boq_id: number | null
}

/** One priced line of a site's BOQ, matched to the master and carrying the site's rate for its item. */
export interface PriceRow {
  line_key: string
  line_id: number
  section: string
  description: string
  item_id: number | null
  item_code: string
  mapped: boolean
  item_name: string
  item_active: boolean
  specification: string
  uom: string
  quantity: number
  rate_only: boolean
  boq_rate: number
  default_rate: number | null
  site_rate: number | null
  amount: number
  status: PriceStatus
  /** Sent back with a save so two people on the same row cannot overwrite one another. */
  version: number
  effective_date: string
  remarks: string
  finalized_by: string
  finalized_at: string
  updated_by: string
  updated_at: string
}

export interface PriceSummary {
  lines: number
  mapped: number
  unmapped: number
  pending: number
  draft: number
  finalized: number
  changed: number
  rate_only: number
  amount: number
}

export interface SitePrices {
  site: { id: number; site_code: string; site_name: string; customer: string }
  boq: { id: number; number: string; title: string; revision: string; editable: boolean } | null
  rows: PriceRow[]
  summary: PriceSummary
}

export interface PriceAudit {
  id: number
  item_code: string
  previous_rate: number | null
  new_rate: number | null
  previous_status: string
  new_status: string
  action: string
  changed_by: string
  changed_at: string
  reason: string
}

export const priceKeys = {
  all: ['site-prices'] as const,
  sites: ['site-prices', 'sites'] as const,
  rows: (siteId: number | null) => ['site-prices', 'rows', siteId] as const,
  audit: (siteId: number | null) => ['site-prices', 'audit', siteId] as const,
}

export function useSites() {
  return useQuery({ queryKey: priceKeys.sites, queryFn: async () => (await get<{ sites: Site[] }>('/api/sites')).sites, retry: false })
}

/** Keyed by site, so a quick switch can never show one site's rows under another's name. */
export function useSitePrices(siteId: number | null) {
  return useQuery({ queryKey: priceKeys.rows(siteId), enabled: siteId !== null, queryFn: () => get<SitePrices>(`/api/sites/${siteId}/boq-items`) })
}

export function usePriceAudit(siteId: number | null, enabled: boolean) {
  return useQuery({ queryKey: priceKeys.audit(siteId), enabled: enabled && siteId !== null, queryFn: async () => (await get<{ audit: PriceAudit[] }>(`/api/sites/${siteId}/item-prices/audit`)).audit })
}

interface Reply {
  summary: PriceSummary
  message: string
}

export const saveRate = (siteId: number, itemId: number, rate: number | null, remarks: string, version: number) =>
  put<Reply>(`/api/sites/${siteId}/item-prices/${itemId}`, { rate, remarks, version })

export const bulkSave = (siteId: number, rates: { item_id: number; rate: number | null; version: number }[], remarks: string) =>
  post<Reply>(`/api/sites/${siteId}/item-prices/bulk`, { rates: rates.map((r) => ({ ...r, remarks })) })

export const finalizeRate = (siteId: number, itemId: number, version: number) => post<Reply>(`/api/sites/${siteId}/item-prices/${itemId}/finalize`, { version })
export const reopenRate = (siteId: number, itemId: number, remarks: string) => post<Reply>(`/api/sites/${siteId}/item-prices/${itemId}/reopen`, { remarks })
export const applyToBoq = (siteId: number) => post<Reply & { applied: number }>(`/api/sites/${siteId}/item-prices/apply-to-boq`, {})
export const mapItem = (siteId: number, lineKey: string, itemId: number) => post<Reply>(`/api/sites/${siteId}/boq-items/${encodeURIComponent(lineKey)}/map-item`, { item_id: itemId })
export const createItemFromLine = (siteId: number, lineKey: string, body: { item_code?: string; item_category?: string; item_type?: string }) =>
  post<Reply & { item: MasterItem }>(`/api/sites/${siteId}/boq-items/${encodeURIComponent(lineKey)}/create-item`, body)
