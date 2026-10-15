import { useEffect, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Paperclip, ScanText } from 'lucide-react'
import { Badge, Button, Modal } from '@/components/ui'
import { keepQuoteDocument, QUOTE_FILES, rfqKeys, type RfqSupplier, type Statement } from '@/api/rfq'
import { api, ApiError } from '@/lib/api'
import { cn, formatINR } from '@/lib/utils'
import { toast } from '@/stores/toast'

interface CheckRow { rfq_line_id: number; item: string; uom: string; qty: number; entered_rate: number | null; paper_rate: number | null; entered_tax: number | null; paper_tax: number | null; status: 'agrees' | 'differs' | 'only_entered' | 'only_paper' | 'not_quoted' }
interface CheckResult {
  available: boolean; message?: string
  rows?: CheckRow[]; terms?: { item: string; entered: number | string; paper: number | string; status: 'agrees' | 'differs' }[]
  differences?: number; agrees?: boolean; unmatched?: string[]; low_confidence?: boolean
}
interface DocText { name: string; kind: string; text: string; shown_as_is: boolean }

const STATUS: Record<CheckRow['status'], { label: string; tone: 'success' | 'danger' | 'warning' | 'neutral' }> = {
  agrees: { label: 'Agrees', tone: 'success' },
  differs: { label: 'Differs', tone: 'danger' },
  only_entered: { label: 'Not on their quote', tone: 'warning' },
  only_paper: { label: 'Not entered', tone: 'warning' },
  not_quoted: { label: 'Not quoted', tone: 'neutral' },
}
const money = (n: number | null) => (n == null ? '-' : formatINR(n))

/** Keep the supplier's quotation with a quote that has none yet. */
export function AttachQuotation({ statement, supplier }: { statement: Statement; supplier: RfqSupplier }) {
  const qc = useQueryClient()
  const ref = useRef<HTMLInputElement>(null)
  const [busy, setBusy] = useState(false)
  const put = async (file: File | null) => {
    if (!file) return
    setBusy(true)
    try {
      const out = await keepQuoteDocument(statement.rfq.id, supplier.quote_id, file)
      toast.success(out.message)
      await qc.invalidateQueries({ queryKey: rfqKeys.all })
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : 'The file could not be kept.')
    } finally {
      setBusy(false)
    }
  }
  return (
    <>
      <input ref={ref} type="file" hidden accept={QUOTE_FILES} aria-label={`${supplier.supplier_name}'s quotation`} onChange={(e) => { void put(e.target.files?.[0] ?? null); e.target.value = '' }} />
      <button type="button" disabled={busy} onClick={() => ref.current?.click()} className="inline-flex items-center gap-0.5 text-primary hover:underline disabled:opacity-50"><Paperclip className="size-3" />{busy ? 'Attaching...' : 'Attach their quote'}</button>
    </>
  )
}

/**
 * A quote beside the supplier's own quotation, as an RA bill is read beside its hard copy: what was entered on the
 * left, their document on the right, and a check that reads the document and compares it item by item. The reading
 * is the AI's; the comparison is plain arithmetic, so every difference shown can be checked against the paper.
 */
export function QuoteCheckModal({ statement, supplier, onClose }: { statement: Statement; supplier: RfqSupplier; onClose: () => void }) {
  const doc = supplier.document!
  const [text, setText] = useState<DocText | 'loading' | 'unreadable'>('loading')
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<CheckResult | null>(null)
  useEffect(() => {
    api<DocText>(`/api/rfqs/${statement.rfq.id}/quotes/${supplier.quote_id}/document-text`).then(setText).catch(() => setText('unreadable'))
  }, [statement.rfq.id, supplier.quote_id])
  const check = async () => {
    setBusy(true)
    try {
      setResult(await api<CheckResult>(`/api/ai/rfqs/${statement.rfq.id}/quotes/${supplier.quote_id}/check`, { method: 'POST' }))
    } catch (e) {
      setResult({ available: false, message: e instanceof ApiError ? e.message : 'The check could not be done. Try again.' })
    } finally {
      setBusy(false)
    }
  }
  const byLine = new Map((result?.rows ?? []).map((r) => [r.rfq_line_id, r]))

  return (
    <Modal open onOpenChange={(o) => !o && onClose()} size="xl" title={`${supplier.supplier_name}: the quote and their quotation`}
      description="What was entered in the app, beside the quotation the supplier sent. Check the figures to compare them item by item.">
      <div className="grid gap-4">
        <div className="flex flex-wrap items-center gap-3">
          <Button loading={busy} onClick={() => void check()}><ScanText /> Check the figures</Button>
          {result?.available && (result.agrees
            ? <Badge tone="success" dot>Everything agrees</Badge>
            : <Badge tone="danger" dot>{result.differences} {result.differences === 1 ? 'difference' : 'differences'}</Badge>)}
          {result?.available && result.low_confidence && <Badge tone="warning">The document was hard to read: look closely</Badge>}
          {result && !result.available && <span className="text-sm text-muted-foreground">{result.message || 'The document could not be read automatically. Compare it by eye below.'}</span>}
        </div>

        <div className="grid gap-4 lg:grid-cols-2">
          {/* what was entered, marked against the paper once checked */}
          <div className="min-w-0">
            <p className="mb-1.5 text-[13px] font-medium">Entered in the app · {formatINR(supplier.landed)} total at site</p>
            <div className="overflow-x-auto rounded-lg border border-border">
              <table className="w-full text-[13px]">
                <thead className="bg-surface text-left text-xs text-muted-foreground">
                  <tr><th className="px-3 py-2">Item</th><th className="px-3 py-2 text-right">Entered</th>{result?.available && <th className="px-3 py-2 text-right">Their quote</th>}{result?.available && <th className="px-3 py-2" />}</tr>
                </thead>
                <tbody>
                  {statement.lines.map((l) => {
                    const o = l.offers.find((x) => x.supplier_name === supplier.supplier_name)
                    const r = byLine.get(l.rfq_line_id)
                    return (
                      <tr key={l.rfq_line_id} className={cn('border-t border-border', r?.status === 'differs' && 'bg-danger/[0.06]', (r?.status === 'only_entered' || r?.status === 'only_paper') && 'bg-warning/[0.06]')}>
                        <td className="px-3 py-2">{l.description}<div className="text-xs text-muted-foreground">{l.qty} {l.uom}</div></td>
                        <td className="px-3 py-2 text-right tabular">{o ? <>{formatINR(o.rate)}<div className="text-xs text-muted-foreground">{o.tax_percent}% GST</div></> : <span className="text-muted-foreground">-</span>}</td>
                        {result?.available && <td className="px-3 py-2 text-right tabular">{r?.paper_rate != null ? <>{money(r.paper_rate)}<div className="text-xs text-muted-foreground">{r.paper_tax != null ? `${r.paper_tax}% GST` : 'GST not stated'}</div></> : <span className="text-muted-foreground">-</span>}</td>}
                        {result?.available && <td className="px-3 py-2">{r && <Badge tone={STATUS[r.status].tone}>{STATUS[r.status].label}</Badge>}</td>}
                      </tr>
                    )
                  })}
                  {(result?.terms ?? []).map((t) => (
                    <tr key={t.item} className={cn('border-t border-border', t.status === 'differs' && 'bg-danger/[0.06]')}>
                      <td className="px-3 py-2">{t.item}</td>
                      <td className="px-3 py-2 text-right tabular">{typeof t.entered === 'number' && t.item.startsWith('Transport') ? formatINR(t.entered) : String(t.entered)}</td>
                      <td className="px-3 py-2 text-right tabular">{typeof t.paper === 'number' && t.item.startsWith('Transport') ? formatINR(t.paper) : String(t.paper)}</td>
                      <td className="px-3 py-2"><Badge tone={t.status === 'agrees' ? 'success' : 'danger'}>{t.status === 'agrees' ? 'Agrees' : 'Differs'}</Badge></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {(result?.unmatched ?? []).length > 0 && <p className="mt-2 text-[13px] text-muted-foreground"><strong className="text-foreground">On their quote but not in the enquiry:</strong> {result!.unmatched!.join('; ')}</p>}
            <p className="mt-2 text-xs text-muted-foreground">Payment: {supplier.payment_terms || 'not stated'} · Delivery: {supplier.delivery_days ? `${supplier.delivery_days} days` : 'not stated'}{supplier.quote_ref && ` · Quote no. ${supplier.quote_ref}`}</p>
          </div>

          {/* their document, as it is where the browser can show it, else its text */}
          <div className="min-w-0">
            <p className="mb-1.5 flex items-center justify-between gap-2 text-[13px] font-medium"><span className="truncate">Their quotation · {doc.name}</span><a href={`/api/files/${doc.id}?download=1`} className="shrink-0 text-xs font-normal text-primary hover:underline">Download</a></p>
            {text === 'loading' ? <div className="grid h-[62vh] place-items-center rounded-lg border border-border text-sm text-muted-foreground">Opening their quotation...</div>
              : text === 'unreadable' ? <div className="grid h-[62vh] place-items-center rounded-lg border border-border p-6 text-center text-sm text-muted-foreground">This file cannot be shown here. Download it to read it.</div>
              : text.shown_as_is ? <iframe title="Their quotation" src={`/api/files/${doc.id}`} className="h-[62vh] w-full rounded-lg border border-border bg-white" />
              : <pre className="h-[62vh] overflow-auto whitespace-pre-wrap rounded-lg border border-border bg-surface p-3 font-mono text-[12px] leading-relaxed">{text.text}</pre>}
          </div>
        </div>
      </div>
    </Modal>
  )
}
