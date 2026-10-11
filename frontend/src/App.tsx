import { lazy, Suspense, useEffect } from 'react'
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { PersistQueryClientProvider } from '@tanstack/react-query-persist-client'
import { MotionConfig } from 'framer-motion'
import { AppShell } from '@/components/layout/AppShell'
import { Toaster, TooltipProvider } from '@/components/ui'
import { LegacyLinks } from '@/lib/legacyLinks'
import { persistOptions, queryClient } from '@/lib/query'
import { watchConnection } from '@/stores/offline'
import { applyTheme, useUI } from '@/stores/ui'
import { SCREENS } from '@/routes'
import HomePage from '@/features/dashboard/HomePage'
import NotFound from '@/pages/NotFound'

const LoginPage = lazy(() => import('@/features/auth/LoginPage'))
const ResetPasswordPage = lazy(() => import('@/features/auth/ResetPasswordPage'))
const OnboardPage = lazy(() => import('@/features/auth/OnboardPage'))
const PortalPage = lazy(() => import('@/features/portal/PortalPage'))
const JobsPage = lazy(() => import('@/features/careers/JobsPage'))
const ApplyPage = lazy(() => import('@/features/careers/ApplyPage'))
const MeetingPage = lazy(() => import('@/features/meeting/MeetingPage'))
const SuperadminPage = lazy(() => import('@/features/superadmin/SuperadminPage'))
const SuperadminLoginPage = lazy(() => import('@/features/auth/SuperadminLoginPage'))
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

  const rawBase = import.meta.env.BASE_URL || ''
  const basename = rawBase === './' || rawBase === '/' ? '' : rawBase.replace(/\/$/, '')

  return (
    <PersistQueryClientProvider client={queryClient} persistOptions={persistOptions} onSuccess={() => void queryClient.invalidateQueries({ queryKey: ['session'] })}>
      <MotionConfig reducedMotion="user">
      <TooltipProvider>
        <BrowserRouter basename={basename}>
          <LegacyLinks />
          <Suspense fallback={null}>
          <Routes>
            <Route path="login" element={<LoginPage />} />
            <Route path="jobs" element={<JobsPage />} />
            <Route path="apply" element={<ApplyPage />} />
            <Route path="meeting" element={<MeetingPage />} />
            <Route path="onboard" element={<OnboardPage />} />
            <Route path="portal" element={<PortalPage />} />
            <Route path="reset-password" element={<ResetPasswordPage />} />
            <Route path="superadmin" element={<SuperadminPage />} />
            <Route path="superadmin/login" element={<SuperadminLoginPage />} />
            <Route element={<AppShell />}>
              <Route index element={<HomePage />} />
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
              {SCREENS.map(({ path, Component }) => (
                <Route key={path} path={path.slice(1)} element={<Component />} />
              ))}
              <Route path="*" element={<NotFound />} />
            </Route>
          </Routes>
          </Suspense>
        </BrowserRouter>
        <Toaster />
      </TooltipProvider>
      </MotionConfig>
    </PersistQueryClientProvider>
  )
}
