import { useNavigate } from 'react-router-dom'
import { AnimatePresence, motion } from 'framer-motion'
import { AlertTriangle, BookOpen, ClipboardCheck, ListChecks, PackageCheck, Ruler, type LucideIcon } from 'lucide-react'
import { useProjects } from '@/api/projects'
import { useSession } from '@/lib/session'
import { cn } from '@/lib/utils'
import { useSite } from './site'

/** The six things recorded on site, and where each is recorded. A tile appears only for someone who may do it. */
const TILES: { label: string; hint: string; path: string; perm?: string; icon: LucideIcon; tone: string }[] = [
  { label: 'Site diary', hint: 'Labour, weather, photos', path: '/projects/diary', perm: 'site.record', icon: BookOpen, tone: 'bg-primary/15 text-primary' },
  { label: 'Tasks', hint: 'Tick what got done', path: '/projects/programme', icon: ListChecks, tone: 'bg-success/15 text-success' },
  { label: 'Measurement', hint: 'No × L × B × D', path: '/subcontractors/measurement-book', perm: 'site.record', icon: Ruler, tone: 'bg-primary/15 text-primary' },
  { label: 'Goods in', hint: 'Material at the gate', path: '/store/goods-receipt', perm: 'stores.receive', icon: PackageCheck, tone: 'bg-warning/15 text-warning' },
  { label: 'Safety', hint: 'Near miss or incident', path: '/projects/safety', icon: AlertTriangle, tone: 'bg-danger/15 text-danger' },
  { label: 'Quality', hint: 'Inspection or snag', path: '/projects/quality', icon: ClipboardCheck, tone: 'bg-muted text-foreground' },
]

/** The sheet the + slides up: record something for the site you are on, in two taps from anywhere. */
export function AddSheet({ open, onClose }: { open: boolean; onClose: () => void }) {
  const go = useNavigate()
  const { can } = useSession()
  const projects = useProjects()
  const site = useSite((s) => s.id)
  const name = projects.data?.find((p) => p.id === site)?.name
  const tiles = TILES.filter((t) => !t.perm || can(t.perm))
  return (
    <AnimatePresence>
      {open && (
        <>
          <motion.button type="button" aria-label="Close" onClick={onClose} className="fixed inset-0 z-50 bg-black/55" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} />
          <motion.div
            role="dialog"
            aria-label="Add a record"
            className="fixed inset-x-0 bottom-0 z-[51] mx-auto max-w-xl rounded-t-[28px] border border-b-0 border-border bg-card px-4 pb-[calc(24px+env(safe-area-inset-bottom))] pt-2.5"
            initial={{ y: '100%' }}
            animate={{ y: 0 }}
            exit={{ y: '100%' }}
            transition={{ type: 'spring', stiffness: 420, damping: 38 }}
            drag="y"
            dragConstraints={{ top: 0, bottom: 0 }}
            dragElastic={{ top: 0, bottom: 0.5 }}
            onDragEnd={(_, i) => i.offset.y > 80 && onClose()}
          >
            <div className="mx-auto mb-3 h-1.5 w-10 rounded-full bg-border" />
            <h2 className="font-display text-[22px] font-bold">Add</h2>
            <p className="mb-4 text-sm text-muted-foreground">{name ? `For ${name}` : 'What happened on site?'}</p>
            <div className="grid grid-cols-3 gap-2.5">
              {tiles.map(({ label, hint, path, icon: Icon, tone }) => (
                <button key={label} type="button" onClick={() => { onClose(); go(path) }} className="flex min-h-[104px] flex-col items-center justify-center gap-2 rounded-2xl bg-muted/60 px-1.5 py-3 text-center active:scale-95">
                  <span className={cn('grid size-10 place-items-center rounded-xl', tone)}><Icon className="size-5" /></span>
                  <span className="text-[13px] font-semibold leading-tight">{label}</span>
                  <span className="text-[11px] leading-tight text-muted-foreground">{hint}</span>
                </button>
              ))}
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  )
}
