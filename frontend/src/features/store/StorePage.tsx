import { useEffect, useState, type FormEvent } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link, useNavigate } from 'react-router-dom'
import { ArrowDownToLine, ArrowUpFromLine, ClipboardCheck, FileBarChart, Repeat, Search, Undo2 } from 'lucide-react'
import { Button, Card, Input } from '@/components/ui'
import { get } from '@/lib/api'
import { useSession } from '@/lib/session'
import { storePerm } from '@/api/store'
import { OldStoreCard } from './OldStore'
import { OverviewBudgets, OverviewMovements, OverviewStats, OverviewWork, useStoreDashboard } from './Overview'
import { SLICES, StoreShell } from './StoreShell'

/** The things people do most, each opening the right form directly. Shown only when the person holds the right to do it. */
const TASKS = [
  { label: 'Receive goods', hint: 'Book a delivery against a purchase order', to: '/store/hub/inward/grn/new', perm: storePerm('inward', 'create'), Icon: ArrowDownToLine },
  { label: 'Issue material', hint: 'Give stock to a site or subcontractor', to: '/store/hub/outward/issue/new', perm: storePerm('outward', 'create'), Icon: ArrowUpFromLine },
  { label: 'Request material', hint: 'Raise an indent for a site', to: '/store/hub/outward/indent/new', perm: storePerm('outward', 'create'), Icon: ClipboardCheck },
  { label: 'Return material', hint: 'Take back unused issued stock', to: '/store/hub/outward/returns/new', perm: storePerm('outward', 'create'), Icon: Undo2 },
  { label: 'Transfer stock', hint: 'Move stock between stores', to: '/store/hub/control/transfer/new', perm: storePerm('control', 'create'), Icon: Repeat },
  { label: 'Count stock', hint: 'Start a physical stock count', to: '/store/hub/control/count/new', perm: storePerm('control', 'create'), Icon: ClipboardCheck },
  { label: 'Reports', hint: 'Stock, consumption and cost', to: '/store/hub/reports', perm: storePerm('reports'), Icon: FileBarChart },
]

/** The Store front page: find stock, see where things stand, do the common jobs in one click, or open any part this person may use. */
export default function StorePage() {
  const { can } = useSession()
  const tasks = TASKS.filter((t) => can(t.perm))
  const any = SLICES.some((s) => can(storePerm(s.slice)))
  const dash = useStoreDashboard(any)
  return (
    <StoreShell slice={null}>
      <OldStoreCard />
      <div className="space-y-8">
        <QuickFind allowed={can(storePerm('enquiry'))} />
        {any && (dash.isError
          ? <p role="alert" className="text-sm text-danger">The store figures could not be loaded. <button type="button" className="underline" onClick={() => void dash.refetch()}>Try again</button></p>
          : <><OverviewStats d={dash.data} /><OverviewWork d={dash.data} /></>)}
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
        {any && !dash.isError && <><OverviewMovements d={dash.data} /><OverviewBudgets d={dash.data} /></>}
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

interface Hit { item_id: number; item_code: string; item_name: string; uom: string; qty: string; stores: number }

/** Type-ahead stock lookup: results appear under the box as you type (after a short pause), so there is no waiting on a full page. */
function QuickFind({ allowed }: { allowed: boolean }) {
  const nav = useNavigate()
  const [q, setQ] = useState('')
  const [term, setTerm] = useState('')
  useEffect(() => { const t = setTimeout(() => setTerm(q.trim()), 200); return () => clearTimeout(t) }, [q])
  const res = useQuery({
    queryKey: ['store', 'enquiry', 'quick', term], enabled: allowed && term.length >= 2, staleTime: 30_000, placeholderData: (prev) => prev,
    queryFn: () => get<{ rows: Hit[] }>(`/api/store/enquiry/quick?q=${encodeURIComponent(term)}`),
  })
  const open = (text: string) => nav(`/store/hub/enquiry?q=${encodeURIComponent(text)}`)
  const submit = (e: FormEvent) => { e.preventDefault(); if (q.trim()) open(q.trim()) }
  const hits = term.length >= 2 ? res.data?.rows ?? [] : []
  return (
    <div className="max-w-2xl">
      <form onSubmit={submit} className="flex gap-2">
        <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Find an item - type its name or code" aria-label="Find an item" autoComplete="off" disabled={!allowed} />
        <Button type="submit" disabled={!allowed || !q.trim()}><Search /> Check stock</Button>
      </form>
      {!allowed && <p className="mt-1 text-xs text-muted-foreground">Stock enquiry is not enabled for your account.</p>}
      {allowed && term.length >= 2 && (
        <Card className="mt-2 overflow-hidden">
          {hits.map((h) => (
            <button key={h.item_id} type="button" onClick={() => open(h.item_code)} className="flex w-full items-center justify-between gap-3 border-b border-border px-4 py-2 text-left text-sm last:border-0 hover:bg-accent">
              <span><span className="font-mono text-xs text-muted-foreground">{h.item_code}</span> {h.item_name}</span>
              <span className={Number(h.qty) > 0 ? 'font-medium' : 'text-muted-foreground'}>{Number(h.qty) > 0 ? `${Number(h.qty).toLocaleString('en-IN', { maximumFractionDigits: 3 })} ${h.uom} in ${h.stores} store${h.stores === 1 ? '' : 's'}` : 'Out of stock'}</span>
            </button>
          ))}
          {hits.length === 0 && <div className="px-4 py-3 text-sm text-muted-foreground">{res.isFetching ? 'Searching...' : 'No matching item.'}</div>}
        </Card>
      )}
    </div>
  )
}
