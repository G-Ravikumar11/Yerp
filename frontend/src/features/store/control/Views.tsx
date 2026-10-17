import { useEffect, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { Badge, Button, Card, Input } from '@/components/ui'
import { toast } from '@/stores/toast'
import { storePerm, storePost, storePut } from '@/api/store'
import { DocShell, Loading, useControlDoc } from './DocShell'
import { errText, money, num, type Adjustment, type Count, type Scrap, type Transfer } from './types'

const th = 'p-3 text-xs uppercase text-muted-foreground'

export function TransferView() {
  const { id, q, busy, act, rights, can, refresh } = useControlDoc<Transfer>('transfers')
  const t = q.data
  const [got, setGot] = useState<Record<number, string>>({})
  const receive = useMutation({
    mutationFn: () => storePost('control', `/transfers/${id}/receive`, { received: Object.fromEntries(Object.entries(got).filter(([, v]) => v !== '')) }),
    onSuccess: () => { toast.success('Received'); refresh() },
    onError: (e) => toast.error(errText(e)),
  })
  useEffect(() => { setGot({}) }, [t?.id])
  if (q.isLoading || !t) return <Loading />
  const receiving = t.transit === 'IN_TRANSIT' && can(storePerm('control', 'post'))
  return (
    <DocShell kind="transfers" id={t.id} number={t.number} status={t.status} cancelReason={t.cancel_reason} log={t.log ?? []} busy={busy} act={act} rights={rights}
      sub={<>{t.store_code} → {t.to_store_code} · {t.trf_date}{t.vehicle_no && ` · ${t.vehicle_no}`} {t.inter_project && <Badge tone="warning">Inter-project</Badge>} {t.transit === 'IN_TRANSIT' && <Badge tone="info">In transit</Badge>} {t.transit === 'RECEIVED' && <Badge tone="success">Received {t.received_on}</Badge>}</>}
      extra={t.status === 'DRAFT' && rights.submit ? <Link to={`/store/hub/control/transfers/${t.id}/edit`}><Button variant="outline" size="sm">Edit</Button></Link> : undefined}>
      <Card className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead><tr className="border-b border-border text-left"><th className={th}>Item</th><th className={`${th} text-right`}>On hand at sender</th><th className={`${th} text-right`}>Sent</th><th className={`${th} text-right`}>Value</th><th className={`${th} text-right`}>Received</th></tr></thead>
          <tbody>
            {(t.lines ?? []).map((l) => (
              <tr key={l.id} className="border-b border-border last:border-0">
                <td className="p-3"><span className="font-mono text-xs text-muted-foreground">{l.item_code}</span> {l.item_name}</td><td className="p-3 text-right">{num(l.on_hand)}</td><td className="p-3 text-right">{num(l.qty)}</td>
                <td className="p-3 text-right">{t.status === 'POSTED' ? money(l.value) : '—'}</td>
                <td className="p-3 text-right">{receiving ? <Input className="ml-auto w-24 text-right" inputMode="decimal" placeholder={num(l.qty)} value={got[l.id] ?? ''} onChange={(e) => setGot({ ...got, [l.id]: e.target.value })} /> : l.received_qty === null ? '—' : num(l.received_qty)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
      {receiving && <div><Button loading={receive.isPending} onClick={() => receive.mutate()}>Confirm receipt</Button><span className="ml-3 text-xs text-muted-foreground">Leave a quantity empty if all of it arrived. Anything short goes back to {t.store_code}.</span></div>}
    </DocShell>
  )
}

export function CountView() {
  const { id, q, busy, act, rights, refresh } = useControlDoc<Count>('counts')
  const c = q.data
  const [vals, setVals] = useState<Record<number, string>>({})
  useEffect(() => { if (c?.lines) setVals(Object.fromEntries(c.lines.map((l) => [l.item_id, l.counted_qty ?? '']))) }, [c])
  const save = useMutation({
    mutationFn: () => storePut('control', `/counts/${id}`, { lines: Object.entries(vals).map(([item_id, counted_qty]) => ({ item_id: Number(item_id), counted_qty })) }),
    onSuccess: () => { toast.success('Counts saved'); refresh() },
    onError: (e) => toast.error(errText(e)),
  })
  if (q.isLoading || !c) return <Loading />
  const entering = c.status === 'DRAFT' && rights.submit
  return (
    <DocShell kind="counts" id={c.id} number={c.number} status={c.status} cancelReason={c.cancel_reason} log={c.log ?? []} busy={busy} act={act} rights={rights}
      sub={<>{c.store_code} · {c.count_date} · {c.counted_count} of {c.line_count} counted {c.status === 'DRAFT' && <Badge tone="warning">Store frozen</Badge>} {!c.revealed && <Badge>Blind count</Badge>}</>}>
      <Card className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead><tr className="border-b border-border text-left"><th className={th}>Item</th>{c.revealed && <th className={`${th} text-right`}>Books</th>}<th className={`${th} text-right`}>Counted</th>{c.revealed && <><th className={`${th} text-right`}>Difference</th><th className={`${th} text-right`}>Value</th></>}</tr></thead>
          <tbody>
            {(c.lines ?? []).map((l) => {
              const diff = Number(l.variance_qty ?? 0)
              return (
                <tr key={l.id} className="border-b border-border last:border-0">
                  <td className="p-3"><span className="font-mono text-xs text-muted-foreground">{l.item_code}</span> {l.item_name}</td>
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
    </DocShell>
  )
}

export function AdjustmentView() {
  const { q, busy, act, rights } = useControlDoc<Adjustment>('adjustments')
  const a = q.data
  if (q.isLoading || !a) return <Loading />
  return (
    <DocShell kind="adjustments" id={a.id} number={a.number} status={a.status} cancelReason={a.cancel_reason} log={a.log ?? []} busy={busy} act={act} rights={rights}
      sub={<>{a.store_code} · {a.adj_date} · {a.kind.toLowerCase()} · {a.reason} {a.high_value && <Badge tone="warning">High value</Badge>}{(a.project_name || a.cost_head) && <div>Charged to {[a.project_name, a.cost_head?.replace(/_/g, ' ').toLowerCase()].filter(Boolean).join(' · ')}</div>}</>}
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
  return (
    <DocShell kind="scrap" id={s.id} number={s.number} status={s.status} cancelReason={s.cancel_reason} log={s.log ?? []} busy={busy} act={act} rights={rights}
      sub={<>{s.store_code} · {s.scrap_date} · {s.reason}{s.buyer && ` · sold to ${s.buyer}`}{s.project_name && ` · ${s.project_name}`}</>}
      extra={s.status === 'DRAFT' && rights.submit ? <Link to={`/store/hub/control/scrap/${s.id}/edit`}><Button variant="outline" size="sm">Edit</Button></Link> : undefined}>
      <Card className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead><tr className="border-b border-border text-left"><th className={th}>Item</th><th className={`${th} text-right`}>Quantity</th><th className={`${th} text-right`}>Book value</th><th className={`${th} text-right`}>Realised</th></tr></thead>
          <tbody>{(s.lines ?? []).map((l) => <tr key={l.id} className="border-b border-border last:border-0"><td className="p-3"><span className="font-mono text-xs text-muted-foreground">{l.item_code}</span> {l.item_name}</td><td className="p-3 text-right">{num(l.qty)}</td><td className="p-3 text-right">{s.status === 'POSTED' ? money(l.book_value) : '—'}</td><td className="p-3 text-right">{money(l.realised_value)}</td></tr>)}</tbody>
        </table>
        {s.status === 'POSTED' && <div className="flex justify-between border-t border-border p-3 text-sm"><span className="text-muted-foreground">Gain / loss on scrap</span><strong>₹{money(String(Number(s.realised_value) - Number(s.book_value)))}</strong></div>}
      </Card>
    </DocShell>
  )
}
