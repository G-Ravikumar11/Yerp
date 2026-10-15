import { useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { FileUp, Loader2, ScanText, X } from 'lucide-react'
import { Badge, Button, Field, Input, Modal, NumField } from '@/components/ui'
import { keepQuoteDocument, QUOTE_FILES, recordQuote, rfqKeys, useSupplierNames, type Statement } from '@/api/rfq'
import { readQuote, type ReadQuote } from '@/api/aiPurchasing'
import { ApiError } from '@/lib/api'
import { today } from '@/lib/format'
import { toast } from '@/stores/toast'

/**
 * Add a supplier's quote in one place: choose his quotation (any PDF, Word, Excel or photo - every supplier has his own
 * style) and its rates are read into the form; check them, fix anything, save. His file is kept with the quote.
 * Without a file, the rates are simply typed in.
 */
export function QuoteModal({ statement, open, onClose, supplier = '' }: { statement: Statement | null; open: boolean; onClose: () => void; supplier?: string }) {
  return (
    <Modal open={open && !!statement} onOpenChange={(o) => !o && onClose()} size="lg" title={statement ? `Add a quote - ${statement.rfq.number}` : ''}
      description="Choose the supplier's quotation and its rates are filled in for you to check, or type them. Items a supplier did not price are shown as not quoted.">
      {open && statement && <Form statement={statement} supplier={supplier} onClose={onClose} />}
    </Modal>
  )
}

function Form({ statement, supplier, onClose }: { statement: Statement; supplier: string; onClose: () => void }) {
  const qc = useQueryClient()
  const names = useSupplierNames()
  const fileRef = useRef<HTMLInputElement>(null)
  const [file, setFile] = useState<File | null>(null)
  const [reading, setReading] = useState(false)
  const [read, setRead] = useState<ReadQuote | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [f, setF] = useState({ supplier_name: supplier, quote_ref: '', quote_date: today(), payment_terms: '', valid_until: '' })
  const [freight, setFreight] = useState(0)
  const [days, setDays] = useState(0)
  const [rates, setRates] = useState(() => statement.lines.map(() => ({ rate: 0, tax: 18 })))
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF((x) => ({ ...x, [k]: e.target.value }))
  const edit = (i: number, patch: Partial<{ rate: number; tax: number }>) => setRates((r) => r.map((x, j) => (j === i ? { ...x, ...patch } : x)))

  /** The file chosen: kept to be saved with the quote, and read straight away to fill the form. */
  const choose = async (picked: File | null) => {
    setFile(picked)
    setRead(null)
    setError('')
    if (!picked) return
    setReading(true)
    try {
      const r = await readQuote(statement.rfq.id, { file: picked })
      setRead(r)
      if (r.available) {
        setF((x) => ({
          supplier_name: x.supplier_name || r.supplier_name || '', quote_ref: r.quote_ref || x.quote_ref, quote_date: r.quote_date || x.quote_date,
          payment_terms: r.payment_terms || x.payment_terms, valid_until: r.valid_until || x.valid_until,
        }))
        if (r.freight) setFreight(r.freight)
        if (r.delivery_days) setDays(r.delivery_days)
        setRates((old) => statement.lines.map((l, i) => {
          const got = r.lines?.find((x) => x.rfq_line_id === l.rfq_line_id)
          return got ? { rate: got.rate, tax: got.tax_percent ?? old[i].tax } : old[i]
        }))
      }
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'The file could not be read. Type the rates instead.')
    } finally {
      setReading(false)
    }
  }

  const save = async () => {
    setBusy(true)
    setError('')
    try {
      const out = await recordQuote(statement.rfq.id, { ...f, freight, delivery_days: days, lines: statement.lines.map((l, i) => ({ rfq_line_id: l.rfq_line_id, rate: rates[i].rate, tax_percent: rates[i].tax })) })
      if (file && out.quote_id) {
        try { await keepQuoteDocument(statement.rfq.id, out.quote_id, file) } catch { toast.info('The quote is saved, but its file could not be kept. Add it again from the comparison.') }
      }
      await qc.invalidateQueries({ queryKey: rfqKeys.all })
      toast.success(out.message)
      onClose()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'The quote could not be saved. Try again.')
    } finally {
      setBusy(false)
    }
  }
  const priced = rates.filter((r) => r.rate > 0).length

  return (
    <div className="grid gap-4">
      {/* 1. his quotation */}
      <div className="rounded-lg border border-dashed border-border bg-surface/50 p-4">
        <div className="flex flex-wrap items-center gap-3">
          <input ref={fileRef} type="file" accept={QUOTE_FILES} className="hidden" aria-label="The supplier's quotation file" onChange={(e) => void choose(e.target.files?.[0] ?? null)} />
          <Button variant="outline" onClick={() => fileRef.current?.click()} disabled={reading}><FileUp /> {file ? 'Choose another file' : "Choose the supplier's quotation"}</Button>
          {file && <span className="inline-flex items-center gap-1.5 text-sm">{file.name}<button type="button" aria-label="Remove the file" onClick={() => { void choose(null); if (fileRef.current) fileRef.current.value = '' }}><X className="size-3.5" /></button></span>}
          {reading && <span className="inline-flex items-center gap-1.5 text-sm text-muted-foreground"><Loader2 className="size-4 animate-spin" /> Reading the rates...</span>}
        </div>
        <p className="mt-2 text-xs text-muted-foreground">Any PDF (typed or scanned), Word, Excel, CSV or a photo of the printed quotation. The rates found are filled in below for you to check. The file is kept with the quote.</p>
        {read && (read.available ? (
          <p role="status" className="mt-2 flex flex-wrap items-center gap-2 text-sm"><ScanText className="size-4 text-primary" /> Read: {read.lines_priced} of {read.lines_in_enquiry} items priced{read.low_confidence && <Badge tone="warning">check carefully</Badge>}{(read.unmatched ?? []).length > 0 && <span className="text-muted-foreground">· not matched: {read.unmatched!.slice(0, 3).join('; ')}</span>}</p>
        ) : <p role="status" className="mt-2 text-sm text-muted-foreground">{read.message || 'This file could not be read automatically.'} Type the rates below; the file is still kept with the quote.</p>)}
      </div>

      {/* 2. who and on what terms */}
      <div className="grid gap-4 sm:grid-cols-4">
        <Field label="Supplier" htmlFor="rq-sup" className="sm:col-span-2"><Input id="rq-sup" list="rq-names" value={f.supplier_name} onChange={set('supplier_name')} placeholder="Who sent this quote" /></Field>
        <datalist id="rq-names">{(names.data ?? []).map((n) => <option key={n.name} value={n.name} />)}</datalist>
        <Field label="Their quote no." htmlFor="rq-ref"><Input id="rq-ref" value={f.quote_ref} onChange={set('quote_ref')} /></Field>
        <Field label="Quote date" htmlFor="rq-date"><Input id="rq-date" type="date" value={f.quote_date} onChange={set('quote_date')} /></Field>
        <Field label="Payment terms" htmlFor="rq-terms" className="sm:col-span-2"><Input id="rq-terms" value={f.payment_terms} onChange={set('payment_terms')} placeholder="30 days from delivery" /></Field>
        <Field label="Transport to site (Rs)" htmlFor="rq-freight" hint="Lump sum, if charged"><NumField id="rq-freight" value={freight} onValue={setFreight} /></Field>
        <Field label="Delivery in (days)" htmlFor="rq-days"><NumField id="rq-days" value={days} onValue={setDays} /></Field>
      </div>

      {/* 3. his rates */}
      <div className="overflow-x-auto rounded-lg border border-border">
        <table aria-label="Rates" className="w-full min-w-[520px] text-[13px]">
          <thead className="bg-surface text-left text-xs text-muted-foreground"><tr><th className="px-3 py-2">Item</th><th className="w-32 px-3 py-2 text-right">Rate per unit (Rs)</th><th className="w-24 px-3 py-2 text-right">GST %</th></tr></thead>
          <tbody>{statement.lines.map((l, i) => (
            <tr key={l.rfq_line_id} className="border-t border-border">
              <td className="px-3 py-2">{l.description}<div className="text-xs text-muted-foreground">{l.qty} {l.uom}{l.item_code && ` · ${l.item_code}`}</div></td>
              <td className="px-3 py-2"><NumField aria-label={`Rate ${i + 1}`} value={rates[i].rate} onValue={(n) => edit(i, { rate: n })} /></td>
              <td className="px-3 py-2"><NumField aria-label={`GST ${i + 1}`} value={rates[i].tax} onValue={(n) => edit(i, { tax: n })} /></td>
            </tr>
          ))}</tbody>
        </table>
      </div>

      <div className="flex flex-wrap items-center justify-end gap-2 border-t border-border pt-4">
        {error ? <p role="alert" className="mr-auto text-[13px] text-danger">{error}</p> : <p className="mr-auto text-xs text-muted-foreground">{priced} of {statement.lines.length} items priced. Leave an item at 0 if they did not quote it.</p>}
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button loading={busy} disabled={!f.supplier_name.trim() || priced === 0 || reading} onClick={() => void save()}>Save the quote</Button>
      </div>
    </div>
  )
}
