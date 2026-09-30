import { Suspense, useEffect } from 'react'
import { Outlet, useLocation } from 'react-router-dom'
import { motion } from 'framer-motion'
import { trailFor } from '@/lib/nav'
import { useSession } from '@/lib/session'
import { useUI } from '@/stores/ui'
import { Button, Skeleton } from '@/components/ui'
import { PageErrorBoundary } from './PageErrorBoundary'
import { Sidebar, SIDEBAR_COLLAPSED, SIDEBAR_WIDTH } from './Sidebar'
import { Topbar } from './Topbar'

/**
 * The frame every screen sits in: rail, top bar, and a content area whose page
 * eases in on each navigation. The left padding follows the rail's width so
 * collapsing it hands the space to the page rather than leaving a gap.
 */
export function AppShell() {
  const { pathname } = useLocation()
  const collapsed = useUI((s) => s.sidebarCollapsed)
  const { isLoading, isAnonymous, error } = useSession()
  // The design pages are open to anyone; everything else needs a signed-in person.
  const gated = !pathname.startsWith('/design')

  // The tab and the history say where you are, and a screen reader hears the change.
  useEffect(() => {
    const trail = trailFor(pathname)
    document.title = `${trail[trail.length - 1].label} - Y ERP`
  }, [pathname])

  // Signed out: go to the sign-in page rather than draw a page full of failures.
  useEffect(() => {
    if (gated && isAnonymous && import.meta.env.PROD) window.location.assign('/login.html')
  }, [gated, isAnonymous])

  // A new page starts at its top, as a page does.
  useEffect(() => {
    window.scrollTo({ top: 0 })
  }, [pathname])

  return (
    <div className="min-h-dvh">
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
        <main id="main" className="mx-auto w-full min-w-0 max-w-[1600px] overflow-x-clip px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
          <motion.div
            key={pathname}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.32, ease: [0.16, 1, 0.3, 1] }}
          >
            {gated && isLoading ? (
              <div className="space-y-4" role="status" aria-label="Loading">
                <Skeleton className="h-9 w-64" />
                <Skeleton className="h-4 w-96 max-w-full" />
                <Skeleton className="mt-6 h-64 w-full" />
              </div>
            ) : gated && (isAnonymous || error) ? (
              <div className="mx-auto max-w-md py-24 text-center">
                <h1 className="text-2xl font-semibold">{error ? 'Could not reach the server' : 'Please sign in'}</h1>
                <p className="mt-2 text-[15px] text-muted-foreground">
                  {error ? 'Check the connection and try again.' : 'Your session has ended, or you have not signed in yet.'}
                </p>
                <Button asChild className="mt-6">
                  <a href="/login.html">Go to sign in</a>
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
          </motion.div>
        </main>
      </motion.div>
    </div>
  )
}
