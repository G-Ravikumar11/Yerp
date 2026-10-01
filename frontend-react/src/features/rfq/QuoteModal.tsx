import { useState } from 'react'
import { Button, Field, Input, Modal, NumField } from '@/components/ui'
import { recordQuote, rfqKeys, useSupplierNames, type Statement } from '@/api/rfq'
import { useAction } from '@/lib/mutate'
import { today } from '@/lib/format'

/** One supplier's answer: a rate and its tax for every line, the freight, the terms. */
export function QuoteModal({ statement, open, onClose }: { statement: Statement | null; open: boolean; onClose: () => void }) {
  return (
    <Modal open={open && !!statement} onOpenChange={(o) => !o && onClose()} title={statement ? `Record a quote - ${statement.rfq.number}` : ''} description="Whatever a supplier left off a line is shown as not quoted in the comparison." size="lg">
      {open && statement && <Form statement={statement} onClose={onClose} />}
    </Modal>
  )
}

function Form({ statement, onClose }: { statement: Statement; onClose: () => void }) {
  const names = useSupplierNames()
  const [f, setF] = useState({ supplier_name: '', quote_ref: '', quote_date: today(), payment_terms: '' })
  const [freight, setFreight] = useState(0)
  const [days, setDays] = useState(0)
  const [rates, setRates] = useState(() => statement.lines.map(() => ({ rate: 0, tax: 18 })))
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF((x) => ({ ...x, [k]: e.target.value }))
  const edit = (i: number, patch: Partial<{ rate: number; tax: number }>) => setRates((r) => r.map((x, j) => (j === i ? { ...x, ...patch } : x)))
  const save = useAction(() => recordQuote(statement.rfq.id, { ...f, freight, delivery_days: days, lines: statement.lines.map((l, i) => ({ rfq_line_id: l.rfq_line_id, rate: rates[i].rate, tax_percent: rates[i].tax })) }), { invalidate: [rfqKeys.all], success: (r) => r.message, onSuccess: onClose })
  return (
    <div>
      <div className="grid gap-4 sm:grid-cols-4">
        <Field label="Supplier" htmlFor="rq-sup" className="sm:col-span-2"><Input id="rq-sup" list="rq-names" value={f.supplier_name} onChange={set('supplier_name')} autoFocus /></Field>
        <datalist id="rq-names">{(names.data ?? []).map((n) => <option key={n} value={n} />)}</datalist>
        <Field label="Their quote ref" htmlFor="rq-ref"><Input id="rq-ref" value={f.quote_ref} onChange={set('quote_ref')} /></Field>
        <Field label="Quote date" htmlFor="rq-date"><Input id="rq-date" type="date" value={f.quote_date} onChange={set('quote_date')} /></Field>
        <Field label="Payment terms" htmlFor="rq-terms" className="sm:col-span-2"><Input id="rq-terms" value={f.payment_terms} onChange={set('payment_terms')} placeholder="30 days from delivery" /></Field>
        <Field label="Freight" htmlFor="rq-freight"><NumField id="rq-freight" value={freight} onValue={setFreight} /></Field>
        <Field label="Delivery (days)" htmlFor="rq-days"><NumField id="rq-days" value={days} onValue={setDays} /></Field>
      </div>
      <div className="mt-4 overflow-hidden rounded-lg border border-border">
        <table aria-label="Rates" className="w-full text-[13px]">
          <thead className="bg-surface text-left text-xs text-muted-foreground"><tr><th className="px-3 py-2">Item</th><th className="w-36 px-3 py-2 text-right">Rate</th><th className="w-24 px-3 py-2 text-right">GST %</th></tr></thead>
          <tbody>{statement.lines.map((l, i) => <tr key={l.rfq_line_id} className="border-t border-border"><td className="px-3 py-2">{l.description}<div className="text-xs text-muted-foreground">{l.qty} {l.uom}</div></td><td className="px-3 py-2"><NumField aria-label={`Rate ${i + 1}`} value={rates[i].rate} onValue={(n) => edit(i, { rate: n })} /></td><td className="px-3 py-2"><NumField aria-label={`GST ${i + 1}`} value={rates[i].tax} onValue={(n) => edit(i, { tax: n })} /></td></tr>)}</tbody>
        </table>
      </div>
      <div className="mt-5 flex items-center justify-end gap-2 border-t border-border pt-4">
        {save.error && <p role="alert" className="mr-auto text-[13px] text-danger">{save.error.message}</p>}
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button loading={save.isPending} disabled={!f.supplier_name.trim()} onClick={() => save.mutate()}>Record the quote</Button>
      </div>
    </div>
  )
}
