import { lazy, Suspense, useEffect } from 'react'
import { useSession } from '@/lib/session'
import { canPassVouchers } from '@/lib/voucher'
import { useVoucher } from '@/stores/voucher'

// The screen and the five forms behind it are only fetched when it is first opened.
const NewVoucher = lazy(() => import('./NewVoucher'))

/**
 * Lives in the app shell: listens for Alt+V, and shows the New voucher screen when it is open. It does nothing for a
 * person with no right to pass a voucher, and never opens over a form that is already open.
 */
export function NewVoucherHost() {
  const { can } = useSession()
  const open = useVoucher((s) => s.open)
  const show = useVoucher((s) => s.show)
  const allowed = canPassVouchers(can)
  useEffect(() => {
    if (!allowed) return
    const onKey = (e: KeyboardEvent) => {
      // By position, not character: Option+V types a different letter on a Mac.
      if (e.code !== 'KeyV' || !e.altKey || e.ctrlKey || e.metaKey || e.shiftKey || e.repeat) return
      if (document.querySelector('[role="dialog"]')) return
      e.preventDefault()
      show()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [allowed, show])
  if (!open || !allowed) return null
  return <Suspense fallback={null}><NewVoucher /></Suspense>
}
