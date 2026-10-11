import { useQuery } from '@tanstack/react-query'
import { get, put } from '@/lib/api'

export interface GstSettings {
  gstin: string
  state: string
  state_code: string
  states: Record<string, string>
}

export interface OutwardSupply {
  date: string
  number: string
  party: string
  project: string
  place_of_supply: string
  rate: number
  taxable: number
  cgst: number
  sgst: number
  igst: number
  total: number
}

export interface Outward {
  supplies: OutwardSupply[]
  by_month: { month: string; bills: number; taxable: number; cgst: number; sgst: number; igst: number; tax: number }[]
  summary: { taxable: number; cgst: number; sgst: number; igst: number; tax: number; missing_place_of_supply: number }
}

export interface InwardSupply {
  date: string
  number: string
  kind: string
  party: string
  party_gstin: string
  rate: number
  taxable: number
  tax: number
}

export interface Inward {
  supplies: InwardSupply[]
  summary: { taxable: number; tax: number; bills: number; missing_party_gstin: number }
}

export const gstKeys = { all: ['gst'] as const }
const q = (from: string, to: string) => `?date_from=${encodeURIComponent(from)}&date_to=${encodeURIComponent(to)}`

export const useGstSettings = () => useQuery({ queryKey: ['gst', 'settings'], queryFn: () => get<GstSettings>('/api/gst/settings') })
export const useOutward = (from: string, to: string) => useQuery({ queryKey: ['gst', 'outward', from, to], queryFn: () => get<Outward>(`/api/gst/outward${q(from, to)}`) })
export const useInward = (from: string, to: string) => useQuery({ queryKey: ['gst', 'inward', from, to], queryFn: () => get<Inward>(`/api/gst/inward${q(from, to)}`) })
export const saveGstin = (gstin: string) => put<{ state?: string }>('/api/gst/settings', { gstin })
export const gstExport = (kind: 'outward' | 'inward', from: string, to: string) => `/api/gst/${kind}.xlsx${q(from, to)}`
