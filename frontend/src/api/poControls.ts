import { useQuery } from '@tanstack/react-query'
import { del, get, post, put } from '@/lib/api'

/** One price the item was bought at, on an approved order. */
export interface PricePoint { on: string; rate: number; supplier: string; po: string; po_id: number }
export interface RateContract { id: number; contract_no?: string; supplier_name: string; item_code: string; rate: number; valid_from: string; valid_to: string; reference: string }
export interface PriceHistory { item_code: string; points: PricePoint[]; last_by_supplier: PricePoint[]; contracts: RateContract[] }

/** What an order would find as it is filled in: each BOQ item's budget, and the lines priced over the last price. */
export interface BudgetRow { key: string; label: string; budget: number | null; spent: number | null; committed: number | null; this: number; over_by: number; note: string }
export interface RateFlag { item_code: string; description: string; rate: number; last_rate: number | null; contract_rate: number | null; why: string }
export interface OrderCheck { budget: BudgetRow[]; over_budget: boolean; rates: RateFlag[] }
export interface BudgetHead { key: string; label: string; heading: boolean; budget: number; spent: number }

export const priceKeys = { all: ['po-controls'] as const }
export const usePriceHistory = (code: string) =>
  useQuery({ queryKey: [...priceKeys.all, 'history', code], enabled: !!code, queryFn: () => get<PriceHistory>(`/api/items/price-history?item_code=${encodeURIComponent(code)}`) })
export const useBudgetHeads = (jobId: number) =>
  useQuery({ queryKey: [...priceKeys.all, 'heads', jobId], enabled: jobId > 0, queryFn: async () => (await get<{ heads: BudgetHead[] }>(`/api/jobs/${jobId}/budget-heads`)).heads })
export interface PurchaseControls { rate_alert_pct: number; purchasing_emails: string; late_delivery_emails: boolean }
export const usePurchaseControls = () => useQuery({ queryKey: [...priceKeys.all, 'settings'], queryFn: () => get<PurchaseControls>('/api/purchase-controls') })
export const savePurchaseControls = (b: Partial<PurchaseControls>) => put<PurchaseControls>('/api/purchase-controls', b)

export const checkOrder = (b: { job_id: number | null; supplier_name: string; order_id?: number | null; line_items: { boq_key?: string; item_code?: string; description?: string; qty: number; price: number }[] }) =>
  post<OrderCheck>('/api/purchase-orders/check', b)
export const addRateContract = (b: Omit<RateContract, 'id' | 'contract_no'>) => post<{ message: string }>('/api/rate-contracts', b)
export const removeRateContract = (id: number) => del<{ ok: boolean }>(`/api/rate-contracts/${id}`)
export const setRateAlert = (pct: number) => put<{ rate_alert_pct: number }>('/api/purchase-controls', { rate_alert_pct: pct })

/** A rate contract with its items: numbered, for a supplier, over a period. */
export interface Contract { contract_no: string; supplier_name: string; valid_from: string; valid_to: string; reference: string; status: string; days_left: number | null
  items: { id: number; item_code: string; item_name: string; rate: number }[] }
export const useContracts = () => useQuery({ queryKey: [...priceKeys.all, 'contracts'], queryFn: async () => (await get<{ contracts: Contract[] }>('/api/rate-contracts/by-contract')).contracts })
/** {item_code: rate} the supplier's contracts set today: what an order to them picks by itself. */
export const useContractRates = (supplier: string) =>
  useQuery({ queryKey: [...priceKeys.all, 'active', supplier], enabled: !!supplier.trim(), queryFn: async () => (await get<{ rates: Record<string, number> }>(`/api/rate-contracts/active?supplier=${encodeURIComponent(supplier.trim())}`)).rates })
export const makeContract = (b: { supplier_name: string; valid_from: string; valid_to: string; reference: string; items: { item_code: string; rate: number }[] }) =>
  post<{ message: string; contract_no: string }>('/api/rate-contracts', b)
