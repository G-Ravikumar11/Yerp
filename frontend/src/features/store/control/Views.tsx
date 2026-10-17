import { useEffect, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { Badge, Button, Card, ConfirmDialog, Input, Select } from '@/components/ui'
import { toast } from '@/stores/toast'
import { storePerm, storePost, storePut } from '@/api/store'
import { DocShell, Loading, useControlDoc, useControlMeta } from './DocShell'
import { errText, label, money, num, type Adjustment, type Count, type Scrap, type Transfer } from './types'

const th = 'p-3 text-xs uppercase text-muted-foreground'

export function TransferView() {
  const { id, q, busy, act, rights, can, refresh } = useControlDoc<Transfer>('transfers')
  const meta = useControlMeta()
  const t = q.data
  const [lost, setLost] = useState<Record<number, { qty: string; reason: string }>>({})
  const receive = useMutation({
    mutationFn: () => storePost('control', `/transfers/${id}/receive`, {
      losses: Object.fromEntries(Object.entries(lost).filter(([, v]) => Number(v.qty) > 0).map(([lineId, v]) => [lineId, { qty: v.qty, reason: v.reason }])),
    }),
    onSuccess: () => { toast.success('Received'); refresh() },
    onError: (e) => toast.error(errText(e)),
  })
  const approveLoss = useMutation({
    mutationFn: () => storePost('control', `/transfers/${id}/approve-loss`),
    onSuccess: () => { toast.success('Loss approved and posted as wastage'); refresh() },
    onError: (e) => toast.error(errText(e)),
  })
  useEffect(() => { setLost({}) }, [t?.id])
  if (q.isLoading || !t) return <Loading />
  const receiving = t.transit === 'IN_TRANSIT' && can(storePerm('control', 'post'))
  const lostRows = (t.lines ?? []).filter((l) => Number(l.loss_qty) > 0)
  return (
    <DocShell kind="transfers" id={t.id} number={t.number} status={t.status} cancelReason={t.cancel_reason} log={t.log ?? []} busy={busy} act={act} rights={rights}
      prints={[{ label: 'Challan', form: '' }]}
      sub={<>{t.store_code} → {t.to_store_code} · {t.trf_date}{t.vehicle_no && ` · ${t.vehicle_no}`}{t.challan_no && ` · challan ${t.challan_no}`}{t.driver_name && ` · ${t.driver_name}`}{' '}
        {t.inter_project && <Badge tone="warning">Inter-project</Badge>} {t.transit === 'IN_TRANSIT' && <Badge tone="info">In transit</Badge>} {t.transit === 'RECEIVED' && <Badge tone="success">Received {t.received_on}</Badge>} {t.loss_status === 'PENDING' && <Badge tone="danger">Loss awaiting approval</Badge>}</>}
      extra={t.status === 'DRAFT' && rights.submit ? <Link to={`/store/hub/control/transfers/${t.id}/edit`}><Button variant="outline" size="sm">Edit</Button></Link> : undefined}>
      <Card className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead><tr className="border-b border-border text-left"><th className={th}>Item</th><th className={`${th} text-right`}>On hand at sender</th><th className={`${th} text-right`}>Sent</th><th className={`${th} text-right`}>Value</th><th className={`${th} text-right`}>Received</th><th className={th}>Lost in transit</th></tr></thead>
          <tbody>
            {(t.lines ?? []).map((l) => {
              const v = lost[l.id] ?? { qty: '', reason: '' }
              const got = Math.max(Number(l.qty) - Number(v.qty || 0), 0)
              return (
                <tr key={l.id} className="border-b border-border last:border-0 align-top">
                  <td className="p-3"><span className="font-mono text-xs text-muted-foreground">{l.item_code}</span> {l.item_name}</td><td className="p-3 text-right">{num(l.on_hand)}</td><td className="p-3 text-right">{num(l.qty)}</td>
                  <td className="p-3 text-right">{t.status === 'POSTED' ? money(l.value) : '—'}</td>
                  <td className="p-3 text-right">{receiving ? num(String(got)) : l.received_qty === null ? '—' : num(l.received_qty)}</td>
                  <td className="p-3">
                    {receiving
                      ? <div className="flex gap-2"><Input className="w-24 text-right" inputMode="decimal" placeholder="0" value={v.qty} onChange={(e) => setLost({ ...lost, [l.id]: { ...v, qty: e.target.value } })} />
                        <Select className="w-44" value={v.reason} placeholder="Reason" disabled={!Number(v.qty)} options={(meta.data?.wastage_reasons ?? []).map((r) => ({ value: r, label: label(r) }))} onChange={(e) => setLost({ ...lost, [l.id]: { ...v, reason: e.target.value } })} /></div>
                      : Number(l.loss_qty) > 0 ? <span>{num(l.loss_qty)} · {label(l.loss_reason)}</span> : '—'}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </Card>
      {receiving && <div><Button loading={receive.isPending} disabled={Object.values(lost).some((v) => Number(v.qty) > 0 && !v.reason)} onClick={() => receive.mutate()}>Confirm receipt</Button><span className="ml-3 text-xs text-muted-foreground">Type a quantity under Lost in transit for anything that did not arrive, with the reason. Received plus lost always equals what was sent.</span></div>}
      {t.loss_status === 'PENDING' && (
        <Card className="space-y-2 border-warning/40 p-4 text-sm">
          <p>Lost in transit: {lostRows.map((l) => `${num(l.loss_qty)} × ${l.item_name} (${label(l.loss_reason)})`).join('; ')} — worth ₹{money(t.loss_value)}. It stays on the in-transit register until it is approved and posted as wastage.</p>
          {rights.approve && <Button size="sm" loading={approveLoss.isPending} onClick={() => approveLoss.mutate()}>Approve loss</Button>}
        </Card>
      )}
    </DocShell>
  )
}

export function CountView() {
  const { id, q, busy, act, rights, refresh } = useControlDoc<Count>('counts')
  const c = q.data
  const [vals, setVals] = useState<Record<number, string>>({})
  const [again, setAgain] = useState<number[]>([])
  const [asking, setAsking] = useState(false)
  useEffect(() => { if (c?.lines) { setVals(Object.fromEntries(c.lines.map((l) => [l.item_id, l.counted_qty ?? '']))); setAgain([]) } }, [c])
  const save = useMutation({
    mutationFn: () => storePut('control', `/counts/${id}`, { lines: Object.entries(vals).map(([item_id, counted_qty]) => ({ item_id: Number(item_id), counted_qty })) }),
    onSuccess: () => { toast.success('Counts saved'); refresh() },
    onError: (e) => toast.error(errText(e)),
  })
  const recount = (reason: string) => storePost('control', `/counts/${id}/recount`, { line_ids: again, reason }).then(() => { toast.success('Sent back for a recount'); setAsking(false); refresh() }).catch((e) => { toast.error(errText(e)); throw e })
  if (q.isLoading || !c) return <Loading />
  const entering = c.status === 'DRAFT' && rights.submit
  const reviewing = c.status === 'SUBMITTED' && rights.approve
  return (
    <DocShell kind="counts" id={c.id} number={c.number} status={c.status} cancelReason={c.cancel_reason} log={c.log ?? []} busy={busy} act={act} rights={rights}
      prints={[{ label: 'Count sheet', form: '' }, ...(c.revealed ? [{ label: 'Variance statement', form: 'variance' }] : [])]}
      sub={<>{c.store_code} · {c.count_date} · {c.counted_count} of {c.line_count} counted{c.bin_code && ` · bin ${c.bin_code}`}{c.categories.length > 0 && ` · ${c.categories.map(label).join(', ')}`}{' '}
        {c.status === 'DRAFT' && <Badge tone="warning">Store frozen</Badge>} {!c.revealed && <Badge>Blind count</Badge>} {c.recount_rounds > 0 && <Badge tone="info">Recount round {c.recount_rounds}</Badge>}</>}>
      <Card className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead><tr className="border-b border-border text-left">{reviewing && <th className={th} />}<th className={th}>Item</th>{c.revealed && <th className={`${th} text-right`}>Books</th>}<th className={`${th} text-right`}>Counted</th>{c.revealed && <><th className={`${th} text-right`}>Difference</th><th className={`${th} text-right`}>Value</th></>}</tr></thead>
          <tbody>
            {(c.lines ?? []).map((l) => {
              const diff = Number(l.variance_qty ?? 0)
              return (
                <tr key={l.id} className="border-b border-border last:border-0">
                  {reviewing && <td className="p-3"><input type="checkbox" aria-label={`Recount ${l.item_name}`} checked={again.includes(l.id)} onChange={() => setAgain(again.includes(l.id) ? again.filter((x) => x !== l.id) : [...again, l.id])} /></td>}
                  <td className="p-3"><span className="font-mono text-xs text-muted-foreground">{l.item_code}</span> {l.item_name} {l.recount && <Badge tone="warning">Recount</Badge>}{l.first_count_qty !== null && <div className="text-xs text-muted-foreground">First count {num(l.first_count_qty)}</div>}</td>
                  {c.revealed && <td className="p-3 text-right">{num(l.system_qty)}</td>}
                  <td className="p-3 text-right">{entering ? <Input className="ml-auto w-28 text-right" inputMode="decimal" value={vals[l.item_id] ?? ''} onChange={(e) => setVals({ ...vals, [l.item_id]: e.target.value })} /> : l.counted_qty === null ? '—' : num(l.counted_qty)}</td>
                  {c.revealed && <><td className={`p-3 text-right ${diff < 0 ? 'text-danger' : diff > 0 ? 'text-success' : ''}`}>{diff > 0 ? '+' : ''}{num(l.variance_qty)}</td><td className="p-3 text-right">{money(l.variance_value)}</td></>}
                </tr>
              )
            })}
          </tbody>
        </table>
        {c.revealed && <div className="flex justify-between border-t border-border p-3 text-sm"><span className="text-muted-foreground">Net difference</span><strong>₹{money(c.variance_value)}</strong></div>}
      </Card>
      {entering && <div><Button variant="soft" loading={save.isPending} onClick={() => save.mutate()}>Save counts</Button><span className="ml-3 text-xs text-muted-foreground">Every item must be counted before the sheet can be submitted. Enter 0 for nothing found.</span></div>}
      {reviewing && <div><Button variant="outline" size="sm" disabled={again.length === 0} onClick={() => setAsking(true)}>Ask for a recount of {again.length || 'selected'} line(s)</Button><span className="ml-3 text-xs text-muted-foreground">Tick the lines that look wrong; the sheet goes back to the counters and the first counts are kept.</span></div>}
      <ConfirmDialog open={asking} onOpenChange={setAsking} title="Ask for a recount?" description="The selected lines are cleared and the sheet returns to the counters. The store stays frozen." confirmLabel="Ask for recount" reason={{ label: 'Why a recount?', required: true }} onConfirm={(reason) => recount(reason)} />
    </DocShell>
  )
}

export function AdjustmentView() {
  const { q, busy, act, rights } = useControlDoc<Adjustment>('adjustments')
  const a = q.data
  if (q.isLoading || !a) return <Loading />
  const writeoff = a.kind !== 'STOCK'
  return (
    <DocShell kind="adjustments" id={a.id} number={a.number} status={a.status} cancelReason={a.cancel_reason} log={a.log ?? []} busy={busy} act={act} rights={rights}
      prints={writeoff ? [{ label: 'Write-off note', form: 'writeoff' }, { label: 'Voucher', form: 'voucher' }] : [{ label: 'Voucher', form: '' }]}
      sub={<>{a.store_code} · {a.adj_date} · {a.kind.toLowerCase()} · <Badge>{label(a.reason_code)}</Badge> {a.high_value && <Badge tone="warning">High value</Badge>}
        <div>{a.reason}</div><div>Supporting paper: {a.attachment_ref}</div>{(a.project_name || a.cost_head) && <div>Charged to {[a.project_name, label(a.cost_head)].filter(Boolean).join(' · ')}</div>}</>}
      extra={a.status === 'DRAFT' && rights.submit ? <Link to={`/store/hub/control/adjustments/${a.id}/edit`}><Button variant="outline" size="sm">Edit</Button></Link> : undefined}>
      <Card className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead><tr className="border-b border-border text-left"><th className={th}>Item</th><th className={th}>In / out</th><th className={`${th} text-right`}>Quantity</th><th className={`${th} text-right`}>Rate</th><th className={`${th} text-right`}>Value</th></tr></thead>
          <tbody>{(a.lines ?? []).map((l) => <tr key={l.id} className="border-b border-border last:border-0"><td className="p-3"><span className="font-mono text-xs text-muted-foreground">{l.item_code}</span> {l.item_name}{l.remarks && <div className="text-xs text-muted-foreground">{l.remarks}</div>}</td><td className="p-3">{a.kind === 'WRITEOFF' ? 'Write-off' : l.direction}</td><td className="p-3 text-right">{num(l.qty)}</td><td className="p-3 text-right">{a.status === 'POSTED' ? money(l.rate) : '—'}</td><td className="p-3 text-right">{a.status === 'POSTED' ? money(l.value) : '—'}</td></tr>)}</tbody>
        </table>
      </Card>
    </DocShell>
  )
}

export function ScrapView() {
  const { q, busy, act, rights } = useControlDoc<Scrap>('scrap')
  const s = q.data
  if (q.isLoading || !s) return <Loading />
  const diff = Number(s.difference)
  return (
    <DocShell kind="scrap" id={s.id} number={s.number} status={s.status} cancelReason={s.cancel_reason} log={s.log ?? []} busy={busy} act={act} rights={rights}
      prints={[{ label: 'Scrap sale note', form: '' }]}
      sub={<>{s.store_code} · {s.scrap_date} · {s.reason}{s.buyer && ` · to ${s.buyer}`}{s.gate_pass_no && ` · gate pass ${s.gate_pass_no}`}{s.project_name && ` · ${s.project_name}`}</>}
      extra={s.status === 'DRAFT' && rights.submit ? <Link to={`/store/hub/control/scrap/${s.id}/edit`}><Button variant="outline" size="sm">Edit</Button></Link> : undefined}>
      <Card className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead><tr className="border-b border-border text-left"><th className={th}>Item</th><th className={th}>Class</th><th className={`${th} text-right`}>Quantity</th><th className={`${th} text-right`}>Book value</th><th className={`${th} text-right`}>Realised</th><th className={`${th} text-right`}>Gain / (loss)</th></tr></thead>
          <tbody>{(s.lines ?? []).map((l) => <tr key={l.id} className="border-b border-border last:border-0"><td className="p-3"><span className="font-mono text-xs text-muted-foreground">{l.item_code}</span> {l.item_name}</td><td className="p-3">{label(l.scrap_class)}</td><td className="p-3 text-right">{num(l.qty)}</td><td className="p-3 text-right">{s.status === 'POSTED' ? money(l.book_value) : '—'}</td><td className="p-3 text-right">{money(l.realised_value)}</td><td className="p-3 text-right">{s.status === 'POSTED' ? money(l.difference) : '—'}</td></tr>)}</tbody>
        </table>
        {s.status === 'POSTED' && <div className="flex justify-between border-t border-border p-3 text-sm"><span className="text-muted-foreground">Realised against book value</span><strong className={diff < 0 ? 'text-danger' : ''}>₹{money(s.difference)}</strong></div>}
      </Card>
    </DocShell>
  )
}
