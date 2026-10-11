import { useState } from 'react'
import { PageHeader } from '@/components/layout/PageHeader'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { Badge, Button, ConfirmDialog, Stat, StatGrid, Tabs } from '@/components/ui'
import { cancelRelease, owedKeys, useOwedPayables, useOwedReceivables, useRetentionPage, type Payable, type Position, type Receivable, type Release } from '@/api/owed'
import { PayModal } from '@/features/money/PayModal'
import { EInvoiceModal } from '@/features/einvoice/EInvoiceModal'
import { useAction } from '@/lib/mutate'
import { useSession } from '@/lib/session'
import { formatDate } from '@/lib/format'
import { compactINR, formatINR } from '@/lib/utils'
import { AgeingStrip } from './AgeingStrip'
import { ReleaseModal } from './ReleaseModal'

type Tab = 'owed' | 'owe' | 'retention'

function Age({ r }: { r: { bucket: string; days_overdue: number } }) {
  if (r.bucket === 'Not due') return <Badge tone="neutral">not due</Badge>
  return <Badge tone={r.days_overdue > 60 ? 'danger' : 'warning'}>{r.days_overdue} days late</Badge>
}

const money = 'tabular whitespace-nowrap'

export default function OwedPage() {
  const { can } = useSession()
  const [tab, setTab] = useState<Tab>('owed')
  const recv = useOwedReceivables()
  const pay = useOwedPayables()
  const ret = useRetentionPage()
  const [settle, setSettle] = useState<{ type: string; id: number; title: string; verb: 'Receive' | 'Pay' } | null>(null)
  const [releasing, setReleasing] = useState<Position | null>(null)
  const [cancelling, setCancelling] = useState<Release | null>(null)
  const [einvoice, setEinvoice] = useState<number | null>(null)
  const cancel = useAction((a: { r: Release; reason: string }) => cancelRelease(a.r.id, a.reason), { invalidate: [owedKeys.all], onSuccess: () => setCancelling(null) })
  const canPay = can('bills.pay')
  const rs = recv.data?.summary ?? {}
  const ps = pay.data?.summary ?? {}
  const t = ret.data?.summary

  const recvCols: TableColumn<Receivable>[] = [
    { id: 'no', header: 'Invoice', sort: (r) => r.number, cell: (r) => <div><span className="font-mono text-[13px] font-semibold">{r.number}</span><div className="text-xs text-muted-foreground">{r.kind}</div></div> },
    { id: 'cust', header: 'Customer', cell: (r) => <div className="max-w-xs"><div className="truncate">{r.customer || '-'}</div>{r.project && <div className="truncate text-xs text-muted-foreground">{r.project}</div>}</div> },
    { id: 'due', header: 'Due', hideBelow: 'md', sort: (r) => r.due_date, cell: (r) => formatDate(r.due_date) || '-' },
    { id: 'total', header: 'Total', hideBelow: 'lg', align: 'right', cell: (r) => <span className={money}>{formatINR(r.total)}</span> },
    { id: 'paid', header: 'Received', hideBelow: 'lg', align: 'right', cell: (r) => <span className={money}>{formatINR(r.paid)}</span> },
    { id: 'out', header: 'Outstanding', align: 'right', sort: (r) => r.outstanding, cell: (r) => <span className={`${money} font-bold`}>{formatINR(r.outstanding)}</span> },
    { id: 'age', header: 'Age', cell: (r) => <div className="flex items-center gap-2"><Age r={r} />{r.doc_type && canPay && <Button size="sm" variant="outline" onClick={() => setSettle({ type: r.doc_type!, id: r.id, title: r.number, verb: 'Receive' })}>Receive</Button>}</div> },
  ]

  const payCols: TableColumn<Payable>[] = [
    { id: 'no', header: 'Bill', cell: (r) => <div><span className="font-mono text-[13px] font-semibold">{r.number}</span><div className="text-xs text-muted-foreground">{r.kind}</div></div> },
    { id: 'party', header: 'Party', cell: (r) => <div className="max-w-xs"><div className="truncate">{r.party || '-'}</div>{r.project && <div className="truncate text-xs text-muted-foreground">{r.project}</div>}</div> },
    { id: 'due', header: 'Due', hideBelow: 'md', cell: (r) => formatDate(r.due_date) || '-' },
    { id: 'out', header: 'Outstanding', align: 'right', sort: (r) => r.outstanding, cell: (r) => <span className={`${money} font-bold`}>{formatINR(r.outstanding)}</span> },
    { id: 'ap', header: 'Approval', hideBelow: 'md', cell: (r) => <Badge tone={r.approved ? 'success' : 'warning'}>{r.approved ? 'approved' : 'not approved'}</Badge> },
    { id: 'age', header: 'Age', cell: (r) => <div className="flex items-center gap-2"><Age r={r} />{r.doc_type && r.approved !== false && canPay && <Button size="sm" variant="outline" onClick={() => setSettle({ type: r.doc_type!, id: r.id, title: r.number, verb: 'Pay' })}>Pay</Button>}</div> },
  ]

  const posCols = (gang: boolean): TableColumn<Position>[] => [
    { id: 'order', header: 'Order', cell: (p) => <div><span className="font-mono text-[13px] font-semibold">{p.order_number || '-'}</span><div className="text-xs text-muted-foreground">{p.project}</div></div> },
    { id: 'party', header: gang ? 'Contractor' : 'Client', cell: (p) => p.party || '-' },
    { id: 'held', header: 'Held', hideBelow: 'md', align: 'right', cell: (p) => <span className={money}>{formatINR(p.held)}</span> },
    { id: 'rel', header: 'Released', hideBelow: 'md', align: 'right', cell: (p) => <span className={money}>{formatINR(p.released)}</span> },
    { id: 'bal', header: 'Still held', align: 'right', cell: (p) => <span className={`${money} font-bold`}>{formatINR(p.balance)}</span> },
    {
      id: 'st',
      header: gang ? 'Defects period' : 'Job',
      cell: (p) =>
        gang ? (p.dlp_ends ? (p.dlp_over && p.balance > 0 ? <Badge tone="warning">ended {p.dlp_ends} - pay it</Badge> : `ends ${p.dlp_ends}`) : <span className="text-muted-foreground">not set on the order</span>) : p.balance <= 0 ? <Badge tone="success">all released</Badge> : p.finished ? <Badge tone="danger">job finished - claim it</Badge> : <Badge>{p.job_status || 'running'}</Badge>,
    },
    { id: 'act', header: '', align: 'right', cell: (p) => (p.balance > 0 && canPay ? <Button size="sm" variant="outline" onClick={() => setReleasing(p)}>Release</Button> : null) },
  ]

  const relCols: TableColumn<Release>[] = [
    { id: 'no', header: 'Release', cell: (r) => <div><span className="font-mono text-[13px] font-semibold">{r.number}</span><div className="text-xs text-muted-foreground">{formatDate(r.release_on)} · {r.stage}</div></div> },
    { id: 'party', header: 'Party', cell: (r) => <div>{r.party || '-'}<div className="text-xs text-muted-foreground">{r.side === 'client' ? 'client' : 'contractor'} · {r.order_number}</div></div> },
    { id: 'amt', header: 'Amount', hideBelow: 'md', align: 'right', cell: (r) => <span className={money}>{formatINR(r.amount)}</span> },
    { id: 'net', header: 'With GST', align: 'right', cell: (r) => <div className={`${money} font-bold`}>{formatINR(r.net_amount)}<div className="text-xs font-normal text-muted-foreground">GST {formatINR(r.gst_amount)}</div></div> },
    { id: 'out', header: 'Outstanding', hideBelow: 'lg', align: 'right', cell: (r) => <span className={money}>{formatINR(r.outstanding)}</span> },
    { id: 'st', header: 'Status', cell: (r) => <Badge tone={r.status === 'PAID' ? 'success' : r.status === 'CANCELLED' ? 'neutral' : 'warning'}>{r.status === 'CERTIFIED' ? (r.side === 'client' ? 'to receive' : 'to pay') : r.status.toLowerCase()}</Badge> },
    {
      id: 'act',
      header: '',
      align: 'right',
      cell: (r) => (
        <div className="flex flex-wrap items-center justify-end gap-1.5">
          {r.status === 'CERTIFIED' && r.outstanding > 0 && canPay && <Button size="sm" variant="outline" onClick={() => setSettle({ type: 'retention_release', id: r.id, title: r.number, verb: r.side === 'client' ? 'Receive' : 'Pay' })}>{r.side === 'client' ? 'Receive' : 'Pay'}</Button>}
          <Button size="sm" variant="outline" asChild><a href={`/api/retention/releases/${r.id}/export.xlsx`}>Sheet</a></Button>
          {r.side === 'client' && r.status !== 'CANCELLED' && can('accounts.manage') && <Button size="sm" variant="outline" onClick={() => setEinvoice(r.id)}>e-Invoice</Button>}
          {r.status === 'CERTIFIED' && !r.settled && canPay && <Button size="sm" variant="outline" onClick={() => setCancelling(r)}>Cancel</Button>}
        </div>
      ),
    },
  ]

  const positions = ret.data?.positions ?? []
  return (
    <>
      <PageHeader eyebrow="Money" title="Owed & Retention" description="Who owes what today, and the retention nobody chases. Money that is not late yet is kept apart from money that is." />
      <div className="mb-5"><Tabs label="View" value={tab} onChange={setTab} items={[{ value: 'owed', label: 'Owed to us' }, { value: 'owe', label: 'We owe' }, { value: 'retention', label: 'Retention' }]} /></div>

      {tab === 'owed' && (
        <>
          <StatGrid className="xl:grid-cols-4">
            <Stat label="Owed to us" value={compactINR(rs.owed)} loading={recv.isPending} />
            <Stat label="Past due" value={compactINR(rs.overdue)} tone={rs.overdue ? 'warning' : undefined} loading={recv.isPending} />
            <Stat label="Over 90 days" value={compactINR(rs.over_90)} tone={rs.over_90 ? 'danger' : undefined} loading={recv.isPending} />
            <Stat label="Worst debt" value={`${rs.worst_days ?? 0} days`} loading={recv.isPending} />
          </StatGrid>
          <AgeingStrip buckets={recv.data?.buckets} total={rs.owed ?? 0} />
          <DataTable label="Owed to us" rows={recv.data?.rows ?? []} columns={recvCols} rowKey={(r) => `${r.doc_type ?? 'inv'}-${r.id}`} loading={recv.isPending} empty="Nobody owes anything. Nothing to chase." />
        </>
      )}
      {tab === 'owe' && (
        <>
          <StatGrid className="xl:grid-cols-4">
            <Stat label="We owe" value={compactINR(ps.owed)} loading={pay.isPending} />
            <Stat label="Past due" value={compactINR(ps.overdue)} tone={ps.overdue ? 'danger' : undefined} loading={pay.isPending} />
            <Stat label="Waiting on approval" value={compactINR(ps.awaiting_approval)} loading={pay.isPending} />
            <Stat label="Over 90 days" value={compactINR(ps.over_90)} loading={pay.isPending} />
          </StatGrid>
          <AgeingStrip buckets={pay.data?.buckets} total={ps.owed ?? 0} />
          <DataTable label="We owe" rows={pay.data?.rows ?? []} columns={payCols} rowKey={(r) => `${r.doc_type ?? 'b'}-${r.id}`} loading={pay.isPending} empty="Nothing outstanding." />
        </>
      )}
      {tab === 'retention' && (
        <>
          <StatGrid>
            <Stat label="Client is holding" value={compactINR(t?.client_held)} loading={ret.isPending} />
            <Stat label="On finished jobs" value={compactINR(t?.client_on_finished)} loading={ret.isPending} />
            <Stat label="Released, still to receive" value={compactINR(t?.client_to_receive)} loading={ret.isPending} />
            <Stat label="We hold from contractors" value={compactINR(t?.contractor_held)} loading={ret.isPending} />
            <Stat label="Contractors due back" value={compactINR(t?.contractor_dlp_over)} tone={t?.contractor_dlp_over ? 'warning' : undefined} loading={ret.isPending} />
          </StatGrid>
          <h2 className="mb-3 text-lg font-semibold">Held by clients</h2>
          <DataTable label="Retention held by clients" rows={positions.filter((p) => p.side === 'client')} columns={posCols(false)} rowKey={(p) => `c-${p.order_id}`} loading={ret.isPending} empty="Nothing held back yet. Retention appears once a bill is certified." className="mb-8" />
          <h2 className="mb-3 text-lg font-semibold">Held by us, from contractors</h2>
          <DataTable label="Retention held from contractors" rows={positions.filter((p) => p.side === 'contractor')} columns={posCols(true)} rowKey={(p) => `g-${p.order_id}`} loading={ret.isPending} empty="No contractor has retention with us." className="mb-8" />
          <h2 className="mb-3 text-lg font-semibold">Releases</h2>
          <DataTable label="Retention releases" rows={ret.data?.releases ?? []} columns={relCols} rowKey={(r) => r.id} loading={ret.isPending} empty="No retention released yet." />
        </>
      )}

      <ReleaseModal position={releasing} stages={ret.data?.stages ?? []} onClose={() => setReleasing(null)} />
      <EInvoiceModal docType="retention_release" docId={einvoice} onClose={() => setEinvoice(null)} />
      {settle && <PayModal docType={settle.type} docId={settle.id} title={settle.title} verb={settle.verb} open onOpenChange={(o) => !o && setSettle(null)} invalidate={[owedKeys.all, ['dashboard']]} />}
      <ConfirmDialog open={!!cancelling} onOpenChange={(o) => !o && setCancelling(null)} title={`Cancel ${cancelling?.number ?? 'this release'}?`} description="The retention goes back to being held." confirmLabel="Cancel the release" tone="danger" reason={{ label: 'Why is this release being cancelled?', required: true }} loading={cancel.isPending} onConfirm={(reason) => { if (cancelling) cancel.mutate({ r: cancelling, reason }) }} />
    </>
  )
}
