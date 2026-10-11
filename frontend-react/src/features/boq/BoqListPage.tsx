import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Plus } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { Badge, Button, Field, Input, Modal, Select } from '@/components/ui'
import { boqKeys, createBoq, useBoqs, type BoqHead } from '@/api/boq'
import { projectLabel, useProjects } from '@/api/projects'
import { useAction } from '@/lib/mutate'
import { useSession } from '@/lib/session'
import { formatINR } from '@/lib/utils'
import { MasterDelete } from '@/features/deleteorder/MasterDelete'

/** Every project's BOQ: the client's bill of quantities, once, with its revisions. */
export default function BoqListPage() {
  const nav = useNavigate()
  const { can } = useSession()
  const list = useBoqs()
  const projects = useProjects()
  const [creating, setCreating] = useState(false)
  const [job, setJob] = useState('')
  const [title, setTitle] = useState('')
  const rows = list.data?.boqs ?? []
  const withBoq = new Set(rows.map((b) => b.job_id))
  const create = useAction(() => createBoq(Number(job), title.trim()), {
    invalidate: [boqKeys.all],
    success: (r) => r.message,
    onSuccess: (r) => {
      setCreating(false)
      nav(`/projects/boq/${r.boq.id}`)
    },
  })

  const columns: TableColumn<BoqHead>[] = [
    { id: 'no', header: 'BOQ', width: '7rem', sort: (b) => b.number, cell: (b) => <span className="font-mono text-[13px] font-semibold">{b.number}</span> },
    {
      id: 'project',
      header: 'Project',
      sort: (b) => b.project,
      cell: (b) => (
        <div className="max-w-sm">
          <div className="truncate font-medium">{b.project}</div>
          <div className="truncate text-xs text-muted-foreground">{b.customer || b.title}</div>
        </div>
      ),
    },
    { id: 'rev', header: 'Revision', cell: (b) => <Badge tone={b.status === 'OPEN' ? 'warning' : 'success'}>{b.revision}</Badge> },
    { id: 'items', header: 'Priced lines', align: 'right', hideBelow: 'md', cell: (b) => b.items },
    { id: 'total', header: 'Value', align: 'right', sort: (b) => b.total, cell: (b) => <span className="font-semibold">{formatINR(b.total)}</span> },
    { id: 'master-del', header: '', align: 'right', width: '3.5rem', cell: (r) => <MasterDelete kind="boq" id={r.id} label={String(r.number)} noun="BOQ" /> },
  ]

  return (
    <>
      <PageHeader
        eyebrow="Projects"
        title="BOQ"
        description="The client's bill of quantities, kept once. Sections, items and sub-items as their sheet numbers them; orders and bills hang off it."
        actions={
          can('workorders.manage') && (
            <Button onClick={() => setCreating(true)}>
              <Plus /> New BOQ
            </Button>
          )
        }
      />
      <DataTable label="BOQs" rows={rows} columns={columns} rowKey={(b) => b.id} loading={list.isPending} onRowClick={(b) => nav(`/projects/boq/${b.id}`)} empty="No BOQ yet. Start one for a project, then paste or import the client's sheet." />

      <Modal
        open={creating}
        onOpenChange={setCreating}
        title="New BOQ"
        description="One BOQ to a project. It opens as R0, ready for the client's sheet."
        footer={
          <>
            <Button variant="ghost" onClick={() => setCreating(false)}>
              Cancel
            </Button>
            <Button loading={create.isPending} disabled={!job} onClick={() => create.mutate()}>
              Open the BOQ
            </Button>
          </>
        }
      >
        <div className="grid gap-4">
          <Field label="Project" htmlFor="boq-project">
            <Select
              id="boq-project"
              value={job}
              onChange={(e) => setJob(e.target.value)}
              placeholder="Choose the project"
              options={(projects.data ?? []).filter((p) => !withBoq.has(p.id)).map((p) => ({ value: p.id, label: projectLabel(p) }))}
            />
          </Field>
          <Field label="Title (optional)" htmlFor="boq-title">
            <Input id="boq-title" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="BOQ - Tower C" />
          </Field>
        </div>
      </Modal>
    </>
  )
}
