import { useQuery } from '@tanstack/react-query'
import { apiUrl, get } from '@/lib/api'

export type ItemSheetStatus = 'To arrange' | 'Issued past need' | 'Not budgeted' | 'Covered'

/** One BOQ line a material comes from: its quantity, how much of the material one unit takes, and what that makes. */
export interface ItemSheetLine {
  key: string
  boq_line_id: number
  item_no: string
  description: string
  boq_qty: number
  boq_unit: string
  per_unit: number
  budget_unit: string
  wastage_percent: number
  wastage_source: 'STORE_NORM' | 'BUDGETING'
  required: number
  issued: number
}

/** One material of the project: what its BOQ needs (services/item_sheet.py), and what the store and purchase have done about it. */
export interface ItemSheetRow {
  item_id: number | null
  item_code: string
  item_name: string
  uom: string
  in_master: boolean
  required: number
  without_wastage: number
  value: number
  indented: number
  ordered: number
  on_way: number
  issued: number
  at_site: number
  to_arrange: number
  to_arrange_value: number
  status: ItemSheetStatus
  unit_notes: string[]
  lines: ItemSheetLine[]
}

export interface ItemSheet {
  job_id: number
  code: string
  name: string
  boq: boolean
  totals: { items: number; to_arrange: number; over_issued: number; not_in_master: number; not_budgeted: number; value: number; to_arrange_value: number; boq_lines: number; boq_lines_with_materials: number } | null
  rows: ItemSheetRow[]
}

export const useItemSheet = (job: number) =>
  useQuery({ queryKey: ['item-sheet', job], queryFn: () => get<ItemSheet>(`/api/jobs/${job}/item-sheet`), enabled: job > 0, staleTime: 0 })

export const itemSheetFileUrl = (job: number) => apiUrl(`/api/jobs/${job}/item-sheet.xlsx`)

/** The rights that open the Item sheet: HO QS (budget), purchase and the store. */
export const ITEM_SHEET_PERM = 'budget.view|budget.edit|purchase.manage|stores.manage|stores.receive|store.reports.view|store.outward.view'
