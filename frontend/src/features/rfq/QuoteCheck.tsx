import { useEffect, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Paperclip } from 'lucide-react'
import { Modal } from '@/components/ui'
import { keepQuoteDocument, QUOTE_FILES, rfqKeys, type RfqSupplier, type Statement } from '@/api/rfq'
import { api, ApiError } from '@/lib/api'
import { formatINR } from '@/lib/utils'
import { toast } from '@/stores/toast'

/** One supplier however the name was typed: case, spacing and full stops aside, as the server's norm_name has it. */
const flatName = (s: string) => (s || '').toLowerCase().replace(/[^a-z0-9]/g, '')
const sameName = (a: string, b: string) => flatName(a) === flatName(b)

interface DocText { name: string; kind: string; text: string; shown_as_is: boolean }

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
      <button type="button" disabled={busy} onClick={() => ref.current?.click()} className="inline-flex items-center gap-1 text-muted-foreground transition-colors hover:text-primary disabled:opacity-50" title="Keep the supplier's own quotation file with this quote"><Paperclip className="size-3.5" />{busy ? 'Attaching...' : 'Attach file'}</button>
    </>
  )
}

/** A quote beside the supplier's own quotation: what was entered on the left, their document on the right, to check by eye. */
export function QuoteCheckModal({ statement, supplier, onClose }: { statement: Statement; supplier: RfqSupplier; onClose: () => void }) {
  const doc = supplier.document!
  const [text, setText] = useState<DocText | 'loading' | 'unreadable'>('loading')
  useEffect(() => {
    api<DocText>(`/api/rfqs/${statement.rfq.id}/quotes/${supplier.quote_id}/document-text`).then(setText).catch(() => setText('unreadable'))
  }, [statement.rfq.id, supplier.quote_id])

  return (
    <Modal open onOpenChange={(o) => !o && onClose()} size="xl" title={`${supplier.supplier_name}: the quote and their quotation`}
      description="What was entered in the app, beside the quotation the supplier sent. Check the rates against the paper.">
      <div className="grid gap-4 lg:grid-cols-2">
        <div className="min-w-0">
          <p className="mb-1.5 text-[13px] font-medium">Entered in the app · {formatINR(supplier.landed)} total at site</p>
          <div className="overflow-x-auto rounded-lg border border-border">
            <table className="w-full text-[13px]">
              <thead className="bg-surface text-left text-xs text-muted-foreground"><tr><th className="px-3 py-2">Item</th><th className="px-3 py-2 text-right">Rate</th></tr></thead>
              <tbody>
                {statement.lines.map((l) => {
                  const o = l.offers.find((x) => sameName(x.supplier_name, supplier.supplier_name))
                  return (
                    <tr key={l.rfq_line_id} className="border-t border-border">
                      <td className="px-3 py-2">{l.description}<div className="text-xs text-muted-foreground">{l.qty} {l.uom}</div></td>
                      <td className="px-3 py-2 text-right tabular">{o ? <>{formatINR(o.rate)}<div className="text-xs text-muted-foreground">GST {o.tax_percent}%</div></> : <span className="text-muted-foreground">-</span>}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
          <p className="mt-2 text-xs text-muted-foreground">Transport: {supplier.freight ? formatINR(supplier.freight) : 'none'} · Payment: {supplier.payment_terms || 'not stated'} · Delivery: {supplier.delivery_days ? `${supplier.delivery_days} days` : 'not stated'}{supplier.quote_ref && ` · Quote no. ${supplier.quote_ref}`}</p>
        </div>
        <div className="min-w-0">
          <p className="mb-1.5 flex items-center justify-between gap-2 text-[13px] font-medium"><span className="truncate">Their quotation · {doc.name}</span><a href={`/api/files/${doc.id}?download=1`} className="shrink-0 text-xs font-normal text-primary hover:underline">Download</a></p>
          {text === 'loading' ? <div className="grid h-[62vh] place-items-center rounded-lg border border-border text-sm text-muted-foreground">Opening their quotation...</div>
            : text === 'unreadable' ? <div className="grid h-[62vh] place-items-center rounded-lg border border-border p-6 text-center text-sm text-muted-foreground">This file cannot be shown here. Download it to read it.</div>
            : text.shown_as_is ? <iframe title="Their quotation" src={`/api/files/${doc.id}`} className="h-[62vh] w-full rounded-lg border border-border bg-white" />
            : <pre className="h-[62vh] overflow-auto whitespace-pre-wrap rounded-lg border border-border bg-surface p-3 font-mono text-[12px] leading-relaxed">{text.text}</pre>}
        </div>
      </div>
    </Modal>
  )
}
