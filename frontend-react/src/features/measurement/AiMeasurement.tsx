import { useState } from 'react'
import { AlertTriangle, ScanText, Sparkles } from 'lucide-react'
import { Badge, Button, Field, Input, Modal, Textarea } from '@/components/ui'
import { analyseBook, askBook, readSheet, type BookAnswer, type MeasurementAnalysis, type ReadSheet } from '@/api/aiMeasurement'
import type { Flag } from '@/api/aiSubcontracts'
import { mbKeys, recordUrl, type MbLine } from '@/api/mb'
import { post } from '@/lib/api'
import { useAction } from '@/lib/mutate'
import { formatDate, formatQty } from '@/lib/format'

const TONE = { stop: 'danger', check: 'warning', note: 'neutral' } as const

/** What the measurement book shows, checked by plain rules and put in words. Nothing is changed. */
export function BookAnalysis({ orderId }: { orderId: number }) {
  const [out, setOut] = useState<MeasurementAnalysis | null>(null)
  const run = useAction(() => analyseBook(orderId), { success: false, onSuccess: setOut })
  return (
    <div className="mb-4 rounded-lg border border-border px-4 py-3 text-[13.5px]">
      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" variant="outline" loading={run.isPending} onClick={() => run.mutate()}><Sparkles /> Analyse the book</Button>
        {!out && <span className="text-muted-foreground">Looks for over-measured items, double entries, odd quantities and work running behind time.</span>}
      </div>
      {out && (
        <div aria-label="Measurement analysis" className="mt-3 grid gap-2">
          <p className="text-muted-foreground">{out.work_percent ?? 0}% of the order&apos;s value measured{out.time_percent != null && ` with ${out.time_percent}% of the time gone`}.</p>
          {out.summary && <p>{out.summary}</p>}
          {!out.available && out.message && <p className="text-muted-foreground">{out.message}</p>}
          {out.findings.length === 0 ? <p className="text-muted-foreground">Nothing looks wrong in the book.</p> : (
            <ul className="grid gap-1">{out.findings.map((f) => <li key={f.text} className="flex items-start gap-2"><Badge tone={TONE[f.level]}>{f.level}</Badge><span>{f.text}</span></li>)}</ul>
          )}
        </div>
      )}
      <AskBook orderId={orderId} />
    </div>
  )
}

const QUESTIONS = ['Which items are behind?', 'Anything that looks like a mistake?', 'What is left to measure?']

/** A question put to the book in plain words, answered from its own figures. */
function AskBook({ orderId }: { orderId: number }) {
  const [q, setQ] = useState('')
  const [answer, setAnswer] = useState<BookAnswer | null>(null)
  const go = useAction((question: string) => askBook(orderId, question), { success: false, onSuccess: setAnswer })
  const ask = (question: string) => { if (question.trim()) { setQ(question); go.mutate(question) } }
  return (
    <div className="mt-3 border-t border-border pt-3">
      <form className="flex flex-wrap items-center gap-2" onSubmit={(e) => { e.preventDefault(); ask(q) }}>
        <Input aria-label="Ask about this book" className="h-9 min-w-56 flex-1" placeholder="Ask about this book, e.g. which items are behind?" value={q} onChange={(e) => setQ(e.target.value)} />
        <Button size="sm" type="submit" variant="outline" loading={go.isPending} disabled={!q.trim()}>Ask</Button>
      </form>
      <div className="mt-2 flex flex-wrap gap-1.5">{QUESTIONS.map((s) => <button key={s} type="button" className="rounded-full border border-border px-2.5 py-0.5 text-xs text-muted-foreground hover:text-foreground" onClick={() => ask(s)}>{s}</button>)}</div>
      {answer && <p aria-label="Answer" className="mt-2 text-sm">{answer.available ? answer.answer : <span className="text-muted-foreground">{answer.message}</span>}</p>}
    </div>
  )
}

/** A mark on an entry the plain checks find odd, with the reason on hover and for a screen reader. */
export function EntryFlag({ flags }: { flags?: Flag[] }) {
  if (!flags?.length) return null
  const text = flags.map((f) => f.text).join(' ')
  return <span title={text} aria-label={`Check this entry: ${text}`} className={flags.some((f) => f.level === 'stop' || f.level === 'check') ? 'text-warning' : 'text-muted-foreground'}><AlertTriangle className="size-4" /></span>
}

/** Choose a photo or PDF of a site sheet, or paste it. The rows it reads are shown for checking; they are added only on the button. */
export function ReadSheetModal({ orderId, lines, open, onClose }: { orderId: number; lines: MbLine[]; open: boolean; onClose: () => void }) {
  const [text, setText] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [read, setRead] = useState<ReadSheet | null>(null)
  const go = useAction(() => readSheet(orderId, { text, file }), { success: false, onSuccess: setRead })
  const label = (id: number) => {
    const l = lines.find((x) => x.item_id === id)
    return l ? `${l.activity_no} ${l.description}`.trim() : `item ${id}`
  }
  const add = useAction(
    async () => {
      const rows = read?.rows ?? []
      for (const r of rows) await post(recordUrl(orderId), { item_id: r.item_id, quantity: r.quantity, location: r.location, measured_on: r.measured_on || undefined, remarks: r.remarks })
      return { message: `${rows.length} measurements added to the book.` }
    },
    { invalidate: [mbKeys.all, ['subbills']], onSuccess: () => { setRead(null); setText(''); setFile(null); onClose() } },
  )
  return (
    <Modal open={open} onOpenChange={(o) => !o && onClose()} size="lg" title="Read a measurement sheet" description="Choose a photo or PDF of the site sheet, or paste it. Check the rows before adding them to the book.">
      <div className="grid gap-4">
        <Field label="Sheet text" htmlFor="ms-text"><Textarea id="ms-text" rows={4} value={text} onChange={(e) => setText(e.target.value)} placeholder="Paste the measurements here" /></Field>
        <Field label="Or a photo or PDF" htmlFor="ms-file"><input id="ms-file" type="file" accept=".pdf,image/*" onChange={(e) => setFile(e.target.files?.[0] ?? null)} /></Field>
        <div><Button loading={go.isPending} disabled={!text.trim() && !file} onClick={() => go.mutate()}><ScanText /> Read it</Button></div>
        {read && (!read.available ? <p role="alert" className="text-sm text-muted-foreground">{read.message}</p> : (
          <div aria-label="Rows read" className="grid gap-2 text-sm">
            {read.low_confidence && <Badge tone="warning">not confident - check every row</Badge>}
            <ul>{(read.rows ?? []).map((r, i) => <li key={i}>{label(r.item_id)}: {formatQty(r.quantity)}{r.location && ` at ${r.location}`}{r.measured_on && ` on ${formatDate(r.measured_on)}`}</li>)}</ul>
            {(read.unmatched ?? []).length > 0 && <p className="text-muted-foreground">Not matched to any item: {read.unmatched!.join('; ')}</p>}
            <div><Button loading={add.isPending} disabled={!read.rows?.length} onClick={() => add.mutate()}>Add {read.rows?.length ?? 0} to the book</Button></div>
          </div>
        ))}
      </div>
    </Modal>
  )
}
