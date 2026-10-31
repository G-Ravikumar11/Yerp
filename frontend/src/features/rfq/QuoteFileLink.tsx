import { useState } from 'react'
import { Sparkles } from 'lucide-react'
import { Button, Field, Input, Modal, Select } from '@/components/ui'
import { confirmQuoteFile, linkQuoteFile, quoteFileKeys, readQuoteFile, rfqKeys, useRfqs, useStatement, type QuoteFile, type QuoteFileRead } from '@/api/rfq'
import { useAction } from '@/lib/mutate'

/** On a quotation file's card: the enquiry it answers, and - once linked - the AI quote reader to fill its rates. */
export function QuoteFileLink({ f }: { f: QuoteFile }) {
  const rfqs = useRfqs()
  const link = useAction((rfq_id: number) => linkQuoteFile(f.id, rfq_id || null), { invalidate: [quoteFileKeys.all], success: (r) => r.message })
  const [reading, setReading] = useState(false)
  const open = (rfqs.data?.rfqs ?? []).filter((r) => r.status === 'OPEN' || r.id === f.rfq_id)
  return (
    <div className="mt-2 flex flex-wrap items-center gap-2">
      <Select aria-label={`Enquiry for ${f.name}`} className="h-8 min-w-44 flex-1 text-xs" value={f.rfq_id ?? ''} placeholder="Link to an enquiry" onChange={(e) => link.mutate(Number(e.target.value) || 0)}
        options={open.map((r) => ({ value: r.id, label: `${r.number} - ${r.title}` }))} />
      {f.rfq_id && f.rfq_status === 'OPEN' && <Button size="sm" variant="outline" onClick={() => setReading(true)}><Sparkles /> Read the rates</Button>}
      {reading && f.rfq_id && <ReadModal f={f} rfqId={f.rfq_id} onClose={() => setReading(false)} />}
    </div>
  )
}

/** The rates the AI read off the file, against the enquiry's items, for the buyer to check and correct. Nothing is
 * recorded until Confirm. */
function ReadModal({ f, rfqId, onClose }: { f: QuoteFile; rfqId: number; onClose: () => void }) {
  const st = useStatement(rfqId)
  const [read, setRead] = useState<QuoteFileRead | null>(null)
  const [rates, setRates] = useState<Record<number, { rate: string; tax: string }>>({})
  const [supplier, setSupplier] = useState(f.supplier_name)
  const run = useAction(() => readQuoteFile(f.id), {
    onSuccess: (r) => {
      setRead(r)
      if (r.available) {
        setSupplier(r.supplier_name || f.supplier_name)
        setRates(Object.fromEntries((r.lines ?? []).map((l) => [l.rfq_line_id, { rate: String(l.rate), tax: l.tax_percent == null ? '18' : String(l.tax_percent) }])))
      }
    },
  })
  const lines = st.data?.lines ?? []
  const priced = lines.filter((l) => Number(rates[l.rfq_line_id]?.rate) > 0)
  const confirm = useAction(() => confirmQuoteFile(f.id, {
    supplier_name: supplier.trim(), quote_ref: read?.quote_ref ?? '', quote_date: read?.quote_date ?? '', delivery_days: read?.delivery_days ?? 0,
    payment_terms: read?.payment_terms ?? '', freight: read?.freight ?? 0, valid_until: read?.valid_until ?? '',
    lines: priced.map((l) => ({ rfq_line_id: l.rfq_line_id, rate: Number(rates[l.rfq_line_id].rate), tax_percent: Number(rates[l.rfq_line_id].tax) || 0 })),
  }), { invalidate: [quoteFileKeys.all, rfqKeys.all], success: (r) => r.message, onSuccess: onClose })
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} size="lg" title={`Read ${f.name}`} description={`The AI quote reader matches the file to ${st.data?.rfq.number ?? 'the enquiry'}'s items. Check each rate - correct any it got wrong - then confirm. Nothing is recorded until you do.`}>
      {!read ? (
        <div className="grid gap-3">
          <p className="text-sm">Read the rates off this file now?</p>
          {run.error && <p role="alert" className="text-[13px] text-danger">{run.error.message}</p>}
          <div className="flex justify-end gap-2"><Button variant="ghost" onClick={onClose}>Cancel</Button><Button loading={run.isPending} onClick={() => run.mutate()}><Sparkles /> Read the rates</Button></div>
        </div>
      ) : !read.available ? (
        <div className="grid gap-3">
          <p role="alert" className="text-sm text-danger">{read.message || 'The file could not be read automatically.'}</p>
          <p className="text-sm text-muted-foreground">Enter the rates from the enquiry's page instead.</p>
          <div className="flex justify-end"><Button variant="ghost" onClick={onClose}>Close</Button></div>
        </div>
      ) : (
        <form className="grid gap-3" onSubmit={(e) => { e.preventDefault(); if (supplier.trim() && priced.length) confirm.mutate() }}>
          {read.low_confidence && <p className="rounded-lg bg-warning-soft px-3 py-2 text-[13px] text-warning">The reader was unsure of this file: check every rate.</p>}
          <Field label="Supplier" htmlFor="qr-sup"><Input id="qr-sup" value={supplier} onChange={(e) => setSupplier(e.target.value)} /></Field>
          <ul className="grid gap-2">
            {lines.map((l) => (
              <li key={l.rfq_line_id} className="flex flex-wrap items-center gap-2 rounded-lg border border-border px-3 py-2 text-sm">
                <span className="min-w-0 flex-1">{l.description}<span className="block text-xs text-muted-foreground">{l.qty} {l.uom}{!rates[l.rfq_line_id] && ' - not found on the file'}</span></span>
                <Input aria-label={`Rate for ${l.description}`} inputMode="decimal" className="h-9 w-28 text-right" placeholder="Rate" value={rates[l.rfq_line_id]?.rate ?? ''} onChange={(e) => setRates((r) => ({ ...r, [l.rfq_line_id]: { rate: e.target.value, tax: r[l.rfq_line_id]?.tax ?? '18' } }))} />
                <Input aria-label={`GST % for ${l.description}`} inputMode="decimal" className="h-9 w-20 text-right" placeholder="GST %" value={rates[l.rfq_line_id]?.tax ?? ''} onChange={(e) => setRates((r) => ({ ...r, [l.rfq_line_id]: { rate: r[l.rfq_line_id]?.rate ?? '', tax: e.target.value } }))} />
              </li>
            ))}
          </ul>
          {(read.unmatched ?? []).length > 0 && <p className="text-xs text-muted-foreground">On the file but not on the enquiry: {(read.unmatched ?? []).slice(0, 5).join('; ')}</p>}
          <div className="flex flex-wrap items-center justify-end gap-2 border-t border-border pt-3">
            {confirm.error && <p role="alert" className="mr-auto text-[13px] text-danger">{confirm.error.message}</p>}
            <Button type="button" variant="ghost" onClick={onClose}>Cancel</Button>
            <Button type="submit" loading={confirm.isPending} disabled={!supplier.trim() || !priced.length}>Confirm and record {priced.length} rate{priced.length === 1 ? '' : 's'}</Button>
          </div>
        </form>
      )}
    </Modal>
  )
}
