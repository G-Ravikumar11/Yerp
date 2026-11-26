import { useEffect, useLayoutEffect, useMemo, useRef, useState, type CSSProperties } from 'react'
import { createPortal } from 'react-dom'
import { Bell } from 'lucide-react'
import { readAllNotes, readAllOfficeNotes, readNote, readOfficeNote, staffKeys, useNotes } from '@/api/staff'
import type { Note } from '@/api/staff'
import { alertKeys, useOwnerAlerts } from '@/api/alerts'
import { useAction } from '@/lib/mutate'
import { cn } from '@/lib/utils'

// Staff notices say info/success/warning/error; the office's alerts say action, money, wrong or danger.
const dot: Record<string, string> = {
  info: 'bg-primary', success: 'bg-success', warning: 'bg-warning', error: 'bg-danger',
  action: 'bg-warning', money: 'bg-success', wrong: 'bg-danger', danger: 'bg-danger',
}
const when = (at: string) => (at ? at.slice(5, 16).replace('-', '/') : '')

/** A member of staff's notifications (leave decided, a document asked for, an increment due), or, for the Master's
 *  sign-in, the office's own notices. */
export function NotificationBell({ office = false }: { office?: boolean }) {
  return office ? <OfficeBell /> : <StaffBell />
}

function StaffBell() {
  const q = useNotes()
  const one = useAction((id: number) => readNote(id).then(() => ({})), { invalidate: [staffKeys.all], success: false })
  const all = useAction(() => readAllNotes(), { invalidate: [staffKeys.all], success: false })
  return <Bell_ q={q} one={(id) => one.mutate(id)} all={() => all.mutate()} />
}

function OfficeBell() {
  const alerts = useOwnerAlerts(true)
  const data = useMemo(
    () =>
      alerts.data && {
        unread_count: alerts.data.unread,
        notifications: alerts.data.alerts.map((a): Note => ({ id: a.id, title: a.title, message: a.body, type: a.severity, is_read: a.read, link: '', created_at: a.created_at })),
      },
    [alerts.data],
  )
  const one = useAction((id: number) => readOfficeNote(id).then(() => ({})), { invalidate: [alertKeys.all], success: false })
  const all = useAction(() => readAllOfficeNotes(), { invalidate: [alertKeys.all], success: false })
  return <Bell_ q={{ data: data || undefined, isPending: alerts.isPending, isError: alerts.isError }} one={(id) => one.mutate(id)} all={() => all.mutate()} />
}

interface BellQuery {
  data?: { unread_count: number; notifications: Note[] }
  isPending?: boolean
  isError?: boolean
}

/** Where the panel goes: just under the bell, and on a tablet or computer with its right edge at the bell's (as it always
 *  was). Read from the bell itself, because the panel is drawn outside the top bar (see below). */
function placeUnder(bell: HTMLElement | null) {
  const r = bell?.getBoundingClientRect()
  if (!r) return { top: 64, right: 16 }
  return { top: Math.round(r.bottom + 8), right: Math.max(8, Math.round(window.innerWidth - r.right)) }
}

function Bell_({ q, one, all }: { q: BellQuery; one: (id: number) => void; all: () => void }) {
  const [open, setOpen] = useState(false)
  const box = useRef<HTMLDivElement>(null)
  const panel = useRef<HTMLDivElement>(null)
  const [at, setAt] = useState({ top: 64, right: 16 })
  useLayoutEffect(() => {
    if (!open) return
    const place = () => setAt(placeUnder(box.current))
    place()
    window.addEventListener('resize', place)
    window.addEventListener('scroll', place, true)
    return () => { window.removeEventListener('resize', place); window.removeEventListener('scroll', place, true) }
  }, [open])
  useEffect(() => {
    if (!open) return
    const away = (e: MouseEvent) => {
      const t = e.target as Node
      if (!box.current?.contains(t) && !panel.current?.contains(t)) setOpen(false)
    }
    const esc = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('mousedown', away)
    document.addEventListener('keydown', esc)
    return () => { document.removeEventListener('mousedown', away); document.removeEventListener('keydown', esc) }
  }, [open])
  const unread = q.data?.unread_count ?? 0
  const notes = q.data?.notifications ?? []
  return (
    <div ref={box} className="relative">
      <button type="button" aria-label={unread ? `Notifications, ${unread} unread` : 'Notifications'} aria-expanded={open} onClick={() => setOpen((o) => !o)} className="relative grid size-9 place-items-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground">
        <Bell className="size-[18px]" />
        {unread > 0 && <span className="absolute -right-0.5 -top-0.5 grid min-w-4 place-items-center rounded-full bg-danger px-1 text-[10px] font-bold leading-4 text-white">{unread > 99 ? '99+' : unread}</span>}
      </button>
      {/* Drawn on the page body, not inside the top bar: the bar's backdrop blur makes it the box a fixed panel is placed in,
          and its own stacking layer. Anchored to the bell's right edge, a 320px panel ran off the left of a phone, where the
          bell is not at the screen's edge. On a phone it spans the screen less a margin either side; from 640px it is the
          same 320px dropdown under the bell as before. It never grows past the bottom of the screen: the list scrolls. */}
      {open && createPortal(
        <div
          ref={panel}
          role="dialog"
          aria-label="Notifications"
          style={{ '--bell-top': `${at.top}px`, '--bell-right': `${at.right}px` } as CSSProperties}
          className="fixed inset-x-3 top-[var(--bell-top)] z-40 mx-auto flex max-h-[calc(100dvh-var(--bell-top)-0.75rem)] max-w-md flex-col overflow-hidden rounded-xl border border-border bg-card shadow-md sm:left-auto sm:right-[var(--bell-right)] sm:mx-0 sm:w-80 sm:max-w-[calc(100vw-1rem)]"
        >
          <div className="flex shrink-0 items-center justify-between gap-3 border-b border-border px-4 py-3"><h2 className="text-sm font-semibold">Notifications</h2>{unread > 0 && <button type="button" className="shrink-0 text-xs font-medium text-primary hover:underline" onClick={all}>Mark all read</button>}</div>
          <ul className="min-h-0 flex-1 overflow-y-auto overscroll-contain sm:max-h-80">
            {notes.length === 0 && (
              <li className="p-6 text-center text-sm text-muted-foreground">{q.isError ? 'Could not load the notifications. Try again in a moment.' : q.isPending ? 'Loading...' : 'Nothing yet'}</li>
            )}
            {notes.map((n) => (
              <li key={n.id}>
                <button type="button" onClick={() => !n.is_read && one(n.id)} className={cn('flex w-full items-start gap-3 px-4 py-3 text-left transition-colors hover:bg-accent', !n.is_read && 'bg-primary-soft/40')}>
                  <span className={cn('mt-1.5 size-2 shrink-0 rounded-full', dot[n.type] ?? 'bg-subtle')} aria-hidden />
                  <span className="min-w-0 flex-1 [overflow-wrap:anywhere]"><span className="block text-[13px] font-medium">{n.title}</span><span className="block text-[13px] text-muted-foreground">{n.message}</span><span className="mt-0.5 block text-[11px] text-subtle">{when(n.created_at)}</span></span>
                </button>
              </li>
            ))}
          </ul>
        </div>,
        document.body,
      )}
    </div>
  )
}
