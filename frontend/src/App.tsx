import { lazy, Suspense, useEffect } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { PersistQueryClientProvider } from '@tanstack/react-query-persist-client'
import { MotionConfig } from 'framer-motion'
import { Loader2 } from 'lucide-react'
import { Toaster, TooltipProvider } from '@/components/ui'
import { UpdatePrompt } from '@/components/UpdatePrompt'
import { FreshBuild } from '@/lib/freshness'
import { LegacyLinks } from '@/lib/legacyLinks'
import { persistOptions, queryClient } from '@/lib/query'
import { watchConnection } from '@/stores/offline'
import { AppShell, HomePage, SCREENS } from '@/app-mobile/entry'
import NotFound from '@/pages/NotFound'
import { REDIRECTS } from '@/routes'

const LoginPage = lazy(() => import('@/features/auth/LoginPage'))
const TermsPage = lazy(() => import('@/features/legal/LegalPage').then((m) => ({ default: m.TermsPage })))
const PrivacyPage = lazy(() => import('@/features/legal/LegalPage').then((m) => ({ default: m.PrivacyPage })))
const ForgotPasswordPage = lazy(() => import('@/features/auth/ForgotPasswordPage'))
const ResetPasswordPage = lazy(() => import('@/features/auth/ResetPasswordPage'))
const OnboardPage = lazy(() => import('@/features/auth/OnboardPage'))
const PortalPage = lazy(() => import('@/features/portal/PortalPage'))
const JobsPage = lazy(() => import('@/features/careers/JobsPage'))
const ApplyPage = lazy(() => import('@/features/careers/ApplyPage'))
const VendorQuotePage = lazy(() => import('@/features/rfq/VendorQuotePage'))
const MeetingPage = lazy(() => import('@/features/meeting/MeetingPage'))
const SuperadminPage = lazy(() => import('@/features/superadmin/SuperadminPage'))
const SuperadminLoginPage = lazy(() => import('@/features/auth/SuperadminLoginPage'))
const ResetPage = lazy(() => import('@/features/auth/ResetPage'))

/** While a page's code is still downloading. It appears only after a moment, so a quick load shows nothing at all
 * rather than a flash; a slow one (a site on a weak signal) shows that something is happening instead of a blank page. */
function PageLoading() {
  return (
    <div role="status" aria-label="Loading" className="grid min-h-dvh place-items-center bg-background">
      <span className="animate-fade-in [animation-delay:400ms]"><Loader2 className="size-6 animate-spin text-muted-foreground" aria-hidden /></span>
    </div>
  )
}

export default function App() {
  useEffect(() => watchConnection(), [])

  // Something was deleted. Every screen not on show had kept its own copy of its lists, and drew that copy first when
  // opened - so the deleted record still showed elsewhere until a fresh answer came, for as long as the connection
  // took. Those copies are dropped; the screens on show are read again at once.
  useEffect(() => {
    const on = () => {
      queryClient.removeQueries({ type: 'inactive' })
      void queryClient.invalidateQueries({ type: 'active' })
    }
    window.addEventListener('yerp:deleted', on)
    return () => window.removeEventListener('yerp:deleted', on)
  }, [])

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
          <FreshBuild />
          <Suspense fallback={<PageLoading />}>
          <Routes>
            <Route path="login" element={<LoginPage />} />
            <Route path="terms" element={<TermsPage />} />
            <Route path="privacy" element={<PrivacyPage />} />
            <Route path="jobs" element={<JobsPage />} />
            <Route path="apply" element={<ApplyPage />} />
            <Route path="quote" element={<VendorQuotePage />} />
            <Route path="meeting" element={<MeetingPage />} />
            <Route path="onboard" element={<OnboardPage />} />
            <Route path="portal" element={<PortalPage />} />
            <Route path="forgot-password" element={<ForgotPasswordPage />} />
            <Route path="reset-password" element={<ResetPasswordPage />} />
            <Route path="superadmin" element={<SuperadminPage />} />
            <Route path="superadmin/login" element={<SuperadminLoginPage />} />
            <Route path="reset" element={<ResetPage />} />
            <Route element={<AppShell />}>
              <Route index element={<HomePage />} />
              {SCREENS.map(({ path, Component }) => (
                <Route key={path} path={path.slice(1)} element={<Component />} />
              ))}
              {REDIRECTS.map(({ from, to }) => (
                <Route key={from} path={from.slice(1)} element={<Navigate to={to} replace />} />
              ))}
              <Route path="*" element={<NotFound />} />
            </Route>
          </Routes>
          </Suspense>
        </BrowserRouter>
        <Toaster />
        <UpdatePrompt />
      </TooltipProvider>
      </MotionConfig>
    </PersistQueryClientProvider>
  )
}
