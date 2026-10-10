import { Fragment } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { ChevronRight, Download, LogOut, Menu, Monitor, Moon, Sun } from 'lucide-react'
import { post } from '@/lib/api'
import { useInstall } from '@/lib/install'
import { forgetLocalData } from '@/lib/query'
import { useOffline } from '@/stores/offline'
import { trailFor } from '@/lib/nav'
import { initials, useSession } from '@/lib/session'
import { cn } from '@/lib/utils'
import { type Theme, useUI } from '@/stores/ui'
import { useState } from 'react'
import { ConfirmDialog, Skeleton, Tooltip } from '@/components/ui'
import { NotificationBell } from './NotificationBell'
import { SyncIndicator } from './SyncIndicator'

function Breadcrumbs() {
  const { pathname } = useLocation()
  const { user } = useSession()
  const trail = trailFor(pathname, user?.type === 'employee')
  return (
    <nav aria-label="Breadcrumb" className="min-w-0">
      <ol className="flex items-center gap-1.5 text-[13px]">
        {trail.map((crumb, i) => {
          const last = i === trail.length - 1
          return (
            <Fragment key={i}>
              {i > 0 && <ChevronRight className="size-3.5 shrink-0 text-subtle" aria-hidden />}
              <li className={cn('truncate', !last && 'hidden sm:block')}>
                {crumb.path && !last ? (
                  <Link to={crumb.path} className="text-muted-foreground transition-colors hover:text-foreground">
                    {crumb.label}
                  </Link>
                ) : (
                  <span aria-current={last ? 'page' : undefined} className={last ? 'font-medium text-foreground' : 'text-muted-foreground'}>
                    {crumb.label}
                  </span>
                )}
              </li>
            </Fragment>
          )
        })}
      </ol>
    </nav>
  )
}

const THEMES: { value: Theme; label: string; icon: typeof Sun }[] = [
  { value: 'light', label: 'Light', icon: Sun },
  { value: 'dark', label: 'Dark', icon: Moon },
  { value: 'system', label: 'System', icon: Monitor },
]

function ThemeSwitch() {
  const { theme, setTheme } = useUI()
  return (
    <div role="radiogroup" aria-label="Theme" className="flex items-center gap-0.5 rounded-lg bg-muted p-0.5">
      {THEMES.map(({ value, label, icon: Icon }) => {
        const on = theme === value
        return (
          <Tooltip key={value} content={label} side="bottom">
            <button
              type="button"
              role="radio"
              aria-checked={on}
              aria-label={label}
              onClick={() => setTheme(value)}
              className={cn('grid size-7 place-items-center rounded-md transition-all duration-150', on ? 'bg-card text-foreground shadow-xs' : 'text-muted-foreground hover:text-foreground')}
            >
              <Icon className="size-3.5" />
            </button>
          </Tooltip>
        )
      })}
    </div>
  )
}

function UserChip() {
  const { user, isLoading } = useSession()
  const unsent = useOffline((s) => s.queue.length)
  const [asking, setAsking] = useState(false)
  if (isLoading) return <Skeleton className="h-9 w-28 rounded-lg" />

  const signOut = async () => {
    // Both: this browser may hold an owner's sign-in and a staff one, and the login page signs back in on either.
    for (const path of user?.type === 'employee' ? ['/api/employee/auth/logout', '/api/client/logout'] : ['/api/client/logout', '/api/employee/auth/logout']) {
      try {
        await post(path)
      } catch {
        // Already signed out - or no signal - either way this device is done with them.
      }
    }
    // What this device kept for them - the data, and any change not yet sent - goes too.
    useOffline.setState({ queue: [] })
    await forgetLocalData()
    window.location.assign('/next/login?signedout=1')
  }

  return (
    <div className="flex items-center gap-2 rounded-lg py-1 pl-1 pr-1 sm:gap-2.5">
      <span className="grid size-8 place-items-center rounded-full bg-gradient-to-br from-steel-400 to-steel-600 text-[11px] font-semibold text-white">{initials(user?.name)}</span>
      <span className="hidden min-w-0 leading-tight sm:block">
        <span className="block max-w-36 truncate text-[13px] font-medium">{user?.name ?? 'Guest'}</span>
        <span className="block text-[11px] text-muted-foreground">{user ? [user.roleLabel, user.department].filter(Boolean).join(' · ') : 'Not signed in'}</span>
      </span>
      {user && (
        <Tooltip content="Sign out" side="bottom">
          <button type="button" onClick={() => (unsent ? setAsking(true) : void signOut())} aria-label="Sign out" className="grid size-8 place-items-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground">
            <LogOut className="size-4" />
          </button>
        </Tooltip>
      )}
      <ConfirmDialog
        open={asking}
        onOpenChange={setAsking}
        title="Sign out with changes unsent?"
        description={`${unsent} change${unsent === 1 ? ' is' : 's are'} still on this device, waiting for a connection. Signing out throws ${unsent === 1 ? 'it' : 'them'} away. Stay signed in and they go up as soon as the signal returns.`}
        confirmLabel="Discard and sign out"
        tone="danger"
        onConfirm={() => signOut()}
      />
    </div>
  )
}

/** Offered only when the browser says the app can be installed, and never once it has been. */
function InstallButton() {
  const { canInstall, install } = useInstall()
  if (!canInstall) return null
  return (
    <Tooltip content="Put Y ERP on this device" side="bottom">
      <button type="button" onClick={() => void install()} className="hidden items-center gap-1.5 rounded-full bg-primary-soft px-3 py-1.5 text-xs font-medium text-primary ring-1 ring-inset ring-primary/25 transition-colors hover:brightness-110 sm:inline-flex">
        <Download className="size-3.5" /> Install
      </button>
    </Tooltip>
  )
}

export function Topbar() {
  const setMobileNav = useUI((s) => s.setMobileNav)
  const { user } = useSession()
  return (
    <header className="pt-safe glass sticky top-0 z-20 border-b border-border">
      <div className="flex h-16 items-center gap-3 px-4 sm:px-6 lg:px-8">
        <button
          type="button"
          onClick={() => setMobileNav(true)}
          aria-label="Open navigation"
          className="-ml-1 grid size-10 place-items-center rounded-lg text-muted-foreground transition-colors hover:bg-accent hover:text-foreground lg:hidden"
        >
          <Menu className="size-5" />
        </button>
        <Breadcrumbs />
        <div className="ml-auto flex items-center gap-3">
          <InstallButton />
          {user?.type === 'employee' && <NotificationBell />}
          <SyncIndicator />
          <ThemeSwitch />
          <span className="hidden h-6 w-px bg-border sm:block" aria-hidden />
          <UserChip />
        </div>
      </div>
    </header>
  )
}
