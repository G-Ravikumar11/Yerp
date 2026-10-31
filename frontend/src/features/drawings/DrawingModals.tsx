import { OpenFile } from '@/components/data/FileView'
import { useRef, useState } from 'react'
import { FileUp } from 'lucide-react'
import { Button, Field, Input, Modal, Select, Skeleton, Textarea } from '@/components/ui'
import { addDrawing, addRevision, drwKeys, setDrawingStatus, useDrawing, type Drawing } from '@/api/drawings'
import { useAction } from '@/lib/mutate'
import { formatDate, today } from '@/lib/format'

/** Add a sheet to the register by its number; its revisions follow as they arrive. */
export function AddDrawingModal({ job, disciplines, open, onClose, onAdded }: { job: number; disciplines: string[]; open: boolean; onClose: () => void; onAdded: (id: number, number: string) => void }) {
  const [number, setNumber] = useState('')
  const [title, setTitle] = useState('')
  const [disc, setDisc] = useState('Structural')
  const save = useAction(() => addDrawing(job, { number, title, discipline: disc }), { invalidate: [drwKeys.all], success: (r) => `${r.drawing.number} added. Now add its first revision.`, onSuccess: (r) => { setNumber(''); setTitle(''); onAdded(r.drawing.id, r.drawing.number) } })
  return (
    <Modal open={open} onOpenChange={(o) => !o && onClose()} title="Add a drawing" description="Add each sheet by the number printed on it, then its revisions as they arrive.">
      <form onSubmit={(e) => { e.preventDefault(); if (number.trim() && !save.isPending) save.mutate() }}>
      <div className="grid gap-4">
        <Field label="Drawing number" htmlFor="dw-no"><Input id="dw-no" value={number} onChange={(e) => setNumber(e.target.value)} placeholder="STR-101" autoFocus /></Field>
        <Field label="What it shows" htmlFor="dw-title"><Input id="dw-title" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Raft reinforcement" /></Field>
        <Field label="Discipline" htmlFor="dw-disc"><Select id="dw-disc" value={disc} onChange={(e) => setDisc(e.target.value)} options={(disciplines.length ? disciplines : ['Structural']).map((d) => ({ value: d, label: d }))} /></Field>
      </div>
      <div className="mt-5 flex items-center justify-end gap-2 border-t border-border pt-4">
        {save.error && <p role="alert" className="mr-auto text-[13px] text-danger">{save.error.message}</p>}
        <Button type="button" variant="ghost" onClick={onClose}>Cancel</Button>
        <Button type="submit" loading={save.isPending} disabled={!number.trim()}>Add the drawing</Button>
      </div>
      </form>
    </Modal>
  )
}

/** A new sheet of a drawing: the file, its revision letter, who sent it and its status. */
export function RevisionModal({ drawing, statuses, onClose }: { drawing: Drawing | null; statuses: string[]; onClose: () => void }) {
  return (
    <Modal open={!!drawing} onOpenChange={(o) => !o && onClose()} title={drawing ? `New revision - ${drawing.number}` : ''}>
      {drawing && <RevisionForm key={drawing.id} drawing={drawing} statuses={statuses} onClose={onClose} />}
    </Modal>
  )
}

function RevisionForm({ drawing, statuses, onClose }: { drawing: Drawing; statuses: string[]; onClose: () => void }) {
  const [file, setFile] = useState<File | null>(null)
  const [rev, setRev] = useState('')
  const [status, setStatus] = useState(statuses.filter((s) => s !== 'Superseded')[0] ?? 'For approval')
  const [on, setOn] = useState(today())
  const [from, setFrom] = useState('')
  const [remarks, setRemarks] = useState('')
  const save = useAction(() => addRevision(drawing.id, file as File, { revision: rev.trim(), status, received_on: on, received_from: from, remarks }), { invalidate: [drwKeys.all], success: (r) => r.message, onSuccess: onClose })
  const picker = useRef<HTMLInputElement>(null)
  const ready = !!file && !!rev.trim()
  return (
    <form onSubmit={(e) => { e.preventDefault(); if (ready && !save.isPending) save.mutate() }}>
      <div className="grid gap-4 sm:grid-cols-3">
        <Field label="The sheet" htmlFor="rv-file" className="sm:col-span-3">
          <input ref={picker} id="rv-file" type="file" accept=".pdf,.dwg,.dxf,image/*" className="sr-only" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
          <Button type="button" variant="outline" className="h-11 w-full justify-start gap-2 font-normal" onClick={() => picker.current?.click()}>
            <FileUp className="size-4 shrink-0" />
            <span className={`truncate ${file ? '' : 'text-muted-foreground'}`}>{file ? file.name : 'Choose a file (PDF, DWG, DXF or image)'}</span>
          </Button>
        </Field>
        <Field label="Revision" htmlFor="rv-rev"><Input id="rv-rev" value={rev} onChange={(e) => setRev(e.target.value)} placeholder="R1, A, B..." /></Field>
        <Field label="Status" htmlFor="rv-status"><Select id="rv-status" value={status} onChange={(e) => setStatus(e.target.value)} options={statuses.filter((s) => s !== 'Superseded').map((s) => ({ value: s, label: s }))} /></Field>
        <Field label="Received on" htmlFor="rv-on"><Input id="rv-on" type="date" value={on} onChange={(e) => setOn(e.target.value)} /></Field>
        <Field label="Received from" htmlFor="rv-from" className="sm:col-span-3"><Input id="rv-from" value={from} onChange={(e) => setFrom(e.target.value)} placeholder="The architect, the consultant..." /></Field>
        <Field label="Remarks" htmlFor="rv-remarks" className="sm:col-span-3"><Textarea id="rv-remarks" rows={2} value={remarks} onChange={(e) => setRemarks(e.target.value)} /></Field>
      </div>
      <div className="mt-5 flex items-center justify-end gap-2 border-t border-border pt-4">
        {save.error && <p role="alert" className="mr-auto text-[13px] text-danger">{save.error.message}</p>}
        <Button type="button" variant="ghost" onClick={onClose}>Cancel</Button>
        <Button type="submit" loading={save.isPending} disabled={!ready}>Add the revision</Button>
      </div>
    </form>
  )
}

/** Every revision a drawing has had, the current one in bold, and the status it can be moved to. */
export function HistoryModal({ id, onClose }: { id: number | null; onClose: () => void }) {
  const q = useDrawing(id)
  const d = q.data
  const move = useAction((s: string) => setDrawingStatus(id as number, s), { invalidate: [drwKeys.all], success: (r) => `${r.drawing.number} updated`, onSuccess: onClose })
  return (
    <Modal open={id !== null} onOpenChange={(o) => !o && onClose()} title={d ? `${d.number} - ${d.title}` : 'Drawing'} size="lg">
      {!d ? <Skeleton className="h-40 w-full" /> : (
        <div>
          <div className="overflow-x-auto rounded-lg border border-border">
            <table aria-label="Revisions" className="w-full text-[13px]">
              <thead className="bg-surface text-left text-xs text-muted-foreground"><tr><th className="px-3 py-2">S.No.</th><th className="px-3 py-2">Rev</th><th className="px-3 py-2">Status</th><th className="px-3 py-2">Received</th><th className="px-3 py-2">From</th><th className="px-3 py-2">Remarks</th><th /></tr></thead>
              <tbody>{d.history.slice().reverse().map((h, i) => <tr key={i} className={`border-t border-border ${h.current ? 'font-semibold' : 'text-muted-foreground'}`}><td className="tabular px-3 py-2">{i + 1}</td><td className="px-3 py-2 font-mono">{h.revision}</td><td className="px-3 py-2">{h.status}</td><td className="px-3 py-2">{formatDate(h.received_on)}</td><td className="px-3 py-2">{h.received_from}</td><td className="px-3 py-2">{h.remarks}</td><td className="px-3 py-2 text-right">{h.file_id && <OpenFile className="text-primary hover:underline" id={h.file_id} name={`${d.number} rev ${h.revision}`}>Open</OpenFile>}</td></tr>)}</tbody>
            </table>
          </div>
          {(d.status_log ?? []).length > 0 && (
            <section aria-label="Status changes" className="mt-4">
              <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Status changes</p>
              <ul className="space-y-0.5 text-[13px]">{(d.status_log ?? []).map((l, i) => <li key={i}><span className="text-muted-foreground">{formatDate(l.at.slice(0, 10))}{l.by ? ` · ${l.by}` : ''}:</span> {l.change}</li>)}</ul>
            </section>
          )}
          {d.deletable === false && <p className="mt-3 text-xs text-muted-foreground">Released Good for construction at some point, so it stays on the register: supersede it with a new revision instead of deleting it.</p>}
          {d.current_revision && <div className="mt-4 flex flex-wrap gap-2">{['For approval', 'Approved', 'Good for construction'].map((s) => <Button key={s} size="sm" variant="outline" loading={move.isPending && move.variables === s} onClick={() => move.mutate(s)}>Mark {s.toLowerCase()}</Button>)}</div>}
        </div>
      )}
    </Modal>
  )
}
