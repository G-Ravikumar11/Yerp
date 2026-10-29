import { Suspense, useEffect } from 'react'
import { Outlet, useLocation } from 'react-router-dom'
import { motion } from 'framer-motion'
import { trailFor } from '@/lib/nav'
import { useSession } from '@/lib/session'
import { registerPush } from '@/lib/mobile'
import { useUI } from '@/stores/ui'
import { Button, Skeleton } from '@/components/ui'
import { CompanyNotice } from '@/components/company/CompanyNotice'
import { PageErrorBoundary } from './PageErrorBoundary'
import { ErrorPage } from '@/components/errors/ErrorPage'
import { useErrorPage } from '@/stores/errorPage'
import { Sidebar, SIDEBAR_COLLAPSED, SIDEBAR_WIDTH } from './Sidebar'
import { Topbar } from './Topbar'
import { NotificationPopups } from './NotificationPopups'
import { appUrl } from '@/lib/paths'
import { ApiError } from '@/lib/api'

/**
 * The frame every screen sits in: rail, top bar, and a content area whose page
 * eases in on each navigation. The left padding follows the rail's width so
 * collapsing it hands the space to the page rather than leaving a gap.
 */
export function AppShell() {
  const { pathname } = useLocation()
  const collapsed = useUI((s) => s.sidebarCollapsed)
  const { isLoading, isAnonymous, error, user } = useSession()
  // The tab and the history say where you are, and a screen reader hears the change.
  useEffect(() => {
    const trail = trailFor(pathname, user?.type === 'employee')
    document.title = `${trail[trail.length - 1].label} - Y ERP`
  }, [pathname, user?.type])

  // Signed out: go to the sign-in page rather than draw a page full of failures.
  useEffect(() => {
    if (isAnonymous && (import.meta.env.PROD || import.meta.env.VITE_API_BASE_URL)) {
      window.location.assign(appUrl('login'))
    }
  }, [isAnonymous])

  // In the native app, a signed-in phone is offered notifications.
  useEffect(() => {
    if (!isLoading && !isAnonymous) void registerPush()
  }, [isLoading, isAnonymous])

  // A new page starts at its top, as a page does.
  useEffect(() => {
    window.scrollTo({ top: 0 })
  }, [pathname])

  // A failed save's error page belongs to the screen it happened on: going somewhere else closes it.
  const shownError = useErrorPage((s) => s.shown)
  const clearError = useErrorPage((s) => s.clear)
  useEffect(() => {
    clearError()
  }, [pathname, clearError])

  return (
    <div className="relative isolate min-h-dvh">
      {shownError && <ErrorPage overlay kind={shownError.kind} code={shownError.code} errorRef={shownError.ref} message={shownError.message} onBack={clearError} />}
      <a
        href="#main"
        className="sr-only z-[60] rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground focus:not-sr-only focus:fixed focus:left-4 focus:top-4"
      >
        Skip to content
      </a>
      <Sidebar />
      <motion.div
        initial={false}
        animate={{ paddingLeft: collapsed ? SIDEBAR_COLLAPSED : SIDEBAR_WIDTH }}
        transition={{ type: 'spring', stiffness: 420, damping: 40 }}
        className="max-lg:!pl-0"
      >
        <Topbar />
        <NotificationPopups />
        <main id="main" className="mx-auto w-full min-w-0 max-w-[1600px] overflow-x-clip px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
          <div key={pathname}>
            {!isLoading && !isAnonymous && !pathname.startsWith('/settings') && <CompanyNotice />}
            {isLoading ? (
              <div className="space-y-4" role="status" aria-label="Loading">
                <Skeleton className="h-9 w-64" />
                <Skeleton className="h-4 w-96 max-w-full" />
                <Skeleton className="mt-6 h-64 w-full" />
              </div>
            ) : error ? (
              // Who is signed in could not be asked: the server is down, busy or unreachable. The whole page says so.
              <ErrorPage
                kind={error instanceof ApiError ? (error.code.startsWith('YE-BUSY') ? 'busy' : 'server') : 'offline'}
                code={error instanceof ApiError ? error.code : 'YE-NET'}
                errorRef={error instanceof ApiError ? error.ref : undefined}
                onRetry={() => window.location.reload()}
              />
            ) : isAnonymous ? (
              <div className="mx-auto max-w-md py-24 text-center">
                <h1 className="text-2xl font-semibold">Please sign in</h1>
                <p className="mt-2 text-[15px] text-muted-foreground">Your session has ended, or you have not signed in yet.</p>
                <Button asChild className="mt-6">
                  <a href={appUrl('login')}>Go to sign in</a>
                </Button>
              </div>
            ) : (
              <PageErrorBoundary resetKey={pathname}>
              <Suspense
                fallback={
                  <div className="space-y-4" role="status" aria-label="Loading">
                    <Skeleton className="h-9 w-64" />
                    <Skeleton className="h-72 w-full" />
                  </div>
                }
              >
                <Outlet />
              </Suspense>
              </PageErrorBoundary>
            )}
          </div>
        </main>
      </motion.div>
    </div>
  )
}
