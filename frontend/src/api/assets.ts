import { useQuery } from '@tanstack/react-query'
import { get, post, put } from '@/lib/api'

export interface BookYear {
  fy?: string
  opening: number
  added: number
  depreciation: number
  closing: number
  days: number
  accumulated?: number
  disposed?: boolean
  disposal_value?: number
  gain?: number
}

/** The book of one owned asset: how it is written down, and what it is worth this year. */
export interface AssetBook {
  asset_id: number
  code: string
  name: string
  category?: string
  method: 'WDV' | 'SLM'
  life_years: number
  rate_percent?: number
  residual_percent: number
  put_to_use_on: string
  cost: number
  tax_block: string
  opening_fy: string
  opening_book_value: number
  disposed_on?: string
  year: BookYear
}

export interface BookInput {
  method: string
  life_years: number
  residual_percent: number
  put_to_use_on: string
  cost: number
  tax_block: string
  opening_fy: string
  opening_book_value: number
}

export interface NotSetUp {
  asset_id: number
  code: string
  name: string
  category: string
  suggest: Partial<BookInput>
  ready: boolean
}

export interface Register {
  fy: string
  fys: string[]
  assets: AssetBook[]
  not_set_up: NotSetUp[]
  methods: string[]
  blocks: string[]
  totals: { cost: number; depreciation: number; closing: number; accumulated: number; gain: number }
}

export interface TaxBlock {
  block_id: number
  block: string
  rate: number
  opening: number
  added_full: number
  added_half: number
  deleted: number
  depreciation: number
  closing: number
  short_term_gain: number
  short_term_loss: number
  opening_fy: string
  opening_wdv: number
}

export interface TaxBlocks {
  blocks: TaxBlock[]
  totals: { opening: number; added_full: number; added_half: number; deleted: number; depreciation: number; closing: number; short_term_gain: number; short_term_loss: number }
}

export const assetKeys = { all: ['assets'] as const }
export const useRegister = (fy: string) => useQuery({ queryKey: ['assets', 'register', fy], queryFn: () => get<Register>(`/api/fixed-assets${fy ? `?fy=${encodeURIComponent(fy)}` : ''}`) })
export const useTaxBlocks = (fy: string, enabled: boolean) => useQuery({ queryKey: ['assets', 'blocks', fy], queryFn: () => get<TaxBlocks>(`/api/fixed-assets/tax-blocks?fy=${encodeURIComponent(fy)}`), enabled: enabled && !!fy })
export const useSchedule = (id: number) =>
  useQuery({ queryKey: ['assets', 'schedule', id], queryFn: () => get<{ book: AssetBook; rows: (BookYear & { fy: string })[] }>(`/api/fixed-assets/${id}/schedule`), enabled: id > 0 })

export const saveBook = (id: number, b: BookInput) => put<{ message: string }>(`/api/fixed-assets/${id}/book`, b)
export const setUpAll = () => post<{ message: string }>('/api/fixed-assets/set-up-all')
export const disposeAsset = (id: number, b: { disposed_on: string; disposal_value: number; note: string }) => post<{ message: string }>(`/api/fixed-assets/${id}/dispose`, b)
export const saveBlock = (id: number, b: { rate: number; opening_fy: string; opening_wdv: number }) => put<{ message: string }>(`/api/fixed-assets/tax-blocks/${id}`, b)
export const assetsExcel = (tab: 'register' | 'blocks', fy: string) => (tab === 'register' ? `/api/fixed-assets.xlsx?fy=${fy}` : `/api/fixed-assets/tax-blocks.xlsx?fy=${fy}`)
export const methodText = (b: { method: string; life_years: number; rate_percent?: number }) => (b.method === 'SLM' ? `SLM, ${b.life_years} yrs` : `WDV ${b.rate_percent ?? ''}%`)
