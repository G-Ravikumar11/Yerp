import { describe, expect, it } from 'vitest'
import { visibleNav } from '@/lib/nav'
import { infoFor } from '@/lib/pageInfo'
import { availableActions } from './DocActionsBar'
import { baseQty } from './UomQtyInput'

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
  // The Store menu lists every store screen; "All Store Screens" (the Hub) shows to whoever may open one of its parts.
  const storeTiles = (held: string[]) => {
    const can = canWith('store.view', ...held)
    const store = visibleNav(can, true).find((e) => e.kind === 'group' && e.id === 'store')
    return store && store.kind === 'group' ? store.items.map((i) => i.path) : []
  }
  it('shows the hub to anyone who may open one of its parts', () => {
    expect(storeTiles(['store.inward.view'])).toContain('/store/hub')
    expect(storeTiles([])).not.toContain('/store/hub')
  })
  it('explains every address beneath a part', () => {
    expect(infoFor('/store/hub/inward/grn/12')).toBe(infoFor('/store/hub/inward/*'))
    expect(infoFor('/store/hub/inward/grn/12')).not.toBe('')
  })
})
