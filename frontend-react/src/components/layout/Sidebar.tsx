import { useEffect, useMemo } from 'react'
import { NavLink, useLocation } from 'react-router-dom'
import { AnimatePresence, motion } from 'framer-motion'
import { ChevronDown, PanelLeftClose, PanelLeftOpen } from 'lucide-react'
import { cn } from '@/lib/utils'
import { groupFor, visibleNav, type NavGroup } from '@/lib/nav'
import { useSession } from '@/lib/session'
import { useUI } from '@/stores/ui'
import { Tooltip } from '@/components/ui'

export const SIDEBAR_WIDTH = 272
export const SIDEBAR_COLLAPSED = 76

function Brand({ collapsed }: { collapsed: boolean }) {
  return (
    <NavLink to="/" className="flex items-center gap-3 rounded-lg px-1 outline-offset-4" aria-label="Y ERP home">
      <span className="grid size-10 shrink-0 place-items-center rounded-xl bg-gradient-to-br from-ember-300 to-ember-600 shadow-glow">
        <svg viewBox="0 0 24 24" className="size-5 text-white" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round">
          <path d="M6 6l6 8 6-8M12 14v6" />
        </svg>
      </span>
      <AnimatePresence initial={false}>
        {!collapsed && (
          <motion.span
            initial={{ opacity: 0, x: -6 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: -6 }}
            transition={{ duration: 0.15 }}
            className="min-w-0 leading-tight"
          >
            <span className="block font-display text-[17px] font-semibold tracking-tight">Y ERP</span>
            <span className="block text-[11px] text-muted-foreground">Civil contracting</span>
          </motion.span>
        )}
      </AnimatePresence>
    </NavLink>
  )
}

const itemBase =
  'group relative flex items-center gap-3 rounded-lg px-3 text-[13.5px] font-medium transition-colors duration-150'

function LinkItem({ to, label, icon: Icon, collapsed }: { to: string; label: string; icon: NavGroup['icon']; collapsed: boolean }) {
  return (
    <Tooltip content={label} disabled={!collapsed}>
      <NavLink
        to={to}
        end
        className={({ isActive }) =>
          cn(itemBase, 'h-10', isActive ? 'text-foreground' : 'text-muted-foreground hover:bg-accent hover:text-foreground')
        }
      >
        {({ isActive }) => (
          <>
            {isActive && (
              <motion.span
                layoutId="nav-active"
                className="absolute inset-0 rounded-lg bg-primary-soft ring-1 ring-primary/25"
                transition={{ type: 'spring', stiffness: 500, damping: 38 }}
              />
            )}
            <Icon className={cn('relative size-[18px] shrink-0', isActive && 'text-primary')} />
            {!collapsed && <span className="relative truncate">{label}</span>}
          </>
        )}
      </NavLink>
    </Tooltip>
  )
}

function Group({ group, collapsed }: { group: NavGroup; collapsed: boolean }) {
  const { pathname } = useLocation()
  const { openGroups, toggleGroup, setGroup, toggleSidebar } = useUI()
  const active = groupFor(pathname) === group.id
  const open = !!openGroups[group.id]
  const Icon = group.icon

  // Arriving on a page by URL opens the section it lives in.
  useEffect(() => {
    if (active) setGroup(group.id, true)
  }, [active, group.id, setGroup])

  if (collapsed) {
    return (
      <Tooltip content={group.label}>
        <button
          type="button"
          onClick={() => {
            toggleSidebar()
            setGroup(group.id, true)
          }}
          className={cn(itemBase, 'h-10 w-full', active ? 'bg-primary-soft text-primary' : 'text-muted-foreground hover:bg-accent hover:text-foreground')}
          aria-label={group.label}
        >
          <Icon className="size-[18px] shrink-0" />
        </button>
      </Tooltip>
    )
  }

  return (
    <div>
      <button
        type="button"
        onClick={() => toggleGroup(group.id)}
        aria-expanded={open}
        aria-controls={`nav-${group.id}`}
        className={cn(itemBase, 'h-10 w-full', active ? 'text-foreground' : 'text-muted-foreground hover:bg-accent hover:text-foreground')}
      >
        <Icon className={cn('size-[18px] shrink-0', active && 'text-primary')} />
        <span className="flex-1 truncate text-left">{group.label}</span>
        <ChevronDown className={cn('size-4 shrink-0 opacity-60 transition-transform duration-200', open && 'rotate-180')} />
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.ul
            id={`nav-${group.id}`}
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.22, ease: [0.16, 1, 0.3, 1] }}
            className="overflow-hidden"
          >
            <div className="relative ml-[21px] mt-0.5 flex flex-col gap-0.5 border-l border-border pb-1 pl-3">
              {group.items.map((item) => (
                <li key={item.path}>
                  <NavLink
                    to={item.path}
                    end
                    className={({ isActive }) =>
                      cn(
                        'relative flex h-8 items-center rounded-md px-2.5 text-[13px] transition-colors duration-150',
                        isActive ? 'font-medium text-foreground' : 'text-muted-foreground hover:bg-accent hover:text-foreground',
                      )
                    }
                  >
                    {({ isActive }) => (
                      <>
                        {isActive && (
                          <motion.span
                            layoutId="nav-active-sub"
                            className="absolute -left-[13px] top-1/2 h-4 w-0.5 -translate-y-1/2 rounded-full bg-primary"
                            transition={{ type: 'spring', stiffness: 500, damping: 38 }}
                          />
                        )}
                        <span className="truncate">{item.label}</span>
                      </>
                    )}
                  </NavLink>
                </li>
              ))}
            </div>
          </motion.ul>
        )}
      </AnimatePresence>
    </div>
  )
}

function SidebarBody({ collapsed, showToggle }: { collapsed: boolean; showToggle: boolean }) {
  const toggle = useUI((s) => s.toggleSidebar)
  const { user, can } = useSession()
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const nav = useMemo(() => visibleNav(can), [user])
  return (
    <div className="flex h-full flex-col">
      <div className={cn('flex h-16 shrink-0 items-center px-4', collapsed && 'justify-center px-0')}>
        <Brand collapsed={collapsed} />
      </div>
      <nav aria-label="Main" className="flex-1 overflow-y-auto overflow-x-hidden px-3 pb-4 pt-2">
        <div className="flex flex-col gap-1">
          {nav.map((entry) =>
            entry.kind === 'link' ? (
              <LinkItem key={entry.id} to={entry.path} label={entry.label} icon={entry.icon} collapsed={collapsed} />
            ) : (
              <Group key={entry.id} group={entry} collapsed={collapsed} />
            ),
          )}
        </div>
      </nav>
      {showToggle && (
        <div className="shrink-0 border-t border-sidebar-border p-3">
          <Tooltip content="Expand sidebar" disabled={!collapsed}>
            <button
              type="button"
              onClick={toggle}
              className={cn(itemBase, 'h-9 w-full text-muted-foreground hover:bg-accent hover:text-foreground', collapsed && 'justify-center px-0')}
              aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            >
              {collapsed ? <PanelLeftOpen className="size-[18px]" /> : <PanelLeftClose className="size-[18px]" />}
              {!collapsed && <span>Collapse</span>}
            </button>
          </Tooltip>
        </div>
      )}
    </div>
  )
}

/** Fixed rail on desktop; a slide-in drawer below `lg`. */
export function Sidebar() {
  const { sidebarCollapsed, mobileNavOpen, setMobileNav } = useUI()
  const { pathname } = useLocation()

  // A drawer that stays open after choosing a page is in the way.
  useEffect(() => {
    setMobileNav(false)
  }, [pathname, setMobileNav])

  return (
    <>
      <motion.aside
        initial={false}
        animate={{ width: sidebarCollapsed ? SIDEBAR_COLLAPSED : SIDEBAR_WIDTH }}
        transition={{ type: 'spring', stiffness: 420, damping: 40 }}
        className="fixed inset-y-0 left-0 z-30 hidden border-r border-sidebar-border bg-sidebar lg:block"
      >
        <SidebarBody collapsed={sidebarCollapsed} showToggle />
      </motion.aside>

      <AnimatePresence>
        {mobileNavOpen && (
          <>
            <motion.div
              className="fixed inset-0 z-40 bg-black/55 backdrop-blur-[2px] lg:hidden"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              onClick={() => setMobileNav(false)}
            />
            <motion.aside
              className="pt-safe pb-safe fixed inset-y-0 left-0 z-50 w-[min(86vw,20rem)] border-r border-sidebar-border bg-sidebar shadow-pop lg:hidden"
              initial={{ x: '-100%' }}
              animate={{ x: 0 }}
              exit={{ x: '-100%' }}
              transition={{ type: 'spring', stiffness: 400, damping: 40 }}
              aria-label="Navigation"
            >
              <SidebarBody collapsed={false} showToggle={false} />
            </motion.aside>
          </>
        )}
      </AnimatePresence>
    </>
  )
}
