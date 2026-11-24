import { useQuery } from '@tanstack/react-query'
import { api, apiUrl, get, post, put } from '@/lib/api'

export type ItemSheetStatus = 'DRAFT' | 'SUBMITTED' | 'APPROVED'

/** A material on the project's Item sheet, under one of its BOQ's group codes. HSN and unit come from the item master. */
export interface ItemSheetLine {
  id: number
  group_code: string
  item_id: number
  item_code: string
  item_name: string
  hsn: string
  unit: string
  qty: number
  remarks: string
}

/** By the approved sheet: how much of an item it allows, and what the project's live indents have asked for. */
export interface ItemSheetUsage {
  item_id: number
  item_code: string
  item_name: string
  unit: string
  sheet_qty: number
  indented: number
  on_sheet: boolean
}

export interface ItemSheet {
  job_id: number
  code: string
  name: string
  exists: boolean
  status: ItemSheetStatus | null
  /** The group codes on the project's BOQ: the only ones a line can be under. */
  groups: string[]
  lines: ItemSheetLine[]
  approved: boolean
  changed_since_approval: boolean
  approved_by: string
  approved_at: string
  submitted_by: string
  submitted_at: string
  returned_note: string
  updated_by: string
  updated_at: string
  usage: ItemSheetUsage[]
  item_count: number
  is_master: boolean
}

export interface ItemSheetSummary { job_id: number; code: string; name: string; status: ItemSheetStatus | null; approved: boolean; lines: number; updated_at: string }

export interface ItemSheetLineIn { group_code: string; item_code: string; qty: number | null; remarks: string }

const BASE = '/api/store/item-sheet'
export const itemSheetKeys = { all: ['item-sheet'] as const, one: (job: number) => ['item-sheet', job] as const }

export const useItemSheets = () => useQuery({ queryKey: itemSheetKeys.all, queryFn: () => get<{ items: ItemSheetSummary[]; is_master: boolean }>(BASE) })
export const useItemSheet = (job: number) =>
  useQuery({ queryKey: itemSheetKeys.one(job), enabled: job > 0, queryFn: () => get<ItemSheet>(`${BASE}/${job}`) })

export const saveItemSheet = (job: number, lines: ItemSheetLineIn[]) => put<ItemSheet>(`${BASE}/${job}`, { lines })
export function uploadItemSheet(job: number, file: File) {
  const form = new FormData()
  form.append('file', file)
  return api<ItemSheet>(`${BASE}/${job}/upload`, { method: 'POST', body: form })
}
export const submitItemSheet = (job: number) => post<ItemSheet>(`${BASE}/${job}/submit`)
export const approveItemSheet = (job: number) => post<ItemSheet>(`${BASE}/${job}/approve`)
export const sendBackItemSheet = (job: number, note: string) => post<ItemSheet>(`${BASE}/${job}/send-back`, { note })
export const itemSheetFileUrl = (job: number) => apiUrl(`${BASE}/${job}/template.xlsx`)

/** Who sees the sheet, and who makes it (the storekeeper). Approving is the Master's alone. */
export const ITEM_SHEET_VIEW = 'store.outward.view|store.inward.view|store.admin'
export const ITEM_SHEET_EDIT = ['store.inward.post', 'store.outward.post', 'store.admin']
