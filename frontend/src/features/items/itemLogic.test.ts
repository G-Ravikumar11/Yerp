import { beforeEach, describe, expect, it } from 'vitest'
import { DEFAULT_FILTERS, buildChips, clearAll, clearFilter, isFiltered, loadFilters, saveFilters, stockLabel } from './itemLogic'

describe('filter chips', () => {
  it('has none when nothing is chosen, and the default "active only" is not a chip', () => {
    expect(buildChips(DEFAULT_FILTERS)).toEqual([])
    expect(isFiltered(DEFAULT_FILTERS)).toBe(false)
  })

  it('has one removable chip for each filter in use, in plain words', () => {
    const f = { ...DEFAULT_FILTERS, category: 'Cement', uom: 'bag', status: 'inactive', site_id: '4' }
    expect(buildChips(f, () => 'Kokapet').map((c) => c.label)).toEqual(['Category: Cement', 'Unit: bag', 'Inactive items', 'Site: Kokapet'])
  })

  it('removing the category also removes its subcategory, and returns to page one', () => {
    const f = { ...DEFAULT_FILTERS, category: 'Cement', subcategory: 'OPC', page: 3 }
    expect(clearFilter(f, 'category')).toMatchObject({ category: '', subcategory: '', page: 1 })
    expect(clearFilter(f, 'subcategory')).toMatchObject({ category: 'Cement', subcategory: '' })
  })

  it('"Clear all" keeps how the list is sorted and paged, but nothing that narrows it', () => {
    const f = { ...DEFAULT_FILTERS, category: 'Cement', status: 'all', q: 'opc', sort: 'name', direction: 'desc' as const, page_size: 50, page: 4 }
    expect(clearAll(f)).toEqual({ ...DEFAULT_FILTERS, sort: 'name', direction: 'desc', page_size: 50 })
  })

  it('a search alone counts as narrowing the list', () => {
    expect(isFiltered({ ...DEFAULT_FILTERS, q: '  ' })).toBe(false)
    expect(isFiltered({ ...DEFAULT_FILTERS, q: 'opc' })).toBe(true)
  })
})

describe('remembering filters per person', () => {
  beforeEach(() => localStorage.clear())

  it('brings back the last filters but never the search text or the page', () => {
    saveFilters('a@x.in', { ...DEFAULT_FILTERS, category: 'Steel', q: 'tmt', page: 5 })
    expect(loadFilters('a@x.in')).toEqual({ ...DEFAULT_FILTERS, category: 'Steel' })
  })

  it('keeps each person\'s filters apart', () => {
    saveFilters('a@x.in', { ...DEFAULT_FILTERS, category: 'Steel' })
    expect(loadFilters('b@x.in')).toEqual(DEFAULT_FILTERS)
  })

  it('ignores a damaged saved value', () => {
    localStorage.setItem('yerp.items.filters.a@x.in', '{not json')
    expect(loadFilters('a@x.in')).toEqual(DEFAULT_FILTERS)
  })
})

describe('stock column', () => {
  it('shows a quantity with its unit for a material, and a dash for a work item', () => {
    expect(stockLabel('RM', 12500.5, 'kg')).toBe('12,500.5 kg')
    expect(stockLabel('FG', 4, 'cum')).toBe('-')
    expect(stockLabel('RM', null, 'kg')).toBe('-')
  })
})
