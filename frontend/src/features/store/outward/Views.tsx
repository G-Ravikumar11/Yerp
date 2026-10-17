import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Printer } from 'lucide-react'
import { Link, useParams } from 'react-router-dom'
import { Badge, Button, Card, SkeletonRows } from '@/components/ui'
import { apiUrl } from '@/lib/api'
import { useSession } from '@/lib/session'
import { toast } from '@/stores/toast'
import { storeGet, storePerm, storePost, type DocStatus } from '@/api/store'
import { DocActionsBar, DocStatusBadge } from '../shared'
import type { DocAction } from '../shared/DocActionsBar'
import { errText, money, num, type Issue, type IssueReturn, type LogRow, type Requisition } from './types'

const when = (s: string | null) => (s ? new Date(s).toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' }) : '')

function History({ log }: { log: LogRow[] }) {
  return (
    <Card className="p-5">
      <h3 className="mb-2 text-sm font-semibold">History</h3>
      <ul className="space-y-1 text-sm">{log.map((l, i) => <li key={i}><Badge>{l.to}</Badge> <span className="text-muted-foreground">{l.user} · {when(l.at)}{l.note && !l.note.startsWith('Created') ? ` · ${l.note}` : ''}</span></li>)}</ul>
    </Card>
  )
}

function useDoc<T extends { status: DocStatus }>(kind: 'requisitions' | 'issues' | 'returns') {
  const { id } = useParams()
  const qc = useQueryClient()
  const { can } = useSession()
  const q = useQuery({ queryKey: ['store', 'outward', kind, id], queryFn: () => storeGet<T>('outward', `/${kind}/${id}`) })
  const [busy, setBusy] = useState<DocAction | null>(null)
  const act = async (a: DocAction, reason?: string) => {
    setBusy(a)
    try {
      await storePost('outward', `/${kind}/${id}/${a}`, { reason: reason ?? '' })
      toast.success(a === 'post' ? 'Posted to stock' : a === 'cancel' ? 'Cancelled' : a === 'submit' ? 'Submitted' : 'Approved')
      await qc.invalidateQueries({ queryKey: ['store'] })
    } catch (e) { toast.error(errText(e)); throw e } finally { setBusy(null) }
  }
  const rights = { submit: can(storePerm('outward', 'create')), approve: can(storePerm('outward', 'approve')), post: kind !== 'requisitions' && can(storePerm('outward', 'post')), cancel: can(storePerm('outward', 'cancel')) }
  return { q, busy, act, rights, can }
}

const Print = ({ path }: { path: string }) => (
  <a href={apiUrl(`/api/store/outward${path}/pdf`)} target="_blank" rel="noreferrer"><Button variant="outline" size="sm"><Printer /> Print</Button></a>
)
const Where = ({ d }: { d: { project_name: string; work_order_number: string; cost_head: string | null } }) => (
  <p className="text-sm text-muted-foreground">{[d.project_name, d.work_order_number && `WO ${d.work_order_number}`, d.cost_head && d.cost_head.replace(/_/g, ' ').toLowerCase()].filter(Boolean).join(' · ') || 'No costing'}</p>
)
const th = 'p-3 text-xs uppercase text-muted-foreground'

export function RequisitionView() {
  const { q, busy, act, rights, can } = useDoc<Requisition>('requisitions')
  const r = q.data
  if (q.isLoading || !r) return <SkeletonRows rows={6} cols={4} />
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div><h2 className="text-xl font-semibold">{r.number}</h2><p className="text-sm text-muted-foreground">{r.store_code} · {r.req_date}{r.required_by && ` · needed by ${r.required_by}`} · {r.purpose}</p><Where d={r} /></div>
        <div className="flex items-center gap-2"><DocStatusBadge status={r.status} />{r.status === 'DRAFT' && rights.submit && <Link to={`/store/hub/outward/requisitions/${r.id}/edit`}><Button variant="outline" size="sm">Edit</Button></Link>}<Print path={`/requisitions/${r.id}`} /></div>
      </div>
      <DocActionsBar status={r.status} can={rights} busy={busy} onAction={act} />
      {r.status === 'APPROVED' && can(storePerm('outward', 'create')) && <Link to={`/store/hub/outward/issues/new?req=${r.id}`}><Button variant="soft" size="sm">Issue against this requisition</Button></Link>}
      {r.status === 'CANCELLED' && <p className="text-sm text-danger">Cancelled: {r.cancel_reason}</p>}
      <Card className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead><tr className="border-b border-border text-left"><th className={th}>Item</th><th className={`${th} text-right`}>Asked</th><th className={`${th} text-right`}>Issued</th><th className={`${th} text-right`}>Still to issue</th></tr></thead>
          <tbody>{(r.lines ?? []).map((l) => <tr key={l.id} className="border-b border-border last:border-0"><td className="p-3"><span className="font-mono text-xs text-muted-foreground">{l.item_code}</span> {l.item_name}</td><td className="p-3 text-right">{num(l.entered_qty)} {l.uom}<div className="text-xs text-muted-foreground">{num(l.qty)} {l.base_uom}</div></td><td className="p-3 text-right">{num(l.issued_qty)}</td><td className="p-3 text-right">{num(String(Math.max(Number(l.qty) - Number(l.issued_qty), 0)))}</td></tr>)}</tbody>
        </table>
      </Card>
      <History log={r.log ?? []} />
    </div>
  )
}

export function IssueView() {
  const { q, busy, act, rights, can } = useDoc<Issue>('issues')
  const d = q.data
  if (q.isLoading || !d) return <SkeletonRows rows={6} cols={4} />
  const open = (d.lines ?? []).some((l) => Number(l.outstanding_qty) > 0)
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold">{d.number}</h2>
          <p className="text-sm text-muted-foreground">{d.store_code} · {d.issue_date} · {d.issue_type === 'SUBCONTRACTOR' ? `to ${d.subcontractor_name}` : 'site use'} · {d.direct ? 'direct issue' : `against ${d.requisition_number}`}</p>
          <Where d={d} />
          {d.holder_name && <p className="text-sm text-muted-foreground">Returnables held by {d.holder_name}{d.expected_return_date && `, due ${d.expected_return_date}`}</p>}
        </div>
        <div className="flex items-center gap-2"><DocStatusBadge status={d.status} />{d.status === 'DRAFT' && rights.submit && <Link to={`/store/hub/outward/issues/${d.id}/edit`}><Button variant="outline" size="sm">Edit</Button></Link>}<Print path={`/issues/${d.id}`} /></div>
      </div>
      <DocActionsBar status={d.status} can={rights} busy={busy} onAction={act} />
      {d.status === 'CANCELLED' && <p className="text-sm text-danger">Cancelled: {d.cancel_reason}</p>}
      <Card className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead><tr className="border-b border-border text-left"><th className={th}>Item</th><th className={`${th} text-right`}>Issued</th><th className={`${th} text-right`}>Rate</th><th className={`${th} text-right`}>Value</th><th className={`${th} text-right`}>Back</th><th className={`${th} text-right`}>Lost</th><th className={`${th} text-right`}>Still out</th></tr></thead>
          <tbody>
            {(d.lines ?? []).map((l) => (
              <tr key={l.id} className="border-b border-border last:border-0">
                <td className="p-3"><span className="font-mono text-xs text-muted-foreground">{l.item_code}</span> {l.item_name} {l.returnable && <Badge tone="info">Returnable</Badge>} {l.chargeable && <Badge tone="warning">Recover ₹{money(l.recovery_rate)}</Badge>}</td>
                <td className="p-3 text-right">{num(l.entered_qty)} {l.uom}<div className="text-xs text-muted-foreground">{num(l.qty)} {l.base_uom}</div></td>
                <td className="p-3 text-right">{d.status === 'POSTED' ? money(l.rate) : '—'}</td><td className="p-3 text-right">{d.status === 'POSTED' ? money(l.value) : '—'}</td>
                <td className="p-3 text-right">{num(l.returned_qty)}</td><td className="p-3 text-right">{num(l.lost_qty)}</td><td className="p-3 text-right">{d.status === 'POSTED' ? num(l.outstanding_qty) : '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {d.status === 'POSTED' && <div className="flex justify-between border-t border-border p-3 text-sm"><span className="text-muted-foreground">Total value</span><strong>₹{money(d.total_value)}</strong></div>}
      </Card>
      {d.status === 'POSTED' && open && can(storePerm('outward', 'create')) && <Link to={`/store/hub/outward/returns/new?issue=${d.id}`}><Button variant="soft" size="sm">Record a return</Button></Link>}
      <History log={d.log ?? []} />
    </div>
  )
}

export function ReturnView() {
  const { q, busy, act, rights } = useDoc<IssueReturn>('returns')
  const r = q.data
  if (q.isLoading || !r) return <SkeletonRows rows={6} cols={4} />
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div><h2 className="text-xl font-semibold">{r.number}</h2><p className="text-sm text-muted-foreground">{r.store_code} · {r.return_date} · against <Link className="text-primary hover:underline" to={`/store/hub/outward/issues/${r.issue_id}`}>{r.issue_number}</Link> · {r.holder_name}</p></div>
        <div className="flex items-center gap-2"><DocStatusBadge status={r.status} /><Print path={`/returns/${r.id}`} /></div>
      </div>
      <DocActionsBar status={r.status} can={rights} busy={busy} onAction={act} />
      {r.status === 'CANCELLED' && <p className="text-sm text-danger">Cancelled: {r.cancel_reason}</p>}
      <Card className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead><tr className="border-b border-border text-left"><th className={th}>Item</th><th className={`${th} text-right`}>Returned</th><th className={`${th} text-right`}>Lost</th><th className={`${th} text-right`}>Value</th><th className={th}>Remarks</th></tr></thead>
          <tbody>{(r.lines ?? []).map((l) => <tr key={l.id} className="border-b border-border last:border-0"><td className="p-3"><span className="font-mono text-xs text-muted-foreground">{l.item_code}</span> {l.item_name}</td><td className="p-3 text-right">{num(l.qty)} {l.base_uom}</td><td className="p-3 text-right">{num(l.lost_qty)}</td><td className="p-3 text-right">{r.status === 'POSTED' ? money(l.value) : '—'}</td><td className="p-3">{l.remarks}</td></tr>)}</tbody>
        </table>
      </Card>
      <History log={r.log ?? []} />
    </div>
  )
}
