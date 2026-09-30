import { lazy, Suspense } from 'react'
import { Skeleton } from '@/components/ui'
import { useSession } from '@/lib/session'
import Dashboard from './Dashboard'

const MyOverviewPage = lazy(() => import('@/features/staff/MyOverviewPage'))

/** The front page: the account holder's Command Center, or a member of staff's own day. */
export default function Home() {
  const { user, isLoading } = useSession()
  if (isLoading) return <Skeleton className="h-64 w-full" />
  if (user?.type === 'employee') return <Suspense fallback={<Skeleton className="h-64 w-full" />}><MyOverviewPage /></Suspense>
  return <Dashboard />
}
