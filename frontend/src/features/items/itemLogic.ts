import type { Gap, ItemFilters } from '@/api/itemMaster'

/** What the list shows when nobody has chosen anything: active items only, by code. */
export const DEFAULT_FILTERS: ItemFilters = {
  q: '',
  category: '',
  subcategory: '',
  item_type: '',
  uom: '',
  status: 'active',
  site_id: '',
  kind: '',
  missing: '',
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

/** Each gap in words, as a person would say what is missing. */
export const GAP_LABEL: Record<Gap, string> = { category: 'No category', gst: 'No GST rate', hsn: 'No HSN / SAC code', rate: 'No purchase rate', make: 'No make' }
/** The same, inside a sentence: "the items with no GST rate". */
export const gapPhrase = (g: Gap) => GAP_LABEL[g].charAt(0).toLowerCase() + GAP_LABEL[g].slice(1)

/** One removable chip for every filter that is not at its default. The search box and the kind are not chips: they are already on screen. */
export function buildChips(f: ItemFilters, siteName: (id: string) => string = (id) => id): Chip[] {
  const chips: Chip[] = []
  if (f.category) chips.push({ key: 'category', label: f.category === NO_CATEGORY ? 'No category yet' : `Category: ${f.category}` })
  if (f.subcategory) chips.push({ key: 'subcategory', label: `Subcategory: ${f.subcategory}` })
  if (f.item_type) chips.push({ key: 'item_type', label: `Type: ${f.item_type}` })
  if (f.uom) chips.push({ key: 'uom', label: `Unit: ${f.uom}` })
  if (f.status !== DEFAULT_FILTERS.status) chips.push({ key: 'status', label: STATUS_LABEL[f.status] ?? f.status })
  if (f.site_id) chips.push({ key: 'site_id', label: `Site: ${siteName(f.site_id)}` })
  if (f.missing) chips.push({ key: 'missing', label: GAP_LABEL[f.missing] })
  return chips
}

/** Take one filter off. A subcategory means nothing without its category, so it goes with it. */
export function clearFilter(f: ItemFilters, key: keyof ItemFilters): ItemFilters {
  const next: ItemFilters = { ...f, [key]: DEFAULT_FILTERS[key] as never, page: 1 }
  if (key === 'category') next.subcategory = ''
  return next
}

/** Everything back to the default, but the way the list is sorted and paged, and which kind is shown, is how the person likes it, not a filter. */
export function clearAll(f: ItemFilters): ItemFilters {
  return { ...DEFAULT_FILTERS, sort: f.sort, direction: f.direction, page_size: f.page_size, kind: f.kind }
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

/** What the store holds. A quantity wherever the store has a record of the item; otherwise a material has none in hand, and a work item is not kept in stock at all. */
export function stockLabel(kind: 'RM' | 'FG', stock: number | null, unit: string) {
  if (stock === null) return kind === 'RM' ? `0 ${unit}` : 'Not stocked'
  return `${new Intl.NumberFormat('en-IN', { maximumFractionDigits: 2 }).format(stock)} ${unit}`
}

/** The rate to show as the purchase rate: the one kept for the item, else the last one it was bought or sold at, said so. */
export function purchaseRateOf(i: { purchase_rate: number; last_rate: number }): { value: number; lastUsed: boolean } | null {
  if (i.purchase_rate > 0) return { value: i.purchase_rate, lastUsed: false }
  if (i.last_rate > 0) return { value: i.last_rate, lastUsed: true }
  return null
}

/** The filter value that finds items nobody has put in a category yet. */
export const NO_CATEGORY = '__none__'

/* --- The item form ----------------------------------------------------------------------------------------------- */

/** GST rates an item may carry. The server checks the same list. */
export const GST_RATES = ['0', '5', '12', '18', '28']

const COMMON_UNITS = ['cum', 'sqm', 'rmt', 'Bags', 'Kgs', 'MT', 'Nos', 'Meters', 'Litres', 'Hours', 'Days']

/** The units a contractor reaches for first, then the rest in the order the app lists them. */
export function orderUnits(units: readonly string[]): string[] {
  const first = COMMON_UNITS.filter((u) => units.includes(u))
  return [...first, ...units.filter((u) => !first.includes(u))]
}

/** The unit as the app spells it ("bags" -> "Bags"), or '' when it is not one of them. */
export function matchUnit(text: string, units: readonly string[]): string {
  const t = text.trim().toLowerCase()
  return units.find((u) => u.toLowerCase() === t) ?? ''
}

export interface ItemForm {
  item_code: string
  item_name: string
  kind: 'RM' | 'FG'
  units_of_measure: string
  item_category: string
  item_subcategory: string
  specification: string
  purchase_rate: string
  selling_rate: string
  gst_percent: string
  hsn_code: string
  item_type: string
  preferred_supplier: string
  reorder_level: string
  description: string
  remarks: string
  is_active: boolean
  make: string
  segment: string
}

export type ItemErrors = Partial<Record<keyof ItemForm, string>>

const CODE = /^[A-Za-z0-9][A-Za-z0-9._/-]{0,29}$/
const isMoney = (v: string) => v.trim() === '' || (Number.isFinite(Number(v)) && Number(v) >= 0)

/** Everything wrong with the form, in words that say how to put it right. Empty when it can be saved. */
export function validateItem(f: ItemForm, units: readonly string[]): ItemErrors {
  const e: ItemErrors = {}
  if (!f.item_name.trim()) e.item_name = 'Give the item a name, for example "Cement - OPC 53 grade".'
  if (!f.units_of_measure.trim()) e.units_of_measure = 'Choose how the item is counted, for example Bags, cum or Kgs.'
  else if (!matchUnit(f.units_of_measure, units)) e.units_of_measure = `"${f.units_of_measure}" is not a unit in the list. Pick one, for example Bags, cum or Kgs.`
  if (f.item_code.trim() && !CODE.test(f.item_code.trim())) e.item_code = 'Use letters, numbers and - _ / . only, up to 30 characters, with no spaces.'
  if (f.item_subcategory && !f.item_category) e.item_subcategory = 'Choose the category first.'
  if (!isMoney(f.purchase_rate)) e.purchase_rate = 'Enter an amount of 0 or more, for example 415.'
  if (!isMoney(f.selling_rate)) e.selling_rate = 'Enter an amount of 0 or more, for example 520.'
  if (f.gst_percent !== '' && !GST_RATES.includes(f.gst_percent)) e.gst_percent = 'Choose 0, 5, 12, 18 or 28 per cent.'
  if (!isMoney(f.reorder_level)) e.reorder_level = 'Enter a quantity of 0 or more.'
  return e
}

/** Raw materials are bought and kept in stock; work items are what a BOQ line is made of. */
export const defaultTypeFor = (kind: 'RM' | 'FG') => (kind === 'RM' ? 'Purchased' : 'Work')

/** The same figure written the Indian way: 1,25,000.50. */
export function groupINR(text: string): string {
  const n = Number(text)
  return text.trim() === '' || !Number.isFinite(n) ? '' : new Intl.NumberFormat('en-IN', { maximumFractionDigits: 4 }).format(n)
}
