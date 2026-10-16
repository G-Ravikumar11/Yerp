import { useQuery } from '@tanstack/react-query'
import { get,} from '@/lib/api'

type ItemKind = 'RM' | 'FG'

export interface Item {
  id: number
  kind: ItemKind
  item_code: string
  item_name: string
  description: string
  category: string
  item_type: string
  units_of_measure: string
  hsn_code: string
  item_tax_type: string
  last_rate: number
  reorder_level: number
}

export interface ItemList {
  items: Item[]
  counts: Record<ItemKind, number>
}

export interface ItemVocabulary {
  kinds: ItemKind[]
  item_types: string[]
  boq_item_types: string[]
  units: string[]
  tax_rates: string[]
}

export const itemKeys = {
  all: ['items'] as const,
  list: (kind: string, q: string) => ['items', 'list', kind, q] as const,
  vocabulary: ['items', 'vocabulary'] as const,
}

export function useItems(kind: string, q: string) {
  return useQuery({
    queryKey: itemKeys.list(kind, q),
    queryFn: () => get<ItemList>(`/api/erp/items?kind=${encodeURIComponent(kind)}&q=${encodeURIComponent(q)}`),
    placeholderData: (prev) => prev,
  })
}

export function useItemVocabulary() {
  return useQuery({ queryKey: itemKeys.vocabulary, queryFn: () => get<ItemVocabulary>('/api/erp/vocabulary'), staleTime: 60 * 60_000 })
}
