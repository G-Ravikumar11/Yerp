import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

// A stand-in for the native plugin: what the web app asks of it, and the taps it can send back.
const native = vi.hoisted(() => {
  const listeners = new Map<string, (e?: { id: string }) => void>()
  const calls: Array<[string, unknown]> = []
  const plugin = {
    addListener: vi.fn(async (event: string, fn: (e?: { id: string }) => void) => { listeners.set(event, fn); return { remove: vi.fn(async () => { listeners.delete(event) }) } }),
    showTabBar: vi.fn(async (o: unknown) => { calls.push(['showTabBar', o]); return { height: 70.4 } }),
    select: vi.fn(async (o: unknown) => { calls.push(['select', o]) }),
    setBadge: vi.fn(async (o: unknown) => { calls.push(['setBadge', o]) }),
    setVisible: vi.fn(async (o: unknown) => { calls.push(['setVisible', o]) }),
    hideTabBar: vi.fn(async () => { calls.push(['hideTabBar', null]) }),
  }
  return { listeners, calls, plugin, platform: 'ios', available: true }
})

vi.mock('@capacitor/core', () => ({
  Capacitor: { getPlatform: () => native.platform, isPluginAvailable: () => native.available },
  registerPlugin: () => native.plugin,
}))

import { NATIVE_TABS, pathForTab, tabIdFor, useNativeTabBar } from './glassTabBar'

describe('which tab a screen belongs to', () => {
  it('names the four tabs and lights the one a sub-screen sits under', () => {
    expect(tabIdFor('/')).toBe('home')
    expect(tabIdFor('/projects')).toBe('projects')
    expect(tabIdFor('/projects/12/diary')).toBe('projects')
    expect(tabIdFor('/approvals')).toBe('approvals')
    expect(tabIdFor('/more')).toBe('more')
  })
  it('lights none for a screen outside the tabs, and does not mistake a longer first word', () => {
    expect(tabIdFor('/people/attendance')).toBe('')
    expect(tabIdFor('/projectsarchive')).toBe('')
  })
  it('sends each tab to its own path, and an unknown id nowhere', () => {
    for (const t of NATIVE_TABS) expect(pathForTab(t.id)).toBe(t.path)
    expect(pathForTab('nope')).toBe('')
  })
})

describe('the native bar from the phone shell', () => {
  const go = vi.fn()
  const onAdd = vi.fn()
  const opts = (over: Partial<Parameters<typeof useNativeTabBar>[0]> = {}) => ({ pathname: '/', waiting: 0, covered: false, go, onAdd, ...over })

  beforeEach(() => {
    native.platform = 'ios'
    native.available = true
    native.listeners.clear()
    native.calls.length = 0
    vi.clearAllMocks()
  })

  it('leaves the web bar alone in a browser, on Android, and in an iPhone app without the plugin', () => {
    for (const [platform, available] of [['web', false], ['android', false], ['ios', false]] as const) {
      native.platform = platform
      native.available = available
      const { result } = renderHook(() => useNativeTabBar(opts()))
      expect(result.current).toEqual({ webBar: true, height: 0 })
    }
    expect(native.plugin.showTabBar).not.toHaveBeenCalled()
  })

  it('puts the bar up with the open tab and the approvals count, and gives back its height', async () => {
    const { result } = renderHook(() => useNativeTabBar(opts({ pathname: '/projects/3', waiting: 12 })))
    // Until it is up neither bar is drawn, so the wrong one never flashes.
    expect(result.current).toEqual({ webBar: false, height: 0 })
    await waitFor(() => expect(result.current.height).toBe(70))
    expect(result.current.webBar).toBe(false)
    const shown = native.calls.find(([name]) => name === 'showTabBar')?.[1] as { tabs: Array<{ id: string; badge?: string }>; selected: string; actionTitle: string }
    expect(shown.selected).toBe('projects')
    expect(shown.actionTitle).toBe('Add a record')
    expect(shown.tabs.map((t) => t.id)).toEqual(['home', 'projects', 'approvals', 'more'])
    expect(shown.tabs.find((t) => t.id === 'approvals')?.badge).toBe('9+')
  })

  it('falls back to the web bar when the plugin cannot draw its bar', async () => {
    native.plugin.showTabBar.mockRejectedValueOnce(new Error('no view'))
    const { result } = renderHook(() => useNativeTabBar(opts()))
    await waitFor(() => expect(result.current).toEqual({ webBar: true, height: 0 }))
  })

  it('follows the screen, the count and the sheet once it is up', async () => {
    const { result, rerender } = renderHook((p: Parameters<typeof useNativeTabBar>[0]) => useNativeTabBar(p), { initialProps: opts() })
    await waitFor(() => expect(result.current.height).toBe(70))
    native.calls.length = 0
    rerender(opts({ pathname: '/approvals', waiting: 3, covered: true }))
    await waitFor(() => expect(native.calls.map(([n]) => n).sort()).toEqual(['select', 'setBadge', 'setVisible']))
    expect(native.calls).toContainEqual(['select', { id: 'approvals' }])
    expect(native.calls).toContainEqual(['setBadge', { id: 'approvals', count: 3 }])
    expect(native.calls).toContainEqual(['setVisible', { visible: false }])
  })

  it('answers a tab tap by going there, and the + by opening the sheet, with the latest handlers', async () => {
    const first = vi.fn()
    const { result, rerender } = renderHook((p: Parameters<typeof useNativeTabBar>[0]) => useNativeTabBar(p), { initialProps: opts({ go: first }) })
    await waitFor(() => expect(result.current.height).toBe(70))
    const later = vi.fn()
    rerender(opts({ go: later }))
    act(() => native.listeners.get('tabSelected')?.({ id: 'more' }))
    expect(later).toHaveBeenCalledWith('/more')
    expect(first).not.toHaveBeenCalled()
    act(() => native.listeners.get('tabSelected')?.({ id: 'bogus' }))
    expect(later).toHaveBeenCalledTimes(1)
    act(() => native.listeners.get('actionTapped')?.())
    expect(onAdd).toHaveBeenCalledTimes(1)
  })

  it('takes the bar down when the shell goes', async () => {
    const { result, unmount } = renderHook(() => useNativeTabBar(opts()))
    await waitFor(() => expect(result.current.height).toBe(70))
    unmount()
    expect(native.plugin.hideTabBar).toHaveBeenCalled()
    await waitFor(() => expect(native.listeners.size).toBe(0))
  })
})
