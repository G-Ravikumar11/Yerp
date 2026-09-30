import { useQuery } from '@tanstack/react-query'
import { del, get, post, put } from '@/lib/api'

/** A bill from a vendor or supplier: money we owe, once it has been checked and accepted. */
export interface SupplierBill {
  id: number
  number: string
  vendor_name: string
  vendor_email: string
  category: string
  issue_date: string
  due_date: string
  amount: number
  tax_amount: number
  total: number
  amount_paid: number
  status: string
  reference: string
  notes: string
  approval_status: string
}

export type BillInput = Pick<SupplierBill, 'number' | 'vendor_name' | 'vendor_email' | 'category' | 'issue_date' | 'due_date' | 'amount' | 'tax_amount' | 'total' | 'reference' | 'notes'>

export const CATEGORIES = ['materials', 'labour', 'equipment', 'services', 'general']

export const billKeys = { all: ['supplier-bills'] as const, list: ['supplier-bills', 'list'] as const }

export const useSupplierBills = () => useQuery({ queryKey: billKeys.list, queryFn: () => get<SupplierBill[]>('/api/bills') })
export const useTaxRates = () => useQuery({ queryKey: ['tax-rates'], queryFn: () => get<{ id: number; percent: number; label: string; is_default: boolean }[]>('/api/tax-rates'), staleTime: 10 * 60_000 })
export const nextBillNumber = async () => (await get<{ number: string }>('/api/next-bill-number')).number

export const createBill = (b: BillInput) => post<{ number: string }>('/api/bills', { ...b, status: 'Draft' })
export const updateBill = (id: number, b: Partial<BillInput> & { status?: string }) => put<{ number: string }>(`/api/bills/${id}`, b)
export const deleteBill = (id: number) => del<{ message?: string }>(`/api/bills/${id}`)
