import { api, get, post } from '@/lib/api'
import type { AiStatus, Flag } from '@/api/aiSubcontracts'

export interface PoReview {
  flags: Flag[]
  stop: boolean
  summary: string | null
  ai_message?: string
  ai: AiStatus
}

export interface PoEmail {
  to: string
  subject: string
  body: string
  written_by_ai: boolean
  ai_message?: string
}

export interface QuoteRecommendation {
  l1: string
  l1_landed: number
  flags: Flag[]
  recommendation: string | null
  ai_message?: string
  ai: AiStatus
}

export interface ReadQuote {
  available: boolean
  message?: string
  reason?: string
  supplier_name?: string
  quote_ref?: string
  quote_date?: string
  valid_until?: string
  delivery_days?: number
  payment_terms?: string
  freight?: number
  lines?: { rfq_line_id: number; rate: number; tax_percent: number | null; remarks: string }[]
  unmatched?: string[]
  lines_priced?: number
  lines_in_enquiry?: number
  low_confidence?: boolean
}

export const reviewPo = (id: number) => get<PoReview>(`/api/ai/purchase-orders/${id}/review`)
export const draftPoEmail = (id: number) => post<PoEmail>(`/api/ai/purchase-orders/${id}/draft-email`)
export const recommendQuote = (id: number) => get<QuoteRecommendation>(`/api/ai/rfqs/${id}/recommend`)
export const readQuote = (id: number, input: { text?: string; file?: File | null }) => {
  const form = new FormData()
  if (input.file) form.append('file', input.file)
  if (input.text) form.append('text', input.text)
  return api<ReadQuote>(`/api/ai/rfqs/${id}/read-quote`, { method: 'POST', body: form })
}
