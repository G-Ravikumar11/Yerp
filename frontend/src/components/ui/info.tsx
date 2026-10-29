import { useEffect, useId, useRef, useState } from 'react'
import { Info } from 'lucide-react'
import { cn } from '@/lib/utils'

/**
 * A small (i) button: press it and a few lines say what this screen or tab is for. It closes on a second press,
 * on Escape, and on a click anywhere else.
 */
export function InfoTip({ title, children, align = 'left', className }: { title: string; children: React.ReactNode; align?: 'left' | 'right'; className?: string }) {
  const [open, setOpen] = useState(false)
  const root = useRef<HTMLSpanElement>(null)
  const id = useId()
  useEffect(() => {
    if (!open) return
    const away = (e: PointerEvent) => { if (!root.current?.contains(e.target as Node)) setOpen(false) }
    const esc = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('pointerdown', away)
    document.addEventListener('keydown', esc)
    return () => { document.removeEventListener('pointerdown', away); document.removeEventListener('keydown', esc) }
  }, [open])
  return (
    <span ref={root} className={cn('relative inline-flex', className)}>
      <button
        type="button"
        aria-label={`About ${title}`}
        aria-expanded={open}
        aria-controls={open ? id : undefined}
        onClick={() => setOpen((o) => !o)}
        className={cn('grid size-7 place-items-center rounded-full text-muted-foreground transition-colors hover:bg-accent hover:text-foreground', open && 'bg-accent text-foreground')}
      >
        <Info className="size-4" />
      </button>
      {open && (
        <div id={id} role="note" className={cn('absolute top-full z-40 mt-2 w-72 max-w-[calc(100vw-2rem)] rounded-lg border border-border bg-popover p-3 text-left shadow-lift animate-pop', align === 'right' ? 'right-0' : 'left-0')}>
          <p className="text-[13px] font-semibold text-foreground">{title}</p>
          <p className="mt-1 text-[13px] leading-snug text-muted-foreground">{children}</p>
        </div>
      )}
    </span>
  )
}
