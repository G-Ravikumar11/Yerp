import { afterEach, describe, expect, it, vi } from 'vitest'
import { attachNavigator, linkTarget, openLink } from './deepLink'

describe('the place a notification link means', () => {
  it('takes the website prefix off', () => {
    expect(linkTarget('/next/approvals')).toBe('/approvals')
    expect(linkTarget('/next/projects/documents')).toBe('/projects/documents')
    expect(linkTarget('/next/subcontractors/work-orders?tab=bills#top')).toBe('/subcontractors/work-orders?tab=bills#top')
  })
  it('leaves a path of the app alone, and a bare /next is Home', () => {
    expect(linkTarget('/approvals')).toBe('/approvals')
    expect(linkTarget('/next')).toBe('/')
    expect(linkTarget('/next?x=1')).toBe('/?x=1')
  })
  it('does not mistake a path that merely starts with next', () => {
    expect(linkTarget('/nextgen/plan')).toBe('/nextgen/plan')
  })
  it('refuses anything that is not a path inside the app', () => {
    for (const bad of ['', 'approvals', 'https://evil.example/x', '//evil.example/x', '/\\evil.example', null, undefined, 7, {}]) expect(linkTarget(bad)).toBe('')
  })
})

describe('opening a tapped notification', () => {
  let detach: () => void = () => {}
  afterEach(() => detach())

  it('goes straight there once the app can move', () => {
    const to = vi.fn()
    detach = attachNavigator(to)
    openLink('/next/approvals')
    expect(to).toHaveBeenCalledExactlyOnceWith('/approvals')
  })
  it('keeps a tap that started the app until the shell is ready, then opens it once', () => {
    openLink('/next/store/hub/outward/issue/9')
    const to = vi.fn()
    detach = attachNavigator(to)
    expect(to).toHaveBeenCalledExactlyOnceWith('/store/hub/outward/issue/9')
    detach()
    const again = vi.fn()
    detach = attachNavigator(again)
    expect(again).not.toHaveBeenCalled()
  })
  it('ignores a link that is not for the app', () => {
    const to = vi.fn()
    detach = attachNavigator(to)
    openLink('https://evil.example')
    expect(to).not.toHaveBeenCalled()
  })
})
