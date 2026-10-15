import { useEffect, useRef, useState } from 'react'
import { CheckCircle2, FileUp, Loader2, ScanText, X } from 'lucide-react'
import { Badge, Button, Field, Input, Textarea } from '@/components/ui'
import { QUOTE_FILES, vendorQuotePage, vendorReadQuote, vendorSendQuote, type VendorQuotePage as Page } from '@/api/rfq'
import { ApiError } from '@/lib/api'
import { formatDate } from '@/lib/format'

interface Row { rate: string; tax: string; remarks: string }

/**
 * The page a supplier's link opens, on their phone, with no login: the items and quantities asked for, and their
 * answer. They upload their quotation as they have it - any PDF, Word, Excel or a photo - and the rates are filled in
 * for them to check; or they type them. They can send again until the company decides.
 */
export default function VendorQuotePage() {
  const token = new URLSearchParams(window.location.search).get('token') || ''
  const [page, setPage] = useState<Page | null>(null)
  const [fatal, setFatal] = useState(token ? '' : 'This link is not complete. Ask the company to send it again.')
  const [rows, setRows] = useState<Row[]>([])
  const [terms, setTerms] = useState({ quote_ref: '', valid_until: '', delivery_days: '', freight: '', payment_terms: '', message: '' })
  const fileRef = useRef<HTMLInputElement>(null)
  const [file, setFile] = useState<File | null>(null)
  const [reading, setReading] = useState(false)
  const [readNote, setReadNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [sent, setSent] = useState('')

  useEffect(() => {
    if (!token) return
    vendorQuotePage(token)
      .then((p) => {
        setPage(p)
        setRows(p.lines.map((l) => ({ rate: l.rate ? String(l.rate) : '', tax: l.tax_percent != null ? String(l.tax_percent) : '18', remarks: l.remarks || '' })))
        if (p.answer) setTerms({ quote_ref: p.answer.quote_ref, valid_until: p.answer.valid_until, delivery_days: p.answer.delivery_days ? String(p.answer.delivery_days) : '',
          freight: p.answer.freight ? String(p.answer.freight) : '', payment_terms: p.answer.payment_terms, message: '' })
      })
      .catch((e) => setFatal(e instanceof ApiError && e.status !== 404 ? e.message : 'This link is not valid any more. Ask the company for a new one.'))
  }, [token])

  const setRow = (i: number, k: keyof Row, v: string) => setRows((r) => r.map((x, j) => (j === i ? { ...x, [k]: v } : x)))
  const setTerm = (k: keyof typeof terms) => (e: { target: { value: string } }) => setTerms((t) => ({ ...t, [k]: e.target.value }))

  const choose = async (picked: File | null) => {
    setFile(picked)
    setReadNote('')
    setError('')
    if (!picked || !page?.can_read) return
    setReading(true)
    try {
      const r = await vendorReadQuote(token, picked)
      if (!r.available) { setReadNote(r.message || 'Your file could not be read automatically. Type the rates below, or just send the file.'); return }
      setRows((old) => page.lines.map((l, i) => {
        const got = r.lines?.find((x) => x.rfq_line_id === l.rfq_line_id)
        return got ? { rate: String(got.rate), tax: got.tax_percent != null ? String(got.tax_percent) : old[i].tax, remarks: got.remarks || old[i].remarks } : old[i]
      }))
      setTerms((t) => ({ ...t, quote_ref: r.quote_ref || t.quote_ref, valid_until: r.valid_until || t.valid_until,
        delivery_days: r.delivery_days ? String(r.delivery_days) : t.delivery_days, freight: r.freight ? String(r.freight) : t.freight, payment_terms: r.payment_terms || t.payment_terms }))
      setReadNote(`We filled ${r.lines_priced ?? 0} of ${r.lines_in_enquiry ?? page.lines.length} rates from your file${r.low_confidence ? '. Some may be wrong' : ''}. Please check each one before sending.`)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Your file could not be read. Type the rates, or send the file as it is.')
    } finally {
      setReading(false)
    }
  }

  const send = async () => {
    if (!page) return
    setBusy(true)
    setError('')
    try {
      const out = await vendorSendQuote(token, {
        ...terms, delivery_days: Number(terms.delivery_days) || 0, freight: Number(terms.freight) || 0,
        lines: page.lines.map((l, i) => ({ rfq_line_id: l.rfq_line_id, rate: Number(rows[i].rate) || 0, tax_percent: rows[i].tax === '' ? null : Number(rows[i].tax), remarks: rows[i].remarks })),
      }, file)
      setSent(out.message)
      window.scrollTo({ top: 0, behavior: 'smooth' })
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Your quote could not be sent. Check your connection and try again.')
    } finally {
      setBusy(false)
    }
  }

  if (fatal) return <Shell><p role="alert" className="rounded-lg border border-danger/40 bg-danger/10 p-4 text-sm text-danger">{fatal}</p></Shell>
  if (!page) return <Shell><p className="flex items-center gap-2 text-sm text-muted-foreground"><Loader2 className="size-4 animate-spin" /> Opening the enquiry...</p></Shell>

  const priced = rows.filter((r) => Number(r.rate) > 0).length
  return (
    <Shell company={page.company}>
      <header className="mb-5">
        <p className="text-xs font-semibold uppercase tracking-[0.14em] text-primary">Request for quotation · {page.rfq.number}</p>
        <h1 className="mt-1 text-xl font-semibold sm:text-2xl">{page.rfq.title}</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          {[page.rfq.project, page.rfq.site].filter(Boolean).join(' · ')}{page.rfq.needed_by && <> · needed by <strong className="text-foreground">{formatDate(page.rfq.needed_by)}</strong></>}
        </p>
        <p className="mt-2 text-sm">Quoting as <strong>{page.supplier_name}</strong></p>
        {page.rfq.notes && <p className="mt-2 whitespace-pre-line rounded-lg bg-muted/50 p-3 text-sm">{page.rfq.notes}</p>}
      </header>

      {sent && <p role="status" className="mb-5 flex items-start gap-2 rounded-lg border border-success/40 bg-success/10 p-4 text-sm"><CheckCircle2 className="mt-0.5 size-4 shrink-0 text-success" />{sent}</p>}
      {!page.open && <p role="alert" className="mb-5 rounded-lg border border-warning/40 bg-warning/10 p-4 text-sm">This enquiry is closed. Thank you, no more quotes are being taken.</p>}
      {page.submitted_at && !sent && page.open && <p className="mb-5 rounded-lg border border-info/40 bg-info/10 p-3 text-sm">You sent a quote on {formatDate(page.submitted_at.slice(0, 10))}. Change anything below and send again to revise it.</p>}

      {page.open && (
        <section className="mb-5 rounded-xl border border-dashed border-border bg-surface/50 p-4">
          <h2 className="text-sm font-semibold">1. Upload your quotation (optional)</h2>
          <p className="mt-1 text-xs text-muted-foreground">In any form you have it: PDF (typed or scanned), Word, Excel, or a photo of the printed page.{page.can_read && ' We will fill in your rates from it for you to check.'}</p>
          <div className="mt-3 flex flex-wrap items-center gap-3">
            <input ref={fileRef} type="file" accept={QUOTE_FILES} className="hidden" aria-label="Your quotation file" onChange={(e) => void choose(e.target.files?.[0] ?? null)} />
            <Button variant="outline" onClick={() => fileRef.current?.click()} disabled={reading}><FileUp /> {file ? 'Choose another file' : 'Choose your file'}</Button>
            {file && <span className="inline-flex items-center gap-1.5 text-sm">{file.name}<button type="button" aria-label="Remove the file" onClick={() => { setFile(null); setReadNote(''); if (fileRef.current) fileRef.current.value = '' }}><X className="size-3.5" /></button></span>}
            {reading && <span className="inline-flex items-center gap-1.5 text-sm text-muted-foreground"><Loader2 className="size-4 animate-spin" /> Reading your rates...</span>}
          </div>
          {readNote && <p role="status" className="mt-2 flex items-start gap-2 text-sm"><ScanText className="mt-0.5 size-4 shrink-0 text-primary" />{readNote}</p>}
          {page.document_sent && !file && <p className="mt-2 text-xs text-muted-foreground">Your file from before is already with them.</p>}
        </section>
      )}

      <section className="mb-5">
        <h2 className="mb-2 text-sm font-semibold">{page.open ? '2. Your rates' : 'The items'}</h2>
        <ul className="grid gap-2">
          {page.lines.map((l, i) => (
            <li key={l.rfq_line_id} className="rounded-xl border border-border p-3">
              <div className="flex flex-wrap items-baseline justify-between gap-x-3">
                <span className="font-medium">{l.description}</span>
                <span className="text-sm text-muted-foreground">{l.qty} {l.uom}{l.item_code && ` · ${l.item_code}`}</span>
              </div>
              {page.open && (
                <div className="mt-2 grid grid-cols-[1fr_88px] gap-2 sm:grid-cols-[180px_100px_1fr]">
                  <Field label={`Rate (Rs / ${l.uom || 'unit'})`} htmlFor={`vq-r${i}`}><Input id={`vq-r${i}`} inputMode="decimal" value={rows[i]?.rate ?? ''} onChange={(e) => setRow(i, 'rate', e.target.value)} placeholder="0" /></Field>
                  <Field label="GST %" htmlFor={`vq-t${i}`}><Input id={`vq-t${i}`} inputMode="decimal" value={rows[i]?.tax ?? ''} onChange={(e) => setRow(i, 'tax', e.target.value)} /></Field>
                  <Field label="Note (optional)" htmlFor={`vq-n${i}`} className="col-span-2 sm:col-span-1"><Input id={`vq-n${i}`} value={rows[i]?.remarks ?? ''} onChange={(e) => setRow(i, 'remarks', e.target.value)} placeholder="Brand, make, or 'not available'" /></Field>
                </div>
              )}
            </li>
          ))}
        </ul>
      </section>

      {page.open && (
        <>
          <section className="mb-5">
            <h2 className="mb-2 text-sm font-semibold">3. Your terms</h2>
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Your quotation no." htmlFor="vq-ref"><Input id="vq-ref" value={terms.quote_ref} onChange={setTerm('quote_ref')} /></Field>
              <Field label="Prices valid until" htmlFor="vq-valid"><Input id="vq-valid" type="date" value={terms.valid_until} onChange={setTerm('valid_until')} /></Field>
              <Field label="Delivery in (days)" htmlFor="vq-days"><Input id="vq-days" inputMode="numeric" value={terms.delivery_days} onChange={setTerm('delivery_days')} /></Field>
              <Field label="Transport to site (Rs, if charged)" htmlFor="vq-freight"><Input id="vq-freight" inputMode="decimal" value={terms.freight} onChange={setTerm('freight')} /></Field>
              <Field label="Payment terms" htmlFor="vq-pay" className="sm:col-span-2"><Input id="vq-pay" value={terms.payment_terms} onChange={setTerm('payment_terms')} placeholder="30 days from delivery" /></Field>
              <Field label="Message to the company (optional)" htmlFor="vq-msg" className="sm:col-span-2"><Textarea id="vq-msg" rows={2} value={terms.message} onChange={setTerm('message')} /></Field>
            </div>
          </section>
          <div className="sticky bottom-0 -mx-4 border-t border-border bg-card/95 px-4 py-3 backdrop-blur sm:static sm:mx-0 sm:border-0 sm:bg-transparent sm:px-0">
            {error && <p role="alert" className="mb-2 text-sm text-danger">{error}</p>}
            <div className="flex flex-wrap items-center gap-3">
              <Button size="lg" loading={busy} disabled={reading || (priced === 0 && !file)} onClick={() => void send()}>{page.submitted_at ? 'Send my revised quote' : 'Send my quote'}</Button>
              <span className="text-xs text-muted-foreground">{priced} of {page.lines.length} rates filled{priced === 0 && file ? ' · your file will be sent for them to read' : ''}</span>
            </div>
          </div>
        </>
      )}
    </Shell>
  )
}

function Shell({ company, children }: { company?: string; children: React.ReactNode }) {
  return (
    <main className="min-h-screen bg-background px-4 py-6 sm:py-10">
      <div className="mx-auto w-full max-w-3xl">
        {company && <p className="mb-4 flex items-center gap-2 text-sm font-semibold"><Badge tone="neutral">{company}</Badge></p>}
        <div className="rounded-2xl border border-border bg-card p-4 shadow-card sm:p-6">{children}</div>
        <p className="mt-4 text-center text-xs text-muted-foreground">Only the items asked for are shown here; other suppliers cannot see your prices.</p>
      </div>
    </main>
  )
}
