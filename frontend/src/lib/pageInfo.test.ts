import { describe, expect, it } from 'vitest'
import { allRoutes } from './nav'
import { SCREENS } from '@/routes'
import { infoFor, PAGE_INFO } from './pageInfo'

describe('every screen says what it is for', () => {
  it('has a few lines for each screen in the menu and each screen that can be opened', () => {
    const paths = [...allRoutes().map((r) => r.path), ...SCREENS.map((s) => s.path), '/']
    expect(paths.filter((p) => !infoFor(p.replace(/:[a-z]+/g, '1')))).toEqual([])
  })
  it('keeps each one short', () => {
    for (const [path, text] of Object.entries(PAGE_INFO)) expect([path, text.length < 260]).toEqual([path, true])
  })
  it('reads a detail page as the one it belongs to', () => {
    expect(infoFor('/projects/12')).toBe(PAGE_INFO['/projects/:id'])
    expect(infoFor('/projects/boq')).toBe(PAGE_INFO['/projects/boq'])
    expect(infoFor('/projects/boq/3')).toBe(PAGE_INFO['/projects/boq/:id'])
    expect(infoFor('/nowhere')).toBe('')
  })
})
