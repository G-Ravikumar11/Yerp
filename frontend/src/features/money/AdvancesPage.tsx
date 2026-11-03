import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowDownLeft, ArrowUpRight, Download } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { Badge, Button, Select, Stat, StatGrid } from '@/components/ui'
import { useAdvances, type CashWithStaff, type MobilisationAdvance, type OnAccountAdvance } from '@/api/advances'
import { PARTY_LABEL } from '@/api/ledger'
import { projectLabel, useProjects } from '@/api/projects'
import { OnAccountModal } from '@/features/ledger/OnAccountModal'
import { useSession } from '@/lib/session'
import { formatDate } from '@/lib/format'
import { compactINR, formatINR } from '@/lib/utils'

/**
 * Every rupee paid out ahead of the bill it is for, in one place and site by site: mobilisation advances to contractors
 * (taken back from their RA bills), money paid on account to suppliers and contractors (set against their next bill),
 * and staff advances - money paid to a member of staff, and the cash they hold in a site cash box.
 */
export default function AdvancesPage() {
  const { can } = useSession()
  const projects = useProjects()
  const [job, setJob] = useState('')
  const q = useAdvances(Number(job) || 0)
  const d = q.data
  const s = d?.summary
  const [paying, setPaying] = useState<{ direction: 'IN' | 'OUT'; type: string } | null>(null)
  const sites = useMemo(() => (projects.data ?? []).map((p) => ({ value: p.id, label: projectLabel(p) })), [projects.data])

  const mobCols: TableColumn<MobilisationAdvance>[] = [
    {
      id: 'c', header: 'Contractor',
      cell: (r) => (
        <div>
          <div className="font-medium">{r.contractor}</div>
          <Link to={`/subcontractors/work-orders/${r.order_id}`} className="font-mono text-xs text-primary underline-offset-4 hover:underline">{r.order}</Link>
        </div>
      ),
    },
    { id: 'p', header: 'Project', hideBelow: 'md', cell: (r) => r.project || '-' },
    { id: 'a', header: 'Paid', align: 'right', cell: (r) => formatINR(r.advance) },
    { id: 'r', header: 'Taken back', align: 'right', hideBelow: 'md', cell: (r) => <span>{formatINR(r.recovered)} <span className="text-xs text-muted-foreground">({r.percent_recovered}%)</span></span> },
    { id: 'o', header: 'Still out', align: 'right', cell: (r) => <span className="font-semibold">{formatINR(Math.max(0, r.outstanding))}</span> },
    {
      id: 's', header: 'Security',
      cell: (r) => r.over_recovered > 0
        ? <Badge tone="danger" title="The RA bills took back more than was ever paid as the advance. Check the bills' advance recovery.">{formatINR(r.over_recovered)} taken back, never paid</Badge>
        : <Badge tone={r.security === 'secured' || r.security === 'nothing out' ? 'success' : r.security === 'partly secured' ? 'warning' : 'danger'}>{r.security === 'secured' ? 'BG held' : r.security}</Badge>,
    },
  ]
  const accCols: TableColumn<OnAccountAdvance>[] = [
    { id: 'party', header: 'Paid to', cell: (r) => <div><div className="font-medium">{r.party}</div><div className="text-xs text-muted-foreground">{PARTY_LABEL[r.party_type] ?? r.party_type}</div></div> },
    { id: 'p', header: 'Project', hideBelow: 'md', cell: (r) => r.projects.join(', ') || 'Head office' },
    { id: 'l', header: 'Last paid', hideBelow: 'sm', cell: (r) => formatDate(r.last_paid) || '-' },
    { id: 'o', header: 'Not yet set off', align: 'right', cell: (r) => <span className="font-semibold">{formatINR(r.outstanding)}</span> },
  ]
  const cashCols: TableColumn<CashWithStaff>[] = [
    { id: 'who', header: 'Held by', cell: (r) => <div><div className="font-medium">{r.custodian}</div><div className="text-xs text-muted-foreground">{r.box}</div></div> },
    { id: 'p', header: 'Project', hideBelow: 'md', cell: (r) => r.project || '-' },
    { id: 'w', header: 'Spent, waiting to be checked', align: 'right', hideBelow: 'sm', cell: (r) => (r.pending ? formatINR(r.pending) : '-') },
    { id: 'h', header: 'Should be in hand', align: 'right', cell: (r) => <span className="font-semibold">{formatINR(r.in_hand)}</span> },
  ]

  return (
    <>
      <PageHeader
        eyebrow="Accounts"
        title="Advances"
        description="Money paid out before the bill it is for - to contractors, suppliers and staff - and what is still to come back or be set off."
        actions={
          <>
            <Button variant="outline" asChild><a href="/api/registers/advances.xlsx"><Download /> Contractor advances</a></Button>
            {can('bills.pay') && <Button variant="outline" onClick={() => setPaying({ direction: 'IN', type: 'staff' })}><ArrowDownLeft /> Advance returned</Button>}
            {can('bills.pay') && <Button onClick={() => setPaying({ direction: 'OUT', type: 'supplier' })}><ArrowUpRight /> Pay an advance</Button>}
          </>
        }
      />
      <div className="mb-4 w-72"><Select aria-label="Project" value={job} onChange={(e) => setJob(e.target.value)} placeholder="All projects" options={sites} /></div>
      <StatGrid className="xl:grid-cols-4">
        <Stat label="Contractors (mobilisation)" value={compactINR(s?.contractors)} sub={s?.unsecured ? `${compactINR(s.unsecured)} with no guarantee` : 'Taken back from their RA bills'} tone={s?.unsecured ? 'warning' : undefined} loading={q.isPending} />
        <Stat label="Suppliers" value={compactINR(s?.suppliers)} sub="Paid on account, set against their bills" loading={q.isPending} />
        <Stat label="Contractors on account" value={compactINR(s?.on_account_contractors)} loading={q.isPending} />
        <Stat label="Staff" value={compactINR(s?.staff)} sub="Advances, and cash held for site spending" loading={q.isPending} />
      </StatGrid>

      <h2 className="mb-2 mt-2 text-base font-semibold">Contractor mobilisation advances</h2>
      <DataTable
        label="Contractor mobilisation advances" rows={d?.mobilisation ?? []} columns={mobCols} rowKey={(r) => r.order_id} loading={q.isPending} className="mb-8"
        empty="No mobilisation advance is out. It is set on the work order's conditions and paid from Money to Pay."
      />

      <h2 className="mb-2 text-base font-semibold">Paid on account to suppliers and contractors</h2>
      <DataTable
        label="Paid on account" rows={d?.on_account ?? []} columns={accCols} rowKey={(r) => `${r.party_type}-${r.party}`} loading={q.isPending} className="mb-8"
        empty="Nothing paid ahead of a bill. Press Pay an advance to pay a supplier before the goods come."
      />

      <h2 className="mb-2 text-base font-semibold">Staff</h2>
      <DataTable
        label="Staff advances" rows={d?.staff ?? []} columns={accCols} rowKey={(r) => `s-${r.party}`} loading={q.isPending} className="mb-4"
        empty="No advance with any member of staff. Pay an advance with party type Staff; record it as returned when it comes back or is taken from salary (mode Adjustment)."
      />
      <DataTable label="Cash held by staff" rows={d?.site_cash ?? []} columns={cashCols} rowKey={(r) => r.box} loading={q.isPending} empty="No site cash box holds money." />

      <OnAccountModal direction={paying?.direction ?? null} partyType={paying?.type} jobId={Number(job) || undefined} onClose={() => setPaying(null)} />
    </>
  )
}
