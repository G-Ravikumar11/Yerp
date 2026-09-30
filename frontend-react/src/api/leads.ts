import { useQuery } from '@tanstack/react-query'
import { get, post, put } from '@/lib/api'

export type LeadStatus = 'NEW' | 'QUALIFIED' | 'ESTIMATING' | 'SUBMITTED' | 'WON' | 'LOST' | 'DROPPED'

/** A tender in play: from the first enquiry to a bid, a win or a loss. */
export interface Lead {
  id: number
  number: string
  title: string
  customer_name: string
  contact_person: string
  phone: string
  email: string
  location: string
  source: string
  tender_reference: string
  estimated_value: number
  site_visit_on: string
  prebid_on: string
  bid_due_on: string
  days_to_bid: number | null
  emd_amount: number
  emd_mode: string
  emd_reference: string
  emd_paid_on: string
  emd_returned_on: string
  emd_outstanding: boolean
  status: LeadStatus
  lost_reason: string
  winning_bidder: string
  winning_price: number
  our_price: number
  estimate_id: number | null
  estimate_number: string
  notes: string
  days_held?: number
}

export interface Activity {
  id: number
  kind: string
  note: string
  next_action: string
  next_on: string
  by: string
  at: string
}

export interface LeadList {
  leads: Lead[]
  statuses: LeadStatus[]
  sources: string[]
  emd_modes: string[]
  summary: { live: number; pipeline_value: number; due_this_week: number; hit_rate: number; won_value: number; emd_out: number; emd_out_count: number }
}

export interface EmdRegister {
  emds: Lead[]
  summary: { out: number; on_decided_tenders: number; count: number }
}

export type LeadInput = Partial<Omit<Lead, 'id' | 'number' | 'status'>> & { title: string }

export const leadKeys = { all: ['leads'] as const, list: ['leads', 'list'] as const, one: (id: number) => ['leads', id] as const, emd: ['leads', 'emd'] as const }

export const useLeads = () => useQuery({ queryKey: leadKeys.list, queryFn: () => get<LeadList>('/api/leads') })
export const useLead = (id: number) => useQuery({ queryKey: leadKeys.one(id), queryFn: () => get<Lead & { activities: Activity[] }>(`/api/leads/${id}`), enabled: id > 0 })
export const useEmds = (enabled: boolean) => useQuery({ queryKey: leadKeys.emd, queryFn: () => get<EmdRegister>('/api/leads-emd'), enabled })

export const saveLead = (id: number | null, body: LeadInput) => (id ? put<{ lead: Lead; message: string }>(`/api/leads/${id}`, body) : post<{ lead: Lead; message: string }>('/api/leads', body))
export const moveLead = (id: number, body: { status: LeadStatus; lost_reason?: string; winning_bidder?: string; winning_price?: number; note?: string }) => post<{ message: string }>(`/api/leads/${id}/status`, body)
export const addActivity = (id: number, body: { kind: string; note: string; next_action: string; next_on: string }) => post<{ message: string }>(`/api/leads/${id}/activities`, body)
export const priceLead = (id: number) => post<{ message: string }>(`/api/leads/${id}/estimate`)
export const emdBack = (id: number) => post<{ message: string }>(`/api/leads/${id}/emd-returned`, {})
