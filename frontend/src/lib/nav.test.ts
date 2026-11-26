import { describe, expect, it } from 'vitest'
import { matchRoutes } from 'react-router-dom'
import { TILES } from '@/app-mobile/AddSheet'
import { TABS, TAB_TITLES } from '@/app-mobile/tabs'
import { SCREENS } from '@/routes'
import { linkTarget } from './deepLink'
import { trailFor, visibleNav } from './nav'
import { infoFor } from './pageInfo'

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
    expect(groups(['store.view', 'purchase.manage'])).toEqual(['store'])
    expect(groups(['subcontractors.view'])).toEqual(['subcontractors'])
    expect(groups(['clients.view', 'customers.manage'])).toEqual(['clients'])
    expect(groups(['people.manage'])).toEqual(['people'])
  })
  it('still asks a screen for its own right inside a portal', () => {
    const money = visibleNav(canWith('money.view'), true).find((e) => e.kind === 'group' && e.id === 'money')
    expect(money).toBeUndefined() // every Money screen also needs View all bills
  })
  it('opens Settings to staff only with "Manage website", and always to the Master', () => {
    const settings = (can: (p: string) => boolean, staff: boolean) => visibleNav(can, staff).some((e) => e.kind === 'link' && e.id === 'settings')
    expect(settings(canWith('people.manage', 'projects.view', 'bills.view_all'), true)).toBe(false)
    expect(settings(canWith('website.manage'), true)).toBe(true)
    expect(settings(() => true, false)).toBe(true)
  })
  it('gives the Master every portal', () => {
    const everything = () => true
    const ids = visibleNav(everything, false).filter((e) => e.kind === 'group').map((e) => e.id)
    expect(ids).toEqual(expect.arrayContaining(['projects', 'clients', 'subcontractors', 'store', 'money', 'people']))
  })
  it('gives the store its numbered steps, shown to whoever has the Store portal and something to do in it', () => {
    const store = (held: string[]) => visibleNav(canWith(...held), true).some((e) => e.kind === 'group' && e.id === 'store')
    expect(store(['store.view', 'purchase.manage'])).toBe(true)          // purchase
    expect(store(['store.view', 'store.inward.view'])).toBe(true)        // a storekeeper
    expect(store(['purchase.manage'])).toBe(false)                       // no Store portal
    expect(store(['store.view'])).toBe(false)                            // the portal, and nothing in it
  })
  it('keeps a store screen under Store in the path shown at the top', () => {
    expect(trailFor('/store/purchase-orders').map((t) => t.label)).toEqual(['Home', 'Store', '3. Buy (Purchase Order)'])
    expect(trailFor('/store/enquiries/4').map((t) => t.label)).toEqual(['Home', 'Store', 'Supplier Quotes', 'Details'])
    expect(trailFor('/store/hub/outward/indent/7').map((t) => t.label)).toEqual(['Home', 'Store', '5. Material Request', 'Details'])
    expect(trailFor('/store/hub/inward/grn').map((t) => t.label)).toEqual(['Home', 'Store', 'All Store Screens', 'Details'])
    expect(trailFor('/store/receive').map((t) => t.label)).toEqual(['Home', 'Store', '4. Receive Material'])
    expect(trailFor('/store').map((t) => t.label)).toEqual(['Home', 'Store', 'Store Home'])
  })
  it('lists the store work as numbered steps in the order it is done', () => {
    const store = visibleNav(() => true, false).find((e) => e.kind === 'group' && e.id === 'store')
    const labels = store && store.kind === 'group' ? store.items.map((i) => i.label) : []
    expect(labels.slice(0, 9)).toEqual(['Store Home', '1. Items', '2. Item Sheet', '3. Buy (Purchase Order)', '4. Receive Material', '5. Material Request',
      '6. Issue Material', '7. Return Material', '8. Stock'])
  })
  it('gives everybody the Feed, which holds the celebrations, whatever they hold and wherever they land', () => {
    const has = (entries: ReturnType<typeof visibleNav>) => entries.some((e) => e.kind === 'link' && e.path === '/feed')
    expect(has(visibleNav(canWith(), true))).toBe(true)                    // staff with no rights at all
    expect(has(visibleNav(canWith('ho.view_all'), true, true))).toBe(true) // head office
    expect(has(visibleNav(() => true, false))).toBe(true)                  // the Master
  })
})

// ---- the phone layout: its tabs, its + sheet and the links notices carry must all lead to a screen that exists -------------
describe('the phone layout agrees with the menu, the routes and the page info', () => {
  const screens = [...SCREENS.map((s) => ({ path: s.path })), { path: '/more' }] // /more is the phone's own (app-mobile/entry.tsx)
  const routed = (path: string) => path === '/' || !!matchRoutes(screens, path.split(/[?#]/)[0])

  it('has a screen, a title and a line of page info for each tab, and titles exactly the tabs', () => {
    expect([...TABS].sort()).toEqual(Object.keys(TAB_TITLES).sort())
    for (const tab of TABS) expect([tab, routed(tab), !!infoFor(tab)]).toEqual([tab, true, true])
  })

  it('sends every + sheet tile, on a site or on none, to a screen that exists and says what it is for', () => {
    expect(TILES.length).toBeGreaterThan(0)
    for (const tile of TILES) {
      for (const site of [0, 7]) {
        const target = tile.to(site)
        expect([tile.label, target, routed(target), !!infoFor(target.split(/[?#]/)[0])]).toEqual([tile.label, target, true, true])
      }
    }
    expect(new Set(TILES.map((t) => t.label)).size).toBe(TILES.length)
  })

  it('opens the site the person is on, for each tile that is about one', () => {
    for (const tile of TILES) {
      const url = tile.to(7)
      if (url.includes('?')) expect([tile.label, /(^|[?&])(job|site|project)=7(&|$)/.test(url)]).toEqual([tile.label, true])
    }
  })

  it('has each link the server puts on a notice open a screen of the app', () => {
    // Every "/next/..." link the backend gives notify_employee, tell_approvers and push (with an id where it has one).
    const sent = [
      '/next/approvals', '/next/store/enquiries/12', '/next/store/purchase-orders', '/next/projects/documents', '/next/projects/quality?ncr=3',
      '/next/projects/safety', '/next/projects/drawings', '/next/projects/diary', '/next/projects/chart', '/next/subcontractors/work-orders',
      '/next/subcontractors/vendors', '/next/money/dashboard', '/next/people/attendance', '/next/people/employees',
    ]
    for (const link of sent) expect([link, routed(linkTarget(link))]).toEqual([link, true])
  })
})
