import type { ItemFilters } from '@/api/itemMaster'

/** What the list shows when nobody has chosen anything: active items only, by code. */
export const DEFAULT_FILTERS: ItemFilters = {
  q: '',
  category: '',
  subcategory: '',
  item_type: '',
  uom: '',
  status: 'active',
  site_id: '',
  sort: 'code',
  direction: 'asc',
  page: 1,
  page_size: 25,
}

export interface Chip {
  key: keyof ItemFilters
  label: string
}

const STATUS_LABEL: Record<string, string> = { active: 'Active items', inactive: 'Inactive items', all: 'Active and inactive' }

/** One removable chip for every filter that is not at its default. The search box is not a chip: it is already on screen. */
export function buildChips(f: ItemFilters, siteName: (id: string) => string = (id) => id): Chip[] {
  const chips: Chip[] = []
  if (f.category) chips.push({ key: 'category', label: `Category: ${f.category}` })
  if (f.subcategory) chips.push({ key: 'subcategory', label: `Subcategory: ${f.subcategory}` })
  if (f.item_type) chips.push({ key: 'item_type', label: `Type: ${f.item_type}` })
  if (f.uom) chips.push({ key: 'uom', label: `Unit: ${f.uom}` })
  if (f.status !== DEFAULT_FILTERS.status) chips.push({ key: 'status', label: STATUS_LABEL[f.status] ?? f.status })
  if (f.site_id) chips.push({ key: 'site_id', label: `Site: ${siteName(f.site_id)}` })
  return chips
}

/** Take one filter off. A subcategory means nothing without its category, so it goes with it. */
export function clearFilter(f: ItemFilters, key: keyof ItemFilters): ItemFilters {
  const next: ItemFilters = { ...f, [key]: DEFAULT_FILTERS[key] as never, page: 1 }
  if (key === 'category') next.subcategory = ''
  return next
}

/** Everything back to the default, but the way the list is sorted and paged is how the person likes it, not a filter. */
export function clearAll(f: ItemFilters): ItemFilters {
  return { ...DEFAULT_FILTERS, sort: f.sort, direction: f.direction, page_size: f.page_size }
}

/** True when anything narrows the list, search included: the difference between "no items yet" and "nothing matches". */
export const isFiltered = (f: ItemFilters) => !!f.q.trim() || buildChips(f).length > 0

const storeKey = (user: string) => `yerp.items.filters.${user || 'anon'}`

/** The last filters this person used. The search text and the page are not remembered: coming back to an old search is a surprise. */
export function loadFilters(user: string): ItemFilters {
  try {
    const raw = localStorage.getItem(storeKey(user))
    if (!raw) return DEFAULT_FILTERS
    const saved = JSON.parse(raw) as Partial<ItemFilters>
    const known = Object.fromEntries(Object.entries(saved).filter(([k]) => k in DEFAULT_FILTERS))
    return { ...DEFAULT_FILTERS, ...known, q: '', page: 1 }
  } catch {
    return DEFAULT_FILTERS
  }
}

export function saveFilters(user: string, f: ItemFilters) {
  try {
    const { q: _q, page: _page, ...keep } = f
    localStorage.setItem(storeKey(user), JSON.stringify(keep))
  } catch {
    // A private window has no storage: the filters just are not remembered.
  }
}

/** Stock only means something for a material the store keeps; a work item used in BOQs has none. */
export function stockLabel(kind: 'RM' | 'FG', stock: number | null, unit: string) {
  if (kind === 'FG' || stock === null) return '-'
  return `${new Intl.NumberFormat('en-IN', { maximumFractionDigits: 2 }).format(stock)} ${unit}`
}
