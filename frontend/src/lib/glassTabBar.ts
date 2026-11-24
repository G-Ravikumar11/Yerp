import { useEffect, useRef, useState } from 'react'
import { Capacitor, registerPlugin, type PluginListenerHandle } from '@capacitor/core'

/**
 * The iPhone app's bottom bar as native Liquid Glass (the YerpGlass plugin, mobile/plugins/yerp-glass, which uses
 * LiquidGlassKit). Only the iOS app that was built with that plugin has it: a browser, the Android app and an iPhone app
 * from before the plugin all keep the web bar (app-mobile/TabBar.tsx), so nothing here changes them.
 */
interface YerpGlassPlugin {
  showTabBar(options: { tabs: NativeTab[]; selected: string; actionTitle?: string }): Promise<{ height: number }>
  select(options: { id: string }): Promise<void>
  setBadge(options: { id: string; count: number }): Promise<void>
  setVisible(options: { visible: boolean }): Promise<void>
  hideTabBar(): Promise<void>
  addListener(event: 'tabSelected', listener: (e: { id: string }) => void): Promise<PluginListenerHandle>
  addListener(event: 'actionTapped', listener: () => void): Promise<PluginListenerHandle>
}

export interface NativeTab { id: string; title: string; symbol: string; badge?: string }

/** The four tabs: the id the native bar reports, where it goes, its name, and the SF Symbol drawn for it. */
export const NATIVE_TABS = [
  { id: 'home', path: '/', title: 'Home', symbol: 'house' },
  { id: 'projects', path: '/projects', title: 'Projects', symbol: 'folder' },
  { id: 'approvals', path: '/approvals', title: 'Approvals', symbol: 'checkmark.circle' },
  { id: 'more', path: '/more', title: 'Menu', symbol: 'square.grid.2x2' },
] as const

/** The tab a screen belongs to ('' for none): a project's own page still lights Projects, like the web bar does. */
export function tabIdFor(pathname: string): string {
  if (pathname === '/') return 'home'
  for (const tab of NATIVE_TABS) if (tab.path !== '/' && (pathname === tab.path || pathname.startsWith(`${tab.path}/`))) return tab.id
  return ''
}

export function pathForTab(id: string): string {
  return NATIVE_TABS.find((tab) => tab.id === id)?.path ?? ''
}

const plugin = registerPlugin<YerpGlassPlugin>('YerpGlass')

/** True only inside the iPhone app, and only when it was built with the glass plugin. */
export const hasGlassTabBar = () => Capacitor.getPlatform() === 'ios' && Capacitor.isPluginAvailable('YerpGlass')

interface Options {
  pathname: string
  waiting: number
  /** The sheet the + opens is showing: the bar steps aside so it is not drawn over the sheet. */
  covered: boolean
  go: (to: string) => void
  onAdd: () => void
}

export interface NativeBar {
  /** Draw the web bar: not the iPhone app with the plugin, or the plugin could not put its bar up. */
  webBar: boolean
  /** The native bar's height in pixels once it is up (so the screen can leave room for it), else 0. */
  height: number
}

/**
 * Shows the native bar for as long as the phone shell is on screen and keeps it in step with the screen. While it is
 * being put up the web bar stays hidden (no flash of the wrong bar); if it cannot be, the web bar takes over.
 */
export function useNativeTabBar({ pathname, waiting, covered, go, onAdd }: Options): NativeBar {
  const [native] = useState(hasGlassTabBar)
  const [status, setStatus] = useState<'pending' | 'up' | 'failed'>('pending')
  const [height, setHeight] = useState(0)
  const selected = tabIdFor(pathname)
  // Taps are answered with the latest of these, whatever they were when the bar went up.
  const latest = useRef({ go, onAdd })
  useEffect(() => { latest.current = { go, onAdd } })
  const first = useRef({ selected, waiting })

  // Up on mount, away on unmount.
  useEffect(() => {
    if (!native) return
    let gone = false
    const handles: PluginListenerHandle[] = []
    void (async () => {
      try {
        handles.push(await plugin.addListener('tabSelected', ({ id }) => { const to = pathForTab(id); if (to) latest.current.go(to) }))
        handles.push(await plugin.addListener('actionTapped', () => latest.current.onAdd()))
        const { selected: now, waiting: count } = first.current
        const tabs: NativeTab[] = NATIVE_TABS.map(({ id, title, symbol }) => ({ id, title, symbol, ...(id === 'approvals' && count > 0 ? { badge: count > 9 ? '9+' : String(count) } : {}) }))
        const shown = await plugin.showTabBar({ tabs, selected: now, actionTitle: 'Add a record' })
        if (gone) return
        setHeight(Math.round(shown.height))
        setStatus('up')
      } catch {
        if (!gone) setStatus('failed')
      }
    })()
    return () => {
      gone = true
      handles.forEach((h) => void h.remove())
      void plugin.hideTabBar().catch(() => undefined)
    }
  }, [native])

  const up = native && status === 'up'
  useEffect(() => { if (up) void plugin.select({ id: selected }).catch(() => undefined) }, [up, selected])
  useEffect(() => { if (up) void plugin.setBadge({ id: 'approvals', count: waiting }).catch(() => undefined) }, [up, waiting])
  useEffect(() => { if (up) void plugin.setVisible({ visible: !covered }).catch(() => undefined) }, [up, covered])

  return { webBar: !native || status === 'failed', height: up ? height : 0 }
}
