import { Link } from 'react-router-dom'
import { ClipboardList, FileCheck2, FileSignature, Handshake, Package, Truck, Warehouse, type LucideIcon } from 'lucide-react'
import { Card } from '@/components/ui'
import { useSession } from '@/lib/session'
import { STORE_SECTIONS, type StoreSection } from '@/lib/nav'

const ICONS: Record<string, LucideIcon> = {
  '/store/enquiries': ClipboardList,
  '/store/purchase-orders': FileSignature,
  '/store/rate-contracts': Handshake,
  '/store/invoice-tracker': FileCheck2,
  '/store/hub': Warehouse,
  '/store/items': Package,
  '/store/eway': Truck,
}

const BLOCKS: { block: StoreSection['block']; title: string }[] = [
  { block: 'purchase', title: 'Purchase' },
  { block: 'more', title: 'More store work' },
]

/** Below the day's work on the Store page: purchase and the rest of the store, each tile shown only to whoever may open it. */
export function StoreSections() {
  const { can } = useSession()
  const open = STORE_SECTIONS.filter((s) => can(s.perm))
  if (!open.length) return null
  return (
    <div className="space-y-6">
      {BLOCKS.map(({ block, title }) => {
        const tiles = open.filter((s) => s.block === block)
        if (!tiles.length) return null
        return (
          <section key={block}>
            <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-muted-foreground">{title}</h2>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              {tiles.map((s) => {
                const Icon = ICONS[s.path] ?? Package
                return (
                  <Link key={s.path} to={s.path} className="rounded-xl focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                    <Card className="flex h-full items-start gap-3 p-4 transition-colors hover:bg-accent">
                      <Icon className="mt-0.5 size-5 shrink-0 text-primary" />
                      <div><div className="font-medium">{s.label}</div><div className="text-xs text-muted-foreground">{s.hint}</div></div>
                    </Card>
                  </Link>
                )
              })}
            </div>
          </section>
        )
      })}
    </div>
  )
}
