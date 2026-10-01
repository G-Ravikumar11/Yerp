import { useEffect, useRef, useState } from 'react'
import { Bell } from 'lucide-react'
import { readAllNotes, readNote, staffKeys, useNotes } from '@/api/staff'
import { useAction } from '@/lib/mutate'
import { cn } from '@/lib/utils'

const dot: Record<string, string> = { info: 'bg-primary', success: 'bg-success', warning: 'bg-warning', error: 'bg-danger' }
const when = (at: string) => (at ? at.slice(5, 16).replace('-', '/') : '')

/** A member of staff's notifications: leave decided, a document asked for, something sent to them. */
export function NotificationBell() {
  const q = useNotes()
  const [open, setOpen] = useState(false)
  const box = useRef<HTMLDivElement>(null)
  const one = useAction((id: number) => readNote(id).then(() => ({})), { invalidate: [staffKeys.all], success: false })
  const all = useAction(() => readAllNotes(), { invalidate: [staffKeys.all], success: false })
  useEffect(() => {
    if (!open) return
    const away = (e: MouseEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(false) }
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
      {open && (
        <div role="dialog" aria-label="Notifications" className="absolute right-0 z-40 mt-2 w-80 max-w-[calc(100vw-2rem)] overflow-hidden rounded-xl border border-border bg-card shadow-lg">
          <div className="flex items-center justify-between border-b border-border px-4 py-3"><h2 className="text-sm font-semibold">Notifications</h2>{unread > 0 && <button type="button" className="text-xs font-medium text-primary hover:underline" onClick={() => all.mutate()}>Mark all read</button>}</div>
          <ul className="max-h-80 overflow-y-auto">
            {notes.length === 0 && <li className="p-6 text-center text-sm text-muted-foreground">Nothing yet</li>}
            {notes.map((n) => (
              <li key={n.id}>
                <button type="button" onClick={() => !n.is_read && one.mutate(n.id)} className={cn('flex w-full items-start gap-3 px-4 py-3 text-left transition-colors hover:bg-accent', !n.is_read && 'bg-primary-soft/40')}>
                  <span className={cn('mt-1.5 size-2 shrink-0 rounded-full', dot[n.type] ?? 'bg-subtle')} aria-hidden />
                  <span className="min-w-0"><span className="block text-[13px] font-medium">{n.title}</span><span className="block text-[13px] text-muted-foreground">{n.message}</span><span className="mt-0.5 block text-[11px] text-subtle">{when(n.created_at)}</span></span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
