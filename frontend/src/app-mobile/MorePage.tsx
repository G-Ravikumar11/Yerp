import { useState } from 'react'
import { Link } from 'react-router-dom'
import { ChevronRight, LogOut, Monitor, Moon, Sun } from 'lucide-react'
import { post } from '@/lib/api'
import { visibleNav } from '@/lib/nav'
import { appUrl } from '@/lib/paths'
import { forgetLocalData } from '@/lib/query'
import { initials, useSession } from '@/lib/session'
import { cn } from '@/lib/utils'
import { useOffline } from '@/stores/offline'
import { type Theme, useUI } from '@/stores/ui'
import { ConfirmDialog } from '@/components/ui'
import { Label, LargeTitle, Sheet } from './ui'

const THEMES: { value: Theme; label: string; icon: typeof Sun }[] = [
  { value: 'light', label: 'Light', icon: Sun },
  { value: 'dark', label: 'Dark', icon: Moon },
  { value: 'system', label: 'Auto', icon: Monitor },
]

/** Everything else: every screen the website's menu has, as lists, plus the look of the app and signing out. */
export default function MorePage() {
  const { user, can, isHeadOffice } = useSession()
  const theme = useUI((s) => s.theme)
  const setTheme = useUI((s) => s.setTheme)
  const unsent = useOffline((s) => s.queue.length)
  const [asking, setAsking] = useState(false)
  const nav = visibleNav(can, user?.type === 'employee', isHeadOffice)

  const signOut = async () => {
    // Both, as the website does: this device may hold an owner's sign-in and a staff one.
    for (const path of user?.type === 'employee' ? ['/api/employee/auth/logout', '/api/client/logout'] : ['/api/client/logout', '/api/employee/auth/logout']) {
      try { await post(path) } catch { /* already signed out, or no signal: this device is done with them either way */ }
    }
    useOffline.setState({ queue: [] })
    await forgetLocalData()
    window.location.assign(appUrl('login?signedout=1'))
  }

  return (
    <div className="pb-4">
      <LargeTitle title="More" />
      <Sheet className="flex items-center gap-3">
        <span className="grid size-12 place-items-center rounded-full bg-gradient-to-br from-primary to-primary/60 text-base font-bold text-primary-foreground">{initials(user?.name)}</span>
        <div className="min-w-0 leading-tight">
          <div className="truncate text-[17px] font-semibold">{user?.name ?? 'Guest'}</div>
          <div className="truncate text-[13px] text-muted-foreground">{user?.type === 'owner' && user.teamRole === 'owner' ? 'Master' : user?.roleLabel || user?.email}</div>
        </div>
      </Sheet>

      {nav.map((e) => e.kind === 'link' ? null : (
        <section key={e.id}>
          <Label>{e.label}</Label>
          <Sheet className="divide-y divide-border py-0.5">
            {e.items.map((i) => (
              <Link key={i.path + i.label} to={i.path} className="flex min-h-12 items-center justify-between gap-3 py-2.5 text-[15px] font-medium active:opacity-70">
                {i.label}<ChevronRight className="size-4 text-muted-foreground" />
              </Link>
            ))}
          </Sheet>
        </section>
      ))}
      <Label>Others</Label>
      <Sheet className="divide-y divide-border py-0.5">
        {nav.flatMap((e) => (e.kind === 'link' && e.path !== '/' && e.path !== '/approvals' ? [e] : [])).map((e) => (
          <Link key={e.path} to={e.path} className="flex min-h-12 items-center justify-between gap-3 py-2.5 text-[15px] font-medium">{e.label}<ChevronRight className="size-4 text-muted-foreground" /></Link>
        ))}
      </Sheet>

      <Label>Look</Label>
      <div role="radiogroup" aria-label="Theme" className="grid grid-cols-3 gap-1 rounded-2xl bg-card p-1">
        {THEMES.map(({ value, label, icon: Icon }) => (
          <button key={value} type="button" role="radio" aria-checked={theme === value} onClick={() => setTheme(value)} className={cn('flex h-11 items-center justify-center gap-2 rounded-xl text-sm font-semibold', theme === value ? 'bg-muted text-foreground' : 'text-muted-foreground')}>
            <Icon className="size-4" />{label}
          </button>
        ))}
      </div>

      <button type="button" onClick={() => (unsent ? setAsking(true) : void signOut())} className="mt-6 flex h-12 w-full items-center justify-center gap-2 rounded-2xl bg-danger/10 text-[15px] font-semibold text-danger">
        <LogOut className="size-[18px]" />Sign out
      </button>
      <ConfirmDialog open={asking} onOpenChange={setAsking} title="Sign out with unsent changes?" description={`${unsent} change${unsent === 1 ? '' : 's'} made without signal ${unsent === 1 ? 'has' : 'have'} not been sent yet. Signing out now loses ${unsent === 1 ? 'it' : 'them'}.`} confirmLabel="Sign out anyway" tone="danger" onConfirm={() => void signOut()} />
    </div>
  )
}
