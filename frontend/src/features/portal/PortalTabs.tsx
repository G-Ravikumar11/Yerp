import { useState, type ReactNode } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Badge, Button, Field, Input, Stat, StatGrid } from '@/components/ui'
import { ApiError } from '@/lib/api'
import { formatDate } from '@/lib/format'
import { formatINR } from '@/lib/utils'
import { portalAcceptBill, portalSendInvoice, usePortal, type PortalBill, type PortalOrder, type PortalOrderDetail, type PortalPayment, type PortalStatement, type PortalSummary } from '@/api/portal'

const th = 'px-2 py-2 text-left text-xs font-semibold uppercase text-muted-foreground'
const td = 'px-2 py-2 align-top'

function Table({ label, head, empty, children, right = [] }: { label: string; head: string[]; empty: string; children: ReactNode[] | ReactNode; right?: number[] }) {
  const rows = Array.isArray(children) ? children : [children]
  return (
    <div className="overflow-x-auto rounded-xl border border-border bg-card">
      <table aria-label={label} className="w-full text-sm">
        <thead className="border-b border-border"><tr>{head.map((h, i) => <th key={h} className={th + (right.includes(i) ? ' text-right' : '')}>{h}</th>)}</tr></thead>
        <tbody className="divide-y divide-border">{rows.length ? rows : <tr><td colSpan={head.length} className="px-2 py-6 text-center text-muted-foreground">{empty}</td></tr>}</tbody>
      </table>
    </div>
  )
}

export function Overview() {
  const q = usePortal<PortalSummary>('summary', '/api/portal/summary')
  const s = q.data
  return (
    <div className="grid gap-5">
      <h2 className="text-lg font-semibold">Where things stand</h2>
      <StatGrid>
        <Stat label={(s?.balance ?? 0) >= 0 ? 'Due to you' : 'Due from you'} value={formatINR(Math.abs(s?.balance ?? 0))} sub="on your statement today" loading={q.isPending} />
        <Stat label="Passed, not yet paid" value={formatINR(s?.passed_unpaid)} loading={q.isPending} />
        <Stat label="Bills being checked" value={s?.bills_waiting ?? 0} loading={q.isPending} />
        <Stat label="Paid to you so far" value={formatINR(s?.paid_total)} sub={s?.last_payment ? `last ${formatINR(s.last_payment.amount)} on ${formatDate(s.last_payment.paid_on)}` : undefined} loading={q.isPending} />
        <Stat label="Live orders" value={s?.orders ?? 0} sub={formatINR(s?.order_value)} loading={q.isPending} />
        {s?.retention_held !== undefined && <Stat label="Your retention with us" value={formatINR(s.retention_held)} />}
      </StatGrid>
      {!!s?.retention?.length && (
        <>
          <h2 className="text-lg font-semibold">Retention</h2>
          <Table label="Retention" head={['Order', 'Held', 'Released', 'Still held', 'Defects period ends']} empty="" right={[1, 2, 3]}>
            {s.retention.map((r) => <tr key={r.order_number}><td className={td + ' font-mono'}>{r.order_number}</td><td className={td + ' text-right'}>{formatINR(r.held)}</td><td className={td + ' text-right'}>{formatINR(r.released)}</td><td className={td + ' text-right font-semibold'}>{formatINR(r.balance)}</td><td className={td}>{r.dlp_ends ? formatDate(r.dlp_ends) : '-'}</td></tr>)}
          </Table>
        </>
      )}
    </div>
  )
}

export function Orders() {
  const q = usePortal<{ orders: PortalOrder[] }>('orders', '/api/portal/orders')
  const [open, setOpen] = useState(0)
  const detail = usePortal<PortalOrderDetail>('order' + open, `/api/portal/orders/${open}`)
  const orders = q.data?.orders ?? []
  return (
    <div className="grid gap-5">
      <h2 className="text-lg font-semibold">Your orders</h2>
      <Table label="Orders" head={['Order', 'Project', 'Value', 'Period', '']} empty="No orders yet." right={[2]}>
        {orders.map((o) => (
          <tr key={o.id}>
            <td className={td}><span className="font-mono">{o.number}</span> {o.superseded && <Badge>replaced by an amendment</Badge>}{o.subject && <div className="text-xs text-muted-foreground">{o.subject.slice(0, 90)}</div>}</td>
            <td className={td}>{o.project}</td>
            <td className={td + ' text-right'}>{formatINR(o.value)}</td>
            <td className={td + ' whitespace-nowrap text-xs text-muted-foreground'}>{o.from ? formatDate(o.from) : ''}{o.to ? ` → ${formatDate(o.to)}` : ''}</td>
            <td className={td + ' whitespace-nowrap text-right'}>
              <Button size="sm" variant="outline" onClick={() => setOpen(o.id)}>Items</Button>{' '}
              <Button size="sm" variant="outline" asChild><a href={`/api/portal/orders/${o.id}/document.pdf`} target="_blank" rel="noopener noreferrer">PDF</a></Button>
            </td>
          </tr>
        ))}
      </Table>
      {open > 0 && detail.data && (
        <div className="grid gap-3">
          <h2 className="text-lg font-semibold">{detail.data.order.number} - items</h2>
          <Table label="Order items" head={['Item', 'Qty', 'Rate', 'Amount']} empty="No items." right={[1, 2, 3]}>
            {detail.data.lines.map((l, i) => <tr key={i}><td className={td}>{l.code && <span className="font-mono">{l.code} </span>}{l.description}</td><td className={td + ' text-right'}>{l.qty} {l.uom}</td><td className={td + ' text-right'}>{formatINR(l.rate)}</td><td className={td + ' text-right'}>{formatINR(l.amount)}</td></tr>)}
          </Table>
        </div>
      )}
    </div>
  )
}

const tone = (where: string) => (/paid/.test(where) ? 'success' : /sent back/.test(where) ? 'danger' : /passed|accepted/.test(where) ? 'warning' : 'neutral') as 'success' | 'danger' | 'warning' | 'neutral'

export function Bills({ gang }: { gang: boolean }) {
  const qc = useQueryClient()
  const q = usePortal<{ bills: PortalBill[] }>('bills', '/api/portal/bills')
  const [error, setError] = useState('')
  const accept = async (id: number) => {
    if (!window.confirm('Accept this certificate of payment for your firm? It records that you agree with the measurements and the deductions.')) return
    try {
      await portalAcceptBill(id)
      await qc.invalidateQueries({ queryKey: ['portal', 'bills'] })
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Could not accept it.')
    }
  }
  return (
    <div className="grid gap-5">
      <h2 className="text-lg font-semibold">Your bills</h2>
      {error && <p role="alert" className="text-sm text-danger">{error}</p>}
      <Table label="Bills" head={['Bill', 'Where it is', gang ? 'Work claimed' : 'Before tax', 'Payable', 'Paid', 'Left']} empty="No bills yet." right={[2, 3, 4, 5]}>
        {(q.data?.bills ?? []).map((b) => (
          <tr key={b.id}>
            <td className={td}><span className="font-mono">{b.number}</span><div className="text-xs text-muted-foreground">{formatDate(b.date)}</div></td>
            <td className={td}><Badge tone={tone(b.where)}>{b.where}</Badge>{b.note && <div className="text-xs text-muted-foreground">{b.note}</div>}</td>
            <td className={td + ' text-right'}>{formatINR(b.claimed)}<div className="text-xs text-muted-foreground">{gang && (b.retention || b.tds || b.deductions) ? `retention ${formatINR(b.retention)}${b.deductions ? `, recoveries ${formatINR(b.deductions)}` : ''}, TDS ${formatINR(b.tds)}, GST ${formatINR(b.gst)}` : `GST ${formatINR(b.gst)}`}</div></td>
            <td className={td + ' text-right font-semibold'}>{formatINR(b.net)}</td>
            <td className={td + ' text-right'}>{formatINR(b.paid)}</td>
            <td className={td + ' text-right'}>
              {formatINR(b.left)}
              {b.pdf && <div><Button size="sm" variant="outline" asChild><a href={b.pdf} target="_blank" rel="noopener noreferrer">PDF</a></Button></div>}
              {gang && b.pdf && (b.can_accept ? <div><Button size="sm" variant="outline" onClick={() => accept(b.id)}>Accept</Button></div> : <div className="text-xs text-muted-foreground">Accepted by {b.accepted_by}{b.accepted_at ? `, ${b.accepted_at}` : ''}</div>)}
            </td>
          </tr>
        ))}
      </Table>
    </div>
  )
}

export function Payments() {
  const q = usePortal<{ payments: PortalPayment[] }>('payments', '/api/portal/payments')
  return (
    <div className="grid gap-5">
      <h2 className="text-lg font-semibold">Payments to you</h2>
      <Table label="Payments" head={['Date', 'Voucher', 'Against', 'How', 'Amount']} empty="Nothing paid yet." right={[4]}>
        {(q.data?.payments ?? []).map((p, i) => <tr key={i}><td className={td + ' whitespace-nowrap'}>{formatDate(p.paid_on)}</td><td className={td + ' font-mono'}>{p.number}</td><td className={td}>{p.against}</td><td className={td}>{p.mode}{p.reference && <div className="text-xs text-muted-foreground">{p.reference}</div>}</td><td className={td + ' text-right font-semibold'}>{formatINR(p.amount)}</td></tr>)}
      </Table>
    </div>
  )
}

export function Statement() {
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const query = `?date_from=${encodeURIComponent(from)}&date_to=${encodeURIComponent(to)}`
  const q = usePortal<PortalStatement>('statement', '/api/portal/statement' + query)
  const s = q.data
  return (
    <div className="grid gap-4">
      <h2 className="text-lg font-semibold">Statement of account</h2>
      <div className="flex flex-wrap items-end gap-3">
        <Field label="From" htmlFor="ps-from"><Input id="ps-from" type="date" value={from} onChange={(e) => setFrom(e.target.value)} /></Field>
        <Field label="To" htmlFor="ps-to"><Input id="ps-to" type="date" value={to} onChange={(e) => setTo(e.target.value)} /></Field>
        <Button variant="outline" asChild><a href={'/api/portal/statement.pdf' + query} target="_blank" rel="noopener noreferrer">PDF</a></Button>
        <Button variant="outline" asChild><a href={'/api/portal/statement.xlsx' + query}>Excel</a></Button>
      </div>
      {!!s?.opening && <p className="text-sm text-muted-foreground">Brought forward: {formatINR(s.opening)}</p>}
      <Table label="Statement" head={['Date', 'Entry', 'Billed', 'Paid', 'Balance']} empty="Nothing in this period." right={[2, 3, 4]}>
        {(s?.rows ?? []).map((r, i) => (
          <tr key={i}><td className={td + ' whitespace-nowrap'}>{formatDate(r.date)}</td><td className={td}>{r.kind}<div className="text-xs text-muted-foreground">{r.number}{r.against ? ` · against ${r.against}` : ''}{r.reference ? ` · ${r.reference}` : ''}</div></td><td className={td + ' text-right'}>{r.billed ? formatINR(r.billed) : ''}</td><td className={td + ' text-right'}>{r.paid ? formatINR(r.paid) : ''}</td><td className={td + ' text-right font-semibold'}>{formatINR(r.balance)}</td></tr>
        ))}
      </Table>
      {s && <p className="font-semibold">{s.closing >= 0 ? 'Balance due to you: ' : 'Balance due from you: '}{formatINR(Math.abs(s.closing))}</p>}
    </div>
  )
}

export function SendInvoice() {
  const qc = useQueryClient()
  const orders = usePortal<{ orders: PortalOrder[] }>('orders', '/api/portal/orders').data?.orders ?? []
  const [f, setF] = useState({ number: '', issue_date: new Date().toISOString().slice(0, 10), amount: '', tax_amount: '0', po_number: '', note: '' })
  const [file, setFile] = useState<File | null>(null)
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)
  const [busy, setBusy] = useState(false)
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setF((x) => ({ ...x, [k]: e.target.value }))
  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!file) return
    const fd = new FormData()
    Object.entries(f).forEach(([k, v]) => fd.append(k, v))
    fd.append('file', file)
    setBusy(true)
    try {
      const r = await portalSendInvoice(fd)
      setMsg({ ok: true, text: r.message })
      setF({ ...f, number: '', amount: '', tax_amount: '0', po_number: '', note: '' })
      setFile(null)
      await qc.invalidateQueries({ queryKey: ['portal', 'bills'] })
    } catch (err) {
      setMsg({ ok: false, text: err instanceof ApiError ? err.message : 'Not sent.' })
    } finally {
      setBusy(false)
    }
  }
  return (
    <form onSubmit={submit} className="grid max-w-xl gap-4">
      <div><h2 className="text-lg font-semibold">Send us an invoice</h2><p className="text-sm text-muted-foreground">It reaches the office as a bill to check against what was delivered. You will see it under Bills, and when it is accepted and paid.</p></div>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Your invoice number" htmlFor="si-no"><Input id="si-no" required value={f.number} onChange={set('number')} /></Field>
        <Field label="Invoice date" htmlFor="si-date"><Input id="si-date" type="date" required value={f.issue_date} onChange={set('issue_date')} /></Field>
        <Field label="Value before GST" htmlFor="si-amt"><Input id="si-amt" type="number" step="0.01" min="0" required value={f.amount} onChange={set('amount')} /></Field>
        <Field label="GST" htmlFor="si-gst"><Input id="si-gst" type="number" step="0.01" min="0" value={f.tax_amount} onChange={set('tax_amount')} /></Field>
      </div>
      <Field label="Against our order" htmlFor="si-po">
        <select id="si-po" value={f.po_number} onChange={set('po_number')} className="h-10 w-full rounded-md border border-input bg-transparent px-3 text-sm">
          <option value="">Not against an order</option>
          {orders.filter((o) => !o.superseded).map((o) => <option key={o.id}>{o.number}</option>)}
        </select>
      </Field>
      <Field label="The invoice (PDF or a photo)" htmlFor="si-file"><input id="si-file" type="file" accept="application/pdf,image/*" required onChange={(e) => setFile(e.target.files?.[0] ?? null)} /></Field>
      <Field label="Note" htmlFor="si-note"><Input id="si-note" placeholder="Delivery challan numbers, anything the office should know" value={f.note} onChange={set('note')} /></Field>
      <Button type="submit" loading={busy}>Send it</Button>
      {msg && <p role={msg.ok ? 'status' : 'alert'} className={msg.ok ? 'text-sm text-success' : 'text-sm text-danger'}>{msg.text}</p>}
    </form>
  )
}
