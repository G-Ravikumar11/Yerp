import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { PageHeader } from '@/components/layout/PageHeader'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { Badge, Button, ConfirmDialog, Field, Input, Modal, Stat, StatGrid, Tabs } from '@/components/ui'
import { decideWorkType, orderKeys, requestWorkType, returnGuarantee, useGuarantees, useWorkTypes, type Guarantee, type WorkTypeRow } from '@/api/orders'
import { get } from '@/lib/api'
import { useAction } from '@/lib/mutate'
import { useSession } from '@/lib/session'
import { formatDate } from '@/lib/format'
import { formatINR } from '@/lib/utils'

type Tab = 'guarantees' | 'recoveries' | 'types'

const BG_TONE = { valid: 'success', expiring: 'warning', expired: 'danger', returned: 'neutral', undated: 'warning' } as const
const BG_WORD = { valid: 'valid', expiring: 'runs out soon', expired: 'ran out', returned: 'returned', undated: 'no date' } as const

/**
 * The registers kept beside the work orders: every bank guarantee a contractor has given and when it runs out,
 * the material issued to contractors to be taken off their bills, and the kinds of work an order can be raised for.
 */
export default function RegistersPage() {
  const [tab, setTab] = useState<Tab>('guarantees')
  return (
    <>
      <PageHeader
        eyebrow="Subcontractors"
        title="Guarantees & registers"
        description="Bank guarantees and when each runs out, the material recovered from contractors' bills, and the kinds of work orders are raised for."
      />
      <div className="mb-5">
        <Tabs
          label="Registers"
          value={tab}
          onChange={setTab}
          items={[
            { value: 'guarantees', label: 'Bank guarantees' },
            { value: 'recoveries', label: 'Material recovered' },
            { value: 'types', label: 'Kinds of work' },
          ]}
        />
      </div>
      {tab === 'guarantees' && <Guarantees />}
      {tab === 'recoveries' && <Recoveries />}
      {tab === 'types' && <WorkTypes />}
    </>
  )
}

function Guarantees() {
  const q = useGuarantees()
  const { can } = useSession()
  const [returning, setReturning] = useState<Guarantee | null>(null)
  const back = useAction((a: { g: Guarantee; comments: string }) => returnGuarantee(a.g.order_id, a.comments), { invalidate: [orderKeys.all], onSuccess: () => setReturning(null) })
  const rows = q.data?.guarantees ?? []
  const s = q.data?.summary
  const columns: TableColumn<Guarantee>[] = [
    {
      id: 'o',
      header: 'Order',
      cell: (g) => (
        <div>
          <Link to={`/subcontractors/work-orders/${g.order_id}`} className="font-mono text-[13px] font-semibold hover:underline">
            {g.wo_number}
          </Link>
          <div className="text-xs text-muted-foreground">{g.project}</div>
        </div>
      ),
    },
    { id: 'c', header: 'Contractor', cell: (g) => g.contractor || '-' },
    { id: 'n', header: 'Guarantee', hideBelow: 'md', cell: (g) => <div>{g.number || '-'}<div className="text-xs text-muted-foreground">{g.bank}</div></div> },
    { id: 'a', header: 'Amount', align: 'right', sort: (g) => g.amount, cell: (g) => <span className="tabular">{formatINR(g.amount)}</span> },
    { id: 'v', header: 'Valid to', sort: (g) => g.valid_to, cell: (g) => <div>{formatDate(g.valid_to) || '-'}{g.days_left != null && g.state !== 'returned' && <div className="text-xs text-muted-foreground">{g.days_left >= 0 ? `${g.days_left} days left` : `${-g.days_left} days ago`}</div>}</div> },
    { id: 's', header: 'State', cell: (g) => <Badge tone={BG_TONE[g.state]}>{BG_WORD[g.state]}</Badge> },
    {
      id: 'act',
      header: '',
      align: 'right',
      cell: (g) =>
        g.state !== 'returned' && can('subcontracts.approve') ? (
          <Button size="sm" variant="outline" onClick={() => setReturning(g)}>
            Returned
          </Button>
        ) : null,
    },
  ]
  return (
    <>
      <StatGrid className="xl:grid-cols-4">
        <Stat label="Guarantees" value={s?.count ?? 0} loading={q.isPending} />
        <Stat label="Held" value={formatINR(s?.held ?? 0)} loading={q.isPending} />
        <Stat label="Running out within 30 days" value={s?.expiring ?? 0} tone={s?.expiring ? 'warning' : undefined} loading={q.isPending} />
        <Stat label="Already run out" value={s?.expired ?? 0} tone={s?.expired ? 'danger' : undefined} loading={q.isPending} />
      </StatGrid>
      <DataTable label="Bank guarantees" rows={rows} columns={columns} rowKey={(g) => g.order_id} loading={q.isPending} empty="No order carries a bank guarantee." />
      <ConfirmDialog
        open={!!returning}
        onOpenChange={(o) => !o && setReturning(null)}
        title={`Guarantee on ${returning?.wo_number ?? 'this order'} returned?`}
        description="It is handed back to the contractor and stops being watched for expiry."
        confirmLabel="Mark as returned"
        reason={{ label: returning && returning.status !== 'CLOSED' ? 'The order is still open - why is it going back now?' : 'Note (optional)', required: !!returning && returning.status !== 'CLOSED' }}
        loading={back.isPending}
        onConfirm={(comments) => {
          if (returning) back.mutate({ g: returning, comments })
        }}
      />
    </>
  )
}

interface Recovery {
  id: number
  order_id: number
  order: string
  contractor: string
  issue_number: string
  item_code: string
  item_name: string
  uom: string
  quantity: number
  rate: number
  amount: number
  issued_on: string
  sub_bill_id: number | null
  bill: string
  state: 'waiting' | 'recovered'
}

function Recoveries() {
  const q = useQuery({ queryKey: ['subbills', 'recoveries'], queryFn: () => get<{ recoveries: Recovery[]; summary: { waiting: number; recovered: number } }>('/api/material-recoveries') })
  const rows = q.data?.recoveries ?? []
  const columns: TableColumn<Recovery>[] = [
    { id: 'i', header: 'Issue', cell: (r) => <div><span className="font-mono text-[13px]">{r.issue_number}</span><div className="text-xs text-muted-foreground">{formatDate(r.issued_on)}</div></div> },
    { id: 'o', header: 'Order', cell: (r) => <div><Link to={`/subcontractors/work-orders/${r.order_id}`} className="font-mono text-[13px] hover:underline">{r.order}</Link><div className="text-xs text-muted-foreground">{r.contractor}</div></div> },
    { id: 'm', header: 'Material', cell: (r) => <div>{r.item_name || r.item_code}<div className="text-xs text-muted-foreground">{r.quantity} {r.uom} at {formatINR(r.rate)}</div></div> },
    { id: 'a', header: 'Amount', align: 'right', sort: (r) => r.amount, cell: (r) => <span className="tabular font-medium">{formatINR(r.amount)}</span> },
    {
      id: 's',
      header: 'Taken back',
      cell: (r) =>
        r.state === 'recovered' ? (
          <Link to={`/subcontractors/ra-bills/${r.sub_bill_id}`} className="hover:underline">
            <Badge tone="success">on {r.bill || 'a bill'}</Badge>
          </Link>
        ) : (
          <Badge tone="warning">waiting for the next bill</Badge>
        ),
    },
  ]
  return (
    <>
      <StatGrid className="xl:grid-cols-2">
        <Stat label="Waiting to be taken off a bill" value={formatINR(q.data?.summary.waiting ?? 0)} loading={q.isPending} />
        <Stat label="Taken back so far" value={formatINR(q.data?.summary.recovered ?? 0)} loading={q.isPending} />
      </StatGrid>
      <DataTable label="Material recovered from contractors" rows={rows} columns={columns} rowKey={(r) => r.id} loading={q.isPending} empty="No material has been issued to a contractor to be recovered." />
    </>
  )
}

function WorkTypes() {
  const q = useWorkTypes()
  const [asking, setAsking] = useState(false)
  const [name, setName] = useState('')
  const [department, setDepartment] = useState('')
  const [reason, setReason] = useState('')
  const ask = useAction(() => requestWorkType({ name, department, request_reason: reason }), {
    invalidate: [orderKeys.all],
    onSuccess: () => {
      setAsking(false)
      setName('')
      setDepartment('')
      setReason('')
    },
  })
  const decide = useAction((a: { id: number; approve: boolean }) => decideWorkType(a.id, a.approve), { invalidate: [orderKeys.all] })
  const admin = !!q.data?.may_administer
  const columns: TableColumn<WorkTypeRow>[] = [
    { id: 'n', header: 'Kind of work', sort: (w) => w.name, cell: (w) => <div className="font-medium">{w.name}</div> },
    { id: 'c', header: 'Code', hideBelow: 'md', cell: (w) => <span className="font-mono text-xs">{w.code}</span> },
    { id: 'd', header: 'Trade', sort: (w) => w.department, cell: (w) => w.department || '-' },
  ]
  const asked: TableColumn<WorkTypeRow>[] = [
    ...columns,
    { id: 'by', header: 'Asked by', cell: (w) => <div>{w.requested_by_name || '-'}{w.request_reason && <div className="text-xs text-muted-foreground">{w.request_reason}</div>}</div> },
    {
      id: 'act',
      header: '',
      align: 'right',
      cell: (w) =>
        admin ? (
          <div className="flex justify-end gap-1.5">
            <Button size="sm" loading={decide.isPending && decide.variables?.id === w.id && decide.variables.approve} onClick={() => decide.mutate({ id: w.id, approve: true })}>
              Add it
            </Button>
            <Button size="sm" variant="outline" onClick={() => decide.mutate({ id: w.id, approve: false })}>
              Decline
            </Button>
          </div>
        ) : (
          <Badge tone="warning">waiting</Badge>
        ),
    },
  ]
  return (
    <>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <p className="max-w-2xl text-sm text-muted-foreground">
          {admin ? 'The list orders pick their kind of work from. What you add is available at once; what others ask for waits here for you.' : 'The list orders pick their kind of work from. What you ask for is added once whoever administers the system approves it.'}
        </p>
        <Button onClick={() => setAsking(true)}>{admin ? 'Add a kind of work' : 'Ask for a kind of work'}</Button>
      </div>
      {(q.data?.requested ?? []).length > 0 && (
        <>
          <h2 className="mb-3 text-lg font-semibold">Asked for</h2>
          <DataTable label="Kinds of work asked for" rows={q.data?.requested ?? []} columns={asked} rowKey={(w) => w.id} className="mb-8" />
        </>
      )}
      <DataTable label="Kinds of work" rows={q.data?.work_types ?? []} columns={columns} rowKey={(w) => w.id} loading={q.isPending} empty="None yet." />
      <Modal
        open={asking}
        onOpenChange={setAsking}
        size="sm"
        title={admin ? 'Add a kind of work' : 'Ask for a kind of work'}
        footer={
          <>
            <Button variant="ghost" onClick={() => setAsking(false)}>
              Cancel
            </Button>
            <Button loading={ask.isPending} disabled={!name.trim()} onClick={() => ask.mutate()}>
              {admin ? 'Add it' : 'Ask for it'}
            </Button>
          </>
        }
      >
        <div className="grid gap-4">
          <Field label="Name" htmlFor="wt-name">
            <Input id="wt-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Waterproofing - basement" autoFocus />
          </Field>
          <Field label="Trade" htmlFor="wt-dept" hint="The department it is filed under, as on the order.">
            <Input id="wt-dept" value={department} onChange={(e) => setDepartment(e.target.value)} placeholder="Civil" />
          </Field>
          {!admin && (
            <Field label="Why it is needed" htmlFor="wt-why">
              <Input id="wt-why" value={reason} onChange={(e) => setReason(e.target.value)} />
            </Field>
          )}
        </div>
      </Modal>
    </>
  )
}
