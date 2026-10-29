import { describe, expect, it } from 'vitest'
import { visibleNav } from './nav'

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
  it('gives the Master every portal', () => {
    const everything = () => true
    const ids = visibleNav(everything, false).filter((e) => e.kind === 'group').map((e) => e.id)
    expect(ids).toEqual(expect.arrayContaining(['projects', 'clients', 'subcontractors', 'store', 'money', 'people']))
  })
})
