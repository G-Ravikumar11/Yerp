import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { ArrowDownToLine, ArrowUpFromLine, ClipboardCheck, FileBarChart, Repeat, Search, Undo2 } from 'lucide-react'
import { Button, Card, Input } from '@/components/ui'
import { useSession } from '@/lib/session'
import { storePerm } from '@/api/store'
import { SLICES, StoreShell } from './StoreShell'

/** The things people do most, each opening the right form directly. Shown only when the person holds the right to do it. */
const TASKS = [
  { label: 'Receive goods', hint: 'Book a delivery against a purchase order', to: '/store/hub/inward/grn/new', perm: storePerm('inward', 'create'), Icon: ArrowDownToLine },
  { label: 'Issue material', hint: 'Give stock to a site or subcontractor', to: '/store/hub/outward/issues/new', perm: storePerm('outward', 'create'), Icon: ArrowUpFromLine },
  { label: 'Request material', hint: 'Raise a requisition for a site', to: '/store/hub/outward/requisitions/new', perm: storePerm('outward', 'create'), Icon: ClipboardCheck },
  { label: 'Return material', hint: 'Take back unused issued stock', to: '/store/hub/outward/returns/new', perm: storePerm('outward', 'create'), Icon: Undo2 },
  { label: 'Transfer stock', hint: 'Move stock between stores', to: '/store/hub/control/transfers/new', perm: storePerm('control', 'create'), Icon: Repeat },
  { label: 'Count stock', hint: 'Start a physical stock count', to: '/store/hub/control/counts/new', perm: storePerm('control', 'create'), Icon: ClipboardCheck },
  { label: 'Reports', hint: 'Stock, consumption and cost', to: '/store/hub/reports', perm: storePerm('reports'), Icon: FileBarChart },
]

/** The Store front page: find stock, do the common jobs in one click, or open any part this person may use. */
export default function StorePage() {
  const { can } = useSession()
  const nav = useNavigate()
  const [q, setQ] = useState('')
  const tasks = TASKS.filter((t) => can(t.perm))
  const find = (e: FormEvent) => { e.preventDefault(); nav(`/store/hub/enquiry?q=${encodeURIComponent(q.trim())}`) }
  return (
    <StoreShell slice={null}>
      <div className="space-y-8">
        {can(storePerm('enquiry')) && (
          <form onSubmit={find} className="flex max-w-xl gap-2">
            <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Find an item - type its name or code" aria-label="Find an item" />
            <Button type="submit"><Search /> Check stock</Button>
          </form>
        )}
        {tasks.length > 0 && (
          <section>
            <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-muted-foreground">Do something</h2>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              {tasks.map(({ label, hint, to, Icon }) => (
                <Link key={label} to={to}>
                  <Card className="flex h-full items-start gap-3 p-4 transition-colors hover:bg-accent">
                    <Icon className="mt-0.5 size-5 shrink-0 text-primary" />
                    <div><div className="font-medium">{label}</div><div className="text-xs text-muted-foreground">{hint}</div></div>
                  </Card>
                </Link>
              ))}
            </div>
          </section>
        )}
        <section>
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-muted-foreground">Browse</h2>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {SLICES.filter((s) => can(storePerm(s.slice))).map((s) => (
              <Link key={s.slice} to={`/store/hub/${s.slice}`}>
                <Card className="h-full p-4 transition-colors hover:bg-accent">
                  <h3 className="font-semibold">{s.label}</h3>
                  <p className="mt-1 text-sm text-muted-foreground">{s.blurb}</p>
                </Card>
              </Link>
            ))}
          </div>
        </section>
        {SLICES.every((s) => !can(storePerm(s.slice))) && <p className="text-sm text-muted-foreground">You have no Store access yet. Ask your administrator to give you a Store role.</p>}
      </div>
    </StoreShell>
  )
}
