import { describe, expect, it } from 'vitest'
import { REDIRECTS, SCREENS } from './routes'
import { trailFor, visibleNav } from './lib/nav'

/** The addresses a screen answers: a path, with `/*` and `:id` standing for anything. */
const answers = (address: string) => SCREENS.some(({ path }) => new RegExp('^' + path.replace(/\/\*$/, '(/.*)?').replace(/:[^/]+/g, '[^/]+') + '$').test(address))
const redirectOf = (address: string) => REDIRECTS.find((r) => r.from === address || (r.from.endsWith('/*') && address.startsWith(r.from.slice(0, -1))))

describe('the old store is retired', () => {
  it('has no screen of its own under /store/old', () => {
    expect(SCREENS.filter((s) => s.path.startsWith('/store/old'))).toEqual([])
  })

  it('sends each old address to the Store Hub screen that holds what it held, and anything else under /store/old to the Store page', () => {
    expect(redirectOf('/store/old/stock')?.to).toBe('/store/hub/reports/old-store')
    expect(redirectOf('/store/old/goods-receipt')?.to).toBe('/store/hub/reports/old-store/receipts')
    expect(redirectOf('/store/old/material-vouchers')?.to).toBe('/store/hub/reports/old-store/vouchers')
    expect(redirectOf('/store/old/material-costing')?.to).toBe('/store/hub/reports/budget-use')
    expect(redirectOf('/store/old/anything/else')?.to).toBe('/store')
  })

  it('never redirects to a redirect, to itself or to a screen that does not exist: no loop, no blank page', () => {
    for (const { from, to } of REDIRECTS) {
      expect(to, `${from} -> ${to}`).not.toBe(from)
      expect(redirectOf(to), `${from} lands on ${to}, which redirects again`).toBeUndefined()
      expect(answers(to), `${from} lands on ${to}, which no screen answers`).toBe(true)
    }
  })

  it('keeps the earlier moved addresses working', () => {
    for (const from of ['/store/goods-receipt', '/store/stock', '/store/material-vouchers', '/store/material-costing', '/store/desk']) expect(redirectOf(from), from).toBeTruthy()
  })

  it('has no menu entry or breadcrumb for the old store', () => {
    const paths = visibleNav(() => true, false).flatMap((e) => (e.kind === 'group' ? e.items.map((i) => i.path) : [e.path]))
    expect(paths.filter((p) => p.startsWith('/store/old'))).toEqual([])
    expect(trailFor('/store/old/stock').map((t) => t.label)).toEqual(['Home', 'Not found'])             // nothing answers it; the redirect catches it first
    expect(trailFor('/store/hub/reports/old-store/receipts').map((t) => t.label)).toEqual(['Home', 'Store', 'Full store (Hub)', 'Details'])
  })

  it('serves the Store Hub reports, where the old store records and the budget report now live', () => {
    expect(answers('/store/hub/reports/old-store')).toBe(true)
    expect(answers('/store/hub/reports/old-store/vouchers')).toBe(true)
    expect(answers('/store/hub/reports/budget-use')).toBe(true)
  })
})
