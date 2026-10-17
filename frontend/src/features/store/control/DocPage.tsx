import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { ArrowLeft, PackageCheck, Pencil, Play, Printer, Trash2 } from 'lucide-react'
import { Badge, Button, ConfirmDialog, Skeleton } from '@/components/ui'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { useSession } from '@/lib/session'
import { useAction } from '@/lib/mutate'
import { storeDelete, storePerm, storePost } from '@/api/store'
import { DocActionsBar, DocStatusBadge, type DocAction } from '../shared'
import CountSheet from './CountSheet'
import { controlKeys, dmy, headLabel, kindOf, money, num, useDoc, type ControlKind, type Doc, type DocLine } from './api'

/** One control document: its header, lines and history, the actions its status allows, and its printed form. A count also holds its sheet. */
export default function DocPage() {
  const { kind: key, id } = useParams()
  const kind = kindOf(key)
  const nav = useNavigate()
  const { can } = useSession()
  const q = useDoc((kind?.key ?? 'transfer') as ControlKind, Number(id))
  const [discarding, setDiscarding] = useState(false)
  const doc = q.data
  const refresh = [[...controlKeys.all], ['store', 'lookup']]
  const run = useAction(({ action, reason }: { action: DocAction; reason?: string }) => storePost<Doc>('control', `/${kind?.key}/${id}/${action}`, { reason: reason ?? '' }), {
    invalidate: refresh,
    success: (d, v) => ({ submit: 'Submitted', approve: 'Approved', post: kind?.key === 'transfer' ? 'Dispatched - in transit' : 'Posted to stock', cancel: 'Cancelled' })[v.action] + (d.number ? ` - ${d.number}` : ''),
  })
  const receive = useAction(() => storePost<Doc>('control', `/transfer/${id}/receive`), { invalidate: refresh, success: 'Received into the store' })
  const start = useAction(() => storePost<Doc>('control', `/count/${id}/start`), { invalidate: refresh, success: 'Count started - the store is frozen' })
  const discard = useAction(() => storeDelete<{ message: string }>('control', `/${kind?.key}/${id}`), { invalidate: [[...controlKeys.all]], onSuccess: () => nav(`/store/hub/control/${kind?.key}`) })
  if (!kind) return <p className="text-sm text-muted-foreground">There is no such document type.</p>
  const back = <Link to={`/store/hub/control/${kind.key}`} className="mb-3 inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"><ArrowLeft className="size-4" /> {kind.plural}</Link>
  if (q.isPending) return <div>{back}<Skeleton className="h-40 w-full" /></div>
  if (q.isError || !doc) return <div>{back}<p role="alert" className="text-sm text-danger">Could not load this {kind.label.toLowerCase()}.</p></div>

  const columns: TableColumn<DocLine>[] =
    kind.key === 'transfer'
      ? [
          { id: 'item', header: 'Item', cell: (l) => <div><div className="font-medium">{l.item_name}</div><div className="font-mono text-xs text-muted-foreground">{l.item_code}</div></div> },
          { id: 'qty', header: 'Quantity', align: 'right', width: '9rem', cell: (l) => <div>{num(l.entry_qty)} {l.entry_uom}{l.entry_uom !== l.base_uom && <div className="text-xs text-muted-foreground">= {num(l.qty)} {l.base_uom}</div>}</div> },
          { id: 'rate', header: 'Rate', align: 'right', width: '7rem', hideBelow: 'sm', cell: (l) => (Number(l.rate) ? money(l.rate) : '-') },
          { id: 'val', header: 'Value', align: 'right', width: '8rem', cell: (l) => (Number(l.value) ? money(l.value) : '-') },
        ]
      : kind.key === 'scrap'
        ? [
            { id: 'item', header: 'Item', cell: (l) => <div><div className="font-medium">{l.item_name}</div><div className="font-mono text-xs text-muted-foreground">{l.item_code}</div></div> },
            { id: 'qty', header: 'Quantity', align: 'right', width: '9rem', cell: (l) => `${num(l.qty)} ${l.base_uom}` },
            { id: 'disp', header: 'Disposal', width: '8rem', cell: (l) => <Badge tone={l.disposal === 'SCRAP' ? 'info' : 'warning'}>{l.disposal === 'SCRAP' ? 'Scrap' : 'Wastage'}</Badge> },
            { id: 'why', header: 'Reason', hideBelow: 'sm', cell: (l) => <span>{l.reason}{l.cost_head && <span className="text-muted-foreground"> - {headLabel(l.cost_head)}</span>}{l.writeoff_request_id && <Badge className="ml-2">Write-off #{l.writeoff_request_id}</Badge>}</span> },
            { id: 'real', header: 'Realised', align: 'right', width: '8rem', cell: (l) => (l.disposal === 'SCRAP' ? money(l.realised_value) : '-') },
          ]
        : []
  const facts: [string, string][] =
    kind.key === 'transfer'
      ? [['From', `${doc.store_code} - ${doc.store_name}`], ['To', `${doc.to_store_code} - ${doc.to_store_name}`], ['Date', dmy(doc.date)], ['Vehicle', doc.vehicle_no || '-'], ['Between projects', doc.inter_project ? 'Yes' : 'No'],
         ['Receipt', doc.receipt_status === 'RECEIVED' ? `Received by ${doc.received_by || '-'} on ${dmy(doc.received_at ?? '')}` : doc.receipt_status === 'IN_TRANSIT' ? 'In transit' : 'Not yet dispatched'], ['Value', money(doc.value)], ['Remarks', doc.remarks || '-']]
      : kind.key === 'count'
        ? [['Store', `${doc.store_code} - ${doc.store_name}`], ['Date', dmy(doc.date)], ['Type', doc.count_type === 'PARTIAL' ? 'Partial count' : 'Full count'], ['Started', doc.started ? `${dmy(doc.started_at ?? '')} by ${doc.started_by}` : 'Not started'],
           ['Counted', doc.started ? `${doc.counted} of ${doc.line_count}` : '-'], ...(doc.revealed && doc.variance_value != null ? ([['Net difference', money(doc.variance_value)]] as [string, string][]) : []), ['Remarks', doc.remarks || '-']]
        : [['Store', `${doc.store_code} - ${doc.store_name}`], ['Date', dmy(doc.date)], ['Project', doc.project || '-'], ['Buyer', doc.buyer || '-'], ['Gate pass / voucher', doc.reference || '-'], ['Realised', money(doc.realised)], ['Remarks', doc.remarks || '-']]
  const canCreate = can(storePerm('control', 'create'))
  const counting = kind.key === 'count' && doc.status === 'DRAFT' && !!doc.started
  return (
    <div>
      {back}
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="font-mono text-lg font-semibold">{doc.number}</h2>
          <div className="mt-1 flex items-center gap-2 text-sm text-muted-foreground"><DocStatusBadge status={doc.status} /> {kind.label}{doc.frozen && <Badge tone="warning" dot>Store frozen</Badge>}{doc.receipt_status === 'IN_TRANSIT' && <Badge tone="warning" dot>In transit</Badge>}</div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="outline" asChild><a href={`/api/store/control/${kind.key}/${doc.id}/print`} target="_blank" rel="noreferrer"><Printer /> {kind.key === 'count' ? 'Print count sheet' : 'Print'}</a></Button>
          {kind.key === 'count' && doc.status === 'DRAFT' && !doc.started && canCreate && <Button loading={start.isPending} onClick={() => start.mutate()}><Play /> Start count (freezes the store)</Button>}
          {kind.key === 'transfer' && doc.status === 'POSTED' && doc.receipt_status === 'IN_TRANSIT' && can(storePerm('control', 'post')) && <Button loading={receive.isPending} onClick={() => receive.mutate()}><PackageCheck /> Receive</Button>}
          {doc.status === 'DRAFT' && canCreate && kind.key !== 'count' && (
            <>
              <Button variant="outline" onClick={() => nav(`/store/hub/control/${kind.key}/${doc.id}/edit`)}><Pencil /> Edit</Button>
              <Button variant="ghost" onClick={() => setDiscarding(true)}><Trash2 /> Delete draft</Button>
            </>
          )}
          {doc.status === 'DRAFT' && canCreate && kind.key === 'count' && !doc.started && <Button variant="ghost" onClick={() => setDiscarding(true)}><Trash2 /> Delete draft</Button>}
          <DocActionsBar
            status={doc.status}
            busy={run.isPending ? (run.variables?.action ?? null) : null}
            disabled={kind.key === 'count' && doc.status === 'DRAFT' && !doc.started}
            can={{ submit: canCreate, approve: can(storePerm('control', 'approve')), post: can(storePerm('control', 'post')), cancel: can(storePerm('control', 'cancel')) }}
            onAction={(action, reason) => run.mutateAsync({ action, reason }).then(() => undefined, () => { throw new Error('rejected') })}
          />
        </div>
      </div>
      {doc.status === 'CANCELLED' && <p role="status" className="mb-4 rounded-lg bg-danger-soft px-3 py-2 text-sm text-danger">Cancelled{doc.cancel_reason ? `: ${doc.cancel_reason}` : ''}.</p>}
      {doc.frozen && <p role="status" className="mb-4 rounded-lg bg-warning-soft px-3 py-2 text-sm text-warning">{doc.store_code} is frozen: nothing can move in or out until this count is posted or cancelled.</p>}
      <dl className="mb-5 grid gap-x-6 gap-y-2 rounded-xl border border-border bg-card p-4 text-sm sm:grid-cols-2 lg:grid-cols-3">
        {facts.map(([k, v]) => <div key={k}><dt className="text-xs uppercase tracking-wide text-muted-foreground">{k}</dt><dd className="font-medium">{v}</dd></div>)}
      </dl>
      {kind.key === 'count' ? <CountSheet doc={doc} editable={counting && canCreate} /> : <DataTable label="Lines" rows={doc.lines ?? []} columns={columns} rowKey={(l) => l.id} />}
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
