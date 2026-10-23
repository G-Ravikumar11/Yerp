import { useQuery } from '@tanstack/react-query'
import { storeGet, type CostHead, type DocStatus } from '@/api/store'

export type OutwardKind = 'issue' | 'returns'
export const KINDS: { key: OutwardKind; label: string; plural: string; blurb: string }[] = [
  { key: 'issue', label: 'Issue', plural: 'Issues', blurb: 'Material leaving a store for a project, or handed to a subcontractor.' },
  { key: 'returns', label: 'Return', plural: 'Returns', blurb: 'Issued material coming back to the store, or reported lost or damaged.' },
]
export const kindOf = (key: string | undefined) => KINDS.find((k) => k.key === key)

/** What the outward routes send. Quantities, rates and values are strings. */
export interface IssueLine {
  id: number
  item_id: number
  item_code: string
  item_name: string
  base_uom: string
  entry_uom: string
  entry_qty: string
  qty: string
  boq_item_id: number | null
  boq_item: string
  cost_head: CostHead | null
  chargeable: boolean
  recovery_rate: string
  expected_return_date: string
  returnable: boolean
  outstanding: string | null
  remarks: string
  indent_line_id?: number | null
  recovery_basis?: string
  handling_pct?: string
  batch_no?: string
  resolved_rate?: string | null
}
export interface ReturnLine {
  id: number
  issue_line_id: number
  item_id: number
  item_code: string
  item_name: string
  base_uom: string
  entry_uom: string
  qty_returned: string
  qty_lost: string
  reason: string
  condition?: 'GOOD' | 'DAMAGED'
  bin_id?: number | null
  bin?: string
}
export interface HistoryRow { action: string; from: string; to: string; by: string; at: string; note: string }
export interface Doc {
  kind: OutwardKind
  id: number
  number: string
  status: DocStatus
  store_id: number
  store_code: string
  store_name: string
  date: string
  remarks: string
  cancel_reason: string
  created_by: string
  created_at: string
  posted_at: string
  line_count: number
  // issue
  issue_type?: 'SITE' | 'SUBCONTRACTOR'
  project_id?: number
  project?: string
  work_order_id?: number | null
  work_order?: string
  subcontractor_id?: number | null
  holder_type?: string
  holder_id?: number | null
  holder_name?: string
  purpose?: string
  direct?: boolean
  indent_id?: number | null
  indent_number?: string
  subcontract_order_id?: number | null
  subcontract_order?: string
  received_by_type?: string
  received_by_employee_id?: number | null
  received_by_name?: string
  warnings?: string[]
  gate_passes?: { id: number; number: string; status: string }[]
  // return
  issue_id?: number
  issue_number?: string
  lines?: (IssueLine & ReturnLine)[]
  history?: HistoryRow[]
}
export interface OutstandingLines {
  issue: { id: number; number: string; status: DocStatus; store_id: number; holder_name: string }
  lines: { issue_line_id: number; item_id: number; item_code: string; item_name: string; base_uom: string; issued: string; outstanding: string; returnable: boolean }[]
}
export interface Returnable {
  issue_line_id: number
  issue_id: number
  issue_number: string
  issue_date: string
  store_id: number
  project_id: number
  item_code: string
  item_name: string
  holder_type: string
  holder_name: string
  qty_outstanding: string
  expected_return_date: string
  overdue_days: number
}
export interface Writeoff { id: number; store_code: string; item_code: string; item_name: string; qty: string; reason: string; status: string; created_at: string; closed_ref: string }
export interface Recovery {
  subcontractor: { id: number; name: string }
  total_recovery: string
  items: { issue_line_id: number; issue_date: string; item_code: string; item_name: string; qty_issued: string; qty_returned: string; chargeable: boolean; recovery_rate: string; recovery_value: string }[]
}

export const qs = (params: Record<string, string | number | boolean | null | undefined>) => {
  const p = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) if (v !== '' && v !== 0 && v !== false && v != null) p.set(k, String(v))
  const s = p.toString()
  return s ? `?${s}` : ''
}

export const outwardKeys = { all: ['store', 'outward'] as const }
export const useDocs = (kind: OutwardKind, f: { status: string; store_id: number; q: string }) =>
  useQuery({ queryKey: ['store', 'outward', 'list', kind, f], queryFn: () => storeGet<{ total: number; items: Doc[] }>('outward', `/${kind}${qs({ ...f, limit: 200 })}`) })
export const useDoc = (kind: OutwardKind, id: number) =>
  useQuery({ queryKey: ['store', 'outward', 'doc', kind, id], enabled: id > 0, queryFn: () => storeGet<Doc>('outward', `/${kind}/${id}`) })
export const useOutstanding = (issueId: number) =>
  useQuery({ queryKey: ['store', 'outward', 'issue-lines', issueId], enabled: issueId > 0, queryFn: () => storeGet<OutstandingLines>('outward', `/issue-lines/${issueId}`) })
export const useReturnables = (f: { project_id: number; store_id: number; overdue_only: boolean }) =>
  useQuery({ queryKey: ['store', 'outward', 'returnables', f], queryFn: () => storeGet<{ total: number; overdue: number; items: Returnable[] }>('outward', `/returnables${qs(f)}`) })
export const useWriteoffs = (status: string) =>
  useQuery({ queryKey: ['store', 'outward', 'writeoffs', status], queryFn: async () => (await storeGet<{ items: Writeoff[] }>('outward', `/writeoffs${qs({ status })}`)).items })
export const useRecovery = (id: number, upto: string) =>
  useQuery({ queryKey: ['store', 'outward', 'recovery', id, upto], enabled: id > 0, queryFn: () => storeGet<Recovery>('outward', `/subcontractors/${id}/recovery${qs({ upto })}`) })
export const useBoqItems = (projectId: number) =>
  useQuery({ queryKey: ['store', 'outward', 'boq', projectId], enabled: projectId > 0, queryFn: async () => (await storeGet<{ items: { id: number; item_no: string; description: string; uom: string }[] }>('outward', `/pick/boq-items?project_id=${projectId}`)).items })
export const useWorkOrders = (projectId: number) =>
  useQuery({ queryKey: ['store', 'outward', 'wo', projectId], enabled: projectId > 0, queryFn: async () => (await storeGet<{ items: { id: number; number: string; status: string }[] }>('outward', `/pick/work-orders?project_id=${projectId}`)).items })
export const useSubcontractors = () =>
  useQuery({ queryKey: ['store', 'outward', 'subs'], queryFn: async () => (await storeGet<{ items: { id: number; code: string; name: string }[] }>('outward', '/pick/subcontractors')).items })
export const useEmployees = () =>
  useQuery({ queryKey: ['store', 'outward', 'emps'], queryFn: async () => (await storeGet<{ items: { id: number; name: string; job_title: string }[] }>('outward', '/pick/employees')).items })

export const num = (v: string | undefined | null) => Number(v ?? 0).toLocaleString('en-IN', { maximumFractionDigits: 3 })
export const money = (v: string | undefined) => Number(v ?? 0).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
export const dmy = (iso: string) => (iso ? new Date(iso.slice(0, 10) + 'T00:00').toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' }) : '-')
/** Today on this device's clock - the UTC date is still yesterday for the first hours of an Indian morning. */
export { today } from '@/lib/format'
export const headLabel = (h: string | null) => (h ? h.replace(/_/g, ' ').toLowerCase().replace(/^\w/, (c) => c.toUpperCase()) : '')

/** Indents: a site engineer's request for material, approved by the project manager, then filled by issues. */
export interface IndentLine { id: number; item_id: number; item_code: string; item_name: string; base_uom: string; entry_uom: string; entry_qty: string; qty: string; approved_qty: string | null; fulfilled: string; pending: string | null; purpose: string; reason?: string; substitute_for_line_id?: number | null }
export interface Indent {
  id: number; number: string; status: 'DRAFT' | 'SUBMITTED' | 'OPEN' | 'PARTIAL' | 'CLOSED' | 'CANCELLED'; store_id: number; store_code: string; store_name: string; date: string; required_by: string
  project_id: number; project: string; work_order_id: number | null; work_order: string; boq_item_id: number | null; boq_item: string; activity: string; remarks: string; requested_by: string
  approved_by: string; approved_at: string; approver_remarks: string; cancel_reason: string; short_closed: boolean; line_count: number; fulfilled_pct: number; overdue: boolean
  lines?: IndentLine[]; history?: HistoryRow[]; issues?: { id: number; number: string; status: string }[]
}
export interface IndentPending {
  indent: { id: number; number: string; status: string; store_id: number; project_id: number; work_order_id: number | null; boq_item_id: number | null; boq_item: string }
  lines: { indent_line_id: number; item_id: number; item_code: string; item_name: string; base_uom: string; approved: string; pending: string }[]
}
export interface GatePass {
  id: number; number: string; status: 'ISSUED' | 'CLOSED' | 'CANCELLED'; store_id: number; store_code: string; date: string; issue_id: number; issue_number: string; vehicle_no: string; driver_name: string
  destination: string; purpose: string; returnable: boolean; expected_return_date: string; authorised_by: string; remarks: string; cancel_reason: string; overdue_days: number; line_count: number
  received_by: string; created_by: string; lines?: { id: number; item_code: string; item_name: string; base_uom: string; qty: string }[]; history?: HistoryRow[]
}
export interface Recovery2 {
  id: number; source: 'ISSUE' | 'CONVERSION'; issue_number: string; holder_type: string; holder_name: string; item_code: string; item_name: string; qty: string; qty_returned: string; basis: string
  base_rate: string; handling_pct: string; recovery_rate: string; amount: string; status: string
}
export interface OutwardSettings { subcon_handling_pct: string; default_recovery_basis: 'CONTRACT_RATE' | 'AVERAGE_COST' }

export const useIndents = (f: { status: string; store_id: number; project_id: number; q: string }) =>
  useQuery({ queryKey: ['store', 'outward', 'indents', f], queryFn: () => storeGet<{ total: number; items: Indent[] }>('outward', `/indent${qs({ ...f, limit: 200 })}`) })
export const useIndent = (id: number) => useQuery({ queryKey: ['store', 'outward', 'indent', id], enabled: id > 0, queryFn: () => storeGet<Indent>('outward', `/indent/${id}`) })
export const useIndentPending = (id: number) => useQuery({ queryKey: ['store', 'outward', 'indent-lines', id], enabled: id > 0, queryFn: () => storeGet<IndentPending>('outward', `/indent-lines/${id}`) })
export const useOpenIndents = () => useQuery({ queryKey: ['store', 'outward', 'open-indents'], queryFn: async () => [...(await storeGet<{ items: Indent[] }>('outward', '/indent?status=OPEN&limit=200')).items, ...(await storeGet<{ items: Indent[] }>('outward', '/indent?status=PARTIAL&limit=200')).items] })
export const useGatePasses = (f: { status: string; store_id: number; q: string }) =>
  useQuery({ queryKey: ['store', 'outward', 'gate-passes', f], queryFn: () => storeGet<{ total: number; items: GatePass[] }>('outward', `/gate-pass${qs({ ...f, limit: 200 })}`) })
export const useGatePass = (id: number) => useQuery({ queryKey: ['store', 'outward', 'gate-pass', id], enabled: id > 0, queryFn: () => storeGet<GatePass>('outward', `/gate-pass/${id}`) })
export const useSubOrders = (subcontractorId: number, projectId: number) =>
  useQuery({ queryKey: ['store', 'outward', 'sub-orders', subcontractorId, projectId], enabled: subcontractorId > 0, queryFn: async () => (await storeGet<{ items: { id: number; number: string; subject: string; status: string }[] }>('outward', `/pick/subcontract-orders${qs({ subcontractor_id: subcontractorId, project_id: projectId })}`)).items })
export const useBins = (storeId: number) =>
  useQuery({ queryKey: ['store', 'outward', 'bins', storeId], enabled: storeId > 0, queryFn: async () => (await storeGet<{ items: { id: number; code: string; description: string }[] }>('outward', `/pick/bins?store_id=${storeId}`)).items })
export const useRecoveries = (status: string) =>
  useQuery({ queryKey: ['store', 'outward', 'recoveries', status], queryFn: () => storeGet<{ total_amount: string; items: Recovery2[] }>('outward', `/recoveries${qs({ status })}`) })
export const useOutwardSettings = () => useQuery({ queryKey: ['store', 'outward', 'settings'], queryFn: () => storeGet<OutwardSettings>('outward', '/settings') })

/** What is left of each batch of an item in a store, oldest first (worked out first in, first out), with its shelf life. */
export interface Batch { batch_no: string; source: string; received_on: string; manufacturing_date: string; expiry_date: string; qty: string; state: '' | 'OK' | 'NEAR' | 'EXPIRED'; recommended: boolean }
export const batchesKey = (storeId: number, itemId: number, on: string) => ['store', 'outward', 'batches', storeId, itemId, on] as const
export const useBatches = (storeId: number, itemId: number, on: string) =>
  useQuery({ queryKey: batchesKey(storeId, itemId, on), enabled: storeId > 0 && itemId > 0, queryFn: async () => (await storeGet<{ batches: Batch[] }>('outward', `/batches${qs({ store_id: storeId, item_id: itemId, on })}`)).batches })
