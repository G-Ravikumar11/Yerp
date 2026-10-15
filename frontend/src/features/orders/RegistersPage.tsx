import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { PageHeader } from '@/components/layout/PageHeader'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { Badge, Button, Field, Input, Modal, Stat, StatGrid, Tabs } from '@/components/ui'
import { decideWorkType, orderKeys, requestWorkType, useWorkTypes, type WorkTypeRow } from '@/api/orders'
import { get } from '@/lib/api'
import { useAction } from '@/lib/mutate'
import { useSession } from '@/lib/session'
import { formatDate } from '@/lib/format'
import { formatINR } from '@/lib/utils'

type Tab = 'recoveries' | 'types'

/**
 * The registers kept beside the work orders: the material issued to contractors to be taken off their bills, and
 * the kinds of work an order can be raised for. (Bank guarantees are in Money, TDS, Guarantees & Advances.)
 */
export default function RegistersPage() {
  const [tab, setTab] = useState<Tab>('recoveries')
  return (
    <>
      <PageHeader
        eyebrow="Subcontractors"
        title="Recoveries & kinds of work"
        description="The material issued to contractors and taken back off their bills, and the kinds of work orders are raised for."
      />
      <div className="mb-5">
        <Tabs
          label="Registers"
          value={tab}
          onChange={setTab}
          items={[
            { value: 'recoveries', label: 'Material recovered' },
            { value: 'types', label: 'Kinds of work' },
          ]}
        />
      </div>
      {tab === 'recoveries' && <Recoveries />}
      {tab === 'types' && <WorkTypes />}
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
