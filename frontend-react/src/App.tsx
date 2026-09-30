import { lazy, Suspense, useEffect } from 'react'
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { PersistQueryClientProvider } from '@tanstack/react-query-persist-client'
import { MotionConfig } from 'framer-motion'
import { AppShell } from '@/components/layout/AppShell'
import { Toaster, TooltipProvider } from '@/components/ui'
import { allRoutes } from '@/lib/nav'
import { persistOptions, queryClient } from '@/lib/query'
import { watchConnection } from '@/stores/offline'
import { applyTheme, useUI } from '@/stores/ui'
import { PORTED } from '@/routes'
import Dashboard from '@/pages/Dashboard'
import ModulePlaceholder from '@/pages/ModulePlaceholder'
import NotFound from '@/pages/NotFound'

const DesignSystem = lazy(() => import('@/pages/DesignSystem'))
const GridPlayground = lazy(() => import('@/pages/GridPlayground'))

export default function App() {
  const theme = useUI((s) => s.theme)

  // Keep the page in step with the chosen theme - and, on "system", with the
  // operating system when it changes at dusk.
  useEffect(() => {
    applyTheme(theme)
    if (theme !== 'system') return
    const mq = matchMedia('(prefers-color-scheme: dark)')
    const on = () => applyTheme('system')
    mq.addEventListener('change', on)
    return () => mq.removeEventListener('change', on)
  }, [theme])

  useEffect(() => watchConnection(), [])

  // Any request answered "not signed in" means the session ended: ask who is signed in
  // again, and the app goes to the sign-in page rather than draw failures.
  useEffect(() => {
    const on = () => void queryClient.invalidateQueries({ queryKey: ['session'] })
    window.addEventListener('yerp:unauthorised', on)
    return () => window.removeEventListener('yerp:unauthorised', on)
  }, [])

  return (
    <PersistQueryClientProvider client={queryClient} persistOptions={persistOptions}>
      <MotionConfig reducedMotion="user">
      <TooltipProvider>
        <BrowserRouter basename={import.meta.env.BASE_URL.replace(/\/$/, '')}>
          <Routes>
            <Route element={<AppShell />}>
              <Route index element={<Dashboard />} />
              <Route
                path="design"
                element={
                  <Suspense fallback={null}>
                    <DesignSystem />
                  </Suspense>
                }
              />
              <Route
                path="design/grid"
                element={
                  <Suspense fallback={null}>
                    <GridPlayground />
                  </Suspense>
                }
              />
              {PORTED.map(({ path, Component }) => (
                <Route key={path} path={path.slice(1)} element={<Component />} />
              ))}
              {allRoutes()
                .filter((r) => !PORTED.some((p) => p.path === r.path))
                .map((r) => (
                  <Route key={r.path} path={r.path.slice(1)} element={<ModulePlaceholder title={r.label} group={r.group} />} />
                ))}
              <Route path="*" element={<NotFound />} />
            </Route>
          </Routes>
        </BrowserRouter>
        <Toaster />
      </TooltipProvider>
      </MotionConfig>
    </PersistQueryClientProvider>
  )
}
