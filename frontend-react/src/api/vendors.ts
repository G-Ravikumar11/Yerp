import { useQuery } from '@tanstack/react-query'
import { api, get, post, put } from '@/lib/api'

export type Registration = 'APPROVED' | 'PENDING' | 'REJECTED'

/** The documents the registration form asks for, in its order. */
export const VENDOR_DOCS: { key: string; label: string }[] = [
  { key: 'gst', label: 'A) GST Certificate' },
  { key: 'pan', label: 'B) PAN Card' },
  { key: 'aadhaar', label: 'C) Aadhar Card' },
  { key: 'photos', label: 'D) PassPort Size Photos 2Nos' },
  { key: 'cheque', label: 'E) Cancelled Cheque' },
  { key: 'esi_pf', label: 'F) ESI & PF Reg (if any)' },
]

export interface Vendor {
  id: number
  company_name: string
  vendor_code: string
  contact_person: string
  email: string
  phone_number: string
  pan: string
  gst_number: string
  bank_name: string
  bank_account: string
  bank_ifsc: string
  address: string
  registered_project: string
  joining_date: string
  pin_code: string
  city: string
  state: string
  nature_of_work: string
  entity_type: string
  aadhaar: string
  bank_branch: string
  documents: string[]
  /** Which documents have a file on record, by key - the file's name. Not the file. */
  document_files: Record<string, string>
  declaration_signed: boolean
  registration_status: Registration
  registered_by_name: string
  approved_by_name: string
  approved_at: string
  rejection_reason: string
  created_at: string
  is_active: boolean
}

export type VendorInput = Partial<Omit<Vendor, 'id' | 'document_files' | 'registration_status'>> & {
  company_name: string
  /** Files newly chosen: key -> { name, data (a data URL) }. Only what changed is sent. */
  document_files?: Record<string, { name: string; data: string } | null>
}

export interface VendorList {
  contractors: Vendor[]
  summary: { registered: number; pending: number; sent_back: number }
}

export const vendorKeys = { all: ['vendors'] as const, list: (status: string, q: string) => ['vendors', 'list', status, q] as const }

export function useVendors(status: string, q: string) {
  return useQuery({
    queryKey: vendorKeys.list(status, q),
    queryFn: () => get<VendorList>(`/api/wo/contractors?q=${encodeURIComponent(q)}&status=${encodeURIComponent(status)}`),
    placeholderData: (prev) => prev,
  })
}

export const createVendor = (v: VendorInput) => post<{ id: number; vendor_code: string; message: string }>('/api/wo/contractors', v)
export const updateVendor = (id: number, v: VendorInput) => put<{ message: string }>(`/api/wo/contractors/${id}`, v)
export const decideVendor = (id: number, decision: 'approve' | 'reject', comments?: string) => post<{ message: string }>(`/api/wo/contractors/${id}/${decision}`, { comments: comments ?? '' })

export interface VendorImport {
  message: string
  skipped?: string[]
  warnings?: string[]
}

export function importVendors(file: File) {
  const form = new FormData()
  form.append('file', file)
  return api<VendorImport>('/api/wo/contractors/import', { method: 'POST', body: form })
}
