import { useQuery } from '@tanstack/react-query'
import { get, post, put } from '@/lib/api'

export const ewKeys = { all: ['eway'] as const }

export interface Place { key: string; name: string; gstin: string; address: string; pincode: string; state: string; job_id: number | null }
export interface EwayMeta { places: Place[]; sub_types: Record<string, string>; doc_types: Record<string, string>; modes: Record<string, string>; threshold: number }
export interface Party { name: string; address: string; pincode: string; state_name: string }
export interface EwayLine { item_code?: string; product_name: string; hsn: string; qty: number; unit: string; taxable: number; tax_rate: number }
export interface Eway {
  id: number
  number: string
  source_ref: string
  status: string
  expired: boolean
  from: Party
  to: Party
  distance_km: number
  total_value: number
  taxable_value: number
  igst: number
  cgst: number
  sgst: number
  vehicle_no: string
  ewb_no: string
  ewb_date: string
  valid_upto: string
  doc_type: string
  doc_no: string
  doc_date: string
  sub_type: string
  trans_mode: string
  transporter_id: string
  lines: EwayLine[]
  problems: string[]
  vehicle_history: string[]
  cancel_reason: string
}
export interface Uncovered { number: string; moved_on: string; from_store: string; to_store: string; value: number }

export const useEwayMeta = () => useQuery({ queryKey: ['eway', 'meta'], staleTime: 10 * 60_000, queryFn: () => get<EwayMeta>('/api/eway-places') })
export const useEways = () => useQuery({ queryKey: ['eway', 'list'], queryFn: () => get<{ eway_bills: Eway[]; uncovered_transfers: Uncovered[]; summary: { uncovered: number; drafts: number; live: number; expired: number } }>('/api/eway-bills') })
export const useEway = (id: number | null) => useQuery({ queryKey: ['eway', 'one', id], enabled: !!id, queryFn: async () => (await get<{ eway_bill: Eway }>(`/api/eway-bills/${id}`)).eway_bill })

export const saveEway = (id: number | null, b: Record<string, unknown>) => (id ? put<{ eway_bill: Eway }>(`/api/eway-bills/${id}`, b) : post<{ eway_bill: Eway }>('/api/eway-bills', b))
export const ewayAction = (id: number, path: 'generated' | 'vehicle' | 'cancel', b: Record<string, unknown>) => post<{ eway_bill: Eway; message?: string }>(`/api/eway-bills/${id}/${path}`, b)
