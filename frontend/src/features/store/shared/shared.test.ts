import { describe, expect, it } from 'vitest'
import { visibleNav } from '@/lib/nav'
import { infoFor } from '@/lib/pageInfo'
import { availableActions } from './DocActionsBar'
import { nextIndex, unitsLine } from './ItemPicker'
import { storeLabel } from './StorePicker'
import { baseQty, cleanQty, unitHint } from './UomQtyInput'

describe('which buttons a store document offers', () => {
  const all = { submit: true, approve: true, post: true, cancel: true }
  it('follows the status', () => {
    expect(availableActions('DRAFT', all)).toEqual(['submit', 'cancel'])
    expect(availableActions('SUBMITTED', all)).toEqual(['approve', 'cancel'])
    expect(availableActions('APPROVED', all)).toEqual(['post', 'cancel'])
    expect(availableActions('POSTED', all)).toEqual(['cancel'])
    expect(availableActions('CANCELLED', all)).toEqual([])
  })
  it('leaves out what the person has not been given', () => {
    expect(availableActions('APPROVED', { post: true })).toEqual(['post'])
    expect(availableActions('APPROVED', {})).toEqual([])
  })
})

describe('the quantity in base units', () => {
  const cement = [{ code: 'kg', to_base_factor: 1 }, { code: 'bag', to_base_factor: 50 }]
  it('multiplies by the unit factor', () => expect(baseQty('3', 'bag', cement)).toBe('150.000'))
  it('shows nothing for a blank, a half-typed number or an unknown unit', () => {
    expect(baseQty('', 'bag', cement)).toBeNull()
    expect(baseQty('3.', 'bag', cement)).toBe('150.000')
    expect(baseQty('3', 'MT', cement)).toBeNull()
  })
})

describe('the Store module in the menu and the page notes', () => {
  const canWith = (...held: string[]) => (perm: string) => perm.split('|').some((p) => held.includes(p))
  const storeItems = (held: string[]) => {
    const g = visibleNav(canWith('store.view', ...held), true).find((e) => e.kind === 'group' && e.id === 'store')
    return g && g.kind === 'group' ? g.items.map((i) => i.path) : []
  }
  it('shows the hub to anyone who may open one of its parts', () => {
    expect(storeItems(['store.inward.view'])).toContain('/store/hub')
    expect(storeItems([])).not.toContain('/store/hub')
  })
  it('explains every address beneath a part', () => {
    expect(infoFor('/store/hub/inward/grn/12')).toBe(infoFor('/store/hub/inward/*'))
    expect(infoFor('/store/hub/inward/grn/12')).not.toBe('')
  })
})

describe('moving through the item list with the keys', () => {
  it('goes down and up, and wraps round', () => {
    expect(nextIndex(-1, 'ArrowDown', 3)).toBe(0)
    expect(nextIndex(2, 'ArrowDown', 3)).toBe(0)
    expect(nextIndex(0, 'ArrowUp', 3)).toBe(2)
    expect(nextIndex(1, 'Home', 3)).toBe(0)
    expect(nextIndex(1, 'End', 3)).toBe(2)
  })
  it('has nothing to highlight in an empty list', () => expect(nextIndex(0, 'ArrowDown', 0)).toBe(-1))
})

describe('how units are shown', () => {
  const cement = { base_uom: 'kg', uoms: [{ code: 'kg', to_base_factor: 1 }, { code: 'bag', to_base_factor: 50 }, { code: 'MT', to_base_factor: 1000 }] }
  it('lists the other units an item can be entered in', () => {
    expect(unitsLine(cement)).toBe('kg · also bag, MT')
    expect(unitsLine({ base_uom: 'cum', uoms: [{ code: 'cum', to_base_factor: 1 }] })).toBe('cum')
  })
  it('says what one of the unit is', () => {
    expect(unitHint('bag', 'kg', cement.uoms)).toBe('1 bag = 50 kg')
    expect(unitHint('nos', 'kg', [{ code: 'nos', to_base_factor: 10.666667 }])).toBe('1 nos = 10.667 kg')
    expect(unitHint('kg', 'kg', cement.uoms)).toBeNull()
  })
  it('takes a quantity typed with thousands commas, and nothing else', () => {
    expect(cleanQty('1,000.5')).toBe('1000.5')
    expect(cleanQty('12.3456')).toBeNull()
    expect(cleanQty('abc')).toBeNull()
  })
  it('names a store with its type', () => expect(storeLabel({ code: 'ST01', name: 'Tower A', type: 'SITE' })).toBe('ST01 - Tower A (site)'))
})
