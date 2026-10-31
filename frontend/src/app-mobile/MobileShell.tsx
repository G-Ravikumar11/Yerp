import { Suspense, useEffect, useState } from 'react'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'
import { ChevronLeft } from 'lucide-react'
import { Button, Skeleton } from '@/components/ui'
import { CompanyNotice } from '@/components/company/CompanyNotice'
import { PageErrorBoundary } from '@/components/layout/PageErrorBoundary'
import { registerPush } from '@/lib/mobile'
import { trailFor } from '@/lib/nav'
import { appUrl } from '@/lib/paths'
import { useSession } from '@/lib/session'
import { cn } from '@/lib/utils'
import { AddSheet } from './AddSheet'
import { TabBar } from './TabBar'
import './app-theme.css'

/** The four places the tab bar goes to: these screens are tabs. Every other screen gets a back bar and a title. */
const TABS = new Set(['/', '/projects', '/approvals', '/more'])
const TAB_TITLES: Record<string, string> = { '/': 'Home', '/projects': 'Projects', '/approvals': 'Approvals', '/more': 'Menu' }

/**
 * The frame of the phone app, in place of the website's sidebar and top bar: the screen, a bottom tab bar, and the
 * sheet the + opens. Only the installed app (and a browser asked for it) draws this; the website never does.
 */
export default function MobileShell() {
  const { pathname } = useLocation()
  const go = useNavigate()
  const { isLoading, isAnonymous, error, user } = useSession()
  const [adding, setAdding] = useState(false)
  const isTab = TABS.has(pathname)
  const title = TAB_TITLES[pathname] ?? trailFor(pathname, user?.type === 'employee').at(-1)?.label ?? ''

  useEffect(() => {
    document.title = `${title || 'Y ERP'} - Y ERP`
  }, [title])
  // The phone app's look (app-theme.css) is scoped to this class on <html>, so a dialog that opens outside this element is
  // restyled with the rest, and it goes the moment the shell does.
  useEffect(() => {
    document.documentElement.classList.add('app-ui')
    return () => document.documentElement.classList.remove('app-ui')
  }, [])
  useEffect(() => {
    if (isAnonymous && (import.meta.env.PROD || import.meta.env.VITE_API_BASE_URL)) window.location.assign(appUrl('login'))
  }, [isAnonymous])
  useEffect(() => {
    if (!isLoading && !isAnonymous) void registerPush()
  }, [isLoading, isAnonymous])
  useEffect(() => {
    window.scrollTo({ top: 0 })
    setAdding(false)
  }, [pathname])

  return (
    // --tabbar is the height of the bottom bar: shorter when the phone is turned on its side, so the screen keeps its room.
    // The sides keep clear of a camera cut-out or a fold (the safe-area insets), which only show up when turned.
    <div className="relative isolate min-h-dvh [--tabbar:78px] [@media(max-height:480px)]:[--tabbar:70px]">
      {!isTab && (
        <header className="sticky top-0 z-30 flex h-12 items-center gap-1 border-b border-border bg-[var(--app-glass)] backdrop-blur-xl pl-[max(0.5rem,env(safe-area-inset-left))] pr-[max(0.5rem,env(safe-area-inset-right))]">
          <button type="button" onClick={() => (window.history.length > 1 ? go(-1) : go('/'))} className="flex h-10 items-center gap-0.5 rounded-xl pl-1 pr-3 text-[15px] font-medium text-primary active:opacity-60">
            <ChevronLeft className="size-6" />Back
          </button>
          <span className="min-w-0 flex-1 truncate pr-14 text-center text-[15px] font-semibold">{title}</span>
        </header>
      )}
      <main id="main" className={cn(
          'mx-auto w-full pl-[max(1rem,env(safe-area-inset-left))] pr-[max(1rem,env(safe-area-inset-right))] pb-[calc(var(--tabbar)+32px+env(safe-area-inset-bottom))]',
          // The four tabs read as one column that widens with the screen (phone, large phone, tablet, unfolded); every other
          // screen is the website's own and takes the whole width, up to a size where a line would be too long to follow.
          isTab ? 'max-w-xl pt-3 md:max-w-3xl xl:max-w-5xl' : 'min-w-0 max-w-[1600px] overflow-x-clip pt-4',
        )}>
        {!isLoading && !isAnonymous && !pathname.startsWith('/settings') && pathname === '/more' && <CompanyNotice />}
        {isLoading ? (
          <div className="space-y-4" role="status" aria-label="Loading"><Skeleton className="h-9 w-48" /><Skeleton className="h-48 w-full rounded-lg" /></div>
        ) : isAnonymous || error ? (
          <div className="py-24 text-center">
            <h1 className="text-2xl font-semibold">{error ? 'Could not reach the server' : 'Please sign in'}</h1>
            <p className="mt-2 text-[15px] text-muted-foreground">{error ? 'Check the connection and try again.' : 'Your session has ended, or you have not signed in yet.'}</p>
            <Button asChild className="mt-6"><a href={appUrl('login')}>Go to sign in</a></Button>
          </div>
        ) : (
          <PageErrorBoundary resetKey={pathname}>
            <Suspense fallback={<div className="space-y-4" role="status" aria-label="Loading"><Skeleton className="h-9 w-48" /><Skeleton className="h-64 w-full rounded-lg" /></div>}>
              <Outlet />
            </Suspense>
          </PageErrorBoundary>
        )}
      </main>
      <TabBar onAdd={() => setAdding(true)} />
      <AddSheet open={adding} onClose={() => setAdding(false)} />
    </div>
  )
}
