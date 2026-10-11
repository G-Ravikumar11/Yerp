import { useState } from 'react'
import { ScanText, Sparkles } from 'lucide-react'
import { Badge, Button, Field, Modal, Textarea } from '@/components/ui'
import { readQuote, recommendQuote, type QuoteRecommendation, type ReadQuote } from '@/api/aiPurchasing'
import type { Statement } from '@/api/rfq'
import { useAction } from '@/lib/mutate'
import { formatINR } from '@/lib/utils'

const TONE = { stop: 'danger', check: 'warning', note: 'neutral' } as const

/** A written recommendation on the quotes in hand, and a reader that turns a supplier's quote into the quote form. The buyer awards. */
export function Recommendation({ id }: { id: number }) {
  const [rec, setRec] = useState<QuoteRecommendation | null>(null)
  const run = useAction(() => recommendQuote(id), { success: false, onSuccess: setRec })
  return (
    <div className="border-b border-border px-5 py-3 text-[13.5px]">
      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" variant="outline" loading={run.isPending} onClick={() => run.mutate()}><Sparkles /> Recommend</Button>
        {!rec && <span className="text-muted-foreground">Flags problems with the quotes and suggests who to award. You decide.</span>}
      </div>
      {rec && (
        <div aria-label="Recommendation" className="mt-3 grid gap-2">
          {rec.recommendation && <p>{rec.recommendation}</p>}
          {rec.ai_message && <p className="text-muted-foreground">{rec.ai_message}</p>}
          {rec.flags.length === 0 ? <p className="text-muted-foreground">No problems found with the quotes.</p> : (
            <ul className="grid gap-1">{rec.flags.map((f) => <li key={f.text} className="flex items-start gap-2"><Badge tone={TONE[f.level]}>{f.level}</Badge><span>{f.text}</span></li>)}</ul>
          )}
        </div>
      )}
    </div>
  )
}

/** Paste a quote or choose its file; the figures it reads are shown, then handed to the quote form to check and save. */
export function ReadQuoteModal({ statement, open, onClose, onUse }: { statement: Statement; open: boolean; onClose: () => void; onUse: (q: ReadQuote) => void }) {
  const [text, setText] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [read, setRead] = useState<ReadQuote | null>(null)
  const go = useAction(() => readQuote(statement.rfq.id, { text, file }), { success: false, onSuccess: setRead })
  const name = (id: number) => statement.lines.find((l) => l.rfq_line_id === id)?.description ?? `line ${id}`
  return (
    <Modal open={open} onOpenChange={(o) => !o && onClose()} size="lg" title="Read a quote" description="Paste the quotation or choose its file. Nothing is saved until you check it in the quote form.">
      <div className="grid gap-4">
        <Field label="Quotation text" htmlFor="rd-text"><Textarea id="rd-text" rows={5} value={text} onChange={(e) => setText(e.target.value)} placeholder="Paste the supplier's quotation here" /></Field>
        <Field label="Or a PDF or photo" htmlFor="rd-file" hint="A photo or a PDF with typed text is read. A scanned PDF: upload it as a photo."><input id="rd-file" type="file" accept=".pdf,image/*" onChange={(e) => setFile(e.target.files?.[0] ?? null)} /></Field>
        <div><Button loading={go.isPending} disabled={!text.trim() && !file} onClick={() => go.mutate()}><ScanText /> Read it</Button></div>
        {read && (!read.available ? <p role="alert" className="text-sm text-muted-foreground">{read.message}</p> : (
          <div aria-label="What was read" className="grid gap-2 text-sm">
            <p><strong>{read.supplier_name || 'Supplier not stated'}</strong> {read.quote_ref && `· ${read.quote_ref}`} · priced {read.lines_priced} of {read.lines_in_enquiry} lines {read.low_confidence && <Badge tone="warning">not confident</Badge>}</p>
            <ul>{(read.lines ?? []).map((l) => <li key={l.rfq_line_id}>{name(l.rfq_line_id)}: {formatINR(l.rate)}{l.tax_percent != null && ` + ${l.tax_percent}% tax`}</li>)}</ul>
            {(read.unmatched ?? []).length > 0 && <p className="text-muted-foreground">Not matched to any line: {read.unmatched!.join('; ')}</p>}
            <div><Button onClick={() => onUse(read)} disabled={!read.lines?.length}>Fill the quote form</Button></div>
          </div>
        ))}
      </div>
    </Modal>
  )
}
