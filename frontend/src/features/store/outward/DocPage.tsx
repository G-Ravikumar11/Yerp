import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { ArrowLeft, CornerDownLeft, DoorOpen, Pencil, Printer, Trash2 } from 'lucide-react'
import { Badge, Button, ConfirmDialog, Skeleton } from '@/components/ui'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { useSession } from '@/lib/session'
import { useAction } from '@/lib/mutate'
import { storeDelete, storePerm, storePost } from '@/api/store'
import { ATTACH_TYPE, AttachButton, DocActionsBar, DocStatusBadge, type DocAction } from '../shared'
import { dmy, headLabel, kindOf, num, outwardKeys, useDoc, type Doc, type OutwardKind } from './api'

type Line = NonNullable<Doc['lines']>[number]

/** One outward document: its header, lines and history, the actions its status allows, and its printed form. */
export default function DocPage() {
  const { kind: key, id } = useParams()
  const kind = kindOf(key)
  const nav = useNavigate()
  const { can } = useSession()
  const q = useDoc((kind?.key ?? 'issue') as OutwardKind, Number(id))
  const [discarding, setDiscarding] = useState(false)
  const doc = q.data
  const run = useAction(({ action, reason }: { action: DocAction; reason?: string }) => storePost<Doc>('outward', `/${kind?.key}/${id}/${action}`, { reason: reason ?? '' }), {
    invalidate: [[...outwardKeys.all], ['store', 'lookup']],
    success: (d, v) => ({ submit: 'Submitted', approve: 'Approved', post: 'Posted to stock', cancel: 'Cancelled' })[v.action] + (d.number ? ` - ${d.number}` : ''),
  })
  const discard = useAction(() => storeDelete<{ message: string }>('outward', `/${kind?.key}/${id}`), { invalidate: [[...outwardKeys.all]], onSuccess: () => nav(`/store/hub/outward/${kind?.key}`) })
  if (!kind) return <p className="text-sm text-muted-foreground">There is no such document type.</p>
  const back = <Link to={`/store/hub/outward/${kind.key}`} className="mb-3 inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"><ArrowLeft className="size-4" /> {kind.plural}</Link>
  if (q.isPending) return <div>{back}<Skeleton className="h-40 w-full" /></div>
  if (q.isError || !doc) return <div>{back}<p role="alert" className="text-sm text-danger">Could not load this {kind.label.toLowerCase()}.</p></div>

  const isIssue = kind.key === 'issue'
  const columns: TableColumn<Line>[] = [
    { id: 'item', header: 'Item', cell: (l) => <div><div className="font-medium">{l.item_name}</div><div className="font-mono text-xs text-muted-foreground">{l.item_code}</div>{l.fefo_skipped && <div className="mt-0.5 text-xs text-warning">Earlier-expiry lot {l.fefo_skipped} passed over by {l.fefo_by}{l.fefo_at ? ` on ${l.fefo_at}` : ''}: {l.fefo_reason}</div>}</div> },
    ...(isIssue
      ? ([
          { id: 'qty', header: 'Issued', align: 'right', width: '9rem', cell: (l) => <div>{num(l.entry_qty)} {l.entry_uom}{l.entry_uom !== l.base_uom && <div className="text-xs text-muted-foreground">= {num(l.qty)} {l.base_uom}</div>}</div> },
          { id: 'cost', header: 'Charged to', cell: (l) => l.boq_item || headLabel(l.cost_head) || '-' },
          ...(doc.issue_type === 'SUBCONTRACTOR' ? ([{ id: 'rec', header: 'Recovery', align: 'right', width: '13rem', cell: (l) => (l.chargeable ? `${l.resolved_rate ? num(l.resolved_rate) : '-'}/${l.base_uom} ${l.recovery_basis === 'CONTRACT_RATE' ? 'contract' : 'avg cost'}${Number(l.handling_pct) ? ` + ${num(l.handling_pct)}%` : ''}` : 'Free of cost') }] as TableColumn<Line>[]) : []),
          { id: 'due', header: 'Back by', width: '8rem', hideBelow: 'md', cell: (l) => (l.returnable ? (l.expected_return_date ? dmy(l.expected_return_date) : <Badge>Returnable</Badge>) : '-') },
          ...(doc.status === 'POSTED' ? ([{ id: 'out', header: 'Still out', align: 'right', width: '8rem', cell: (l) => (l.outstanding === null ? '' : `${num(l.outstanding)} ${l.base_uom}`) }] as TableColumn<Line>[]) : []),
        ] as TableColumn<Line>[])
      : ([
          { id: 'back', header: 'Came back', align: 'right', width: '9rem', cell: (l) => `${num(l.qty_returned)} ${l.base_uom}` },
          { id: 'lost', header: 'Lost / damaged', align: 'right', width: '9rem', cell: (l) => (Number(l.qty_lost) ? <span className="text-danger">{num(l.qty_lost)} {l.base_uom}</span> : '-') },
          { id: 'cond', header: 'Condition', width: '11rem', cell: (l) => (l.condition === 'DAMAGED' ? <Badge tone="warning">Damaged - bin {l.bin || '?'}</Badge> : 'Good') },
          { id: 'why', header: 'Reason', cell: (l) => l.reason || '-' },
        ] as TableColumn<Line>[])),
  ]
  const facts: [string, string][] = [
    ['Store', `${doc.store_code} - ${doc.store_name}`],
    ['Date', dmy(doc.date)],
    ...(isIssue
      ? ([['Type', doc.issue_type === 'SUBCONTRACTOR' ? 'Issued to a subcontractor' : 'Site use'], ['Project', doc.project || '-'], ['Work order', doc.work_order || '-'], ['Indent', doc.indent_number || (doc.direct ? 'Direct issue' : '-')],
          ...(doc.issue_type === 'SUBCONTRACTOR' ? ([['Subcontractor', doc.holder_name || '-'], ['Subcontract work order', doc.subcontract_order || '-']] as [string, string][]) : []),
          ['Received by', doc.received_by_name ? `${doc.received_by_name} (${(doc.received_by_type ?? '').toLowerCase()})` : doc.holder_name || '-'], ['Purpose', doc.purpose || '-']] as [string, string][])
      : ([['Against issue', doc.issue_number || '-'], ['Held by', doc.holder_name || '-']] as [string, string][])),
    ['Remarks', doc.remarks || '-'],
    ['Made by', `${doc.created_by || '-'}${doc.created_at ? ' on ' + dmy(doc.created_at) : ''}`],
  ]
  return (
    <div>
      {back}
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="font-mono text-lg font-semibold">{doc.number}</h2>
          <div className="mt-1 flex items-center gap-2 text-sm text-muted-foreground"><DocStatusBadge status={doc.status} /> {kind.label}{doc.direct && <Badge tone="warning">Direct issue</Badge>}</div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <AttachButton type={(ATTACH_TYPE.outward as Record<string, string>)[kind.key]} id={doc.id} title={doc.number} />
          <Button variant="outline" asChild><a href={`/api/store/outward/${kind.key}/${doc.id}/print`} target="_blank" rel="noreferrer"><Printer /> Print</a></Button>
          {isIssue && doc.status === 'POSTED' && can(storePerm('outward', 'create')) && <Button variant="outline" onClick={() => nav(`/store/hub/outward/returns/new?issue=${doc.id}`)}><CornerDownLeft /> Return material</Button>}
          {isIssue && doc.status === 'POSTED' && can(storePerm('outward', 'create')) && <Button variant="outline" onClick={() => nav(`/store/hub/outward/gate-pass/new?issue=${doc.id}`)}><DoorOpen /> Gate pass</Button>}
          {doc.status === 'DRAFT' && can(storePerm('outward', 'create')) && (
            <>
              <Button variant="outline" onClick={() => nav(`/store/hub/outward/${kind.key}/${doc.id}/edit`)}><Pencil /> Edit</Button>
              <Button variant="ghost" onClick={() => setDiscarding(true)}><Trash2 /> Delete draft</Button>
            </>
          )}
          <DocActionsBar
            status={doc.status}
            busy={run.isPending ? (run.variables?.action ?? null) : null}
            can={{ submit: can(storePerm('outward', 'create')), approve: can(storePerm('outward', 'approve')), post: can(storePerm('outward', 'post')), cancel: can(storePerm('outward', 'cancel')) }}
            onAction={(action, reason) => run.mutateAsync({ action, reason }).then(() => undefined, () => { throw new Error('rejected') })}
          />
        </div>
      </div>
      {(doc.warnings ?? []).map((w) => <p key={w} role="status" className="mb-3 rounded-lg bg-warning-soft px-3 py-2 text-sm text-warning">Over the norm: {w}</p>)}
      {(doc.gate_passes ?? []).length > 0 && <p className="mb-3 text-sm text-muted-foreground">Gate passes: {(doc.gate_passes ?? []).map((g) => <Link key={g.id} className="mr-3 font-mono text-primary hover:underline" to={`/store/hub/outward/gate-pass/${g.id}`}>{g.number} ({g.status.toLowerCase()})</Link>)}</p>}
      {doc.status === 'CANCELLED' && <p role="status" className="mb-4 rounded-lg bg-danger-soft px-3 py-2 text-sm text-danger">Cancelled{doc.cancel_reason ? `: ${doc.cancel_reason}` : ''}.</p>}
      <dl className="mb-5 grid gap-x-6 gap-y-2 rounded-xl border border-border bg-card p-4 text-sm sm:grid-cols-2 lg:grid-cols-3">
        {facts.map(([k, v]) => <div key={k}><dt className="text-xs uppercase tracking-wide text-muted-foreground">{k}</dt><dd className="font-medium">{v}</dd></div>)}
      </dl>
      <DataTable label="Lines" rows={doc.lines ?? []} columns={columns} rowKey={(l) => l.id} />
      <section aria-labelledby="doc-history" className="mt-6">
        <h3 id="doc-history" className="mb-2 border-b pb-1 text-sm font-semibold">History</h3>
        <ul className="space-y-1 text-sm">
          {(doc.history ?? []).map((h, i) => (
            <li key={i}><span className="font-medium capitalize">{h.action}</span>{h.to && h.from !== h.to ? ` (${h.from ? h.from.toLowerCase() + ' to ' : ''}${h.to.toLowerCase()})` : ''} by {h.by || 'the account holder'} on {dmy(h.at)}{h.note ? ` - ${h.note}` : ''}</li>
          ))}
        </ul>
      </section>
      <ConfirmDialog open={discarding} onOpenChange={setDiscarding} title="Delete this draft?" description="Nothing has moved in stock. The number it used is not given back." confirmLabel="Delete" tone="danger" onConfirm={() => { discard.mutate(); setDiscarding(false) }} />
    </div>
  )
}
