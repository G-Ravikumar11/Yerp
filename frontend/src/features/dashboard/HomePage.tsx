import { lazy, Suspense } from 'react'
import { Navigate } from 'react-router-dom'
import { Skeleton } from '@/components/ui'
import { useSession } from '@/lib/session'
import DashboardPage from './DashboardPage'

const MyOverviewPage = lazy(() => import('@/features/staff/MyOverviewPage'))

/** The front page: the account holder's Command Center, head office's HO portal, or a member of staff's own day. */
export default function HomePage() {
  const { user, isLoading } = useSession()
  if (isLoading) return <Skeleton className="h-64 w-full" />
  // HO QS and HO Coordinator sign in at the same page as everybody else and land on the HO portal.
  if (user?.headOffice) return <Navigate to="/ho" replace />
  if (user?.type === 'employee') return <Suspense fallback={<Skeleton className="h-64 w-full" />}><MyOverviewPage /></Suspense>
  return <DashboardPage />
}
