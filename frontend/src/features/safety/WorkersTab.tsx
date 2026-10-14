import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { FileText, Trash2, UserPlus } from 'lucide-react'
import { toast } from '@/stores/toast'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { ProjectPicker } from '@/components/data/ProjectPicker'
import { Badge, Button, ConfirmDialog, Field, Input, Modal, Select, Stat, StatGrid, Textarea } from '@/components/ui'
import { removeWorker, screenWorker, useWorkers, workerKeys, type Worker } from '@/api/safety'
import { uploadFiles } from '@/api/files'
import { useAction } from '@/lib/mutate'
import { useSession } from '@/lib/session'
import { formatDate, today } from '@/lib/format'
import { apiUrl } from '@/lib/api'

const initials = (name: string) => name.split(/\s+/).filter(Boolean).slice(0, 2).map((p) => p[0]?.toUpperCase()).join('') || '?'

/** The Workers tab: every worker screened before starting on site - who they are, their trade, photo and medical certificate. */
export function WorkersTab() {
  const { can } = useSession()
  const [job, setJob] = useState(0)
  const [screening, setScreening] = useState(false)
  const [removing, setRemoving] = useState<Worker | null>(null)
  const q = useWorkers(job)
  const d = q.data
  const s = d?.summary
  const remove = useAction((w: Worker) => removeWorker(w.id), { invalidate: [workerKeys.all], onSuccess: () => setRemoving(null) })

  const columns: TableColumn<Worker>[] = [
    { id: 'sn', header: 'S.No.', width: '4rem', cell: (w) => <span className="tabular text-muted-foreground">{(d?.workers.indexOf(w) ?? 0) + 1}</span> },
    {
      id: 'who',
      header: 'Worker',
      cell: (w) => (
        <div className="flex items-center gap-3">
          {w.photo_url ? (
            <a href={apiUrl(w.photo_full_url)} target="_blank" rel="noopener" className="shrink-0">
              <img src={apiUrl(w.photo_url)} alt={`${w.name}'s photo`} className="size-10 rounded-full object-cover ring-1 ring-border" loading="lazy" />
            </a>
          ) : (
            <span className="grid size-10 shrink-0 place-items-center rounded-full bg-muted text-xs font-semibold text-muted-foreground" title="No photo yet">{initials(w.name)}</span>
          )}
          <div className="min-w-0">
            <div className="font-medium">{w.name}</div>
            <div className="font-mono text-xs text-muted-foreground">{w.number}</div>
          </div>
        </div>
      ),
    },
    { id: 'age', header: 'Age', width: '4.5rem', sort: (w) => w.age, cell: (w) => <span className="tabular">{w.age}</span> },
    { id: 'trade', header: 'Trade', sort: (w) => w.trade, cell: (w) => <Badge tone={w.trade.includes('helper') || w.trade.startsWith('Unskilled') ? 'neutral' : 'info'}>{w.trade}</Badge> },
    { id: 'addr', header: 'Address', hideBelow: 'lg', cell: (w) => <span className="line-clamp-2 max-w-64 text-muted-foreground">{w.address || '-'}</span> },
    {
      id: 'med',
      header: 'Medical certificate',
      cell: (w) =>
        w.medical.length ? (
          <div className="flex flex-col gap-0.5">
            {w.medical.map((m) => (
              <a key={m.id} href={apiUrl(m.url)} target="_blank" rel="noopener" className="inline-flex items-center gap-1 text-[13px] text-primary hover:underline">
                <FileText className="size-3.5" /> <span className="max-w-40 truncate">{m.name}</span>
              </a>
            ))}
          </div>
        ) : (
          <Badge tone="warning" dot>Not given</Badge>
        ),
    },
    { id: 'on', header: 'Screened', hideBelow: 'md', sort: (w) => w.screened_on, cell: (w) => <div>{formatDate(w.screened_on)}{w.screened_by && <div className="text-xs text-muted-foreground">by {w.screened_by}</div>}</div> },
    {
      id: 'del',
      header: '',
      align: 'right',
      width: '3.5rem',
      cell: (w) => (can('site.signoff') ? <Button size="icon" variant="ghost" aria-label={`Remove ${w.name}`} onClick={() => setRemoving(w)}><Trash2 /></Button> : null),
    },
  ]

  return (
    <div>
      <div className="mb-6 flex flex-wrap items-center gap-3">
        <div className="min-w-64 flex-1 sm:max-w-md"><ProjectPicker value={job} onChange={setJob} id="wk-job" allowAll /></div>
        <Button className="ml-auto" disabled={!job} title={job ? undefined : 'Pick a project first'} onClick={() => setScreening(true)}><UserPlus /> Add worker</Button>
      </div>
      <StatGrid className="lg:grid-cols-2 xl:grid-cols-2">
        <Stat label="Workers added" value={s?.workers ?? 0} loading={q.isPending} />
        <Stat label="Without a medical certificate" value={s?.without_medical ?? 0} tone={s?.without_medical ? 'warning' : undefined} loading={q.isPending} />
      </StatGrid>
      {d && d.workers.length > 0 && (
        <div className="mb-4 flex flex-wrap gap-2" aria-label="Workers by trade">
          {d.trades.map((t) => (
            <span key={t} className="inline-flex items-center gap-1.5 rounded-full border border-border bg-card px-3 py-1 text-xs">
              {t} <span className="tabular font-semibold">{s?.by_trade[t] ?? 0}</span>
            </span>
          ))}
        </div>
      )}
      <DataTable label="Workers" rows={d?.workers ?? []} columns={columns} rowKey={(w) => w.id} loading={q.isPending} empty={job ? 'Nobody screened on this project yet. Screen each worker before they start.' : 'Nobody screened yet. Pick a project and screen each worker before they start.'} />

      <ScreeningModal job={job} trades={d?.trades ?? []} minAge={d?.min_age ?? 18} open={screening} onClose={() => setScreening(false)} />
      <ConfirmDialog
        open={!!removing}
        onOpenChange={(o) => !o && setRemoving(null)}
        title={removing ? `Remove ${removing.name}?` : ''}
        description="Their photo and medical certificate go with them. It cannot be undone."
        confirmLabel="Remove"
        tone="danger"
        loading={remove.isPending}
        onConfirm={() => { if (removing) remove.mutate(removing) }}
      />
    </div>
  )
}

/** The screening form: who, how old, where from, which trade - then the photo and the medical certificate. */
function ScreeningModal({ job, trades, minAge, open, onClose }: { job: number; trades: string[]; minAge: number; open: boolean; onClose: () => void }) {
  return (
    <Modal open={open} onOpenChange={(o) => !o && onClose()} title="Screening form" description="Screen every worker before they start on site.">
      {open && <ScreeningForm job={job} trades={trades} minAge={minAge} onClose={onClose} />}
    </Modal>
  )
}

function ScreeningForm({ job, trades, minAge, onClose }: { job: number; trades: string[]; minAge: number; onClose: () => void }) {
  const qc = useQueryClient()
  const [f, setF] = useState({ name: '', age: '', address: '', trade: trades[0] ?? '', screened_on: today() })
  const [photo, setPhoto] = useState<File | null>(null)
  const [medical, setMedical] = useState<File[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF((x) => ({ ...x, [k]: e.target.value }))
  const age = parseInt(f.age, 10)
  const ready = f.name.trim() && age >= minAge && f.trade

  const save = async () => {
    setBusy(true)
    setError('')
    try {
      const { worker } = await screenWorker({ job_id: job, name: f.name.trim(), age, address: f.address, trade: f.trade, screened_on: f.screened_on })
      const failed: string[] = []
      if (photo) failed.push(...(await uploadFiles([photo], 'worker', worker.id, { caption: 'Photo', kind: 'photo' })).failed)
      if (medical.length) failed.push(...(await uploadFiles(medical, 'worker', worker.id, { caption: 'Medical certificate', kind: 'document' })).failed)
      await qc.invalidateQueries({ queryKey: workerKeys.all })
      if (failed.length) toast.error(`${worker.name} screened, but a file did not go up: ${failed[0]}`)
      else toast.success(`${worker.name} screened as ${worker.trade.toLowerCase()}`)
      onClose()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Not saved. Try again.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div>
      <div className="grid gap-4 sm:grid-cols-3">
        <Field label="Name" htmlFor="wk-name" className="sm:col-span-2"><Input id="wk-name" value={f.name} autoFocus onChange={set('name')} /></Field>
        <Field label="Age" htmlFor="wk-age" hint={f.age && age < minAge ? `At least ${minAge}` : undefined}><Input id="wk-age" type="number" inputMode="numeric" min={minAge} max={75} value={f.age} onChange={set('age')} /></Field>
        <Field label="Address" htmlFor="wk-addr" className="sm:col-span-3"><Textarea id="wk-addr" rows={2} value={f.address} onChange={set('address')} /></Field>
        <Field label="Trade" htmlFor="wk-trade" className="sm:col-span-2"><Select id="wk-trade" value={f.trade} onChange={set('trade')} options={trades.map((t) => ({ value: t, label: t }))} /></Field>
        <Field label="Screened on" htmlFor="wk-on"><Input id="wk-on" type="date" value={f.screened_on} onChange={set('screened_on')} /></Field>
        <Field label="Picture" htmlFor="wk-photo" className="sm:col-span-3" hint="A clear photo of the face. On a phone this opens the camera.">
          <Input id="wk-photo" type="file" accept="image/*" capture="user" onChange={(e) => setPhoto(e.target.files?.[0] ?? null)} />
        </Field>
        <Field label="Medical certificate" htmlFor="wk-med" className="sm:col-span-3" hint="A photo or a PDF. More than one if there are several pages.">
          <Input id="wk-med" type="file" accept="image/*,application/pdf" multiple onChange={(e) => setMedical(Array.from(e.target.files ?? []))} />
        </Field>
      </div>
      <div className="mt-5 flex items-center justify-end gap-2 border-t border-border pt-4">
        {error && <p role="alert" className="mr-auto text-[13px] text-danger">{error}</p>}
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button loading={busy} disabled={!ready} onClick={() => void save()}>Save the screening</Button>
      </div>
    </div>
  )
}
