import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Search } from 'lucide-react'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { ProjectPicker } from '@/components/data/ProjectPicker'
import { Badge, Button, Card, Field, Input, Modal, Select, Skeleton, Textarea } from '@/components/ui'
import { get, post } from '@/lib/api'
import { useAction } from '@/lib/mutate'
import { useSession } from '@/lib/session'

interface Hold { inspection_ref: string; id: number; kind: string; status: string; reason: string; remarks: string; ncr_id: number | null; ncr_number: string; ncr_status: string; placed_by: string; placed_at: string; released_by: string; released_at: string; release_note: string }
interface Batch {
  id: number; batch_no: string; item_name: string; item_code: string; uom: string; supplier: string; project: string; received_qty: string; available_qty: string; expiry_date: string
  hold_status: string; status_code: string; held_at: string; held_by: string; blocked: boolean; hold_reason: string; ncrs: { id: number; number: string }[]; holds?: Hold[]; all_ncrs?: { id: number; number: string; status: string; raised_on: string; description: string }[]
}
const KEY = ['store', 'batches'] as const
const TONE: Record<string, 'success' | 'warning' | 'info' | 'danger'> = { Available: 'success', 'On Hold': 'warning', Released: 'info', Expired: 'danger', Rejected: 'danger' }
const STATUS_TEXT = (s: string) => (s === 'On Hold' ? 'ON HOLD' : s)
const WHY_BLOCKED: Record<string, string> = { Rejected: 'Blocked: rejected', Expired: 'Blocked: past its expiry' }

/** Every batch in the stores and whether it may be issued. A batch on hold cannot leave for use, whatever is on hand. */
export default function BatchesPage() {
  const { can } = useSession()
  const [q, setQ] = useState('')
  const [status, setStatus] = useState('')
  const [page, setPage] = useState(1)
  const [open, setOpen] = useState<number | null>(null)
  const list = useQuery({ queryKey: [...KEY, q, status, page], staleTime: 0, refetchOnMount: 'always', queryFn: () => get<{ batches: Batch[]; total: number; per_page: number }>(`/api/store/batches?q=${encodeURIComponent(q)}&hold_status=${encodeURIComponent(status)}&page=${page}`) })
  const pages = list.data ? Math.max(1, Math.ceil(list.data.total / list.data.per_page)) : 1
  const cols: TableColumn<Batch>[] = [
    { id: 'b', header: 'Batch', cell: (b) => <button type="button" className="font-mono text-[13px] font-semibold text-primary hover:underline" onClick={() => setOpen(b.id)}>{b.batch_no}</button> },
    { id: 'i', header: 'Material', cell: (b) => <div>{b.item_name}<div className="text-xs text-muted-foreground">{b.supplier}</div></div> },
    { id: 'p', header: 'Project', hideBelow: 'md', cell: (b) => b.project || '-' },
    { id: 'r', header: 'Received', align: 'right', hideBelow: 'lg', cell: (b) => `${b.received_qty} ${b.uom}` },
    { id: 'a', header: 'Available', align: 'right', cell: (b) => `${b.available_qty} ${b.uom}` },
    { id: 's', header: 'Hold status', cell: (b) => <div><Badge tone={TONE[b.hold_status] ?? 'info'} dot>{STATUS_TEXT(b.hold_status)}</Badge>{b.hold_reason && <div className="mt-0.5 max-w-64 truncate text-xs text-muted-foreground">{b.hold_reason}</div>}</div> },
    { id: 'n', header: 'NCR', hideBelow: 'md', cell: (b) => b.ncrs.map((n) => n.number).join(', ') || '-' },
    { id: 'x', header: '', align: 'right', cell: (b) => <Button size="sm" variant="outline" onClick={() => setOpen(b.id)}>Details</Button> },
  ]
  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <div className="w-full sm:w-72"><Input aria-label="Search batches" placeholder="Batch or material" leading={<Search />} value={q} onChange={(e) => { setQ(e.target.value); setPage(1) }} /></div>
        <Button size="sm" variant={status === 'On Hold' ? 'primary' : 'outline'} onClick={() => { setStatus(status === 'On Hold' ? '' : 'On Hold'); setPage(1) }}>Material on hold</Button>
        <Button size="sm" variant={status === 'Expired' ? 'primary' : 'outline'} onClick={() => { setStatus(status === 'Expired' ? '' : 'Expired'); setPage(1) }}>Expired stock</Button>
        <div className="w-40"><Select aria-label="Hold status" value={status} placeholder="Any status" onChange={(e) => { setStatus(e.target.value); setPage(1) }} options={Object.keys(TONE).map((s) => ({ value: s, label: s }))} /></div>
      </div>
      {list.isError ? <p role="alert" className="text-sm text-danger">{list.error.message}</p> : <Card className="overflow-hidden"><DataTable label="Batches" className="rounded-none border-0 shadow-none" rows={list.data?.batches ?? []} columns={cols} rowKey={(b) => b.id} loading={list.isPending} empty="No batches recorded." /></Card>}
      {pages > 1 && <nav aria-label="Pages" className="mt-2 flex items-center justify-end gap-2 text-xs text-muted-foreground"><Button size="sm" variant="outline" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</Button>Page {page} of {pages}<Button size="sm" variant="outline" disabled={page >= pages} onClick={() => setPage(page + 1)}>Next</Button></nav>}
      {open && <BatchDetail id={open} canPlace={can('store.inward.create|site.signoff|store.admin')} canRelease={can('site.signoff|store.admin')} onClose={() => setOpen(null)} />}
    </div>
  )
}

function BatchDetail({ id, canPlace, canRelease, onClose }: { id: number; canPlace: boolean; canRelease: boolean; onClose: () => void }) {
  const q = useQuery({ queryKey: [...KEY, 'one', id], staleTime: 0, queryFn: () => get<Batch>(`/api/store/batches/${id}`) })
  const [mode, setMode] = useState<'hold' | 'release' | 'ncr' | null>(null)
  const [reason, setReason] = useState('')
  const [remarks, setRemarks] = useState('')
  const [job, setJob] = useState(0)
  const hold = useAction(() => post<{ message: string }>(`/api/store/batches/${id}/hold`, { reason, remarks }), { invalidate: [KEY], success: (r) => r.message, onSuccess: () => { setMode(null); setReason(''); setRemarks('') } })
  const release = useAction(() => post<{ message: string }>(`/api/store/batches/${id}/release`, { note: reason }), { invalidate: [KEY], success: (r) => r.message, onSuccess: () => { setMode(null); setReason('') } })
  const raise = useAction(() => post<{ ncr: { number: string } }>('/api/qc/ncrs', { store_batch_id: id, description: reason, severity: 'Minor', job_id: job || undefined }), { invalidate: [KEY, ['qc']], success: (r) => `${r.ncr.number} raised. The batch is on hold.`, onSuccess: () => { setMode(null); setReason('') } })
  const b = q.data
  const manual = b?.holds?.some((h) => h.kind !== 'NCR' && h.status === 'ACTIVE')
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} size="lg" title={b ? `Batch ${b.batch_no}` : 'Batch'} description={b?.blocked ? 'This batch is blocked from issue.' : undefined}
      footer={<>
        <Button variant="ghost" onClick={onClose}>Close</Button>
        {b && !mode && canPlace && <Button variant="outline" onClick={() => setMode('ncr')}>Raise NCR</Button>}
        {b && !mode && canPlace && !b.holds?.some((h) => h.kind === 'MANUAL' && h.status === 'ACTIVE') && <Button variant="outline" onClick={() => setMode('hold')}>Place batch on hold</Button>}
        {b && !mode && canRelease && manual && <Button onClick={() => setMode('release')}>Release hold</Button>}
      </>}>
      {!b ? <Skeleton className="h-40 w-full" /> : (
        <section aria-label="Quality hold">
          <dl className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-[13px] sm:grid-cols-3">
            <div><dt className="text-xs text-muted-foreground">Material</dt><dd>{b.item_name}</dd></div>
            <div><dt className="text-xs text-muted-foreground">Supplier</dt><dd>{b.supplier || '-'}</dd></div>
            <div><dt className="text-xs text-muted-foreground">Project</dt><dd>{b.project || '-'}</dd></div>
            <div><dt className="text-xs text-muted-foreground">Received</dt><dd>{b.received_qty} {b.uom}</dd></div>
            <div><dt className="text-xs text-muted-foreground">Available</dt><dd>{b.available_qty} {b.uom}</dd></div>
            <div><dt className="text-xs text-muted-foreground">Hold status</dt><dd><Badge tone={TONE[b.hold_status] ?? 'info'} dot>{STATUS_TEXT(b.hold_status)}</Badge></dd></div>
            {b.hold_status === 'On Hold' && <div className="col-span-2 sm:col-span-3"><dt className="text-xs text-muted-foreground">Hold reason</dt><dd>{b.hold_reason}</dd></div>}
            {b.hold_status === 'On Hold' && <div><dt className="text-xs text-muted-foreground">Held on</dt><dd>{b.held_at}</dd></div>}
            {b.hold_status === 'On Hold' && <div><dt className="text-xs text-muted-foreground">Held by</dt><dd>{b.held_by}</dd></div>}
            {b.expiry_date && <div><dt className="text-xs text-muted-foreground">Expires</dt><dd>{b.expiry_date}</dd></div>}
            {b.blocked && <div><dt className="text-xs text-muted-foreground">Issue, transfer, write-off</dt><dd className="text-warning">{WHY_BLOCKED[b.hold_status] ?? 'Blocked while on hold'}</dd></div>}
          </dl>
          {mode && (
            <div className="mt-4 grid gap-3 rounded-lg border border-border p-3">
              <Field label={mode === 'hold' ? 'Hold reason' : mode === 'ncr' ? 'What is not as specified' : 'Reason for release'} htmlFor="bh-why"><Input id="bh-why" value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
              {mode === 'ncr' && !b.project && <Field label="Project" htmlFor="bh-job" hint="This batch is in a central store, so say which project it is for"><ProjectPicker id="bh-job" value={job} onChange={setJob} /></Field>}
              {mode === 'hold' && <Field label="Remarks" htmlFor="bh-rem"><Textarea id="bh-rem" rows={2} value={remarks} onChange={(e) => setRemarks(e.target.value)} /></Field>}
              <div className="flex justify-end gap-2"><Button variant="ghost" onClick={() => setMode(null)}>Cancel</Button><Button disabled={!reason.trim() || (mode === 'ncr' && !b.project && !job) || hold.isPending || release.isPending || raise.isPending} loading={hold.isPending || release.isPending || raise.isPending} onClick={() => (mode === 'hold' ? hold.mutate() : mode === 'ncr' ? raise.mutate() : release.mutate())}>{mode === 'hold' ? 'Place on hold' : mode === 'ncr' ? 'Raise NCR' : 'Release'}</Button></div>
              {(hold.error || release.error || raise.error) && <p role="alert" className="text-[13px] text-danger">{(hold.error ?? release.error ?? raise.error)?.message}</p>}
            </div>
          )}
          <h3 className="mb-1.5 mt-4 text-sm font-semibold">Hold history</h3>
          {b.holds?.length ? <ul aria-label="Hold history" className="grid gap-1.5 text-[13px]">{b.holds.map((h) => <li key={h.id} className="rounded-lg border border-border p-2.5"><Badge tone={h.status === 'ACTIVE' ? 'danger' : 'info'} dot>{h.status === 'ACTIVE' ? 'Active' : 'Released'}</Badge> <strong>{h.kind === 'NCR' ? h.ncr_number : h.kind === 'QC' ? 'Failed inspection' : 'Manual hold'}</strong>: {h.reason}{h.inspection_ref && <span className="text-muted-foreground"> ({h.inspection_ref})</span>}<div className="text-xs text-muted-foreground">Placed {h.placed_at} by {h.placed_by}{h.released_at && `. Released ${h.released_at} by ${h.released_by}: ${h.release_note}`}{h.remarks && `. ${h.remarks}`}</div></li>)}</ul> : <p className="text-[13px] text-muted-foreground">Never held.</p>}
          <h3 className="mb-1.5 mt-4 text-sm font-semibold">Linked NCRs</h3>
          {b.all_ncrs?.length ? <ul aria-label="Linked NCRs" className="grid gap-1 text-[13px]">{b.all_ncrs.map((n) => <li key={n.id}><Link className="font-medium text-primary hover:underline" to={`/projects/quality?ncr=${n.id}`}>{n.number}</Link> {n.status} - {n.description}</li>)}</ul> : <p className="text-[13px] text-muted-foreground">None.</p>}
        </section>
      )}
    </Modal>
  )
}
