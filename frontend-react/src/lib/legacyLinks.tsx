import { useEffect } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'

// Saved links, bookmarks and installed shortcuts from the earlier interface named a screen by a #word after /app.html.
// The server forwards that address here with the #word kept, and this sends it to the screen it meant.
const SCREENS: Record<string, string> = {
  '#approvals': '/approvals',
  '#subcontracts': '/subcontractors/work-orders',
  '#vendors': '/subcontractors/vendors',
  '#diary-view': '/projects/diary',
  '#chat-view': '/projects/chat',
  '#drawings-view': '/projects/drawings',
}

export function LegacyLinks() {
  const { pathname, hash } = useLocation()
  const navigate = useNavigate()
  useEffect(() => {
    const to = SCREENS[hash]
    if (pathname === '/' && to) navigate(to, { replace: true })
  }, [pathname, hash, navigate])
  return null
}
