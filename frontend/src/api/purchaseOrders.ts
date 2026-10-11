import { useQuery } from '@tanstack/react-query'
import { get, post, put } from '@/lib/api'

export interface PoLine {
  id?: number
  item_code: string
  description: string
  uom: string
  qty: number
  price: number
  tax_rate: string
  received_qty?: number
}

/** An order for goods from a supplier: spend agreed before it is committed. */
export interface PurchaseOrder {
  id: number
  number: string
  supplier_name: string
  job_id: number | null
  job_name: string
  issue_date: string
  needed_by: string
  amount: number
  tax_amount: number
  total: number
  status: string
  approval_status: string
  rejection_reason: string
  notes: string
  reference?: string
  billed_total: number
  billed_count: number
  received_total?: number
  line_items: PoLine[]
}

export interface PoInput {
  supplier_name: string
  amount: number
  tax_amount: number
  total: number
  issue_date: string
  needed_by: string
  notes: string
  job_id: number | null
  status?: string
  line_items: Omit<PoLine, 'id' | 'received_qty'>[]
}

export const poKeys = { all: ['purchase-orders'] as const }
const base = (staff: boolean) => (staff ? '/api/employee/purchase-orders' : '/api/purchase-orders')

export const usePurchaseOrders = (staff: boolean) => useQuery({ queryKey: ['purchase-orders', 'list', staff], queryFn: async () => (await get<{ orders: PurchaseOrder[] }>(base(staff))).orders ?? [] })

export const savePo = (id: number | null, b: PoInput, staff: boolean) => (id ? put<{ message?: string }>(`/api/purchase-orders/${id}`, b) : post<{ message?: string }>(base(staff), b))
export const resendPo = (id: number) => post<{ message?: string }>(`/api/employee/purchase-orders/${id}/submit`)
export const GST_RATES = [0, 5, 12, 18, 28]
