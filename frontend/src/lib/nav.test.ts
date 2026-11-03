import { describe, expect, it } from 'vitest'
import { trailFor, visibleNav } from './nav'

const canWith = (...held: string[]) => (perm: string) => perm.split('|').some((p) => held.includes(p))
// Everybody on staff has their own work in the menu, so it is left out of what is compared.
const groups = (held: string[], staff = true) => visibleNav(canWith(...held), staff).filter((e) => e.kind === 'group' && e.id !== 'me').map((e) => e.id)

describe('the menu follows the portals a person holds', () => {
  it('shows site staff their own work and the Projects portal, and nothing else', () => {
    expect(groups(['self.service', 'projects.view'])).toEqual(['projects'])
  })
  it('hides a portal from somebody without its right, whatever else they hold', () => {
    expect(groups(['self.service', 'bills.view_all', 'purchase.manage'])).toEqual([])
  })
  it('shows each portal on its own right', () => {
    expect(groups(['money.view', 'bills.view_all'])).toEqual(['money'])
    expect(groups(['store.view', 'purchase.manage'])).toEqual([])
    expect(groups(['subcontractors.view'])).toEqual(['subcontractors'])
    expect(groups(['clients.view', 'customers.manage'])).toEqual(['clients'])
    expect(groups(['people.manage'])).toEqual(['people'])
  })
  it('still asks a screen for its own right inside a portal', () => {
    const money = visibleNav(canWith('money.view'), true).find((e) => e.kind === 'group' && e.id === 'money')
    expect(money).toBeUndefined() // every Money screen also needs View all bills
  })
  it('gives the Master every portal', () => {
    const everything = () => true
    const ids = visibleNav(everything, false).filter((e) => e.kind === 'group').map((e) => e.id)
    expect(ids).toEqual(expect.arrayContaining(['projects', 'clients', 'subcontractors', 'money', 'people']))
    expect(visibleNav(everything, false).some((e) => e.kind === 'link' && e.id === 'store')).toBe(true)
  })
  it('gives the store one entry, shown to whoever has the Store portal and something to do in it', () => {
    const store = (held: string[]) => visibleNav(canWith(...held), true).some((e) => e.kind === 'link' && e.id === 'store')
    expect(store(['store.view', 'purchase.manage'])).toBe(true)          // purchase
    expect(store(['store.view', 'store.inward.view'])).toBe(true)        // a storekeeper
    expect(store(['purchase.manage'])).toBe(false)                       // no Store portal
    expect(store(['store.view'])).toBe(false)                            // the portal, and nothing in it
  })
  it('keeps a store screen under Store in the path shown at the top', () => {
    expect(trailFor('/store/purchase-orders').map((t) => t.label)).toEqual(['Home', 'Store', 'Purchase Orders'])
    expect(trailFor('/store/enquiries/4').map((t) => t.label)).toEqual(['Home', 'Store', 'Enquiries & Comparison', 'Details'])
    expect(trailFor('/store/hub/inward/grn').map((t) => t.label)).toEqual(['Home', 'Store', 'Full store (Hub)', 'Details'])
    expect(trailFor('/store/receive').map((t) => t.label)).toEqual(['Home', 'Store', 'Material Receive'])
    expect(trailFor('/store').map((t) => t.label)).toEqual(['Home', 'Store'])
  })
  it('gives everybody the Feed, which holds the celebrations, whatever they hold and wherever they land', () => {
    const has = (entries: ReturnType<typeof visibleNav>) => entries.some((e) => e.kind === 'link' && e.path === '/feed')
    expect(has(visibleNav(canWith(), true))).toBe(true)                    // staff with no rights at all
    expect(has(visibleNav(canWith('ho.view_all'), true, true))).toBe(true) // head office
    expect(has(visibleNav(() => true, false))).toBe(true)                  // the Master
  })
})
