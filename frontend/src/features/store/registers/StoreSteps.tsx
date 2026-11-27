import { Link } from 'react-router-dom'
import { ArrowDownToLine, ArrowUpFromLine, ClipboardList, Boxes, Package, RotateCcw, ShoppingCart, Undo2, type LucideIcon } from 'lucide-react'
import { STORE_MORE, STORE_STEPS } from '@/lib/nav'
import { useSession } from '@/lib/session'

const ICONS: Record<number, LucideIcon> = { 1: Package, 2: ClipboardList, 3: ShoppingCart, 4: ArrowDownToLine, 5: Undo2, 6: ArrowUpFromLine, 7: RotateCcw, 8: Boxes }

/**
 * The store's work as numbered steps, in the order it is done, in plain words: big cards a person who reads little English can
 * follow - like the Subcontractors menu. Only the steps this person may open are shown; the numbers stay as they are, so
 * "step 4" means the same to everyone.
 */
export function StoreSteps() {
  const { can } = useSession()
  const steps = STORE_STEPS.filter((s) => can(s.perm))
  if (!steps.length) return null
  return (
    <section aria-labelledby="store-steps" className="mb-8">
      <h2 id="store-steps" className="mb-1 text-lg font-semibold">How the store works</h2>
      <p className="mb-3 text-sm text-muted-foreground">Do the work in this order. Click a step to open it.</p>
      <ol className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {steps.map((s) => {
          const Icon = ICONS[s.n] ?? Package
          return (
            <li key={s.n}>
              <Link to={s.path} className="flex h-full items-start gap-3 rounded-2xl border border-border bg-card p-4 transition hover:border-primary hover:bg-primary/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                <span className="flex size-10 shrink-0 items-center justify-center rounded-full bg-primary text-lg font-bold text-primary-foreground" aria-hidden="true">{s.n}</span>
                <span className="min-w-0">
                  <span className="flex items-center gap-2 text-base font-semibold"><Icon className="size-4 shrink-0 text-primary" /> <span className="sr-only">Step {s.n}: </span>{s.label}</span>
                  <span className="mt-0.5 block text-sm text-muted-foreground">{s.say}</span>
                </span>
              </Link>
            </li>
          )
        })}
      </ol>
    </section>
  )
}

/** The rest of the store, after the steps. */
export function StoreMore({ bare = false }: { bare?: boolean }) {
  const { can } = useSession()
  const more = STORE_MORE.filter((s) => can(s.perm))
  if (!more.length) return bare ? <p className="text-sm text-muted-foreground">Nothing more here for you.</p> : null
  return (
    <section aria-labelledby={bare ? undefined : 'store-more'} aria-label={bare ? 'More in the store' : undefined} className={bare ? '' : 'mt-8'}>
      {!bare && <h2 id="store-more" className="mb-3 text-lg font-semibold">More in the store</h2>}
      <ul className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
        {more.map((s) => (
          <li key={s.path}>
            <Link to={s.path} className="block rounded-xl border border-border bg-card px-4 py-3 transition hover:border-primary hover:bg-primary/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
              <span className="block font-medium">{s.label}</span>
              <span className="block text-sm text-muted-foreground">{s.say}</span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  )
}
