import { useQuery } from '@tanstack/react-query'
import { get, put } from '@/lib/api'

export const trackerKeys = { all: ['invoice-tracker'] as const }

export interface TrackerInvoice {
  grn_id: number; grn: string; supplier: string; invoice_number: string; invoice_date: string; received_on: string
  po_number: string; vehicle: string; amount: number; gst: number; freight: number; insurance: number; hamali: number; total: number; trades: string[]; remark: string
  invoice_amount: number | null; difference: number | null
}
export interface SummaryRow { category: string; purchase_amount: number; wo_amount: number; wo_suggested: number; wo_source: '' | 'typed' | 'work orders'; difference: number; remarks: string }
export interface MaterialCell { grn_id: number; qty: number; rate: number; amount: number }
export interface Material {
  key: string; sl: number; item_code: string; description: string; uom: string; cells: MaterialCell[]; total_qty: number; total_amount: number
  total_rate: number; avg_rate: number; working_rate: number | null; working_amount: number | null; on_hand: number; counted: boolean
}
export interface FooterCell { grn_id: number; amount: number; gst: number; total: number; freight: number | null; insurance: number | null; hamali: number | null; invoice_amount: number | null; difference: number | null; whole: boolean; remark: string }
export interface TrackerCategory { name: string; invoice_ids: number[]; materials: Material[]; total: number; footer: FooterCell[]; gst: number; with_gst: number; markup: number; with_markup: number; working_total: number; note: string }
export interface StockItem { item_code: string; item_name: string; uom: string; on_hand: number; counted: boolean }
export interface StockGroup { category: string; items: StockItem[] }
export interface RmcRow {
  line_id: number; n: number; grn_id: number; invoice_date: string; supplier: string; po_number: string; vehicle: string
  invoice_number: string; grade: string; qty: number; rate: number; amount: number; block: string
}
export interface BlockTotal { block: string; loads: number; qty: number; amount: number }
export interface Tracker {
  job_id: number; gst_percent: number; markup_percent: number
  summary: { rows: SummaryRow[]; purchase_amount: number; wo_amount: number; difference: number }
  invoices: TrackerInvoice[]
  categories: TrackerCategory[]
  rmc: { rows: RmcRow[]; blocks: BlockTotal[]; qty: number; amount: number; gst: number; total: number }
  stock: StockGroup[]
  totals: { invoices: number; amount: number; gst: number; freight: number; insurance: number; hamali: number; total: number; unchecked: number; mismatched: number }
}

export const useTracker = (jobId: number, gst: number, markup: number) =>
  useQuery({ queryKey: [...trackerKeys.all, jobId, gst, markup], queryFn: () => get<Tracker>(`/api/invoice-tracker?job_id=${jobId}&gst=${gst}&markup=${markup}`) })

export const trackerExcel = (jobId: number, gst: number, markup: number) => `/api/invoice-tracker/export.xlsx?job_id=${jobId}&gst=${gst}&markup=${markup}`

export interface InvoiceEdit { invoice_date?: string; invoice_amount?: number; clear_amount?: boolean; freight?: number; insurance?: number; hamali?: number; remark?: string }
export const saveInvoice = ({ grnId, ...body }: InvoiceEdit & { grnId: number }) => put<{ ok: boolean }>(`/api/invoice-tracker/invoices/${grnId}`, body)
export const saveBlock = ({ lineId, block }: { lineId: number; block: string }) => put<{ ok: boolean }>(`/api/invoice-tracker/blocks/${lineId}`, { block })
export const saveWorkingRate = (b: { job_id: number; item_key: string; rate: number | null }) => put<{ ok: boolean }>('/api/invoice-tracker/working-rates', b)
export const saveCategory = (b: { job_id: number; category: string; wo_amount?: number; remarks?: string }) => put<{ ok: boolean }>('/api/invoice-tracker/categories', b)
