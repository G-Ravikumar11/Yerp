import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { Badge, Card, CardContent, CardDescription, CardHeader, CardTitle, Skeleton, Stat, StatGrid } from '@/components/ui'
import { get } from '@/lib/api'
import { formatDate } from '@/lib/format'
import { compactINR, formatINR } from '@/lib/utils'

/** One row of money still to come in or go out. */
interface OwedRow {
  id: number
  number: string
  kind: string
  party?: string
  customer?: string
  due_date: string
  outstanding: number
  bucket: string
  days_overdue: number
  approved?: boolean
  payment_request?: { number: string; status: string; label: string } | null
}

interface EntryRow { id: number; number: string; direction: 'IN' | 'OUT'; party_name: string; doc_number: string; doc_type: string; head: string; amount: number; paid_on: string; mode: string }
/** A payment request raised on this project, as Payment Approvals lists it. */
interface RequestRow { id: number; number: string; doc_number: string; party_name: string; head: string; amount: number; status: string; status_label: string; expired: boolean; requested_by_name: string; requested_at: string; approved_by_name: string; rejected_by_name: string; reject_reason: string }
interface Paper { id: number; number: string; status: string; total?: number; value?: number; net?: number; supplier?: string; approval?: string }

/** What the server sends for one project: its figures, and the papers and payments behind them. */
export interface ProjectAccountsData {
  project: {
    job_id: number; number: string; name: string; customer_name: string; status: string
    contract_value: number; billed: number; paid: number; unpaid: number; incurred: number; commitment: number; forecast_cost: number
    invoiced: number; received: number; outstanding: number; retention_held: number; retention_percent: number; margin: number; margin_percent: number
    percent_complete: number; over_billed: number; labour: number; bills_awaiting_approval: number
    categories: { key: string; label: string; amount: number }[]
    bill_list: Paper[]; purchase_order_list: Paper[]; subcontract_list: Paper[]; work_order_list: Paper[]
  }
  to_receive: OwedRow[]
  to_pay: OwedRow[]
  receive_total: number
  pay_total: number
  overdue_receive: number
  overdue_pay: number
  entries: EntryRow[]
  payment_requests: RequestRow[]
  request_summary: { with_accounts: number; with_md: number; to_pay: number; open: number }
  monthly: { month: string; received: number; paid: number }[]
  received: number
  paid: number
  advances: { contractors: number; suppliers: number; on_account_contractors: number; staff: number; other: number }
  site_cash: { box: string; custodian: string; in_hand: number; pending: number }[]
  journal_cost: number
  debit_notes: number
}

/** The page keeps what it last read between visits, so what comes back may be from before a field was added: fill every list and
 * total in, so an older answer shows what it has and never breaks the screen. */
const withDefaults = (d: ProjectAccountsData): ProjectAccountsData => ({
  ...d,
  to_receive: d.to_receive ?? [], to_pay: d.to_pay ?? [], entries: d.entries ?? [], payment_requests: d.payment_requests ?? [], monthly: d.monthly ?? [], site_cash: d.site_cash ?? [],
  request_summary: d.request_summary ?? { with_accounts: 0, with_md: 0, to_pay: 0, open: 0 },
  advances: d.advances ?? { contractors: 0, suppliers: 0, on_account_contractors: 0, staff: 0, other: 0 },
  receive_total: d.receive_total ?? 0, pay_total: d.pay_total ?? 0, overdue_receive: d.overdue_receive ?? 0, overdue_pay: d.overdue_pay ?? 0,
  received: d.received ?? 0, paid: d.paid ?? 0, journal_cost: d.journal_cost ?? 0, debit_notes: d.debit_notes ?? 0,
  project: { ...d.project, categories: d.project?.categories ?? [], bill_list: d.project?.bill_list ?? [], purchase_order_list: d.project?.purchase_order_list ?? [], subcontract_list: d.project?.subcontract_list ?? [], work_order_list: d.project?.work_order_list ?? [] },
})

const useProjectAccounts = (id: number) =>
  useQuery({ queryKey: ['dashboard', 'project-accounts', 'v2', id], enabled: id > 0, retry: false, select: withDefaults, queryFn: () => get<ProjectAccountsData>(`/api/money/project-accounts/${id}`) })

const money = 'tabular text-right'

const approvalText = (r: OwedRow) => {
  const q = r.payment_request
  if (q) return { tone: q.status === 'APPROVED' ? 'success' : q.status === 'REJECTED' || q.status === 'EXPIRED' ? 'danger' : 'warning', text: q.status === 'APPROVED' ? 'approved - to pay' : q.label.toLowerCase() } as const
  if (r.approved === false) return { tone: 'warning', text: 'bill not approved' } as const
  return null
}

const receiveCols: TableColumn<OwedRow>[] = [
  { id: 'no', header: 'Bill', cell: (r) => <div><span className="font-mono text-[13px] font-semibold">{r.number}</span><div className="text-xs text-muted-foreground">{r.kind}</div></div> },
  { id: 'who', header: 'Client', hideBelow: 'md', cell: (r) => r.customer || '-' },
  { id: 'due', header: 'Due', cell: (r) => <div>{formatDate(r.due_date) || '-'}{r.days_overdue > 0 && <Badge tone="danger" className="ml-1.5">{r.days_overdue} days late</Badge>}</div> },
  { id: 'out', header: 'Still to receive', align: 'right', sort: (r) => r.outstanding, cell: (r) => <span className={`${money} font-bold`}>{formatINR(r.outstanding)}</span> },
]

const payCols: TableColumn<OwedRow>[] = [
  { id: 'no', header: 'Bill', cell: (r) => <div><span className="font-mono text-[13px] font-semibold">{r.number}</span><div className="text-xs text-muted-foreground">{r.kind}</div></div> },
  { id: 'who', header: 'Pay to', hideBelow: 'md', cell: (r) => r.party || '-' },
  { id: 'due', header: 'Due', cell: (r) => <div>{formatDate(r.due_date) || '-'}{r.days_overdue > 0 && <Badge tone="danger" className="ml-1.5">{r.days_overdue} days late</Badge>}</div> },
  { id: 'ap', header: 'Approval', hideBelow: 'md', cell: (r) => { const a = approvalText(r); return a ? <Badge tone={a.tone}>{a.text}</Badge> : <Badge tone="success">approved</Badge> } },
  { id: 'out', header: 'Still to pay', align: 'right', sort: (r) => r.outstanding, cell: (r) => <span className={`${money} font-bold`}>{formatINR(r.outstanding)}</span> },
]

const entryCols: TableColumn<EntryRow>[] = [
  { id: 'date', header: 'Date', cell: (e) => formatDate(e.paid_on) },
  { id: 'no', header: 'Entry', hideBelow: 'md', cell: (e) => <span className="font-mono text-[13px]">{e.number}</span> },
  { id: 'who', header: 'Party', cell: (e) => <div>{e.party_name || e.head || '-'}<div className="text-xs text-muted-foreground">{e.doc_number || e.head || e.doc_type.replace('_', ' ')} - {e.mode}</div></div> },
  { id: 'dir', header: '', cell: (e) => <Badge tone={e.direction === 'IN' ? 'success' : 'neutral'}>{e.direction === 'IN' ? 'received' : 'paid'}</Badge> },
  { id: 'amt', header: 'Amount', align: 'right', sort: (e) => e.amount, cell: (e) => <span className={money}>{formatINR(e.amount)}</span> },
]

const requestCols: TableColumn<RequestRow>[] = [
  { id: 'no', header: 'Request', cell: (r) => <div><span className="font-mono text-[13px] font-semibold">{r.number}</span><div className="text-xs text-muted-foreground">{r.doc_number || r.head || 'on account'}</div></div> },
  { id: 'who', header: 'Pay to', hideBelow: 'md', cell: (r) => r.party_name || '-' },
  { id: 'by', header: 'Asked by', hideBelow: 'lg', cell: (r) => <div>{r.requested_by_name || '-'}<div className="text-xs text-muted-foreground">{formatDate(r.requested_at.slice(0, 10))}</div></div> },
  { id: 'st', header: 'Where it stands', cell: (r) => <div><Badge tone={r.status === 'APPROVED' && !r.expired ? 'success' : r.status === 'REJECTED' || r.expired ? 'danger' : r.status === 'PAID' ? 'neutral' : 'warning'}>{r.status_label.toLowerCase()}</Badge>{r.approved_by_name && r.status === 'APPROVED' && <div className="text-xs text-muted-foreground">by {r.approved_by_name}</div>}{r.status === 'REJECTED' && r.reject_reason && <div className="text-xs text-muted-foreground">{r.reject_reason}</div>}</div> },
  { id: 'amt', header: 'Amount', align: 'right', sort: (r) => r.amount, cell: (r) => <span className={money}>{formatINR(r.amount)}</span> },
]

const monthCols: TableColumn<{ month: string; received: number; paid: number }>[] = [
  { id: 'm', header: 'Month', cell: (m) => m.month },
  { id: 'in', header: 'Received', align: 'right', cell: (m) => <span className={money}>{formatINR(m.received)}</span> },
  { id: 'out', header: 'Paid', align: 'right', cell: (m) => <span className={money}>{formatINR(m.paid)}</span> },
  { id: 'net', header: 'Net', align: 'right', cell: (m) => <span className={`${money} font-semibold`}>{formatINR(m.received - m.paid)}</span> },
]

/** The Finance Dashboard for one project: how much it was sold for, billed and received, what it has cost, what is still to pay,
 * and the bills and payments behind each figure. */
export function ProjectAccounts({ id }: { id: number }) {
  const q = useProjectAccounts(id)
  if (q.isPending) return <div className="grid gap-4"><Skeleton className="h-28 w-full" /><Skeleton className="h-64 w-full" /></div>
  if (q.isError || !q.data) return <p role="alert" className="rounded-lg border border-border p-4 text-sm text-muted-foreground">This project's accounts could not be loaded. Accounts and Reports access are needed.</p>
  const d = q.data
  const p = d.project
  const adv = d.advances
  const advances = (adv?.contractors ?? 0) + (adv?.suppliers ?? 0) + (adv?.on_account_contractors ?? 0) + (adv?.staff ?? 0) + (adv?.other ?? 0)
  const papers = (title: string, rows: Paper[], amount: (r: Paper) => number) => (
    <div>
      <h4 className="mb-1 text-[13px] font-semibold">{title} <span className="font-normal text-muted-foreground">({rows.length})</span></h4>
      {rows.length === 0 ? <p className="text-[13px] text-muted-foreground">None.</p> : (
        <ul className="grid gap-1 text-[13px]">
          {rows.slice(0, 8).map((r) => <li key={r.id} className="flex justify-between gap-3"><span><span className="font-mono">{r.number || '-'}</span> <span className="text-muted-foreground">{r.supplier || r.status}</span></span><span className="tabular">{formatINR(amount(r))}</span></li>)}
          {rows.length > 8 && <li className="text-muted-foreground">and {rows.length - 8} more</li>}
        </ul>
      )}
    </div>
  )
  return (
    <div className="grid gap-5">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="font-mono font-semibold">{p.number}</span><span className="font-medium">{p.name}</span>
        <span className="text-muted-foreground">for {p.customer_name || 'no client'}</span><Badge>{p.status || 'running'}</Badge>
        <span className="ml-auto flex flex-wrap gap-3 text-xs font-medium">
          <Link to={`/money/ledgers?project=${p.job_id}`} className="text-primary">Ledgers of this project</Link>
          <Link to={`/money/ledgers?tab=entries&project=${p.job_id}`} className="text-primary">Vouchers of this project</Link>
          <Link to={`/projects/${p.job_id}`} className="text-primary">Open the project</Link>
        </span>
      </div>

      <section aria-label="Money in">
        <h3 className="mb-2 text-sm font-semibold">Money in: what the client pays</h3>
        <StatGrid>
          <Stat label="Contract value" value={compactINR(p.contract_value)} sub={`${p.percent_complete ?? 0}% of the work done`} />
          <Stat label="Billed to client" value={compactINR(p.invoiced)} sub={p.over_billed > 0 ? `${compactINR(p.over_billed)} billed ahead of the work` : undefined} />
          <Stat label="Received" value={compactINR(d.received)} sub={d.entries.some((e) => e.direction === 'IN') ? 'Receipts entered and bills settled' : undefined} />
          <Stat label="Still to receive" value={compactINR(d.receive_total)} tone={d.overdue_receive > 0 ? 'danger' : undefined} sub={d.overdue_receive > 0 ? `${compactINR(d.overdue_receive)} overdue` : undefined} />
          <Stat label="Retention held" value={compactINR(p.retention_held)} sub={p.retention_percent ? `${p.retention_percent}% of each bill` : undefined} />
        </StatGrid>
      </section>

      <section aria-label="Money out">
        <h3 className="mb-2 text-sm font-semibold">Money out: what the project costs</h3>
        <StatGrid>
          <Stat label="Cost so far" value={compactINR(p.incurred)} sub="Bills, contractors, labour, store issues" />
          <Stat label="Promised, not billed" value={compactINR(p.commitment)} sub="Orders placed, bills not yet in" />
          <Stat label="Expected final cost" value={compactINR(p.forecast_cost)} />
          <Stat label="Paid out" value={compactINR(d.paid)} />
          <Stat label="Still to pay" value={compactINR(d.pay_total)} tone={d.overdue_pay > 0 ? 'danger' : undefined} sub={d.overdue_pay > 0 ? `${compactINR(d.overdue_pay)} overdue` : p.bills_awaiting_approval ? `${p.bills_awaiting_approval} bills waiting approval` : undefined} />
        </StatGrid>
      </section>

      <StatGrid>
        <Stat label="Expected profit" value={compactINR(p.margin)} tone={p.margin < 0 ? 'danger' : 'success'} sub={p.contract_value ? `${p.margin_percent}% of the contract` : 'No contract value entered'} />
        <Stat label="Advances not yet adjusted" value={compactINR(advances)} sub="Mobilisation, on account, staff, site cash" />
        <Stat label="Journals on cost" value={compactINR(d.journal_cost)} sub="Approved journals on this project" />
        <Stat label="Debit notes" value={compactINR(d.debit_notes)} sub="Taken back from suppliers" />
      </StatGrid>

      <section aria-label="Payment approvals">
        <h3 className="mb-2 text-sm font-semibold">Payment approvals for this project</h3>
        <StatGrid>
          <Stat label="With the accounts head" value={compactINR(d.request_summary.with_accounts)} to="/money/approvals" />
          <Stat label="With the MD" value={compactINR(d.request_summary.with_md)} to="/money/approvals" />
          <Stat label="Approved, to pay" value={compactINR(d.request_summary.to_pay)} tone={d.request_summary.to_pay > 0 ? 'success' : undefined} to="/money/approvals" />
          <Stat label="Requests open" value={d.request_summary.open} to="/money/approvals" />
        </StatGrid>
        <Card className="mt-3"><CardHeader><CardTitle>Payment requests</CardTitle><CardDescription>Every request raised on this project. Decide them in Payment Approvals; the answer shows here and in To pay.</CardDescription></CardHeader>
          <CardContent><DataTable label="Payment requests" rows={d.payment_requests} columns={requestCols} rowKey={(r) => r.id} empty="No payment has been asked for on this project." /></CardContent></Card>
      </section>

      <div className="grid gap-5 lg:grid-cols-2">
        <Card><CardHeader><CardTitle>To receive</CardTitle><CardDescription>Client bills of this project not fully paid.</CardDescription></CardHeader>
          <CardContent><DataTable label="Bills to receive" rows={d.to_receive} columns={receiveCols} rowKey={(r) => r.kind + r.id} empty="Nothing is waiting to be received on this project." /></CardContent></Card>
        <Card><CardHeader><CardTitle>To pay</CardTitle><CardDescription>Bills of this project not fully paid, with where their payment approval stands.</CardDescription></CardHeader>
          <CardContent><DataTable label="Bills to pay" rows={d.to_pay} columns={payCols} rowKey={(r) => r.kind + r.id} empty="Nothing is waiting to be paid on this project." /></CardContent></Card>
      </div>

      <Card><CardHeader><CardTitle>Payments and receipts</CardTitle><CardDescription>The latest money that moved on this project.</CardDescription></CardHeader>
        <CardContent><DataTable label="Payments and receipts" rows={d.entries} columns={entryCols} rowKey={(e) => e.id} empty="No money has moved on this project yet." /></CardContent></Card>

      <Card><CardHeader><CardTitle>Money by month</CardTitle><CardDescription>What came in and went out of this project, month by month.</CardDescription></CardHeader>
        <CardContent><DataTable label="Money by month" rows={d.monthly} columns={monthCols} rowKey={(m) => m.month} empty="No money has moved on this project yet." /></CardContent></Card>

      <div className="grid gap-5 lg:grid-cols-2">
        <Card><CardHeader><CardTitle>Where the cost went</CardTitle></CardHeader>
          <CardContent>
            <ul className="grid gap-1.5 text-sm">
              {p.categories.filter((c) => c.amount).map((c) => <li key={c.key} className="flex justify-between"><span>{c.label}</span><span className="tabular">{formatINR(c.amount)}</span></li>)}
              {!p.categories.some((c) => c.amount) && <li className="text-muted-foreground">No cost is booked yet.</li>}
            </ul>
          </CardContent></Card>
        <Card><CardHeader><CardTitle>Papers behind the figures</CardTitle></CardHeader>
          <CardContent className="grid gap-4">
            {papers('Supplier bills', p.bill_list, (r) => r.total ?? 0)}
            {papers('Purchase orders', p.purchase_order_list, (r) => r.total ?? 0)}
            {papers('Subcontract orders', p.subcontract_list, (r) => r.net ?? 0)}
            {papers('Work orders from the client', p.work_order_list, (r) => r.value ?? 0)}
          </CardContent></Card>
      </div>
      {d.site_cash.length > 0 && (
        <Card><CardHeader><CardTitle>Site cash</CardTitle><CardDescription>Cash held on site for this project.</CardDescription></CardHeader>
          <CardContent><ul className="grid gap-1 text-sm">{d.site_cash.map((c) => <li key={c.box} className="flex justify-between"><span>{c.box} <span className="text-muted-foreground">with {c.custodian}</span></span><span className="tabular">{formatINR(c.in_hand)}</span></li>)}</ul></CardContent></Card>
      )}
    </div>
  )
}
