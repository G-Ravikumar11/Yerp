import { NavLink } from 'react-router-dom'
import { CheckCircle2, Grid2x2, House, FolderKanban, Plus } from 'lucide-react'
import { useInbox } from '@/api/approvals'
import { cn } from '@/lib/utils'

/** The bar at the bottom of the phone app: the four places people go, and the + that adds a record. */
export function TabBar({ onAdd }: { onAdd: () => void }) {
  const inbox = useInbox()
  const waiting = inbox.data?.mine ?? 0
  const tab = ({ isActive }: { isActive: boolean }) =>
    cn('relative flex w-16 flex-col items-center gap-1 pt-2 text-[11px] font-semibold outline-offset-2 transition-colors', isActive ? 'text-primary' : 'text-muted-foreground')
  return (
    <nav aria-label="Main" className="fixed inset-x-0 bottom-0 z-40 border-t border-border bg-background/90 pb-[env(safe-area-inset-bottom)] backdrop-blur-xl">
      <div className="mx-auto flex h-[64px] max-w-xl items-start justify-around px-2">
        <NavLink to="/" end className={tab}><House className="size-[22px]" />Today</NavLink>
        <NavLink to="/projects" className={tab}><FolderKanban className="size-[22px]" />Projects</NavLink>
        <button type="button" onClick={onAdd} aria-label="Add a record" className="-mt-5 grid size-14 place-items-center rounded-full bg-primary text-primary-foreground shadow-[0_8px_24px_-6px_var(--primary)] ring-[5px] ring-background active:scale-95">
          <Plus className="size-7" strokeWidth={2.5} />
        </button>
        <NavLink to="/approvals" className={tab}>
          <span className="relative"><CheckCircle2 className="size-[22px]" />{waiting > 0 && <span className="absolute -right-2 -top-1.5 grid min-w-4 place-items-center rounded-full bg-danger px-1 text-[10px] font-bold leading-4 text-white">{waiting}</span>}</span>
          Approvals
        </NavLink>
        <NavLink to="/more" className={tab}><Grid2x2 className="size-[22px]" />More</NavLink>
      </div>
    </nav>
  )
}
