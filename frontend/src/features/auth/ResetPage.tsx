import { useEffect, useState } from 'react'
import { resetDevice } from '@/lib/freshness'
import { appUrl } from '@/lib/paths'
import { useOffline } from '@/stores/offline'
import { AuthLayout, Notice } from './AuthLayout'

/** /next/reset: starts this device clean - the saved copy of the app and the data kept from earlier visits - and goes
 * back into the app. The server also tells the browser to empty its own cache for this site on this page. */
export default function ResetPage() {
  const waiting = useOffline((s) => s.queue.length)
  const [done, setDone] = useState(false)
  useEffect(() => {
    void resetDevice().then(() => {
      setDone(true)
      window.setTimeout(() => window.location.replace(appUrl()), 1200)
    })
  }, [])
  return (
    <AuthLayout title="Y ERP" subtitle={done ? 'Done. Opening Y ERP...' : 'Clearing the saved copy of Y ERP on this device...'}>
      <Notice tone="success">
        You stay signed in{waiting ? `, and the ${waiting} save${waiting === 1 ? '' : 's'} made offline and not yet sent are kept` : ''}. The newest
        version of the app is loaded fresh from the server.
      </Notice>
    </AuthLayout>
  )
}
