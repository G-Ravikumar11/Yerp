import { useState } from 'react'
import { Plus } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { Badge, Button, Stat, StatGrid, Tabs } from '@/components/ui'
import { emdBack, leadKeys, useEmds, useLeads, type Lead, type LeadStatus } from '@/api/leads'
import { useAction } from '@/lib/mutate'
import { useSession } from '@/lib/session'
import { formatDate } from '@/lib/format'
import { cn, compactINR, formatINR } from '@/lib/utils'
import { LeadDetailModal } from './LeadDetailModal'
import { LeadFormModal } from './LeadFormModal'

type Tab = 'board' | 'emd' | 'closed'
const STAGES: [LeadStatus, string][] = [['NEW', 'New'], ['QUALIFIED', 'Qualified'], ['ESTIMATING', 'Estimating'], ['SUBMITTED', 'Bid in']]
const CLOSED: LeadStatus[] = ['WON', 'LOST', 'DROPPED']

function Due({ days, on }: { days: number | null; on: string }) {
  if (days == null) return null
  if (days < 0) return <span className="font-semibold text-danger">bid date passed</span>
  if (days <= 3) return <span className="font-semibold text-danger">bid in {days} day{days === 1 ? '' : 's'}</span>
  if (days <= 7) return <span className="text-warning">bid in {days} days</span>
  return <span>bid {formatDate(on)}</span>
}

function Card({ l, onOpen }: { l: Lead; onOpen: () => void }) {
  return (
    <button type="button" onClick={onOpen} className="mb-2 block w-full rounded-lg border border-border bg-card p-2.5 text-left shadow-xs transition-colors hover:border-primary/40">
      <div className="font-mono text-[11px] text-muted-foreground">{l.number}</div>
      <div className="text-[13px] font-semibold leading-snug">{l.title}</div>
      <div className="text-xs text-muted-foreground">{l.customer_name}</div>
      <div className="mt-1.5 flex justify-between gap-2 text-xs">
        <span className="tabular">{formatINR(l.estimated_value)}</span>
        <Due days={l.days_to_bid} on={l.bid_due_on} />
      </div>
      {l.emd_outstanding && <div className="mt-1 text-[11px] text-muted-foreground">EMD {formatINR(l.emd_amount)} out</div>}
    </button>
  )
}

export default function LeadsPage() {
  const { can } = useSession()
  const leads = useLeads()
  const [tab, setTab] = useState<Tab>('board')
  const emds = useEmds(tab === 'emd')
  const [openId, setOpenId] = useState<number | null>(null)
  const [editing, setEditing] = useState<Lead | null>(null)
  const [creating, setCreating] = useState(false)
  const back = useAction((l: Lead) => emdBack(l.id), { invalidate: [leadKeys.all] })

  const d = leads.data
  const s = d?.summary
  const rows = d?.leads ?? []
  const manage = can('billing.manage')

  const closedCols: TableColumn<Lead>[] = [
    { id: 'no', header: 'No.', cell: (l) => <span className="font-mono text-[13px]">{l.number}</span> },
    { id: 'title', header: 'Tender', cell: (l) => <div className="max-w-xs truncate">{l.title}</div> },
    { id: 'client', header: 'Client', hideBelow: 'md', cell: (l) => l.customer_name },
    { id: 'ours', header: 'Our price', align: 'right', cell: (l) => formatINR(l.our_price || l.estimated_value) },
    { id: 'out', header: 'Outcome', cell: (l) => <Badge tone={l.status === 'WON' ? 'success' : l.status === 'LOST' ? 'danger' : 'neutral'}>{l.status.charAt(0) + l.status.slice(1).toLowerCase()}</Badge> },
    { id: 'why', header: 'Why / who won', hideBelow: 'lg', cell: (l) => [l.lost_reason, l.winning_bidder].filter(Boolean).join(' - ') },
    { id: 'theirs', header: 'Their price', hideBelow: 'lg', align: 'right', cell: (l) => (l.winning_price ? formatINR(l.winning_price) : '') },
  ]

  const emdCols: TableColumn<Lead>[] = [
    { id: 'tender', header: 'Tender', cell: (l) => <div className="max-w-xs"><span className="font-mono text-[13px]">{l.number}</span> <span className="truncate">{l.title}</span></div> },
    { id: 'client', header: 'Client', hideBelow: 'md', cell: (l) => l.customer_name },
    { id: 'mode', header: 'Mode / ref.', hideBelow: 'lg', cell: (l) => `${l.emd_mode} ${l.emd_reference}` },
    { id: 'paid', header: 'Paid on', hideBelow: 'lg', cell: (l) => formatDate(l.emd_paid_on) },
    { id: 'held', header: 'Days held', align: 'right', cell: (l) => <span className={cn(CLOSED.includes(l.status) && 'font-bold text-danger')}>{l.days_held ?? 0}</span> },
    { id: 'amt', header: 'Amount', align: 'right', cell: (l) => <span className="font-semibold">{formatINR(l.emd_amount)}</span> },
    { id: 'is', header: 'Tender is', cell: (l) => <span>{l.status.toLowerCase()}{CLOSED.includes(l.status) && <span className="ml-1 text-[11px] text-danger">chase it</span>}</span> },
    { id: 'act', header: '', align: 'right', cell: (l) => manage ? <Button size="sm" variant="outline" loading={back.isPending && back.variables?.id === l.id} onClick={() => back.mutate(l)}>Came back</Button> : null },
  ]

  return (
    <>
      <PageHeader
        eyebrow="Clients"
        title="Tender Pipeline"
        description="The tenders in play by stage, the bid dates coming up, and the earnest money still with clients. Pricing a tender makes it an estimate, and the estimate's win or loss comes back here."
        actions={manage && <Button onClick={() => setCreating(true)}><Plus /> New tender</Button>}
      />
      <StatGrid>
        <Stat label="Live tenders" value={s?.live ?? 0} loading={leads.isPending} />
        <Stat label="Pipeline value" value={compactINR(s?.pipeline_value)} loading={leads.isPending} />
        <Stat label="Bids due this week" value={s?.due_this_week ?? 0} tone={s?.due_this_week ? 'warning' : undefined} loading={leads.isPending} />
        <Stat label="Hit rate" value={`${s?.hit_rate ?? 0}%`} loading={leads.isPending} />
        <Stat label="EMD with clients" value={compactINR(s?.emd_out)} sub={s?.emd_out_count ? `${s.emd_out_count} deposits` : undefined} loading={leads.isPending} />
      </StatGrid>

      <div className="mb-4">
        <Tabs label="View" value={tab} onChange={setTab} items={[{ value: 'board', label: 'Board' }, { value: 'emd', label: 'EMD register' }, { value: 'closed', label: 'Decided' }]} />
      </div>

      {tab === 'board' && (
        <div className="grid gap-3 overflow-x-auto pb-2 md:grid-cols-4">
          {STAGES.map(([st, label]) => {
            const here = rows.filter((l) => l.status === st)
            return (
              <section key={st} aria-label={label} className="min-h-32 min-w-56 rounded-xl bg-muted/50 p-2.5">
                <h2 className="mb-2 flex justify-between text-[13px] font-bold">
                  {label}
                  <span className="font-normal text-muted-foreground">{here.length} · {compactINR(here.reduce((t, l) => t + (l.estimated_value || 0), 0))}</span>
                </h2>
                {here.map((l) => <Card key={l.id} l={l} onOpen={() => setOpenId(l.id)} />)}
              </section>
            )
          })}
        </div>
      )}
      {tab === 'closed' && <DataTable label="Decided tenders" rows={rows.filter((l) => CLOSED.includes(l.status))} columns={closedCols} rowKey={(l) => l.id} loading={leads.isPending} onRowClick={(l) => setOpenId(l.id)} empty="Nothing decided yet." />}
      {tab === 'emd' && <DataTable label="Earnest money out" rows={emds.data?.emds ?? []} columns={emdCols} rowKey={(l) => l.id} loading={emds.isPending} empty="No earnest money out." />}

      <LeadDetailModal id={openId} onClose={() => setOpenId(null)} onEdit={(l) => setEditing(l)} />
      <LeadFormModal open={creating || !!editing} lead={editing} sources={d?.sources ?? []} modes={d?.emd_modes ?? []} onClose={() => { setCreating(false); setEditing(null) }} onSaved={(l) => setOpenId(l.id)} />
    </>
  )
}
