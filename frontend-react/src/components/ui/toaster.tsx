import { AnimatePresence, motion } from 'framer-motion'
import { CheckCircle2, Info, X, XCircle } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useToasts, type ToastTone } from '@/stores/toast'

const icons: Record<ToastTone, typeof Info> = { success: CheckCircle2, error: XCircle, info: Info }
const tones: Record<ToastTone, string> = { success: 'text-success', error: 'text-danger', info: 'text-info' }

/** Messages from the server, in its own words, where they will be seen. */
export function Toaster() {
  const { toasts, dismiss } = useToasts()
  return (
    <div
      aria-live="polite"
      className="pointer-events-none fixed bottom-4 right-4 z-[80] flex w-[min(24rem,calc(100vw-2rem))] flex-col gap-2 pb-safe"
    >
      <AnimatePresence initial={false}>
        {toasts.map((t) => {
          const Icon = icons[t.tone]
          return (
            <motion.div
              key={t.id}
              layout
              role={t.tone === 'error' ? 'alert' : 'status'}
              initial={{ opacity: 0, y: 16, scale: 0.96 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, x: 24 }}
              transition={{ type: 'spring', stiffness: 460, damping: 36 }}
              className="pointer-events-auto flex items-start gap-3 rounded-xl border border-border bg-popover p-3.5 shadow-pop"
            >
              <Icon className={cn('mt-0.5 size-[18px] shrink-0', tones[t.tone])} />
              <p className="min-w-0 flex-1 text-[13.5px] leading-snug">{t.message}</p>
              <button
                type="button"
                onClick={() => dismiss(t.id)}
                aria-label="Dismiss"
                className="-mr-1 grid size-6 shrink-0 place-items-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground"
              >
                <X className="size-3.5" />
              </button>
            </motion.div>
          )
        })}
      </AnimatePresence>
    </div>
  )
}
