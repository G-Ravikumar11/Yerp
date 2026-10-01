import { useState } from 'react'
import { Button, Field, Input, Modal, NumField, Select } from '@/components/ui'
import { sendStock, stockKeys, useStock, useStores } from '@/api/stock'
import { useAction } from '@/lib/mutate'
import { today } from '@/lib/format'

/** Material left at one site, sent to the next at what it cost. Nothing is charged to a project until it is issued at the other end. */
export function TransferModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  return (
    <Modal open={open} onOpenChange={(o) => !o && onClose()} title="Send to another site" description="Not consumption: nothing is charged to a project until it is issued at the other end." size="lg">
      {open && <Form onClose={onClose} />}
    </Modal>
  )
}

function Form({ onClose }: { onClose: () => void }) {
  const stores = useStores()
  const names = (stores.data ?? []).map((s) => s.store)
  const [from, setFrom] = useState('')
  const source = from || names[0] || 'Main store'
  const held = useStock(false, source)
  const [to, setTo] = useState('')
  const [on, setOn] = useState(today())
  const [note, setNote] = useState('')
  const [qty, setQty] = useState<Record<string, number>>({})
  const rows = (held.data?.stock ?? []).filter((r) => r.on_hand > 0)
  const lines = rows.filter((r) => (qty[r.item_code] ?? 0) > 0).map((r) => ({ item_code: r.item_code, qty: qty[r.item_code] }))
  const save = useAction(() => sendStock({ from_store: source, to_store: to, moved_on: on, note, lines }), { invalidate: [stockKeys.all], success: (r) => r.message, onSuccess: onClose })
  return (
    <div>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="From" htmlFor="tr-from"><Select id="tr-from" value={source} onChange={(e) => { setFrom(e.target.value); setQty({}) }} options={(names.length ? names : ['Main store']).map((s) => ({ value: s, label: s }))} /></Field>
        <Field label="To" htmlFor="tr-to"><Input id="tr-to" list="tr-stores" value={to} onChange={(e) => setTo(e.target.value)} placeholder="Another store, or a new one" /></Field>
        <datalist id="tr-stores">{names.map((s) => <option key={s} value={s} />)}</datalist>
        <Field label="On" htmlFor="tr-on"><Input id="tr-on" type="date" value={on} onChange={(e) => setOn(e.target.value)} /></Field>
        <Field label="Note" htmlFor="tr-note"><Input id="tr-note" value={note} onChange={(e) => setNote(e.target.value)} /></Field>
      </div>
      <div className="mt-4 max-h-64 overflow-auto rounded-lg border border-border">
        <table aria-label="Held in this store" className="w-full text-[13px]">
          <thead className="sticky top-0 bg-surface text-left text-xs text-muted-foreground"><tr><th className="px-3 py-2">Item</th><th className="px-3 py-2 text-right">Held</th><th className="w-32 px-3 py-2 text-right">Send</th></tr></thead>
          <tbody>
            {rows.length === 0 && <tr><td colSpan={3} className="px-3 py-5 text-center text-muted-foreground">Nothing held in {source}.</td></tr>}
            {rows.map((r) => <tr key={r.item_code} className="border-t border-border"><td className="px-3 py-2"><span className="font-mono">{r.item_code}</span><div className="text-xs text-muted-foreground">{r.item_name}</div></td><td className="px-3 py-2 text-right tabular">{r.on_hand} {r.uom}</td><td className="px-3 py-2"><NumField aria-label={`Send ${r.item_code}`} value={qty[r.item_code] ?? 0} onValue={(n) => setQty((x) => ({ ...x, [r.item_code]: n }))} /></td></tr>)}
          </tbody>
        </table>
      </div>
      <div className="mt-5 flex items-center justify-end gap-2 border-t border-border pt-4">
        {save.error && <p role="alert" className="mr-auto text-[13px] text-danger">{save.error.message}</p>}
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button loading={save.isPending} disabled={!lines.length || !to.trim()} onClick={() => save.mutate()}>Send it</Button>
      </div>
    </div>
  )
}
