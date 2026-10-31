import { NavLink } from 'react-router-dom'
import { CheckCircle2, FolderKanban, Grid2x2, House, Plus } from 'lucide-react'
import { useInbox } from '@/api/approvals'
import { cn } from '@/lib/utils'

/**
 * The bar at the bottom of the phone app: a floating, rounded bar with the four places people go and a raised + that
 * adds a record. Icons only, with the name kept for screen readers; the open tab is blue with a dot under it.
 */
export function TabBar({ onAdd }: { onAdd: () => void }) {
  const inbox = useInbox()
  const waiting = inbox.data?.mine ?? 0
  const tab = ({ isActive }: { isActive: boolean }) =>
    cn('relative grid h-14 min-w-0 place-items-center outline-offset-2 transition-colors', isActive ? 'text-primary' : 'text-muted-foreground')
  const dot = (isActive: boolean) => isActive && <span className="absolute bottom-1.5 size-1 rounded-full bg-primary" aria-hidden />
  return (
    <nav
      aria-label="Main"
      className="fixed inset-x-0 bottom-0 z-40 pb-[max(0.75rem,env(safe-area-inset-bottom))] pl-[max(0.75rem,env(safe-area-inset-left))] pr-[max(0.75rem,env(safe-area-inset-right))]"
    >
      <div className="mx-auto grid h-[66px] max-w-md grid-cols-[1fr_1fr_76px_1fr_1fr] items-center rounded-[33px] border border-border bg-[var(--app-glass)] px-1.5 shadow-[var(--app-bar-shadow)] backdrop-blur-xl">
        <NavLink to="/" end className={tab} aria-label="Home">
          {({ isActive }) => <><House className={cn('size-[25px]', isActive && '[&>*]:stroke-[2.2]')} />{dot(isActive)}</>}
        </NavLink>
        <NavLink to="/projects" className={tab} aria-label="Projects">
          {({ isActive }) => <><FolderKanban className="size-[25px]" />{dot(isActive)}</>}
        </NavLink>
        <button
          type="button"
          onClick={onAdd}
          aria-label="Add a record"
          className="-mt-7 mx-auto grid size-[58px] place-items-center rounded-full bg-[image:var(--app-grad)] text-white shadow-[0_10px_24px_color-mix(in_srgb,var(--primary)_50%,transparent)] ring-[5px] ring-background active:scale-95"
        >
          <Plus className="size-7" strokeWidth={2.5} />
        </button>
        <NavLink to="/approvals" className={tab} aria-label={waiting > 0 ? `Approvals, ${waiting} waiting` : 'Approvals'}>
          {({ isActive }) => (
            <>
              <span className="relative">
                <CheckCircle2 className="size-[25px]" />
                {waiting > 0 && (
                  <span className="absolute -right-2.5 -top-2 grid h-[18px] min-w-[18px] place-items-center rounded-full bg-danger px-1 text-[10.5px] font-bold leading-none text-white ring-2 ring-background">
                    {waiting > 9 ? '9+' : waiting}
                  </span>
                )}
              </span>
              {dot(isActive)}
            </>
          )}
        </NavLink>
        <NavLink to="/more" className={tab} aria-label="Menu">
          {({ isActive }) => <><Grid2x2 className="size-[25px]" />{dot(isActive)}</>}
        </NavLink>
      </div>
    </nav>
  )
}
