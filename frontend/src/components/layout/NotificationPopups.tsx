import { useEffect, useRef } from 'react'
import { useNotes } from '@/api/staff'
import { useOwnerAlerts } from '@/api/alerts'
import { MOST_AT_ONCE, freshOnes, newestId, popupText, type Popup } from '@/lib/popups'
import { toast } from '@/stores/toast'
import { useSession } from '@/lib/session'

const KEY = 'yerp-popped:'
const read = (who: string): number | null => { try { const v = localStorage.getItem(KEY + who); return v ? Number(v) || 0 : null } catch { return null } }
const remember = (who: string, id: number) => { try { localStorage.setItem(KEY + who, String(id)) } catch { /* private window: it simply pops again next visit */ } }

/** Shows each notification that arrives while the app is open as a message on screen, wherever the person is in the app. */
function usePopOnArrival(who: string, items: Popup[] | undefined) {
  const last = useRef<number | null | undefined>(undefined)       // undefined: not read from this device yet
  useEffect(() => {
    if (!items) return
    if (last.current === undefined) last.current = read(who)
    const fresh = freshOnes(items, last.current)
    const newest = Math.max(newestId(items), last.current ?? 0)
    if (fresh.length) {
      fresh.slice(0, MOST_AT_ONCE).forEach((p) => (p.tone === 'error' ? toast.error(popupText(p)) : toast.info(popupText(p))))
      if (fresh.length > MOST_AT_ONCE) toast.info(`and ${fresh.length - MOST_AT_ONCE} more - see the bell`)
    }
    if (last.current === null || newest > (last.current ?? 0)) { last.current = newest; remember(who, newest) }
  }, [who, items])
}

function StaffPopups({ who }: { who: string }) {
  const notes = useNotes().data?.notifications
  usePopOnArrival(who, notes?.map((n) => ({ id: n.id, title: n.title, body: n.message, tone: n.type === 'error' ? 'error' : 'info', read: n.is_read })))
  return null
}

function OwnerPopups({ who }: { who: string }) {
  const alerts = useOwnerAlerts(true).data?.alerts
  usePopOnArrival(who, alerts?.map((a) => ({ id: a.id, title: a.title, body: a.body, tone: a.severity === 'danger' ? 'error' : 'info', read: a.read })))
  return null
}

/** Mounted once in the frame of the app: whatever the server tells this person, it shows as it comes in. */
export function NotificationPopups() {
  const { user } = useSession()
  if (!user) return null
  const who = `${user.type}:${user.email}`
  return user.type === 'employee' ? <StaffPopups who={who} /> : <OwnerPopups who={who} />
}
