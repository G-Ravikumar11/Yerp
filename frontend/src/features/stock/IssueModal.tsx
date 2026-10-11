import { useMemo, useState } from 'react'
import { Button, Field, Input, Modal, NumField, Select } from '@/components/ui'
import { openIssue, postIssue, stockKeys, useGangOrders, usePlacedOrders, useStock, useStores } from '@/api/stock'
import { projectLabel, useProjects } from '@/api/projects'
import { useAction } from '@/lib/mutate'
import { today } from '@/lib/format'
import { formatINR } from '@/lib/utils'

/** Material from the store to a site, against an order or a project; optionally charged on to a gang. */
export function IssueModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  return (
    <Modal open={open} onOpenChange={(o) => !o && onClose()} title="Issue to site" description="Only what is in the store can be issued from it. The material is charged to the site it goes to." size="xl">
      {open && <Form onClose={onClose} />}
    </Modal>
  )
}

function Form({ onClose }: { onClose: () => void }) {
  const held = useStock(false)
  const orders = usePlacedOrders()
  const jobs = useProjects()
  const stores = useStores()
  const gangs = useGangOrders()
  const [order, setOrder] = useState('')
  const [job, setJob] = useState('')
  const [store, setStore] = useState('')
  const [on, setOn] = useState(today())
  const [to, setTo] = useState('')
  const [purpose, setPurpose] = useState('')
  const [qty, setQty] = useState<Record<string, number>>({})
  const [charge, setCharge] = useState(false)
  const [gang, setGang] = useState('')
  const [markup, setMarkup] = useState(0)
  const rows = useMemo(() => (held.data?.stock ?? []).filter((r) => r.on_hand > 0), [held.data])
  const lines = rows.filter((r) => (qty[r.item_code] ?? 0) > 0).map((r) => ({ item_code: r.item_code, quantity: qty[r.item_code], rate: r.rate }))
  const total = lines.reduce((t, l) => t + l.quantity * l.rate, 0)
  const over = rows.some((r) => (qty[r.item_code] ?? 0) > r.on_hand)
  const save = useAction(async (andPost: boolean) => {
    const made = await openIssue({ work_order_id: order ? Number(order) : null, job_id: !order && job ? Number(job) : null, store, issued_on: on, issued_to: to, purpose, lines })
    if (andPost || charge) return postIssue(made.issue.id, charge ? { recover_from_order_id: Number(gang) || null, markup_percent: markup } : {})
    return { message: made.message }
  }, { invalidate: [stockKeys.all], success: (r) => r.message, onSuccess: onClose })
  return (
    <div>
      <div className="grid gap-4 sm:grid-cols-3">
        <Field label="Against an order" htmlFor="is-order"><Select id="is-order" value={order} placeholder="Not against a particular order" onChange={(e) => setOrder(e.target.value)} options={(orders.data ?? []).map((w) => ({ value: w.id, label: `${w.number} - ${w.job_name}` }))} /></Field>
        {!order && <Field label="Or the project" htmlFor="is-job"><Select id="is-job" value={job} placeholder="Not job-specific" onChange={(e) => setJob(e.target.value)} options={(jobs.data ?? []).map((p) => ({ value: p.id, label: projectLabel(p) }))} /></Field>}
        <Field label="From the store" htmlFor="is-store"><Select id="is-store" value={store} placeholder="Wherever it is held" onChange={(e) => setStore(e.target.value)} options={(stores.data ?? []).filter((x) => x.value > 0).sort((a, b) => b.value - a.value).map((x) => ({ value: x.store, label: x.store }))} /></Field>
        <Field label="Date" htmlFor="is-on"><Input id="is-on" type="date" value={on} onChange={(e) => setOn(e.target.value)} /></Field>
        <Field label="Taken by" htmlFor="is-to"><Input id="is-to" value={to} onChange={(e) => setTo(e.target.value)} /></Field>
        <Field label="Purpose" htmlFor="is-purpose"><Input id="is-purpose" value={purpose} onChange={(e) => setPurpose(e.target.value)} /></Field>
      </div>
      <div className="mt-4 max-h-72 overflow-auto rounded-lg border border-border">
        <table aria-label="Items in the store" className="w-full text-[13px]">
          <thead className="sticky top-0 bg-surface text-left text-xs text-muted-foreground"><tr><th className="px-3 py-2">Item</th><th className="px-3 py-2 text-right">In the store</th><th className="px-3 py-2 text-right">Rate</th><th className="w-32 px-3 py-2 text-right">Issue</th></tr></thead>
          <tbody>
            {rows.length === 0 && <tr><td colSpan={4} className="px-3 py-5 text-center text-muted-foreground">The store is empty.</td></tr>}
            {rows.map((r) => (
              <tr key={r.item_code} className="border-t border-border">
                <td className="px-3 py-2"><span className="font-mono">{r.item_code}</span><div className="text-xs text-muted-foreground">{r.item_name}</div></td>
                <td className="px-3 py-2 text-right tabular">{r.on_hand} {r.uom}</td>
                <td className="px-3 py-2 text-right tabular">{formatINR(r.rate)}</td>
                <td className="px-3 py-2"><NumField aria-label={`Issue ${r.item_code}`} aria-invalid={(qty[r.item_code] ?? 0) > r.on_hand} value={qty[r.item_code] ?? 0} onValue={(n) => setQty((x) => ({ ...x, [r.item_code]: n }))} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-2 flex items-center justify-between text-sm"><span className="text-danger" role="alert">{over ? 'One line asks for more than the store holds.' : ''}</span><span>Value <strong className="tabular">{formatINR(total)}</strong></span></p>
      <label className="mt-3 flex items-center gap-2 text-sm"><input type="checkbox" checked={charge} onChange={(e) => setCharge(e.target.checked)} /> Charge it to a contractor (recover from their next bill)</label>
      {charge && (
        <div className="mt-3 grid gap-4 sm:grid-cols-2">
          <Field label="Recover from" htmlFor="is-gang"><Select id="is-gang" value={gang} placeholder="Choose the contractor's work order" onChange={(e) => setGang(e.target.value)} options={(gangs.data ?? []).map((o) => ({ value: o.id, label: `${o.wo_number} - ${o.contractor}` }))} /></Field>
          <Field label="Mark-up %" htmlFor="is-markup"><NumField id="is-markup" value={markup} onValue={setMarkup} /></Field>
        </div>
      )}
      <div className="mt-5 flex flex-wrap items-center justify-end gap-2 border-t border-border pt-4">
        {save.error && <p role="alert" className="mr-auto text-[13px] text-danger">{save.error.message}</p>}
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button variant="outline" loading={save.isPending} disabled={!lines.length || (charge && !gang)} onClick={() => save.mutate(false)}>Open the note</Button>
        <Button loading={save.isPending} disabled={!lines.length || (charge && !gang)} onClick={() => save.mutate(true)}>Issue it now</Button>
      </div>
    </div>
  )
}
