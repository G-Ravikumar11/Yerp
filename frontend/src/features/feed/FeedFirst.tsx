import type { ElementType } from 'react'
import { Navigate } from 'react-router-dom'
import { appUi } from '@/app-mobile/gate'
import { FEED_SEEN } from '@/api/feed'

function seen(): boolean {
  try { return sessionStorage.getItem(FEED_SEEN) === '1' } catch { return true }       // no storage: do not keep sending people back
}

/**
 * The front page, except that the first time in a session - signing in, or opening the app - it is the Feed instead.
 * The Feed marks itself seen, so the front page is the front page again after that, and a bookmarked screen is never redirected.
 * The phone app has its own front page and keeps it.
 */
export function FeedFirst({ Home }: { Home: ElementType }) {
  if (!appUi() && !seen()) return <Navigate to="/feed" replace />
  return <Home />
}
