import { beforeEach, describe, expect, it } from 'vitest'
import { DEFAULT_FILTERS, GST_RATES, NO_CATEGORY, purchaseRateOf, buildChips, clearAll, clearFilter, defaultTypeFor, groupINR, isFiltered, loadFilters, matchUnit, orderUnits, saveFilters, stockLabel, validateItem, type ItemForm } from './itemLogic'

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
  it('shows the quantity wherever the store has a record, whatever the item is', () => {
    expect(stockLabel('RM', 12500.5, 'kg')).toBe('12,500.5 kg')
    expect(stockLabel('FG', 4, 'cum')).toBe('4 cum')
    expect(stockLabel('RM', 0, 'kg')).toBe('0 kg')
  })

  it('says none in hand for a material with no record, and not stocked for a work item', () => {
    expect(stockLabel('RM', null, 'Bags')).toBe('0 Bags')
    expect(stockLabel('FG', null, 'cum')).toBe('Not stocked')
  })
})

describe('purchase rate column', () => {
  it('shows the kept rate, else the last rate used and says so, else nothing', () => {
    expect(purchaseRateOf({ purchase_rate: 415, last_rate: 300 })).toEqual({ value: 415, lastUsed: false })
    expect(purchaseRateOf({ purchase_rate: 0, last_rate: 250 })).toEqual({ value: 250, lastUsed: true })
    expect(purchaseRateOf({ purchase_rate: 0, last_rate: 0 })).toBeNull()
  })
})

describe('items with no category', () => {
  it('have a chip of their own', () => {
    expect(buildChips({ ...DEFAULT_FILTERS, category: NO_CATEGORY }).map((c) => c.label)).toEqual(['No category yet'])
  })
})

describe('the gaps in the master', () => {
  it('show as a chip that takes the filter off', () => {
    const f = { ...DEFAULT_FILTERS, missing: 'gst' as const }
    expect(buildChips(f).map((c) => c.label)).toEqual(['No GST rate'])
    expect(clearFilter(f, 'missing').missing).toBe('')
  })
  it('are cleared with the rest, but the kind on show stays', () => {
    expect(clearAll({ ...DEFAULT_FILTERS, kind: 'RM', missing: 'hsn', category: 'Cement' })).toEqual({ ...DEFAULT_FILTERS, kind: 'RM' })
    expect(buildChips({ ...DEFAULT_FILTERS, kind: 'RM' })).toEqual([])
  })
})

const UNITS = ['cum', 'sqm', 'rmt', 'cft', 'sqft', 'Nos', 'Sets', 'MT', 'Quintal', 'Kgs', 'Bags', 'Brass', 'Litres', 'KL', 'Hours', 'Days', 'Months', 'Meters', 'Lot', 'Job']
const blank: ItemForm = {
  item_code: '', item_name: 'Cement - OPC 53 grade', kind: 'RM', units_of_measure: 'Bags', item_category: '', item_subcategory: '', specification: '',
  purchase_rate: '', selling_rate: '', gst_percent: '', hsn_code: '', item_type: 'Purchased', preferred_supplier: '', reorder_level: '', description: '', remarks: '', is_active: true,
  make: '', segment: '', shelf_life_applicable: false, shelf_life_days: '', expiry_tracking: false,
}

describe('validating the item form', () => {
  it('passes with only a name and a unit', () => {
    expect(validateItem(blank, UNITS)).toEqual({})
  })

  it('asks for a name and a unit in words that say what to do', () => {
    const e = validateItem({ ...blank, item_name: '  ', units_of_measure: '' }, UNITS)
    expect(e.item_name).toMatch(/Give the item a name/)
    expect(e.units_of_measure).toMatch(/Choose how the item is counted/)
  })

  it('refuses a unit that is not in the list, whatever the case of the ones that are', () => {
    expect(validateItem({ ...blank, units_of_measure: 'furlong' }, UNITS).units_of_measure).toMatch(/not a unit in the list/)
    expect(validateItem({ ...blank, units_of_measure: 'bags' }, UNITS)).toEqual({})
    expect(matchUnit(' BAGS ', UNITS)).toBe('Bags')
    expect(matchUnit('furlong', UNITS)).toBe('')
  })

  it('refuses a code with spaces or odd marks, and one that is too long', () => {
    expect(validateItem({ ...blank, item_code: 'HAS SPACE' }, UNITS).item_code).toBeTruthy()
    expect(validateItem({ ...blank, item_code: 'bad#code' }, UNITS).item_code).toBeTruthy()
    expect(validateItem({ ...blank, item_code: 'X'.repeat(31) }, UNITS).item_code).toBeTruthy()
    expect(validateItem({ ...blank, item_code: 'pcc/m15.a-1_x' }, UNITS)).toEqual({})
  })

  it('refuses negative or non-numeric money, and a GST rate that does not exist', () => {
    expect(validateItem({ ...blank, purchase_rate: '-5' }, UNITS).purchase_rate).toBeTruthy()
    expect(validateItem({ ...blank, selling_rate: 'abc' }, UNITS).selling_rate).toBeTruthy()
    expect(validateItem({ ...blank, gst_percent: '7' }, UNITS).gst_percent).toBeTruthy()
    for (const r of GST_RATES) expect(validateItem({ ...blank, gst_percent: r }, UNITS)).toEqual({})
  })

  it('wants the category before its subcategory', () => {
    expect(validateItem({ ...blank, item_subcategory: 'OPC' }, UNITS).item_subcategory).toMatch(/category first/)
  })
})

describe('form helpers', () => {
  it('lists the units a contractor reaches for first, keeping the rest', () => {
    const ordered = orderUnits(UNITS)
    expect(ordered.slice(0, 4)).toEqual(['cum', 'sqm', 'rmt', 'Bags'])
    expect([...ordered].sort()).toEqual([...UNITS].sort())
  })

  it('writes money the Indian way and leaves a blank blank', () => {
    expect(groupINR('125000.5')).toBe('1,25,000.5')
    expect(groupINR('')).toBe('')
    expect(groupINR('x')).toBe('')
  })

  it('defaults the type from what the item is', () => {
    expect(defaultTypeFor('RM')).toBe('Purchased')
    expect(defaultTypeFor('FG')).toBe('Work')
  })
})
