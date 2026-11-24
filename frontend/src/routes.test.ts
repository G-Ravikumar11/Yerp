import { describe, expect, it } from 'vitest'
import { REDIRECTS, SCREENS } from './routes'
import { trailFor, visibleNav } from './lib/nav'

/** The addresses a screen answers: a path, with `/*` and `:id` standing for anything. */
const answers = (address: string) => SCREENS.some(({ path }) => new RegExp('^' + path.replace(/\/\*$/, '(/.*)?').replace(/:[^/]+/g, '[^/]+') + '$').test(address))
const redirectOf = (address: string) => REDIRECTS.find((r) => r.from === address || (r.from.endsWith('/*') && address.startsWith(r.from.slice(0, -1))))

describe('the old store is removed', () => {
  it('has no screen and no redirect under /store/old: its addresses get the 404 page', () => {
    expect(SCREENS.filter((s) => s.path.startsWith('/store/old'))).toEqual([])
    expect(REDIRECTS.filter((r) => r.from.startsWith('/store/old'))).toEqual([])
    for (const address of ['/store/old/stock', '/store/old/goods-receipt', '/store/old/material-vouchers', '/store/old/material-costing', '/store/old/anything/else']) {
      expect(redirectOf(address), address).toBeUndefined()
      expect(answers(address), address).toBe(false)
    }
  })

  it('never redirects to a redirect, to itself or to a screen that does not exist: no loop, no blank page', () => {
    for (const { from, to } of REDIRECTS) {
      expect(to, `${from} -> ${to}`).not.toBe(from)
      expect(redirectOf(to), `${from} lands on ${to}, which redirects again`).toBeUndefined()
      expect(answers(to), `${from} lands on ${to}, which no screen answers`).toBe(true)
      expect(to.startsWith('/store/old') || to.includes('/old-store'), `${from} -> ${to}`).toBe(false)
    }
  })

  it('keeps the earlier moved addresses working', () => {
    for (const from of ['/store/goods-receipt', '/store/stock', '/store/material-vouchers', '/store/material-costing', '/store/desk']) expect(redirectOf(from), from).toBeTruthy()
  })

  it('has no menu entry or breadcrumb for the old store', () => {
    const paths = visibleNav(() => true, false).flatMap((e) => (e.kind === 'group' ? e.items.map((i) => i.path) : [e.path]))
    expect(paths.filter((p) => p.startsWith('/store/old') || p.includes('old-store'))).toEqual([])
    expect(trailFor('/store/old/stock').map((t) => t.label)).toEqual(['Home', 'Not found'])
  })

  it('still serves the Store Hub reports, the budget report among them', () => {
    expect(answers('/store/hub/reports/budget-use')).toBe(true)
  })
})
