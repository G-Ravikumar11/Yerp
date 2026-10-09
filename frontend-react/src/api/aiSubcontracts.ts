import { useQuery } from '@tanstack/react-query'
import { get, post } from '@/lib/api'

export interface AiStatus {
  enabled: boolean
  configured: boolean
  claude: boolean
  available: boolean
}

export interface Flag {
  level: 'stop' | 'check' | 'note'
  text: string
}

export interface BillReview {
  flags: Flag[]
  stop: boolean
  summary: string | null
  ai_message?: string
  ai: AiStatus
}

export interface HardCopyCheck {
  available: boolean
  message?: string
  reason?: string
  agrees?: boolean
  confidence?: number | null
  low_confidence?: boolean
  notes?: string
  mismatches?: { item: string; paper: number; bill: number; difference: number }[]
  agreed?: { item: string; paper: number; bill: number }[]
  only_on_bill?: { description: string; quantity: number | null; amount: number | null }[]
  only_on_paper?: { description: string; quantity: number | null; amount: number | null }[]
}

export interface ContractorBrief {
  standing: {
    contractor: string
    papers_ok: boolean
    paper_warnings: string[]
    score: { overall: number | null; count: number }
    orders: number
    certified_bills: number
    work_certified: number
    back_charged: number
    back_charges_open: number
    flags: string[]
    verdict: 'good' | 'ordinary' | 'careful'
  }
  summary: string | null
  ai_message?: string
  ai: AiStatus
}

export const useAiStatus = () => useQuery({ queryKey: ['ai', 'status'], queryFn: () => get<AiStatus>('/api/ai/subcontracts/status'), staleTime: 60_000 })
export const reviewBill = (billId: number) => get<BillReview>(`/api/ai/subcontracts/bills/${billId}/review`)
export const checkHardCopy = (billId: number) => post<HardCopyCheck>(`/api/ai/subcontracts/bills/${billId}/hard-copy-check`)
export const contractorBrief = (id: number) => get<ContractorBrief>(`/api/ai/subcontracts/contractors/${id}/brief`)
