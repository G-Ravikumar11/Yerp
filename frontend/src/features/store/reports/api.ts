import { useQuery } from '@tanstack/react-query'
import { storeGet } from '@/api/store'

/** The reports, in menu order. The key is the path under /api/store/reports and under /store/hub/reports. */
export type ReportKey = 'valuation' | 'movement' | 'consumption' | 'norm-variance' | 'slow-moving' | 'reorder' | 'abc' | 'ageing' | 'reconciliation'
export const REPORTS: { key: ReportKey; label: string; blurb: string }[] = [
  { key: 'valuation', label: 'Stock valuation', blurb: 'What each store holds and what it is worth, today or on any past date.' },
  { key: 'movement', label: 'Stock movement', blurb: 'Opening stock, what moved in each group, and closing stock, for a period.' },
  { key: 'consumption', label: 'Material consumption', blurb: 'What was issued to projects, net of what came back, by project, cost head, work order, BOQ item or item.' },
  { key: 'norm-variance', label: 'Norms against use', blurb: 'What each BOQ item should have consumed by its norms, against what was actually issued.' },
  { key: 'slow-moving', label: 'Slow-moving stock', blurb: 'Stock that has not moved for a while, and what is tied up in it.' },
  { key: 'reorder', label: 'Reorder', blurb: 'Items at or below their reorder level, with a suggested quantity.' },
  { key: 'abc', label: 'ABC analysis', blurb: 'Items ranked by what was used of them: A is the few items that make up 70% of the spend, B the next 20%, C the rest.' },
  { key: 'ageing', label: 'Stock ageing', blurb: 'What each store holds, split by how long ago it came in. The oldest stock is taken to have gone out first.' },
  { key: 'reconciliation', label: 'Site reconciliation', blurb: "One statement per item for a project's site: received, transferred, returned, issued, wasted and the balance left, against what the BOQ needs by its norms." },
]
export const reportOf = (key: string | undefined) => REPORTS.find((r) => r.key === key)

/** What the report routes send. Quantities, rates and values are strings. */
export interface Row { [k: string]: string | number | boolean | null }
export interface ReportData {
  report: ReportKey
  filters: string
  rows?: Row[]
  groups?: { key: string | number; name: string; value: string; items: Row[] }[]
  buckets?: { key: string; label: string }[]
  totals?: Record<string, string>
  total_value?: string
  as_on?: string
  from?: string
  to?: string
  by_category?: { category: string; lines: number; value: string }[]
  over?: number
  days?: number
  method?: 'average' | 'fifo'
  classes?: { class: 'A' | 'B' | 'C'; items: number; value: string; share_pct: string }[]
  site_stores?: { id: number; code: string; name: string }[]
  balance_value?: string
}
export interface Saved { id: number; name: string; report: ReportKey; params: Record<string, string>; created_by: string }
export interface Norm {
  id: number
  boq_item_id: number
  boq_item: string
  boq_qty: string
  boq_uom: string
  item_id: number
  item_code: string
  item_name: string
  base_uom: string
  qty_per_unit: string
  wastage_pct: string
  notes: string
  theoretical_qty: string
}
export interface BoqPick { id: number; item_no: string; description: string; uom: string; quantity: string }

export const qs = (params: Record<string, string | number | boolean | null | undefined>) => {
  const p = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) if (v !== '' && v !== 0 && v !== false && v != null) p.set(k, String(v))
  const s = p.toString()
  return s ? `?${s}` : ''
}

export const reportKeys = { all: ['store', 'reports'] as const }
export const useReport = (report: ReportKey, params: Record<string, string | number | boolean>, enabled = true) =>
  useQuery({ queryKey: ['store', 'reports', 'run', report, params], enabled, queryFn: () => storeGet<ReportData>('reports', `/${report}${qs(params)}`) })
export const useSaved = () => useQuery({ queryKey: ['store', 'reports', 'saved'], queryFn: async () => (await storeGet<{ items: Saved[] }>('reports')).items })
export const useNorms = (projectId: number) =>
  useQuery({ queryKey: ['store', 'reports', 'norms', projectId], enabled: projectId > 0, queryFn: async () => (await storeGet<{ items: Norm[] }>('reports', `/norms${qs({ project_id: projectId })}`)).items })
export const useBoqPicks = (projectId: number) =>
  useQuery({ queryKey: ['store', 'reports', 'boq', projectId], enabled: projectId > 0, queryFn: async () => (await storeGet<{ items: BoqPick[] }>('reports', `/pick/boq-items?project_id=${projectId}`)).items })

export const num = (v: unknown) => Number(v ?? 0).toLocaleString('en-IN', { maximumFractionDigits: 3 })
export const money = (v: unknown) => Number(v ?? 0).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
export const dmy = (iso: unknown) => (iso ? new Date(String(iso).slice(0, 10) + 'T00:00').toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' }) : '-')
