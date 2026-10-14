import { OpenFile } from '@/components/data/FileView'
import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Plus } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { ProjectPicker } from '@/components/data/ProjectPicker'
import { Badge, Button, Input, Select, Stat, StatGrid } from '@/components/ui'
import { deleteDrawing, drwKeys, useDrawings, type Drawing, type DrawingRegister } from '@/api/drawings'
import { ConfirmDialog } from '@/components/ui/confirm'
import { DeleteButton } from '@/features/deleteorder/DeleteButton'
import { useAction } from '@/lib/mutate'
import { useSession } from '@/lib/session'
import { formatDate } from '@/lib/format'
import { AddDrawingModal, HistoryModal, RevisionModal } from './DrawingModals'
import { Plan3DModal } from './Plan3DModal'

const tone = (s: string) => (s === 'Good for construction' ? 'success' : s === 'For approval' ? 'warning' : 'neutral') as 'success' | 'warning' | 'neutral'

/** The trash icon for a sheet, with its confirmation. Shown to everyone who manages drawings, not only the Master. */
function DrawingDelete({ drawing, onDeleted }: { drawing: Drawing; onDeleted: () => void }) {
  const [open, setOpen] = useState(false)
  const del = useAction(() => deleteDrawing(drawing.id), { invalidate: [drwKeys.all], success: (r) => r.message, onSuccess: () => { setOpen(false); onDeleted() } })
  return (
    <>
      <DeleteButton label={drawing.number} onClick={() => setOpen(true)} />
      <ConfirmDialog
        open={open}
        onOpenChange={setOpen}
        title={`Delete ${drawing.number}?`}
        description={`This removes the sheet${drawing.revisions > 1 ? ` and all ${drawing.revisions} of its revisions` : drawing.revisions === 1 ? ' and its revision' : ''}, with their files. It cannot be undone.`}
        confirmLabel="Delete the drawing"
        tone="danger"
        loading={del.isPending}
        onConfirm={() => del.mutate()}
      />
    </>
  )
}

/** Every sheet and every revision, the one to build to marked. */
export default function DrawingsPage() {
  const { can } = useSession()
  const [job, setJob] = useState(0)
  const qc = useQueryClient()
  const q = useDrawings(job)
  const d = q.data
  const [search, setSearch] = useState('')
  const [disc, setDisc] = useState('')
  const [status, setStatus] = useState('')
  const [adding, setAdding] = useState(false)
  const [revising, setRevising] = useState<Drawing | null>(null)
  const [history, setHistory] = useState<number | null>(null)
  const [view3d, setView3d] = useState<Drawing | null>(null)
  const words = search.toLowerCase()
  const rows = (d?.drawings ?? []).filter((w) => (!words || `${w.number} ${w.title}`.toLowerCase().includes(words)) && (!disc || w.discipline === disc) && (!status || (status === 'none' ? !w.current_revision : w.status === status)))
  const removeRow = (id: number) =>
    qc.setQueryData<DrawingRegister>(['drawings', 'register', job], (old) =>
      old ? { ...old, drawings: old.drawings.filter((w) => w.id !== id), summary: { ...old.summary, drawings: old.summary.drawings - 1 } } : old,
    )
  const columns: TableColumn<Drawing>[] = [
    { id: 'no', header: 'Number', sort: (w) => w.number, cell: (w) => <span className="font-mono text-[13px] font-semibold">{w.number}</span> },
    { id: 'title', header: 'Title', cell: (w) => w.title },
    { id: 'disc', header: 'Discipline', hideBelow: 'md', cell: (w) => w.discipline },
    { id: 'rev', header: 'Revision', cell: (w) => <span className="font-mono">{w.current_revision || '-'}{w.revisions > 1 && <span className="ml-1 text-xs text-muted-foreground">({w.revisions})</span>}</span> },
    { id: 'status', header: 'Status', cell: (w) => (w.current_revision ? <Badge tone={tone(w.status)} dot>{w.status}</Badge> : <span className="text-muted-foreground">no sheet yet</span>) },
    { id: 'rec', header: 'Received', hideBelow: 'lg', cell: (w) => formatDate(w.received_on) },
    {
      id: 'act',
      header: '',
      align: 'right',
      cell: (w) => (
        <div className="flex flex-wrap justify-end gap-1.5">
          {w.current_file_id && <Button size="sm" variant="outline" asChild><OpenFile id={w.current_file_id} name={`${w.number} ${w.title}`}>Open</OpenFile></Button>}
          <Button size="sm" variant="outline" onClick={() => setRevising(w)}>New revision</Button>
          {w.current_file_id && <Button size="sm" variant="outline" onClick={() => setView3d(w)}>3D</Button>}
          <Button size="sm" variant="outline" onClick={() => setHistory(w.id)}>History</Button>
        </div>
      ),
    },
    {
      id: 'del',
      header: '',
      align: 'right',
      width: '3.5rem',
      cell: (r) => (can('workorders.manage') ? <DrawingDelete drawing={r} onDeleted={() => removeRow(r.id)} /> : null),
    },
  ]
  return (
    <>
      <PageHeader eyebrow="Projects" title="Drawings" description="Every sheet and every revision, with the one to build to marked." actions={can('workorders.manage') && <Button disabled={!job} onClick={() => setAdding(true)}><Plus /> Drawing</Button>} />
      <div className="mb-6"><ProjectPicker value={job} onChange={setJob} id="drw-job" /></div>
      <StatGrid className="lg:grid-cols-3 xl:grid-cols-3">
            <Stat label="Drawings" value={d?.summary.drawings ?? 0} loading={q.isPending && job > 0} />
            <Stat label="Good for construction" value={d?.summary.gfc ?? 0} loading={q.isPending && job > 0} />
            <Stat label="Awaiting approval" value={d?.summary.awaiting ?? 0} loading={q.isPending && job > 0} />
          </StatGrid>
          <div className="mb-4 flex flex-wrap items-center gap-2">
            <div className="w-64"><Input aria-label="Search" placeholder="Search number or title" value={search} onChange={(e) => setSearch(e.target.value)} /></div>
            <div className="w-48"><Select aria-label="Discipline" value={disc} placeholder="Every discipline" onChange={(e) => setDisc(e.target.value)} options={(d?.disciplines ?? []).map((x) => ({ value: x, label: x }))} /></div>
            <div className="w-52"><Select aria-label="Status" value={status} placeholder="Every status" onChange={(e) => setStatus(e.target.value)} options={[...(d?.statuses ?? []), 'No sheet yet'].map((x) => ({ value: x === 'No sheet yet' ? 'none' : x, label: x }))} /></div>
            <span className="text-[13px] text-muted-foreground">{rows.length} of {d?.drawings.length ?? 0}</span>
          </div>
          <DataTable label="Drawings" rows={rows} columns={columns} rowKey={(w) => w.id} loading={q.isPending && job > 0} empty={d?.drawings.length ? 'No drawing matches the filters.' : 'No drawings on the register. Add each sheet by its number, then its revisions as they arrive.'} />
      <AddDrawingModal job={job} disciplines={d?.disciplines ?? []} open={adding} onClose={() => setAdding(false)} onAdded={(id, number) => { setAdding(false); setRevising(d?.drawings.find((w) => w.id === id) ?? ({ id, number, title: '', discipline: '', current_revision: '', revisions: 0, status: '', received_on: '', current_file_id: null } as Drawing)) }} />
      <RevisionModal drawing={revising} statuses={d?.statuses ?? []} onClose={() => setRevising(null)} />
      <Plan3DModal drawing={view3d} onClose={() => setView3d(null)} />
      <HistoryModal id={history} onClose={() => setHistory(null)} />
    </>
  )
}
