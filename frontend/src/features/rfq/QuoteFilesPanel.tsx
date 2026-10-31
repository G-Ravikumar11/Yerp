import { useRef, useState } from 'react'
import { Columns3, ExternalLink, FileText, Trash2, Upload, X } from 'lucide-react'
import { Button, ConfirmDialog, Field, Input } from '@/components/ui'
import { addQuoteFile, QUOTE_FILES, quoteFileKeys, removeQuoteFile, useQuoteFiles, useQuoteFileText, type QuoteFile } from '@/api/rfq'
import { useAction } from '@/lib/mutate'
import { formatDate } from '@/lib/format'
import { cn } from '@/lib/utils'
import { QuoteFileLink } from './QuoteFileLink'

const MAX_SIDE_BY_SIDE = 4
const shownAsIs = (f: QuoteFile) => f.content_type === 'application/pdf' || f.content_type.startsWith('image/')
const sizeText = (n: number) => (n >= 1024 * 1024 ? `${(n / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`)

/**
 * Suppliers' quotations that came by email or by hand, kept here on their own - no enquiry needed. Tick two or more
 * and they open side by side, to be compared by eye. Nothing is read from them into rates.
 */
export function QuoteFilesPanel() {
  const q = useQuoteFiles()
  const files = q.data?.files ?? []
  const [supplier, setSupplier] = useState('')
  const [chosen, setChosen] = useState<File[]>([])
  const inputRef = useRef<HTMLInputElement>(null)
  const [picked, setPicked] = useState<number[]>([])
  const [side, setSide] = useState(false)
  const [removing, setRemoving] = useState<QuoteFile | null>(null)

  // Several files at once are kept one after the other, each under the supplier's name typed (or its own file name).
  const add = useAction(
    async () => {
      for (const f of chosen) await addQuoteFile(f, supplier.trim() || f.name.replace(/\.[^.]+$/, ''))
      return { message: chosen.length === 1 ? `${chosen[0].name} kept.` : `${chosen.length} files kept.` }
    },
    {
      invalidate: [quoteFileKeys.all],
      onSuccess: () => {
        setChosen([])
        setSupplier('')
        if (inputRef.current) inputRef.current.value = ''
      },
    },
  )
  const remove = useAction((f: QuoteFile) => removeQuoteFile(f.id).then(() => ({ message: `${f.name} removed.` })), {
    invalidate: [quoteFileKeys.all],
    onSuccess: () => {
      setPicked((p) => p.filter((id) => id !== removing?.id))
      setRemoving(null)
    },
  })
  const toggle = (id: number) => setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : p.length >= MAX_SIDE_BY_SIDE ? p : [...p, id]))
  const sideFiles = picked.map((id) => files.find((f) => f.id === id)).filter((f): f is QuoteFile => !!f)

  if (side && sideFiles.length >= 2) return <SideBySide files={sideFiles} onClose={() => setSide(false)} />

  return (
    <div className="grid gap-5">
      <div className="rounded-xl border border-border bg-card p-4 shadow-card">
        <p className="font-medium">Add quotation files</p>
        <p className="mt-0.5 text-[13px] text-muted-foreground">A supplier's quotation as it came - PDF, Excel, Word or a photo. Kept here to open side by side; no enquiry needed.</p>
        <div className="mt-3 grid gap-3 sm:grid-cols-[1fr_1.3fr_auto] sm:items-end">
          <Field label="Supplier" htmlFor="qf-supplier">
            <Input id="qf-supplier" value={supplier} onChange={(e) => setSupplier(e.target.value)} placeholder="Ramco Depot (or leave it to the file name)" />
          </Field>
          <Field label="Files" htmlFor="qf-file">
            <Input id="qf-file" ref={inputRef} type="file" multiple accept={QUOTE_FILES} onChange={(e) => setChosen([...(e.target.files ?? [])])} className="pt-1.5" />
          </Field>
          <Button loading={add.isPending} disabled={!chosen.length} onClick={() => add.mutate()}><Upload /> Add {chosen.length > 1 ? `${chosen.length} files` : 'file'}</Button>
        </div>
        {add.error && <p role="alert" className="mt-2 text-[13px] text-danger">{add.error.message}</p>}
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-muted-foreground">
          {files.length === 0 ? '' : picked.length === 0 ? `Tick the files to compare - at least two, up to ${MAX_SIDE_BY_SIDE}.` : picked.length === 1 ? 'Tick one more to compare.' : `${picked.length} ticked.`}
        </p>
        <Button disabled={picked.length < 2} onClick={() => setSide(true)}><Columns3 /> Compare side by side</Button>
      </div>

      {q.isPending ? <p className="py-8 text-center text-sm text-muted-foreground">Loading...</p>
        : files.length === 0 ? <p className="rounded-xl border border-dashed border-border py-10 text-center text-sm text-muted-foreground">No quotation files yet. Add the first one above.</p>
        : (
          <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {files.map((f) => {
              const on = picked.includes(f.id)
              const full = !on && picked.length >= MAX_SIDE_BY_SIDE
              return (
                <li key={f.id} className={cn('flex gap-3 rounded-xl border bg-card p-3.5 shadow-card transition-colors', on ? 'border-primary ring-1 ring-primary/40' : 'border-border')}>
                  <input type="checkbox" aria-label={`Compare ${f.name}`} className="mt-1 size-4 shrink-0 accent-[var(--primary)]" checked={on} disabled={full} title={full ? `Up to ${MAX_SIDE_BY_SIDE} side by side` : undefined} onChange={() => toggle(f.id)} />
                  <div className="min-w-0 flex-1">
                    <p className="truncate font-medium">{f.supplier_name || f.name}</p>
                    <p className="flex items-center gap-1 truncate text-xs text-muted-foreground"><FileText className="size-3.5 shrink-0" /> {f.name} · {sizeText(f.size)}</p>
                    <p className="mt-0.5 text-xs text-muted-foreground">Added {formatDate(f.added_at.slice(0, 10))}{f.added_by ? ` by ${f.added_by}` : ''}</p>
                    <QuoteFileLink f={f} />
                  </div>
                  <div className="flex shrink-0 flex-col gap-1">
                    <a href={f.url} target="_blank" rel="noreferrer" aria-label={`Open ${f.name}`} title="Open" className="grid size-8 place-items-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground"><ExternalLink className="size-4" /></a>
                    <button type="button" aria-label={`Remove ${f.name}`} title="Remove" onClick={() => setRemoving(f)} className="grid size-8 place-items-center rounded-md text-danger hover:bg-danger-soft"><Trash2 className="size-4" /></button>
                  </div>
                </li>
              )
            })}
          </ul>
        )}

      <ConfirmDialog open={!!removing} onOpenChange={(o) => !o && setRemoving(null)} title="Remove this quotation file?" description={removing ? `${removing.name}${removing.supplier_name ? ` from ${removing.supplier_name}` : ''} is taken off the list for good.` : ''}
        confirmLabel="Remove" tone="danger" loading={remove.isPending} onConfirm={() => { if (removing) remove.mutate(removing) }} />
    </div>
  )
}

/** The ticked quotations in columns, each as it is: a PDF or photo shown, a Word or Excel file as its text. */
function SideBySide({ files, onClose }: { files: QuoteFile[]; onClose: () => void }) {
  return (
    <div className="grid gap-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-muted-foreground">{files.length} quotations side by side. Scroll each one on its own.</p>
        <Button variant="outline" onClick={onClose}><X /> Back to the files</Button>
      </div>
      <div className={cn('grid gap-3', files.length === 2 ? 'lg:grid-cols-2' : files.length === 3 ? 'lg:grid-cols-3' : 'lg:grid-cols-2 2xl:grid-cols-4')}>
        {files.map((f) => (
          <section key={f.id} className="flex min-w-0 flex-col overflow-hidden rounded-xl border border-border bg-card shadow-card">
            <header className="flex items-center justify-between gap-2 border-b border-border px-3.5 py-2.5">
              <div className="min-w-0">
                <p className="truncate font-medium">{f.supplier_name || f.name}</p>
                <p className="truncate text-xs text-muted-foreground">{f.name}</p>
              </div>
              <a href={f.url} target="_blank" rel="noreferrer" aria-label={`Open ${f.name}`} title="Open in a new tab" className="grid size-8 shrink-0 place-items-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground"><ExternalLink className="size-4" /></a>
            </header>
            <Viewer f={f} />
          </section>
        ))}
      </div>
    </div>
  )
}

function Viewer({ f }: { f: QuoteFile }) {
  const asIs = shownAsIs(f)
  const text = useQuoteFileText(f.id, !asIs)
  const box = 'h-[70vh] min-h-[24rem] w-full'
  if (f.content_type.startsWith('image/')) return <div className={cn(box, 'overflow-auto bg-surface')}><img src={f.url} alt={f.name} className="w-full" /></div>
  if (asIs) return <iframe src={f.url} title={f.name} className={cn(box, 'bg-white')} />
  if (text.isPending) return <p className={cn(box, 'grid place-items-center text-sm text-muted-foreground')}>Reading the file...</p>
  if (text.error) return <p role="alert" className={cn(box, 'grid place-items-center px-4 text-center text-sm text-danger')}>{text.error.message}</p>
  return <pre className={cn(box, 'overflow-auto whitespace-pre-wrap bg-surface p-3.5 font-mono text-xs leading-relaxed')}>{text.data?.text || 'The file has no text in it.'}</pre>
}
