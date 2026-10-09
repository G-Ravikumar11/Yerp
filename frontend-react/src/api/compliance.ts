import { useQuery } from '@tanstack/react-query'
import { del, get, post } from '@/lib/api'

export interface DocState {
  kind: string
  label: string
  state: 'valid' | 'expiring' | 'expired' | 'missing'
}

export interface Score {
  count: number
  quality: number | null
  speed: number | null
  safety: number | null
  discipline: number | null
  overall: number | null
}

export interface ContractorStatus {
  contractor_id: number
  contractor: string
  vendor_code: string
  ok: boolean
  warnings: string[]
  required: DocState[]
  score: Score
}

export interface ComplianceHome {
  contractors: ContractorStatus[]
  kinds: Record<string, string>
  back_charge_kinds: string[]
  rating_fields: string[]
}

export interface ComplianceDoc {
  id: number
  kind: string
  kind_label: string
  number: string
  valid_from: string
  valid_to: string
  note: string
  state: 'valid' | 'expiring' | 'expired'
  days_left: number | null
  recorded_by: string
}

export interface ContractorDetail {
  contractor: string
  ok: boolean
  warnings: string[]
  documents: ComplianceDoc[]
  required: DocState[]
  score: Score
  ratings: { id: number; bill_id: number | null; quality: number; speed: number; safety: number; discipline: number; note: string; by: string; at: string }[]
}

export interface BackCharge {
  id: number
  number: string
  contractor_id: number
  contractor: string
  order_id: number | null
  kind: string
  reason: string
  amount: number
  status: 'OPEN' | 'APPLIED' | 'CANCELLED'
  applied_bill_id: number | null
  applied_bill: string
  raised_by: string
  created_at: string
  applied_at: string
}

export interface Settlement {
  order_id: number
  order: string
  bills: number
  work_certified: number
  certified_net: number
  paid: number
  still_to_pay: number
  retention_held: number
  retention_released: number
  retention_balance: number
  advance_given: number
  advance_recovered: number
  advance_outstanding: number
  back_charges_applied: number
  back_charges_open: number
  open_bills: number
  can_close: boolean
}

export const complianceKeys = {
  all: ['compliance'] as const,
  home: () => ['compliance', 'home'] as const,
  one: (id: number) => ['compliance', 'one', id] as const,
  charges: (status: string) => ['compliance', 'charges', status] as const,
  settlement: (id: number) => ['compliance', 'settlement', id] as const,
}

export const useComplianceHome = () => useQuery({ queryKey: complianceKeys.home(), queryFn: () => get<ComplianceHome>('/api/compliance') })
export const useContractorDetail = (id: number) =>
  useQuery({ queryKey: complianceKeys.one(id), queryFn: () => get<ContractorDetail>(`/api/compliance/contractors/${id}`), enabled: id > 0 })
export const useBackCharges = (status = '') =>
  useQuery({ queryKey: complianceKeys.charges(status), queryFn: () => get<{ back_charges: BackCharge[] }>(`/api/back-charges?status=${encodeURIComponent(status)}`) })
export const useSettlement = (orderId: number) =>
  useQuery({ queryKey: complianceKeys.settlement(orderId), queryFn: () => get<Settlement>(`/api/subcontract-orders/${orderId}/settlement`), enabled: orderId > 0 })

export const addDocument = (b: { contractor_id: number; kind: string; number?: string; valid_from?: string; valid_to: string; note?: string }) => post<{ message: string }>('/api/compliance/documents', b)
export const removeDocument = (id: number) => del<{ message: string }>(`/api/compliance/documents/${id}`)
export const raiseBackCharge = (b: { contractor_id: number; order_id?: number | null; kind: string; reason: string; amount: number }) => post<{ message: string }>('/api/back-charges', b)
export const cancelBackCharge = (id: number) => post<{ message: string }>(`/api/back-charges/${id}/cancel`)
export const putBackChargesOnBill = (billId: number, ids: number[]) => post<{ message: string }>(`/api/sub-bills/${billId}/back-charges`, { ids })
export const takeBackChargeOffBill = (billId: number, chargeId: number) => del<{ message: string }>(`/api/sub-bills/${billId}/back-charges/${chargeId}`)
export const rateContractor = (b: { contractor_id: number; bill_id?: number | null; quality: number; speed: number; safety: number; discipline: number; note?: string }) => post<{ message: string }>('/api/compliance/ratings', b)
