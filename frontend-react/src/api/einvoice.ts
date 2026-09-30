import { useQuery } from '@tanstack/react-query'
import { get, post } from '@/lib/api'

/** An invoice reference number the GST portal gave back, as recorded against a bill. */
export interface Irn {
  id: number
  irn: string
  ack_no: string
  ack_date: string
  ewb_no?: string
  created_by_name: string
  qr_url: string
  cancellable: boolean
}

export interface EInvoice {
  number: string
  irn?: Irn | null
  ready?: boolean
  payload?: {
    DocDtls: { No: string }
    BuyerDtls: { Gstin: string }
    ValDtls: { AssVal: number; CgstVal: number; SgstVal: number; IgstVal: number; TotInvVal: number }
  }
  missing?: string[]
  history?: { irn: string; cancelled_at: string; cancel_reason: string }[]
}

export const einvoiceKeys = { one: (type: string, id: number) => ['einvoice', type, id] as const }

export const useEInvoice = (type: string, id: number, enabled: boolean) =>
  useQuery({ queryKey: einvoiceKeys.one(type, id), queryFn: () => get<EInvoice>(`/api/einvoice/${type}/${id}`), enabled, staleTime: 0 })

export type IrnInput = { response: string } | { irn: string; ack_no: string; ack_date: string; signed_qr: string }
export const recordIrn = (type: string, id: number, body: IrnInput) => post<{ message: string }>(`/api/einvoice/${type}/${id}/irn`, body)
export const cancelIrn = (irnId: number, reason: string) => post<{ message: string }>(`/api/einvoice/irns/${irnId}/cancel`, { reason })
