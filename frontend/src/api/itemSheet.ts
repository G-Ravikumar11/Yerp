import { useQuery } from '@tanstack/react-query'
import { api, apiUrl, get, post, put } from '@/lib/api'
import type { StoreItemOption } from '@/api/store'

export type ItemSheetStatus = 'DRAFT' | 'SUBMITTED' | 'APPROVED'

/** A store material one BOQ line needs, with what purchase and the store have done about it for that line (base unit). */
export interface SheetMaterial {
  id: number
  boq_key: string
  item_id: number
  item_code: string
  item_name: string
  hsn: string
  unit: string
  qty: number
  remarks: string
  ordered: number
  awaiting: number
  received: number
  indented: number
  issued: number
}

/** A line of the project's BOQ as it stands, and the materials under it. */
export interface SheetBoqLine {
  key: string
  line_id: number
  item_no: string
  description: string
  unit: string
  qty: number
  boq_item_code: string
  materials: SheetMaterial[]
}

export interface SheetGroup { code: string; lines: SheetBoqLine[] }

/** One item over the whole project: needed on the sheet, and every figure beside it. */
export interface SheetTotal {
  item_id: number
  item_code: string
  item_name: string
  hsn: string
  unit: string
  on_sheet: boolean
  required: number
  approved_qty: number | null
  ordered: number
  awaiting: number
  received: number
  indented: number
  issued: number
  at_site: number
  to_order: number
  to_receive: number
}

export interface SheetOrderLine {
  po_line_id: number
  item_id: number | null
  item_code: string
  item_name: string
  boq_key: string
  unit: string
  po_qty: number
  po_uom: string
  price: number
  ordered: number
  received: number
  pending: number
}
export interface SheetOrder { id: number; number: string; supplier: string; status: string; date: string; total: number; lines: SheetOrderLine[]; receivable: boolean }
export interface SheetReceipt { id: number; number: string; status: string; date: string; po_id: number | null; po_number: string; supplier: string; store_code: string }
export interface SheetIndent { id: number; number: string; status: string; date: string; store_id: number; store_code: string; boq_key: string; boq_item: string; activity: string; requested_by: string }
export interface SheetIssue { id: number; number: string; status: string; date: string; store_code: string; indent_id: number | null; indent_number: string; received_by: string }
export interface SheetStore { id: number; code: string; name: string; type: string; this_project: boolean }

export interface ItemSheet {
  job_id: number
  code: string
  name: string
  exists: boolean
  status: ItemSheetStatus | null
  has_boq: boolean
  group_codes: string[]
  groups: SheetGroup[]
  /** Materials under BOQ lines the BOQ no longer has. */
  orphans: SheetMaterial[]
  material_count: number
  item_count: number
  approved: boolean
  changed_since_approval: boolean
  approved_by: string
  approved_at: string
  submitted_by: string
  submitted_at: string
  returned_note: string
  updated_by: string
  updated_at: string
  totals: SheetTotal[]
  orders: SheetOrder[]
  receipts: SheetReceipt[]
  indents: SheetIndent[]
  issues: SheetIssue[]
  stores: SheetStore[]
  units: string[]
  is_master: boolean
}

export interface ItemSheetSummary { job_id: number; code: string; name: string; status: ItemSheetStatus | null; approved: boolean; materials: number; updated_at: string }

export interface SheetMaterialIn { boq_key: string; item_code: string; qty: number | null; remarks: string }

const BASE = '/api/store/item-sheet'
export const itemSheetKeys = { all: ['item-sheet'] as const, one: (job: number) => ['item-sheet', job] as const }

export const useItemSheets = () => useQuery({ queryKey: itemSheetKeys.all, queryFn: () => get<{ items: ItemSheetSummary[]; is_master: boolean }>(BASE) })
export const useItemSheet = (job: number) =>
  useQuery({ queryKey: itemSheetKeys.one(job), enabled: job > 0, queryFn: () => get<ItemSheet>(`${BASE}/${job}`) })

export const saveItemSheet = (job: number, materials: SheetMaterialIn[], dropOrphans = false) =>
  put<ItemSheet>(`${BASE}/${job}`, { materials, drop_orphans: dropOrphans })
export function uploadItemSheet(job: number, file: File) {
  const form = new FormData()
  form.append('file', file)
  return api<ItemSheet>(`${BASE}/${job}/upload`, { method: 'POST', body: form })
}
export const submitItemSheet = (job: number) => post<ItemSheet>(`${BASE}/${job}/submit`)
export const approveItemSheet = (job: number) => post<ItemSheet>(`${BASE}/${job}/approve`)
export const sendBackItemSheet = (job: number, note: string) => post<ItemSheet>(`${BASE}/${job}/send-back`, { note })
export const itemSheetFileUrl = (job: number) => apiUrl(`${BASE}/${job}/template.xlsx`)
export const addSheetItem = (job: number, b: { item_name: string; units_of_measure: string; hsn_code: string; make: string }) =>
  post<{ item: StoreItemOption & { hsn: string }; message: string }>(`${BASE}/${job}/items`, b)

// --- the usual documents, raised from the sheet's screen ------------------------------------------------------------

export interface PoLineIn { description: string; item_code: string; uom: string; qty: number; price: number; tax_rate: string; boq_key: string }
export const raisePurchaseOrder = (b: { supplier_name: string; job_id: number; needed_by: string; notes: string; category: string; budget_reason: string; line_items: PoLineIn[] }) =>
  post<{ id?: number; number?: string; order?: { id: number; number: string }; message?: string }>('/api/purchase-orders', b)

export const createGrn = (b: { store_id: number; grn_date: string; po_id: number; project_id: number; challan_no: string; vehicle_no: string; lines: { po_line_id: number; qty: string; uom: string }[] }) =>
  post<{ id: number; number: string }>('/api/store/inward/grn', b)
export const createIndent = (b: { store_id: number; project_id: number; boq_item_id: number; activity: string; required_by: string; lines: { item_id: number; qty: string; uom: string }[] }) =>
  post<{ id: number; number: string }>('/api/store/outward/indent', b)
export const createIssue = (b: { store_id: number; issue_date: string; project_id: number; indent_id: number; received_by_type: string; received_by_name: string;
  lines: { item_id: number; qty: string; uom: string; indent_line_id: number }[] }) => post<{ id: number; number: string }>('/api/store/outward/issue', b)

export interface PendingIndentLine { indent_line_id: number; item_id: number; item_code: string; item_name: string; base_uom: string; approved: string; pending: string }
export const pendingIndentLines = (indentId: number) =>
  get<{ indent: { id: number; number: string; store_id: number }; lines: PendingIndentLine[] }>(`/api/store/outward/indent-lines/${indentId}`)

/** One step of a store document: submit, approve or post (indents: submit or approve). */
export function stepDocument(kind: 'grn' | 'indent' | 'issue', id: number, action: 'submit' | 'approve' | 'post') {
  const area = kind === 'grn' ? 'inward' : 'outward'
  return post<{ number: string; status: string }>(`/api/store/${area}/${kind}/${id}/${action}`, kind === 'indent' && action === 'approve' ? {} : undefined)
}

/** Who sees the sheet, and who makes it (the storekeeper). Approving the sheet is the Master's alone. */
export const ITEM_SHEET_VIEW = 'store.outward.view|store.inward.view|store.admin'
export const ITEM_SHEET_EDIT = 'store.inward.post|store.outward.post|store.admin'
