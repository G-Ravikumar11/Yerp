import { Link } from 'react-router-dom'
import { TriangleAlert } from 'lucide-react'
import { useIdentity } from '@/api/identity'
import { useSession } from '@/lib/session'

/**
 * Every document the company issues is headed with its name, address, GSTIN, PAN and logo. When any is
 * missing the owner is told, on every page, until it is filled in.
 */
export function CompanyNotice() {
  const { isOwner } = useSession()
  const { data } = useIdentity()
  if (!isOwner || !data || data.missing.length === 0) return null
  return (
    <div role="note" className="mb-6 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-warning/40 bg-warning/10 px-4 py-3 text-sm">
      <p className="flex items-start gap-2">
        <TriangleAlert className="mt-0.5 size-4 shrink-0 text-warning" aria-hidden />
        <span>
          Your work orders, bills and exports go out without your <strong>{data.missing.join(', ')}</strong>. Add {data.missing.length > 1 ? 'them' : 'it'} once and every document carries {data.missing.length > 1 ? 'them' : 'it'}.
        </span>
      </p>
      <Link to="/settings" className="shrink-0 font-medium text-primary hover:underline">
        Complete company details
      </Link>
    </div>
  )
}
