import { useNavigate } from 'react-router-dom'
import { AnimatePresence, motion } from 'framer-motion'
import { AlertTriangle, BookOpen, ClipboardCheck, ListChecks, PackageCheck, Ruler, type LucideIcon } from 'lucide-react'
import { useSession } from '@/lib/session'
import { useCurrentSite } from './site'

/** The six things recorded on site, and where each is recorded. A tile appears only for someone who may do it. */
const TILES: { label: string; hint: string; path: string; perm?: string; icon: LucideIcon; from: string; to: string }[] = [
  { label: 'Site diary', hint: 'Labour, weather, photos', path: '/projects/diary', perm: 'site.record', icon: BookOpen, from: '#8b5cf6', to: '#a78bfa' },
  { label: 'Tasks', hint: 'Tick what got done', path: '/projects/programme', icon: ListChecks, from: '#10b981', to: '#34d399' },
  { label: 'Measurement', hint: 'No × L × B × D', path: '/subcontractors/measurement-book', perm: 'site.record', icon: Ruler, from: '#0ea5e9', to: '#38bdf8' },
  { label: 'Goods in', hint: 'Material at the gate', path: '/store/hub/inward/grn/new', perm: 'store.inward.create', icon: PackageCheck, from: '#f59e0b', to: '#fbbf24' },
  { label: 'Safety', hint: 'Near miss or incident', path: '/projects/safety', icon: AlertTriangle, from: '#ef4444', to: '#f87171' },
  { label: 'Quality', hint: 'Inspection or snag', path: '/projects/quality', icon: ClipboardCheck, from: '#64748b', to: '#94a3b8' },
]

/** The sheet the + slides up: record something for the site you are on, in two taps from anywhere. */
export function AddSheet({ open, onClose }: { open: boolean; onClose: () => void }) {
  const go = useNavigate()
  const { can } = useSession()
  const { site } = useCurrentSite()
  const name = site?.name
  const tiles = TILES.filter((t) => !t.perm || can(t.perm))
  return (
    <AnimatePresence>
      {open && (
        <>
          <motion.button type="button" aria-label="Close" onClick={onClose} className="fixed inset-0 z-50 bg-black/55 backdrop-blur-[2px]" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} />
          <motion.div
            role="dialog"
            aria-label="Add a record"
            className="fixed inset-x-0 bottom-0 z-[51] mx-auto max-w-xl rounded-t-[28px] border border-b-0 border-border bg-card pl-[max(1rem,env(safe-area-inset-left))] pr-[max(1rem,env(safe-area-inset-right))] pb-[calc(24px+env(safe-area-inset-bottom))] pt-2.5 md:max-w-3xl"
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
            <h2 className="text-[22px] font-extrabold tracking-tight">Add</h2>
            <p className="mb-4 text-sm text-muted-foreground">{name ? `For ${name}` : 'What happened on site?'}</p>
            {/* Two rows of three on a phone held upright; one row of six where there is width, or too little height for two rows. */}
            <div className="grid grid-cols-3 gap-2.5 md:grid-cols-6 [@media(max-height:480px)]:grid-cols-6">
              {tiles.map(({ label, hint, path, icon: Icon, from, to }) => (
                <button key={label} type="button" onClick={() => { onClose(); go(path) }} className="flex min-h-[108px] flex-col items-center justify-start gap-2 rounded-[20px] bg-muted px-1.5 py-3.5 text-center active:scale-95">
                  <span className="grid size-11 place-items-center rounded-[15px] text-white" style={{ background: `linear-gradient(135deg, ${from}, ${to})` }}><Icon className="size-5" /></span>
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
