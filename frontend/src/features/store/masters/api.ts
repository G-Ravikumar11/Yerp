import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { storeDelete, storeGet, storeKeys, storePost, storePut, type DocStatus, type StoreType } from '@/api/store'

/** Store > Masters: stores, bins, people, item settings, units and opening stock. Quantities and money are strings. */

export const mastersKeys = {
  all: storeKeys.slice('masters'),
  stores: (inactive: boolean) => [...storeKeys.slice('masters'), 'stores', inactive] as const,
  bins: (storeId: number) => [...storeKeys.slice('masters'), 'bins', storeId] as const,
  users: (storeId: number) => [...storeKeys.slice('masters'), 'users', storeId] as const,
  employees: (q: string) => [...storeKeys.slice('masters'), 'employees', q] as const,
  items: (q: string, configured: string) => [...storeKeys.slice('masters'), 'items', q, configured] as const,
  item: (id: number) => [...storeKeys.slice('masters'), 'item', id] as const,
  openings: (storeId: number, status: string) => [...storeKeys.slice('masters'), 'openings', storeId, status] as const,
  opening: (id: number) => [...storeKeys.slice('masters'), 'opening', id] as const,
}

export interface StoreRow {
  id: number; code: string; name: string; type: StoreType; project_id: number | null; project: string; address: string
  is_active: boolean; accessible: boolean; frozen: boolean; bins: number; users: number
}
export interface BinRow { id: number; store_id: number; code: string; description: string; is_active: boolean }
export interface AssignmentRow {
  id: number; store_id: number; employee_id: number; name: string; email: string; job_title: string; role: string
  is_active: boolean; assigned_at: string
}
export interface EmployeeOption { id: number; name: string; email: string; job_title: string }
export interface UomRow { id: number | null; code: string; to_base_factor: string; base: boolean }
export interface ItemSettings {
  category: string; base_uom: string; reorder_level: string; min_qty: string; max_qty: string; qc_required: boolean
  over_receipt_tolerance_pct: string; is_batch_tracked: boolean
}
export interface ItemRow {
  id: number; code: string; name: string; item_category: string; item_uom: string; configured: boolean
  settings: ItemSettings | null; base_uom: string; uoms: UomRow[]; has_stock_history: boolean
}
export interface TrailRow { from: string | null; to: string; by: string; at: string; note: string }
export interface OpeningLine {
  id?: number; line_no: number; item_id: number; item_code: string; item_name: string; qty: string; uom: string; rate: string
  base_qty: string; base_uom: string; base_rate: string; value: string; bin_id: number | null; bin_code: string; remarks: string
}
export interface Opening {
  id: number; number: string; store_id: number; store_code: string; store_name: string; opening_date: string; status: DocStatus
  source: 'MANUAL' | 'CSV' | 'LEGACY'; remarks: string; created_by: string; created_at: string; posted_at: string
  cancel_reason: string; lines_count: number; total_value: string; lines?: OpeningLine[]; trail?: TrailRow[]
}
export interface OpeningLineInput { item_id: number; qty: string; uom: string; rate: string; bin_id: number | null; remarks: string }
export interface PreviewRow extends Partial<OpeningLine> { line_no: number; item_code: string; errors: string[] }
export interface Preview { rows: PreviewRow[]; summary: { rows: number; ok: number; errors: number; total_value: string } }

const m = 'masters' as const

export const useStores = (inactive = false) =>
  useQuery({ queryKey: mastersKeys.stores(inactive), queryFn: async () => (await storeGet<{ stores: StoreRow[] }>(m, `/stores${inactive ? '?include_inactive=true' : ''}`)).stores })
export const saveStore = (id: number | null, body: Partial<StoreRow>) => (id ? storePut<StoreRow>(m, `/stores/${id}`, body) : storePost<StoreRow>(m, '/stores', body))

export const useBins = (storeId: number) =>
  useQuery({ queryKey: mastersKeys.bins(storeId), enabled: storeId > 0, queryFn: async () => (await storeGet<{ bins: BinRow[] }>(m, `/stores/${storeId}/bins`)).bins })
export const addBin = (storeId: number, body: { code: string; description: string }) => storePost<BinRow>(m, `/stores/${storeId}/bins`, body)
export const updateBin = (id: number, body: Partial<BinRow>) => storePut<BinRow>(m, `/bins/${id}`, body)

export const useAssignments = (storeId: number) =>
  useQuery({ queryKey: mastersKeys.users(storeId), enabled: storeId > 0, queryFn: () => storeGet<{ users: AssignmentRow[]; roles: string[] }>(m, `/stores/${storeId}/users`) })
export const assign = (storeId: number, body: { employee_id: number; role: string }) => storePost<AssignmentRow>(m, `/stores/${storeId}/users`, body)
export const updateAssignment = (id: number, body: { role?: string; is_active?: boolean }) => storePut<AssignmentRow>(m, `/assignments/${id}`, body)
export const useEmployees = (q: string, enabled = true) =>
  useQuery({ queryKey: mastersKeys.employees(q), enabled, queryFn: async () => (await storeGet<{ employees: EmployeeOption[] }>(m, `/employees?q=${encodeURIComponent(q)}`)).employees })

export const useMasterItems = (q: string, configured = '') =>
  useQuery({ queryKey: mastersKeys.items(q, configured), queryFn: async () => (await storeGet<{ items: ItemRow[] }>(m, `/items?q=${encodeURIComponent(q)}${configured ? `&configured=${configured}` : ''}`)).items })
export const useMasterItem = (id: number | null) =>
  useQuery({ queryKey: mastersKeys.item(id ?? 0), enabled: !!id, queryFn: () => storeGet<ItemRow>(m, `/items/${id}`) })
export const saveSettings = (itemId: number, body: ItemSettings) => storePut<ItemRow>(m, `/items/${itemId}/settings`, body)
type Uoms = { item_id: number; base_uom: string; uoms: UomRow[] }
export const addUom = (itemId: number, body: { from_uom: string; to_base_factor: string }) => storePost<Uoms>(m, `/items/${itemId}/uoms`, body)
export const addPreset = (itemId: number, body: { kind: 'CEMENT' | 'STEEL' | 'VOLUME'; dia_mm?: string; bar_length_m?: string }) =>
  storePost<Uoms>(m, `/items/${itemId}/uoms/preset`, body)
export const updateUom = (id: number, to_base_factor: string) => storePut<Uoms>(m, `/uoms/${id}`, { to_base_factor })
export const deleteUom = (id: number) => storeDelete<Uoms>(m, `/uoms/${id}`)

export const useOpenings = (storeId = 0, status = '') =>
  useQuery({ queryKey: mastersKeys.openings(storeId, status), queryFn: async () => (await storeGet<{ openings: Opening[] }>(m, `/opening?store_id=${storeId}&status=${status}`)).openings })
export const useOpening = (id: number) => useQuery({ queryKey: mastersKeys.opening(id), enabled: id > 0, queryFn: () => storeGet<Opening>(m, `/opening/${id}`) })
export const createOpening = (body: { store_id: number; opening_date: string; remarks: string; lines: OpeningLineInput[] }) => storePost<Opening>(m, '/opening', body)
export const updateOpening = (id: number, body: { opening_date?: string; remarks?: string; lines?: OpeningLineInput[] }) => storePut<Opening>(m, `/opening/${id}`, body)
export const openingAction = (id: number, action: string, reason?: string) => storePost<Opening>(m, `/opening/${id}/${action}`, { reason: reason ?? '' })
export const openingPdf = (id: number) => `/api/store/masters/opening/${id}/document.pdf`
export const OPENING_TEMPLATE = '/api/store/masters/opening/template.csv'

function sheetForm(file: File, storeId: number, openingDate: string, extra: Record<string, string> = {}) {
  const form = new FormData()
  form.append('file', file)
  form.append('store_id', String(storeId))
  form.append('opening_date', openingDate)
  for (const [k, v] of Object.entries(extra)) form.append(k, v)
  return form
}
export const previewSheet = (file: File, storeId: number, openingDate: string) =>
  api<Preview>('/api/store/masters/opening/import/preview', { method: 'POST', body: sheetForm(file, storeId, openingDate) })
export const importSheet = (file: File, storeId: number, openingDate: string, remarks: string, skipErrors: boolean) =>
  api<{ opening: Opening; summary: Preview['summary'] }>('/api/store/masters/opening/import', {
    method: 'POST',
    body: sheetForm(file, storeId, openingDate, { remarks, skip_errors: String(skipErrors) }),
  })

export const ROLE_LABEL: Record<string, string> = {
  STOREKEEPER: 'Store keeper', SITE_ENGINEER: 'Site engineer', STORE_INCHARGE: 'Store in-charge', APPROVER: 'Approver', VIEWER: 'Viewer',
}
export const STORE_TYPE_LABEL: Record<StoreType, string> = { CENTRAL: 'Central', SITE: 'Site', YARD: 'Yard' }
