import { useState } from 'react'
import { Link } from 'react-router-dom'
import { ChevronRight, LogOut, Monitor, Moon, Search, Sun, X } from 'lucide-react'
import { post } from '@/lib/api'
import { type NavEntry, visibleNav } from '@/lib/nav'
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

/** Each group of the website's menu keeps one colour here, so a person learns "money is green" at a glance. */
const GROUP_COLOURS: Record<string, [string, string]> = {
  me: ['#2563eb', '#60a5fa'],
  projects: ['#7c3aed', '#a78bfa'],
  clients: ['#0891b2', '#22d3ee'],
  subcontractors: ['#d97706', '#fbbf24'],
  store: ['#ea580c', '#fb923c'],
  money: ['#059669', '#34d399'],
  people: ['#db2777', '#f472b6'],
}
const FALLBACK: [string, string] = ['#475569', '#94a3b8']
const colourOf = (id: string) => GROUP_COLOURS[id] ?? FALLBACK

type Hit = { path: string; label: string; group: string }

/** Everything else: every screen the website's menu has, as colour-coded groups with a search across them, plus the look of the app and signing out. */
export default function MorePage() {
  const { user, can, isHeadOffice } = useSession()
  const theme = useUI((s) => s.theme)
  const setTheme = useUI((s) => s.setTheme)
  const unsent = useOffline((s) => s.queue.length)
  const [asking, setAsking] = useState(false)
  const [query, setQuery] = useState('')
  const [open, setOpen] = useState<string | null>(null)
  const nav = visibleNav(can, user?.type === 'employee', isHeadOffice)
  const groups = nav.filter((e): e is Extract<NavEntry, { kind: 'group' }> => e.kind === 'group')
  const others = nav.filter((e): e is Extract<NavEntry, { kind: 'link' }> => e.kind === 'link' && e.path !== '/' && e.path !== '/approvals')
  const opened = groups.find((g) => g.id === open)

  const q = query.trim().toLowerCase()
  const hits: Hit[] = !q ? [] : [
    ...groups.flatMap((g) => g.items.filter((i) => i.label.toLowerCase().includes(q) || g.label.toLowerCase().includes(q)).map((i) => ({ path: i.path, label: i.label, group: g.label }))),
    ...others.filter((l) => l.label.toLowerCase().includes(q)).map((l) => ({ path: l.path, label: l.label, group: 'Shortcut' })),
  ]

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
      <LargeTitle title="Menu" />

      <Sheet className="flex items-center gap-3.5">
        <span className="grid size-[52px] shrink-0 place-items-center rounded-full bg-[image:var(--app-grad)] text-lg font-bold text-white">{initials(user?.name)}</span>
        <div className="min-w-0 leading-tight">
          <div className="truncate text-[17px] font-bold tracking-tight">{user?.name ?? 'Guest'}</div>
          <div className="truncate text-[13px] text-muted-foreground">{user?.type === 'owner' && user.teamRole === 'owner' ? 'Master' : user?.roleLabel || user?.email}</div>
        </div>
      </Sheet>

      <label className="mt-3.5 flex h-12 items-center gap-2.5 rounded-full border border-border bg-card px-4 text-muted-foreground shadow-[var(--app-card-shadow)] focus-within:border-primary">
        <Search className="size-[18px] shrink-0" />
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search every screen"
          aria-label="Search every screen"
          type="search"
          enterKeyHint="search"
          className="min-w-0 flex-1 bg-transparent text-[15px] text-foreground outline-none placeholder:text-muted-foreground [&::-webkit-search-cancel-button]:hidden"
        />
        {query && <button type="button" aria-label="Clear search" onClick={() => setQuery('')} className="grid size-6 place-items-center rounded-full bg-muted"><X className="size-3.5" /></button>}
      </label>

      {q ? (
        <>
          <Label>{hits.length === 1 ? '1 screen' : `${hits.length} screens`}</Label>
          {hits.length === 0 ? (
            <Sheet><p className="py-2 text-center text-sm text-muted-foreground">Nothing is called that. Try another word.</p></Sheet>
          ) : (
            <Sheet className="divide-y divide-border py-0.5">
              {hits.map((h) => (
                <Link key={h.group + h.path + h.label} to={h.path} className="flex min-h-12 items-center justify-between gap-3 py-2.5 active:opacity-70">
                  <span className="min-w-0"><b className="block truncate text-[15px] font-medium">{h.label}</b><span className="text-xs text-muted-foreground">{h.group}</span></span>
                  <ChevronRight className="size-4 shrink-0 text-muted-foreground" />
                </Link>
              ))}
            </Sheet>
          )}
        </>
      ) : (
        <>
          <Label>All sections</Label>
          <div className="grid grid-cols-2 gap-2.5">
            {groups.map((g) => {
              const [from, to] = colourOf(g.id)
              const on = g.id === open
              return (
                <button key={g.id} type="button" aria-expanded={on} onClick={() => setOpen(on ? null : g.id)} className={cn('flex flex-col items-start gap-2.5 rounded-2xl border bg-card p-3.5 text-left shadow-[var(--app-card-shadow)] active:scale-[0.98]', on ? 'border-primary' : 'border-border')}>
                  <span className="grid size-11 shrink-0 place-items-center rounded-[14px] text-white" style={{ background: `linear-gradient(135deg, ${from}, ${to})` }}><g.icon className="size-5" /></span>
                  <span className="min-w-0 max-w-full leading-tight"><b className="block truncate text-[15px] font-semibold">{g.label}</b><span className="text-xs text-muted-foreground">{g.items.length} {g.items.length === 1 ? 'screen' : 'screens'}</span></span>
                </button>
              )
            })}
          </div>

          {opened && (
            <>
              <Label>{opened.label}</Label>
              <Sheet className="divide-y divide-border py-0.5">
                {opened.items.map((i) => (
                  <Link key={i.path + i.label} to={i.path} className="flex min-h-12 items-center justify-between gap-3 py-2.5 text-[15px] font-medium active:opacity-70">
                    {i.label}<ChevronRight className="size-4 text-muted-foreground" />
                  </Link>
                ))}
              </Sheet>
            </>
          )}

          {others.length > 0 && (
            <>
              <Label>Shortcuts</Label>
              <Sheet className="divide-y divide-border py-0.5">
                {others.map((e) => (
                  <Link key={e.path} to={e.path} className="flex min-h-12 items-center gap-3 py-2.5 text-[15px] font-medium active:opacity-70">
                    <e.icon className="size-[18px] text-muted-foreground" /><span className="flex-1">{e.label}</span><ChevronRight className="size-4 text-muted-foreground" />
                  </Link>
                ))}
              </Sheet>
            </>
          )}
        </>
      )}

      <Label>Look</Label>
      <div role="radiogroup" aria-label="Theme" className="grid grid-cols-3 gap-1 rounded-full border border-border bg-card p-1">
        {THEMES.map(({ value, label, icon: Icon }) => (
          <button key={value} type="button" role="radio" aria-checked={theme === value} onClick={() => setTheme(value)} className={cn('flex h-10 items-center justify-center gap-2 rounded-full text-sm font-semibold', theme === value ? 'bg-primary text-primary-foreground' : 'text-muted-foreground')}>
            <Icon className="size-4" />{label}
          </button>
        ))}
      </div>

      <button type="button" onClick={() => (unsent ? setAsking(true) : void signOut())} className="mt-6 flex h-12 w-full items-center justify-center gap-2 rounded-full bg-danger/10 text-[15px] font-semibold text-danger active:opacity-80">
        <LogOut className="size-[18px]" />Sign out
      </button>
      <ConfirmDialog open={asking} onOpenChange={setAsking} title="Sign out with unsent changes?" description={`${unsent} change${unsent === 1 ? '' : 's'} made without signal ${unsent === 1 ? 'has' : 'have'} not been sent yet. Signing out now loses ${unsent === 1 ? 'it' : 'them'}.`} confirmLabel="Sign out anyway" tone="danger" onConfirm={() => void signOut()} />
    </div>
  )
}
