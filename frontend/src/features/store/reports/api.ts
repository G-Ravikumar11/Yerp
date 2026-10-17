import { useQuery } from '@tanstack/react-query'
import { api, get } from '@/lib/api'
import { storeDelete, storeGet, storeKeys, storePost, storePut } from '@/api/store'

/** Store > Reports: reports, norms, reconciliation, dashboard, and the read-only hooks other modules use. */

const r = 'reports' as const
export const reportKeys = { all: storeKeys.slice('reports'), list: (...p: unknown[]) => [...storeKeys.slice('reports'), ...p] as const }

export interface Column { key: string; label: string; align: 'L' | 'C' | 'R' }
export interface Report { code: string; title: string; columns: Column[]; rows: Record<string, string | number | null>[]; totals: Record<string, string>; notes: string[] }
export interface ReportFilters { project_id: number; store_id: number; item_id: number; category: string; date_from: string; date_to: string; group: string; days: number; subcontractor_id: number }

export const blankFilters = (): ReportFilters => ({ project_id: 0, store_id: 0, item_id: 0, category: '', date_from: '', date_to: '', group: 'work_order', days: 90, subcontractor_id: 0 })
export function reportQuery(f: Partial<ReportFilters>, format = 'json') {
  const p = new URLSearchParams()
  for (const [k, v] of Object.entries(f)) if (v !== '' && v !== 0 && v != null) p.set(k, String(v))
  p.set('format', format)
  return p.toString()
}
export const useCatalogue = () => useQuery({ queryKey: reportKeys.list('catalogue'), staleTime: 3600_000, queryFn: () => storeGet<{ reports: { code: string; title: string }[]; consumption_groups: string[] }>(r, '/catalogue') })
export const useReport = (code: string, f: ReportFilters) =>
  useQuery({ queryKey: reportKeys.list('run', code, f), enabled: !!code, queryFn: () => storeGet<Report>(r, `/run/${code}?${reportQuery(f)}`) })
export const reportFile = (code: string, f: ReportFilters, format: 'xlsx' | 'pdf') => `/api/store/reports/run/${code}?${reportQuery(f, format)}`

export interface Dashboard {
  stock_value: string; by_store: { store_id: number; code: string; name: string; value: string; items: number }[]
  pending_indents: number | null; grns_pending_qc: number | null; in_transit: { lines: number; value: string }
  below_reorder: number; overdue_returnables: number; frozen_stores: { store_id: number; code: string; reason: string; since: string }[]
}
export const useDashboard = () => useQuery({ queryKey: reportKeys.list('dashboard'), queryFn: () => storeGet<Dashboard>(r, '/dashboard') })

export interface Norm { id: number; work_item_code: string; boq_item_id: number | null; boq_item: string; description: string; work_uom: string; item_id: number; item_code: string; item_name: string; base_uom: string; coefficient: string; wastage_pct: string; penal_rate: string | null; is_active: boolean }
export interface NormInput { work_item_code: string; boq_item_id: number | null; description: string; work_uom: string; item_id: number; coefficient: string; wastage_pct: string; penal_rate: string | null; is_active: boolean }
export const useNorms = (q: string) => useQuery({ queryKey: reportKeys.list('norms', q), queryFn: async () => (await storeGet<{ norms: Norm[] }>(r, `/norms?q=${encodeURIComponent(q)}`)).norms })
export const saveNorm = (id: number | null, b: NormInput) => (id ? storePut<Norm>(r, `/norms/${id}`, b) : storePost<Norm>(r, '/norms', b))
export const retireNorm = (id: number) => storeDelete<Norm>(r, `/norms/${id}`)
export const useWorkItems = () => useQuery({ queryKey: reportKeys.list('work-items'), queryFn: async () => (await storeGet<{ items: { boq_item_id: number; code: string; description: string; uom: string }[] }>(r, '/work-items')).items })
export interface ImportRow { row: number; work_item_code: string; item_code: string; coefficient: string; errors: string[]; action: string }
export async function importNorms(file: File, apply: boolean) {
  const form = new FormData()
  form.append('file', file)
  return api<{ applied: boolean; rows: ImportRow[]; summary: { rows: number; ok: number; errors: number } }>(`/api/store/reports/norms/import?apply=${apply}`, { method: 'POST', body: form })
}
export const NORM_TEMPLATE = '/api/store/reports/norms/template.csv'

export const useSubcontractors = () => useQuery({ queryKey: reportKeys.list('subs'), queryFn: async () => (await storeGet<{ subcontractors: { id: number; name: string }[] }>(r, '/subcontractors')).subcontractors })
export const reconciliationPath = (scope: string, id: number, extra = '', format = 'json') => `/api/store/reports/reconciliation?scope=${scope}&scope_id=${id}${extra}&format=${format}`
export const useReconciliation = (scope: string, id: number, extra = '') =>
  useQuery({ queryKey: reportKeys.list('recon', scope, id, extra), enabled: id > 0, queryFn: () => get<Report>(reconciliationPath(scope, id, extra)) })
export const useClientSupply = (projectId: number) =>
  useQuery({ queryKey: reportKeys.list('client-supply', projectId), enabled: projectId > 0, queryFn: () => storeGet<Report>(r, `/client-supply?project_id=${projectId}`) })

// --- the hooks the rest of the ERP shows --------------------------------------------------------------------------
export interface LegacyStatus { store_active: boolean; legacy_movements: boolean; legacy_migrated: boolean; redirect: boolean; legacy_receipt_blocked: boolean }
export const useLegacyStatus = () => useQuery({ queryKey: ['store', 'integration', 'status'], staleTime: 5 * 60_000, queryFn: () => get<LegacyStatus>('/api/store/reports/integration/status') })
export interface PoReceipts { po_id: number; number: string; store_module: boolean; receive_path: string; lines: { po_line_id: number; description: string; item_code: string; uom: string; ordered: string; received: string; accepted: string; rejected: string; pending: string }[] }
export const usePoReceipts = (poId: number | null) => useQuery({ queryKey: ['store', 'integration', 'po', poId], enabled: !!poId, queryFn: () => get<PoReceipts>(`/api/store/reports/integration/po/${poId}`) })
export interface RecoveryDue {
  sub_bill_id: number; number: string; upto: string; material: { issue_date: string; item_code: string; item_name: string; issued: string; returned: string; rate: string; value: string }[]
  material_recoverable: string; material_recovered: string; material_due: string; wastage: Record<string, string>[]; wastage_recoverable: string; wastage_recovered: string
  wastage_due: string; total_due: string; on_this_bill: { id: number; kind: string; amount: string; note: string; by: string; at: string }[]; note: string
}
export const useRecoveryDue = (billId: number) => useQuery({ queryKey: ['store', 'integration', 'sub-bill', billId], enabled: billId > 0, queryFn: () => get<RecoveryDue>(`/api/store/reports/integration/sub-bills/${billId}/recovery`) })
export const recordRecovery = (billId: number, b: { kind: string; amount: string; note: string }) => storePost<RecoveryDue>(r, `/integration/sub-bills/${billId}/recovery`, b)
