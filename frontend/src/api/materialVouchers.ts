import { useQuery } from '@tanstack/react-query'
import { del, get, post } from '@/lib/api'

/** Store > Material Issue Voucher: the printed voucher, field for field, in Sl. No. order. */
export const voucherKeys = { all: ['material-vouchers'] as const }

export interface VoucherLine { description: string; uom: string; issued_qty: number; returned_qty: number; remarks: string }
export interface Voucher {
  id: number
  job_id: number
  project: string
  number: number
  voucher_on: string
  indented_by: string
  issued_by: string
  issued_for: string
  lines: VoucherLine[]
  recorded_by: string
  total_issued: number
  total_returned: number
}
export interface VoucherInput { job_id: number; voucher_on: string; indented_by: string; issued_by: string; issued_for: string; lines: VoucherLine[] }

export const useVouchers = (job: number) =>
  useQuery({ queryKey: ['material-vouchers', job], queryFn: () => get<{ vouchers: Voucher[]; summary: { vouchers: number; lines: number } }>(`/api/material-vouchers${job ? `?job_id=${job}` : ''}`) })
export const addVoucher = (b: VoucherInput) => post<{ voucher: Voucher; message: string }>('/api/material-vouchers', b)
export const removeVoucher = (id: number) => del<{ message: string }>(`/api/material-vouchers/${id}`)
export const voucherPdf = (id: number) => `/api/material-vouchers/${id}/document.pdf`
export const voucherRegister = (job: number) => `/api/material-vouchers.xlsx${job ? `?job_id=${job}` : ''}`
