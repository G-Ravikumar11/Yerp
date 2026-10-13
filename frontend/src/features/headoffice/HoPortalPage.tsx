import { Link, useNavigate } from 'react-router-dom'
import { AlertTriangle, ArrowRight, Building2, CheckCheck, FilePlus2, HardHat, Landmark, Layers, Receipt, Ruler, UserPlus } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { Badge, Skeleton, Stat, StatGrid } from '@/components/ui'
import { hrefFor, type ApprovalItem } from '@/api/approvals'
import { useHoOverview, type HoDraft, type HoProject } from '@/api/headOffice'
import { ClockCard } from '@/features/staff/ClockCard'
import { formatDate, plural } from '@/lib/format'
import { useSession } from '@/lib/session'
import { compactINR, formatINR } from '@/lib/utils'

/** What HO QS opens. Each lands on its register with the form already open. */
const OPEN = [
  { key: 'vendors', to: '/subcontractors/vendors?new=1', label: 'Open a vendor code', hint: 'Register a sub contractor', icon: UserPlus },
  { key: 'work_orders', to: '/subcontractors/work-orders?new=1', label: 'New sub contractor work order', hint: 'Issue work to a contractor', icon: HardHat },
  { key: 'work_orders', to: '/clients/work-orders?new=1', label: 'New client work order', hint: 'The order the client gave us', icon: FilePlus2 },
  { key: 'boq', to: '/projects/boq?new=1', label: 'Open a BOQ', hint: "A project's bill of quantities", icon: Layers },
] as const

/** Every register head office keeps an eye on. */
const REGISTERS = [
  { to: '/subcontractors/vendors', label: 'Vendor Register', icon: UserPlus },
  { to: '/subcontractors/work-orders', label: 'Sub contractor Work Orders', icon: HardHat },
  { to: '/clients/work-orders', label: 'Client Work Orders', icon: FilePlus2 },
  { to: '/projects/boq', label: 'BOQ', icon: Layers },
  { to: '/subcontractors/ra-bills', label: 'Sub contractor RA Bills', icon: Receipt },
  { to: '/subcontractors/measurement-book', label: 'Measurement Book', icon: Ruler },
  { to: '/clients/measurement', label: 'Client Measurement & RA Bills', icon: Building2 },
  { to: '/approvals', label: 'Approvals', icon: CheckCheck },
]

/**
 * Head office's front page. HO QS and HO Coordinator sign in at the same door as everybody else and
 * land here: every site at once - what is open, what is in draft, what waits on whom, and which
 * projects have no BOQ yet. Only HO QS (and the Master) opens vendor codes, work orders and BOQs, so
 * only they see the buttons that do; the coordinator follows them up.
 */
export default function HoPortalPage() {
  const { user } = useSession()
  const nav = useNavigate()
  const q = useHoOverview()
  const d = q.data
  const may = d?.person.may_create
  const opener = !!may && (may.vendors || may.work_orders || may.boq)
  const first = (user?.name || '').split(' ')[0]
  const hour = new Date().getHours()
  const greeting = hour < 12 ? 'Good morning' : hour < 17 ? 'Good afternoon' : 'Good evening'
  const role = d?.person.role_label || user?.roleLabel || 'Head office'

  const waitingColumns: TableColumn<ApprovalItem>[] = [
    { id: 'what', header: 'Waiting', sort: (w) => w.kind_label, cell: (w) => <div><div className="text-[13px] font-medium">{w.kind_label}</div><div className="font-mono text-xs text-muted-foreground">{w.number}</div></div> },
    { id: 'party', header: 'Party / project', hideBelow: 'md', cell: (w) => <div className="max-w-xs"><div className="truncate text-[13px]">{w.party || '-'}</div><div className="truncate text-xs text-muted-foreground">{w.project}</div></div> },
    { id: 'on', header: 'Waiting on', sort: (w) => w.waiting_on, cell: (w) => <span className="text-[13px] font-medium">{w.waiting_on || 'The Master'}</span> },
    { id: 'since', header: 'Since', sort: (w) => w.since, hideBelow: 'lg', cell: (w) => <span className="text-[13px] text-muted-foreground">{formatDate(w.since)}</span> },
    { id: 'amount', header: 'Value', align: 'right', sort: (w) => w.amount, hideBelow: 'sm', cell: (w) => (w.amount ? formatINR(w.amount) : '-') },
  ]

  const draftColumns: TableColumn<HoDraft>[] = [
    { id: 'number', header: 'Order', sort: (o) => o.number, cell: (o) => <div><div className="font-mono text-[13px] font-semibold">{o.number}</div><div className="text-xs text-muted-foreground">{o.kind_label}</div></div> },
    { id: 'party', header: 'Party / project', hideBelow: 'md', cell: (o) => <div className="max-w-xs"><div className="truncate text-[13px]">{o.party || '-'}</div><div className="truncate text-xs text-muted-foreground">{o.project}</div></div> },
    { id: 'by', header: 'Opened by', sort: (o) => o.raised_by, hideBelow: 'lg', cell: (o) => <span className="text-[13px]">{o.raised_by || '-'}</span> },
    { id: 'since', header: 'Last changed', sort: (o) => o.since, hideBelow: 'lg', cell: (o) => <span className="text-[13px] text-muted-foreground">{formatDate(o.since)}</span> },
    { id: 'amount', header: 'Value', align: 'right', sort: (o) => o.amount, cell: (o) => formatINR(o.amount) },
  ]

  const projectColumns: TableColumn<HoProject>[] = [
    { id: 'number', header: 'Project', sort: (p) => p.number, cell: (p) => <div><div className="text-[13px] font-medium">{p.name}</div><div className="font-mono text-xs text-muted-foreground">{p.number}</div></div> },
    { id: 'status', header: 'Status', cell: (p) => <Badge tone="neutral">{p.status.replace('_', ' ') || '-'}</Badge> },
    {
      id: 'act',
      header: '',
      align: 'right',
      cell: () =>
        may?.boq ? (
          <Link to="/projects/boq?new=1" className="text-[13px] font-medium text-primary hover:underline">
            Open its BOQ
          </Link>
        ) : null,
    },
  ]

  return (
    <>
      <PageHeader
        eyebrow={`Head office · ${role}`}
        title={first ? `${greeting}, ${first}` : 'HO Portal'}
        description={
          opener
            ? 'Every site at once. Vendor codes, work orders and BOQs are opened here, by you - nobody on a site opens them.'
            : 'Every site at once: every vendor, work order, BOQ and bill, and what each is waiting on. HO QS opens vendor codes, work orders and BOQs; you follow them up and keep the drafts up to date.'
        }
      />

      {user?.type === 'employee' && (
        <div className="mb-6">
          <ClockCard />
        </div>
      )}

      {q.isError && (
        <p role="alert" className="mb-6 rounded-lg border border-danger/40 bg-danger-soft p-4 text-sm">
          The HO portal could not be loaded: {q.error instanceof Error ? q.error.message : 'try again in a moment'}.
        </p>
      )}

      {opener && (
        <>
          <h2 className="mb-3 text-sm font-semibold">Open</h2>
          <div className="mb-8 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {OPEN.filter((a) => may?.[a.key]).map(({ to, label, hint, icon: Icon }) => (
              <Link key={to} to={to} className="flex items-center gap-3 rounded-xl border border-border bg-card p-4 shadow-card transition-colors hover:bg-accent">
                <span className="grid size-10 shrink-0 place-items-center rounded-lg bg-primary-soft text-primary">
                  <Icon className="size-5" />
                </span>
                <span className="min-w-0">
                  <span className="block text-sm font-medium">{label}</span>
                  <span className="block text-xs text-muted-foreground">{hint}</span>
                </span>
              </Link>
            ))}
          </div>
        </>
      )}

      {!opener && d && (
        <div className="mb-6 flex items-start gap-3 rounded-xl border border-border bg-muted/40 p-4 text-sm">
          <Landmark className="mt-0.5 size-4 shrink-0 text-primary" />
          <p>
            A vendor code, a work order or a BOQ that is needed goes to <strong>HO QS</strong> to open. Everything already open is yours to follow up: the registers below, and the list of what is waiting on whom.
          </p>
        </div>
      )}

      <StatGrid>
        <Stat label="Vendors registered" value={d?.vendors.registered ?? 0} sub={d && d.vendors.pending ? `${d.vendors.pending} awaiting approval` : undefined} loading={q.isPending} />
        <Stat label="Sub contractor work orders" value={d?.subcontract_orders.total ?? 0} sub={d ? `${d.subcontract_orders.draft} in draft · ${d.subcontract_orders.awaiting} awaiting` : undefined} loading={q.isPending} />
        <Stat label="Client work orders" value={d?.client_orders.total ?? 0} sub={d ? `${d.client_orders.draft} in draft · ${d.client_orders.awaiting} awaiting` : undefined} loading={q.isPending} />
        <Stat label="BOQs" value={d?.boqs.count ?? 0} sub={d && d.boqs.projects_without ? `${plural(d.boqs.projects_without, 'project')} without one` : undefined} tone={d && d.boqs.projects_without ? 'warning' : undefined} loading={q.isPending} />
        <Stat label="RA bills awaiting" value={d?.sub_bills.awaiting ?? 0} sub={d ? `${compactINR(d.sub_bills.claimed)} claimed` : undefined} tone={d && d.sub_bills.awaiting ? 'warning' : undefined} loading={q.isPending} />
      </StatGrid>

      <section aria-label="Waiting on somebody" className="mb-8">
        <h2 className="mb-1 flex items-center gap-2 text-sm font-semibold">
          <AlertTriangle className="size-4 text-warning" /> Waiting on somebody
        </h2>
        <p className="mb-3 text-[13px] text-muted-foreground">Everything in the business sent for a decision and not yet decided, oldest first, with whose desk it is on.</p>
        <DataTable
          label="Waiting on somebody"
          rows={d?.waiting ?? []}
          columns={waitingColumns}
          rowKey={(w) => w.key}
          loading={q.isPending}
          onRowClick={(w) => {
            const h = hrefFor(w)
            if (h.external) window.location.assign(h.to)
            else nav(h.to)
          }}
          empty="Nothing is waiting on anybody."
        />
      </section>

      <section aria-label="Drafts" className="mb-8">
        <h2 className="mb-1 text-sm font-semibold">Orders in draft</h2>
        <p className="mb-3 text-[13px] text-muted-foreground">Opened and not yet sent for approval - finish them and send them up.</p>
        <DataTable label="Orders in draft" rows={d?.drafts ?? []} columns={draftColumns} rowKey={(o) => `${o.kind}:${o.id}`} loading={q.isPending} onRowClick={(o) => nav(o.href)} empty="No orders in draft." />
      </section>

      <section aria-label="Projects without a BOQ" className="mb-8">
        <h2 className="mb-1 text-sm font-semibold">Projects without a BOQ</h2>
        <p className="mb-3 text-[13px] text-muted-foreground">{may?.boq ? 'The next BOQs to open.' : 'Projects HO QS has still to open a BOQ for.'}</p>
        <DataTable label="Projects without a BOQ" rows={d?.projects_without_boq ?? []} columns={projectColumns} rowKey={(p) => p.id} loading={q.isPending} empty="Every live project has its BOQ." />
      </section>

      <h2 className="mb-3 text-sm font-semibold">Registers</h2>
      {q.isPending ? (
        <Skeleton className="h-24 w-full" />
      ) : (
        <div className="mb-8 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {REGISTERS.map(({ to, label, icon: Icon }) => (
            <Link key={to} to={to} className="flex items-center justify-between gap-3 rounded-xl border border-border bg-card p-4 text-sm font-medium shadow-card transition-colors hover:bg-accent">
              <span className="flex min-w-0 items-center gap-3">
                <Icon className="size-4 shrink-0 text-primary" />
                <span className="truncate">{label}</span>
              </span>
              <ArrowRight className="size-4 shrink-0 text-muted-foreground" />
            </Link>
          ))}
        </div>
      )}
    </>
  )
}
