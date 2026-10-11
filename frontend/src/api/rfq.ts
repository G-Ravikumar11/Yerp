import { useQuery } from '@tanstack/react-query'
import { get, post } from '@/lib/api'

export const rfqKeys = { all: ['rfq'] as const }

export interface Rfq { id: number; number: string; title: string; project: string; lines: number; quotes: number; needed_by: string; status: string; award_reason?: string }
export interface Offer { supplier_name: string; rate: number; amount: number; tax_percent: number }
export interface RfqLine { rfq_line_id: number; description: string; item_code: string; uom: string; qty: number; spread_percent: number; awarded_supplier: string; lowest: string; offers: Offer[] }
export interface RfqSupplier { supplier_name: string; rank: string; is_l1: boolean; basic: number; tax: number; freight: number; landed: number; delivery_days: number; payment_terms: string; complete: boolean }
export interface Statement { rfq: Rfq; lines: RfqLine[]; suppliers: RfqSupplier[]; l1: string; l1_landed: number; saving_vs_l2: number; lowest_per_line_basic: number }

export const useRfqs = () => useQuery({ queryKey: ['rfq', 'list'], queryFn: () => get<{ rfqs: Rfq[]; summary: { open: number; waiting_for_quotes: number; awarded: number } }>('/api/rfqs') })
export const useStatement = (id: number | null) => useQuery({ queryKey: ['rfq', 'one', id], enabled: !!id, queryFn: () => get<Statement>(`/api/rfqs/${id}`) })
export const useSupplierNames = () => useQuery({ queryKey: ['rfq', 'suppliers'], staleTime: 5 * 60_000, queryFn: async () => ((await get<{ suppliers: { name: string }[] }>('/api/suppliers')).suppliers ?? []).map((s) => s.name) })

export const openRfq = (b: { title: string; job_id: number | null; needed_by: string; lines: { item_code: string; description: string; uom: string; qty: number }[] }) => post<{ rfq: { id: number }; message: string }>('/api/rfqs', b)
export const openRfqFromOrder = (wo: number) => post<{ rfq: { id: number }; message: string }>(`/api/rfqs/from-work-order/${wo}`)
export const recordQuote = (id: number, b: Record<string, unknown>) => post<{ message: string }>(`/api/rfqs/${id}/quotes`, b)
export const awardRfq = (id: number, b: { mode: string; supplier_name: string; reason: string }) => post<{ message: string }>(`/api/rfqs/${id}/award`, b)
