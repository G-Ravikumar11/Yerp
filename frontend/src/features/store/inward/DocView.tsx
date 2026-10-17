import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Printer } from 'lucide-react'
import { Link, useParams } from 'react-router-dom'
import { Badge, Button, Card, Input, SkeletonRows } from '@/components/ui'
import { apiUrl } from '@/lib/api'
import { useSession } from '@/lib/session'
import { toast } from '@/stores/toast'
import { storePerm, storeGet, storePost } from '@/api/store'
import { DocActionsBar, DocStatusBadge } from '../shared'
import type { DocAction } from '../shared/DocActionsBar'
import { errText, money, num, type Grn, type LogRow, type PurchaseReturn } from './types'

const when = (s: string | null) => (s ? new Date(s).toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' }) : '')

function History({ log }: { log: LogRow[] }) {
  return (
    <Card className="p-5">
      <h3 className="mb-2 text-sm font-semibold">History</h3>
      <ul className="space-y-1 text-sm">{log.map((l, i) => <li key={i}><Badge>{l.to}</Badge> <span className="text-muted-foreground">{l.user} · {when(l.at)}{l.note && l.note !== 'Created' ? ` · ${l.note}` : ''}</span></li>)}</ul>
    </Card>
  )
}

function useDoc<T extends { status: Grn['status'] }>(kind: 'grn' | 'returns') {
  const { id } = useParams()
  const qc = useQueryClient()
  const { can } = useSession()
  const q = useQuery({ queryKey: ['store', 'inward', kind, id], queryFn: () => storeGet<T>('inward', `/${kind}/${id}`) })
  const [busy, setBusy] = useState<DocAction | null>(null)
  const act = async (a: DocAction, reason?: string) => {
    setBusy(a)
    try {
      await storePost('inward', `/${kind}/${id}/${a}`, { reason: reason ?? '' })
      toast.success(a === 'post' ? 'Posted to stock' : a === 'cancel' ? 'Cancelled' : a === 'submit' ? 'Submitted' : 'Approved')
      await qc.invalidateQueries({ queryKey: ['store'] })
    } catch (e) { toast.error(errText(e)); throw e } finally { setBusy(null) }
  }
  const rights = { submit: can(storePerm('inward', 'create')), approve: can(storePerm('inward', 'approve')), post: can(storePerm('inward', 'post')), cancel: can(storePerm('inward', 'cancel')) }
  return { id, q, busy, act, rights, can }
}

const Print = ({ path }: { path: string }) => (
  <a href={apiUrl(`/api/store/inward${path}/pdf`)} target="_blank" rel="noreferrer"><Button variant="outline" size="sm"><Printer /> Print</Button></a>
)

export function GrnView() {
  const { id, q, busy, act, rights, can } = useDoc<Grn>('grn')
  const qc = useQueryClient()
  const g = q.data
  const [qcVals, setQcVals] = useState<Record<number, { ok: string; bad: string; note: string }>>({})
  useEffect(() => { if (g?.lines) setQcVals(Object.fromEntries(g.lines.map((l) => [l.id, { ok: l.qc_done ? l.accepted_qty : l.received_qty, bad: l.qc_done ? l.rejected_qty : '0', note: l.qc_remarks }]))) }, [g])
  const saveQc = useMutation({
    mutationFn: () => storePost('inward', `/grn/${id}/qc`, { lines: Object.entries(qcVals).map(([line_id, v]) => ({ line_id: Number(line_id), accepted_qty: v.ok, rejected_qty: v.bad || '0', remarks: v.note })) }),
    onSuccess: () => { toast.success('Quality check saved'); qc.invalidateQueries({ queryKey: ['store'] }) },
    onError: (e) => toast.error(errText(e)),
  })
  if (q.isLoading || !g) return <SkeletonRows rows={6} cols={4} />
  const checking = (g.status === 'SUBMITTED' || g.status === 'APPROVED') && rights.approve
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div><h2 className="text-xl font-semibold">{g.number}</h2><p className="text-sm text-muted-foreground">{g.store_code} · {g.grn_date}{g.po_number && ` · PO ${g.po_number}`} · {g.supplier_name}</p></div>
        <div className="flex flex-wrap items-center gap-2">
          <DocStatusBadge status={g.status} />
          {g.status === 'DRAFT' && rights.submit && <Link to={`/store/hub/inward/grn/${g.id}/edit`}><Button variant="outline" size="sm">Edit</Button></Link>}
          <Print path={`/grn/${g.id}`} />
        </div>
      </div>
      <DocActionsBar status={g.status} can={rights} busy={busy} onAction={act} />
      {g.status === 'CANCELLED' && <p className="text-sm text-danger">Cancelled: {g.cancel_reason}</p>}
      <Card className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead><tr className="border-b border-border text-left text-xs uppercase text-muted-foreground"><th className="p-3">Item</th><th className="p-3 text-right">Received</th><th className="p-3 text-right">Accepted</th><th className="p-3 text-right">Rejected</th><th className="p-3 text-right">Rate / {'base'}</th><th className="p-3">Quality</th></tr></thead>
          <tbody>
            {(g.lines ?? []).map((l) => {
              const v = qcVals[l.id]
              return (
                <tr key={l.id} className="border-b border-border last:border-0 align-top">
                  <td className="p-3"><span className="font-mono text-xs text-muted-foreground">{l.item_code}</span> {l.item_name}{l.batch_no && <div className="text-xs text-muted-foreground">Batch {l.batch_no}</div>}</td>
                  <td className="p-3 text-right">{num(l.entered_qty)} {l.uom}<div className="text-xs text-muted-foreground">{num(l.received_qty)} {l.base_uom}</div></td>
                  <td className="p-3 text-right">{checking && v ? <Input className="ml-auto w-28 text-right" inputMode="decimal" value={v.ok} onChange={(e) => setQcVals({ ...qcVals, [l.id]: { ...v, ok: e.target.value, bad: String(Math.max(Number(l.received_qty) - Number(e.target.value || 0), 0)) } })} /> : num(l.accepted_qty)}</td>
                  <td className="p-3 text-right">{checking && v ? <Input className="ml-auto w-28 text-right" inputMode="decimal" value={v.bad} onChange={(e) => setQcVals({ ...qcVals, [l.id]: { ...v, bad: e.target.value } })} /> : num(l.rejected_qty)}</td>
                  <td className="p-3 text-right">{money(l.rate)}</td>
                  <td className="p-3">{l.qc_required ? (l.qc_done ? <Badge tone="success">Checked</Badge> : <Badge tone="warning">Pending</Badge>) : <span className="text-muted-foreground">Not needed</span>}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border p-3 text-sm">
          <span className="text-muted-foreground">Value accepted</span><strong>₹{money(g.total_value)}</strong>
        </div>
      </Card>
      {checking && <div><Button variant="soft" loading={saveQc.isPending} onClick={() => saveQc.mutate()}>Save quality check</Button><span className="ml-3 text-xs text-muted-foreground">Accepted + rejected must equal what was received. Only accepted goods are posted to stock.</span></div>}
      {can(storePerm('inward', 'create')) && g.status === 'POSTED' && <Link to={`/store/hub/inward/returns/new?grn=${g.id}`}><Button variant="outline" size="sm">Return goods to supplier</Button></Link>}
      <History log={g.log ?? []} />
    </div>
  )
}

export function ReturnView() {
  const { q, busy, act, rights } = useDoc<PurchaseReturn>('returns')
  const r = q.data
  if (q.isLoading || !r) return <SkeletonRows rows={6} cols={4} />
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div><h2 className="text-xl font-semibold">{r.number}</h2><p className="text-sm text-muted-foreground">{r.store_code} · {r.return_date}{r.grn_number && ` · against ${r.grn_number}`} · {r.supplier_name}</p></div>
        <div className="flex items-center gap-2"><DocStatusBadge status={r.status} /><Print path={`/returns/${r.id}`} /></div>
      </div>
      <p className="text-sm">Reason: {r.reason}</p>
      <DocActionsBar status={r.status} can={rights} busy={busy} onAction={act} />
      {r.status === 'CANCELLED' && <p className="text-sm text-danger">Cancelled: {r.cancel_reason}</p>}
      <Card className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead><tr className="border-b border-border text-left text-xs uppercase text-muted-foreground"><th className="p-3">Item</th><th className="p-3 text-right">Quantity</th><th className="p-3 text-right">Value</th></tr></thead>
          <tbody>{(r.lines ?? []).map((l) => <tr key={l.id} className="border-b border-border last:border-0"><td className="p-3"><span className="font-mono text-xs text-muted-foreground">{l.item_code}</span> {l.item_name}</td><td className="p-3 text-right">{num(l.qty)} {l.base_uom}</td><td className="p-3 text-right">{r.status === 'POSTED' ? money(l.value) : '—'}</td></tr>)}</tbody>
        </table>
      </Card>
      <History log={r.log ?? []} />
    </div>
  )
}
