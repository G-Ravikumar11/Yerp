import { useEffect, useRef, useState } from 'react'
import { AlertTriangle, ChevronLeft, ChevronRight, Paperclip, Search, X } from 'lucide-react'
import { Button, Input, Select, Skeleton } from '@/components/ui'
import { type HistoryLine, type ListQuery } from '@/api/quality'
import { formatDate } from '@/lib/format'
import { cn } from '@/lib/utils'

type Tone = 'success' | 'danger' | 'warning' | 'neutral' | 'info' | 'ember'

export const inspectionTone = (r: string): Tone => (r === 'PASSED' ? 'success' : r === 'FAILED' ? 'danger' : 'warning')
export const ncrTone = (status: string, overdue: boolean): Tone => (status === 'CLOSED' ? 'success' : status === 'REJECTED' ? 'danger' : overdue ? 'danger' : status === 'REINSPECTION' ? 'info' : status === 'OPEN' ? 'warning' : 'ember')
export const cubeTone = (s: string): Tone =>
  s === 'below grade' || s === 'rejected' ? 'danger' : s === 'accepted' ? 'success' : s === 'accepted with conditions' ? 'warning' : s === 'for engineering review' || s === 'criteria not set' ? 'info' : 'neutral'

const LABEL_ACTION: Record<string, string> = {
  'qc.inspection.created': 'Started', 'qc.inspection.edited': 'Edited', 'qc.inspection.submitted': 'Submitted for approval',
  'qc.inspection.returned': 'Returned to the inspector', 'qc.inspection.passed': 'Approved - passed', 'qc.inspection.failed': 'Approved - failed',
  'qc.inspection.reinspection_requested': 'Reinspection requested', 'qc.cube.registered': 'Sample registered', 'qc.cube.result': 'Result recorded',
  'qc.cube.flagged': 'Sent for engineering review', 'qc.cube.decision': 'Engineering decision', 'qc.ncr.raised': 'Raised', 'qc.ncr.assigned': 'Assigned',
  'qc.ncr.corrective_recorded': 'Corrective work recorded', 'qc.ncr.verification_requested': 'Verification requested', 'qc.ncr.verified': 'Verified',
  'qc.ncr.rejected': 'Correction rejected', 'qc.ncr.closed': 'Closed', 'qc.ncr.reinspection': 'Reinspection passed',
}

/** Who did what, newest first: the trail the server keeps for every change of status. */
export function History({ lines, loading }: { lines?: HistoryLine[]; loading?: boolean }) {
  if (loading) return <Skeleton className="h-16 w-full" />
  if (!lines?.length) return <p className="text-[13px] text-muted-foreground">Nothing recorded yet.</p>
  return (
    <ol aria-label="History" className="grid gap-2.5">
      {lines.map((h, i) => (
        <li key={i} className="grid grid-cols-[auto_1fr] gap-x-3 text-[13px]">
          <span className="mt-1.5 size-1.5 rounded-full bg-primary" aria-hidden />
          <div>
            <p><span className="font-medium">{LABEL_ACTION[h.action] ?? h.action}</span> <span className="text-muted-foreground">- {h.who || 'System'}, {formatDate(h.at.slice(0, 10))} {h.at.slice(11, 16)}</span></p>
            {h.details && <p className="text-muted-foreground">{h.details}</p>}
          </div>
        </li>
      ))}
    </ol>
  )
}

/** Search, status, date range and order for one list - the same bar on every tab. */
export function ListBar({ f, set, statuses, sorts, severities, placeholder }: { f: ListQuery; set: (patch: Partial<ListQuery>) => void; statuses: { value: string; label: string }[]; sorts: { value: string; label: string }[]; severities?: string[]; placeholder: string }) {
  // Typing is held locally and sent a moment after the last key, so each letter is not a request.
  const [text, setText] = useState(f.q)
  const seen = useRef(f.q)
  useEffect(() => {
    if (f.q !== seen.current) { seen.current = f.q; setText(f.q) }
  }, [f.q])
  useEffect(() => {
    if (text === seen.current) return
    const t = setTimeout(() => { seen.current = text; set({ q: text, page: 1 }) }, 300)
    return () => clearTimeout(t)
  }, [text, set])
  const active = !!(f.q || f.status || f.from || f.to || f.severity)
  return (
    <div role="search" className="mb-3 flex flex-wrap items-end gap-2">
      <div className="relative min-w-52 flex-1 basis-60">
        <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-subtle" aria-hidden />
        <Input aria-label="Search" className="pl-9" placeholder={placeholder} value={text} onChange={(e) => setText(e.target.value)} />
      </div>
      <div className="w-44"><Select aria-label="Status" value={f.status} onChange={(e) => set({ status: e.target.value, page: 1 })} placeholder="Any status" options={statuses} /></div>
      {severities && <div className="w-36"><Select aria-label="Severity" value={f.severity ?? ''} onChange={(e) => set({ severity: e.target.value, page: 1 })} placeholder="Any severity" options={severities.map((s) => ({ value: s, label: s }))} /></div>}
      <label className="flex flex-col gap-1 text-[11px] uppercase tracking-wide text-muted-foreground">From<Input type="date" aria-label="From date" className="w-36 normal-case tracking-normal" value={f.from} max={f.to || undefined} onChange={(e) => set({ from: e.target.value, page: 1 })} /></label>
      <label className="flex flex-col gap-1 text-[11px] uppercase tracking-wide text-muted-foreground">To<Input type="date" aria-label="To date" className="w-36 normal-case tracking-normal" value={f.to} min={f.from || undefined} onChange={(e) => set({ to: e.target.value, page: 1 })} /></label>
      <div className="w-44"><Select aria-label="Sort by" value={f.sort ? `${f.sort}:${f.dir}` : ''} onChange={(e) => { const [sort, dir] = e.target.value.split(':'); set({ sort: sort ?? '', dir: (dir as 'asc' | 'desc') || 'desc', page: 1 }) }} placeholder="Newest first" options={sorts.flatMap((s) => [{ value: `${s.value}:asc`, label: `${s.label} (A-Z)` }, { value: `${s.value}:desc`, label: `${s.label} (Z-A)` }])} /></div>
      {active && <Button variant="ghost" size="sm" onClick={() => set({ q: '', status: '', from: '', to: '', severity: '', page: 1 })}><X /> Clear</Button>}
    </div>
  )
}

/** Previous and next, and where you are in the list. */
export function Pager({ f, total, set }: { f: ListQuery; total: number; set: (patch: Partial<ListQuery>) => void }) {
  const pages = Math.max(1, Math.ceil(total / f.size))
  if (total <= f.size && f.page === 1) return <p className="px-4 py-2 text-xs text-muted-foreground">{total} {total === 1 ? 'record' : 'records'}</p>
  const first = (f.page - 1) * f.size + 1
  return (
    <nav aria-label="Pages" className="flex flex-wrap items-center justify-between gap-2 px-4 py-2 text-xs text-muted-foreground">
      <span>{total ? `${first}-${Math.min(total, first + f.size - 1)} of ${total}` : 'None'}</span>
      <span className="flex items-center gap-1.5">
        <Button size="sm" variant="outline" disabled={f.page <= 1} onClick={() => set({ page: f.page - 1 })} aria-label="Previous page"><ChevronLeft /></Button>
        <span>Page {f.page} of {pages}</span>
        <Button size="sm" variant="outline" disabled={f.page >= pages} onClick={() => set({ page: f.page + 1 })} aria-label="Next page"><ChevronRight /></Button>
      </span>
    </nav>
  )
}

/** The list's own failure: what the server said, and a way to try again. */
export function LoadError({ message, retry }: { message: string; retry: () => void }) {
  return (
    <div role="alert" className="flex items-center gap-3 rounded-xl border border-danger/30 bg-danger-soft p-4 text-[13.5px] text-danger">
      <AlertTriangle className="size-4 shrink-0" aria-hidden />
      <span className="flex-1">{message || 'This could not be loaded.'}</span>
      <Button size="sm" variant="outline" onClick={retry}>Try again</Button>
    </div>
  )
}

/** Pick photos or papers to be sent once the record they belong to exists. */
export function FilePick({ files, onChange, label = 'Attach photos or documents', accept = 'image/*,.pdf' }: { files: File[]; onChange: (f: File[]) => void; label?: string; accept?: string }) {
  const ref = useRef<HTMLInputElement>(null)
  return (
    <div>
      <input ref={ref} type="file" multiple accept={accept} className="sr-only" aria-label={label} onChange={(e) => { onChange([...files, ...Array.from(e.target.files ?? [])]); e.target.value = '' }} />
      <Button type="button" variant="outline" size="sm" onClick={() => ref.current?.click()}><Paperclip /> {label}</Button>
      {files.length > 0 && (
        <ul className="mt-2 grid gap-1 text-[13px]">
          {files.map((f, i) => (
            <li key={i} className="flex items-center gap-2"><span className="truncate">{f.name}</span><span className="text-muted-foreground">{Math.max(1, Math.round(f.size / 1024))} KB</span>
              <button type="button" aria-label={`Remove ${f.name}`} className="ml-auto text-muted-foreground hover:text-danger" onClick={() => onChange(files.filter((_, n) => n !== i))}><X className="size-3.5" /></button></li>
          ))}
        </ul>
      )}
    </div>
  )
}

export const Section = ({ title, children, className }: { title: string; children: React.ReactNode; className?: string }) => (
  <section className={cn('rounded-lg border border-border p-4', className)}>
    <h3 className="mb-3 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">{title}</h3>
    {children}
  </section>
)

export const Fact = ({ label, children }: { label: string; children: React.ReactNode }) => (
  <div className="min-w-0"><dt className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</dt><dd className="mt-0.5 break-words text-[13.5px]">{children || '-'}</dd></div>
)


