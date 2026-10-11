import { useQuery } from '@tanstack/react-query'
import { del, get, post, put } from '@/lib/api'

export type EstimateStatus = 'DRAFT' | 'SUBMITTED' | 'WON' | 'LOST' | 'WITHDRAWN'
export type RateKind = 'MATERIAL' | 'LABOUR' | 'PLANT' | 'OTHER'
export const RATE_KINDS: RateKind[] = ['MATERIAL', 'LABOUR', 'PLANT', 'OTHER']

/** One resource in a rate build-up: so much of it goes into one unit of the item. */
export interface RateLine {
  kind: RateKind
  description: string
  uom: string
  quantity_per_unit: number
  rate: number
  wastage_percent: number
}

export interface EstimateItem {
  id: number
  item_no: string
  description: string
  fg_code: string
  uom: string
  quantity: number
  cost_rate: number
  quoted_rate: number
  quoted_amount: number
  analysis: RateLine[]
}

/** A tender being priced. Overhead goes on cost and profit on the result, in that order. */
export interface Estimate {
  id: number
  number: string
  title: string
  customer_name: string
  tender_reference: string
  due_on: string
  item_count: number
  cost_total: number
  quoted_total: number
  margin_amount: number
  margin_percent: number
  overhead_percent: number
  profit_percent: number
  status: EstimateStatus
  work_order: string
  notes: string
  editable: boolean
  actions: string[]
  items: EstimateItem[]
}

export interface EstimateList {
  estimates: Estimate[]
  summary: { open: number; out_for_decision: number; won_value: number; strike_rate: number }
}

export const estimateKeys = { all: ['estimates'] as const, list: ['estimates', 'list'] as const, one: (id: number) => ['estimates', id] as const }

export const useEstimates = () => useQuery({ queryKey: estimateKeys.list, queryFn: () => get<EstimateList>('/api/estimates') })
export const useEstimate = (id: number) => useQuery({ queryKey: estimateKeys.one(id), queryFn: () => get<Estimate>(`/api/estimates/${id}`), enabled: id > 0 })

type Reply = { estimate: Estimate; message?: string }
export const createEstimate = (b: { title: string; customer_name: string }) => post<Reply>('/api/estimates', { ...b, overhead_percent: 10, profit_percent: 8 })
export const saveEstimateHead = (e: Estimate, b: { overhead_percent: number; profit_percent: number }) =>
  put<Reply>(`/api/estimates/${e.id}`, { title: e.title, customer_name: e.customer_name, tender_reference: e.tender_reference, due_on: e.due_on, notes: e.notes, ...b })
export const addEstimateItem = (id: number, b: { item_no: string; description: string; uom: string; quantity: number; cost_rate: number }) => post<Reply>(`/api/estimates/${id}/items`, b)
export const removeEstimateItem = (id: number, itemId: number) => del<Reply>(`/api/estimates/${id}/items/${itemId}`)
export const saveAnalysis = (id: number, itemId: number, lines: RateLine[]) => put<Reply>(`/api/estimates/${id}/items/${itemId}/analysis`, { lines })
export const actOnEstimate = (id: number, action: 'submit' | 'win' | 'lose' | 'reopen' | 'withdraw', reason?: string) => post<Reply>(`/api/estimates/${id}/${action}`, reason !== undefined ? { reason } : {})
