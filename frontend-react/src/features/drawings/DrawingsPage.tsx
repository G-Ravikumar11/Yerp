import { useState } from 'react'
import { Plus } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { ProjectPicker } from '@/components/data/ProjectPicker'
import { Badge, Button, Input, Select, Stat, StatGrid, Tabs } from '@/components/ui'
import { useDrawings, type Drawing } from '@/api/drawings'
import { useSession } from '@/lib/session'
import { formatDate } from '@/lib/format'
import { AddDrawingModal, HistoryModal, RevisionModal } from './DrawingModals'
import { PhotosTab } from './PhotosTab'
import { MasterDelete } from '@/features/deleteorder/MasterDelete'

type Tab = 'drawings' | 'photos'
const tone = (s: string) => (s === 'Good for construction' ? 'success' : s === 'For approval' ? 'warning' : 'neutral') as 'success' | 'warning' | 'neutral'

/** Every sheet and every revision, the one to build to marked - and the site's photographs. */
export default function DrawingsPage() {
  const { can } = useSession()
  const [job, setJob] = useState(0)
  const [tab, setTab] = useState<Tab>('drawings')
  const q = useDrawings(job)
  const d = q.data
  const [search, setSearch] = useState('')
  const [disc, setDisc] = useState('')
  const [status, setStatus] = useState('')
  const [adding, setAdding] = useState(false)
  const [revising, setRevising] = useState<Drawing | null>(null)
  const [history, setHistory] = useState<number | null>(null)
  const words = search.toLowerCase()
  const rows = (d?.drawings ?? []).filter((w) => (!words || `${w.number} ${w.title}`.toLowerCase().includes(words)) && (!disc || w.discipline === disc) && (!status || (status === 'none' ? !w.current_revision : w.status === status)))
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
          {w.current_file_id && <Button size="sm" variant="outline" asChild><a href={`/api/files/${w.current_file_id}`} target="_blank" rel="noopener">Open</a></Button>}
          <Button size="sm" variant="outline" onClick={() => setRevising(w)}>New revision</Button>
          <Button size="sm" variant="outline" onClick={() => setHistory(w.id)}>History</Button>
        </div>
      ),
    },
    { id: 'master-del', header: '', align: 'right', width: '3.5rem', cell: (r) => <MasterDelete kind="drawing" id={r.id} label={String(r.number)} noun="drawing" /> },
  ]
  return (
    <>
      <PageHeader eyebrow="Projects" title="Drawings & Photos" description="Every sheet and every revision, the one to build to marked - and the site's photographs." actions={can('workorders.manage') && tab === 'drawings' && <Button disabled={!job} onClick={() => setAdding(true)}><Plus /> Drawing</Button>} />
      <div className="mb-6"><ProjectPicker value={job} onChange={setJob} id="drw-job" /></div>
      <div className="mb-5"><Tabs label="Drawings and photos" value={tab} onChange={setTab} items={[{ value: 'drawings', label: 'Drawings register' }, { value: 'photos', label: 'Photos & files' }]} /></div>
      {tab === 'photos' ? (job > 0 ? <PhotosTab job={job} /> : null) : (
        <>
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
        </>
      )}
      <AddDrawingModal job={job} disciplines={d?.disciplines ?? []} open={adding} onClose={() => setAdding(false)} onAdded={(id, number) => { setAdding(false); setRevising(d?.drawings.find((w) => w.id === id) ?? ({ id, number, title: '', discipline: '', current_revision: '', revisions: 0, status: '', received_on: '', current_file_id: null } as Drawing)) }} />
      <RevisionModal drawing={revising} statuses={d?.statuses ?? []} onClose={() => setRevising(null)} />
      <HistoryModal id={history} onClose={() => setHistory(null)} />
    </>
  )
}
