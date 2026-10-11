import { useQuery } from '@tanstack/react-query'
import { api, get, post } from '@/lib/api'

export interface PortalMe {
  party: string
  party_type: 'contractor' | 'supplier'
  company: string
  name?: string
  email?: string
}

export interface PortalSummary {
  balance: number
  passed_unpaid: number
  bills_waiting: number
  paid_total: number
  last_payment?: { amount: number; paid_on: string } | null
  orders: number
  order_value: number
  retention_held?: number
  retention?: { order_number: string; held: number; released: number; balance: number; dlp_ends?: string }[]
}

export interface PortalOrder { id: number; number: string; project: string; subject?: string; value: number; from?: string; to?: string; superseded?: boolean }
export interface PortalOrderDetail { order: { number: string }; lines: { code?: string; description: string; qty: number; uom: string; rate: number; amount: number }[] }

export interface PortalBill {
  id: number; number: string; date: string; where: string; note?: string; claimed: number; gst: number; retention?: number; tds?: number
  deductions?: number; net: number; paid: number; left: number; pdf?: string; can_accept?: boolean; accepted_by?: string; accepted_at?: string
}

export interface PortalPayment { date?: string; paid_on: string; number: string; against: string; mode: string; reference?: string; amount: number }

export interface PortalStatement {
  opening?: number
  closing: number
  rows: { date: string; kind: string; number: string; against?: string; reference?: string; billed: number; paid: number; balance: number }[]
}

export interface PortalInvite { name?: string; party: string; company: string; email: string }

export const portalKeys = { me: ['portal', 'me'] as const, all: ['portal'] as const }

/** Who is signed in to the portal. A 401 is the answer "nobody", not an error to show. */
export const usePortalMe = () =>
  useQuery({ queryKey: portalKeys.me, queryFn: () => api<PortalMe>('/api/portal/me', { quiet: true }).catch(() => null), retry: false, staleTime: 60_000 })

export const usePortal = <T,>(key: string, url: string) => useQuery({ queryKey: ['portal', key, url], queryFn: () => get<T>(url) })

export const portalLogin = (email: string, password: string) => api('/api/portal/login', { method: 'POST', body: { email, password }, quiet: true })
export const portalLogout = () => post('/api/portal/logout')
export const portalInvite = (token: string) => api<PortalInvite>('/api/portal/invite?token=' + encodeURIComponent(token), { quiet: true })
export const portalAcceptInvite = (token: string, password: string) => post('/api/portal/accept-invite', { token, password })
export const portalAcceptBill = (id: number) => post<{ message?: string }>(`/api/portal/bills/${id}/accept`)
export const portalSendInvoice = (form: FormData) => api<{ message: string }>('/api/portal/invoices', { method: 'POST', body: form })
