import { useRef, useState } from 'react'
import { Camera, FileUp } from 'lucide-react'
import { useQueryClient } from '@tanstack/react-query'
import { Tile } from '@/components/data/FilesModal'
import { Button, ConfirmDialog, Input, Select, Skeleton, Stat, StatGrid, Tabs } from '@/components/ui'
import { drwKeys, useJobPhotos } from '@/api/drawings'
import { fileKeys, fileSize, noFilter, removeFile, uploadFiles, type FileItem } from '@/api/files'
import { useAction } from '@/lib/mutate'
import { toast } from '@/stores/toast'

const SOURCES = [['', 'Kept against: anything'], ['subcontract_order,work_order', 'Work orders'], ['diary', 'Site diary'], ['measurement', 'Measurements'], ['variation', 'Variations'], ['job', 'The project'], ['inspection,ncr', 'Quality'], ['incident', 'Safety']] as const

/** Every photograph, drawing and paper kept on the project, wherever it was added from. */
export function PhotosTab({ job }: { job: number }) {
  const [kind, setKind] = useState('')
  const [q, setQ] = useState('')
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const [source, setSource] = useState('')
  const [busy, setBusy] = useState(false)
  const [removing, setRemoving] = useState<FileItem | null>(null)
  const camera = useRef<HTMLInputElement>(null)
  const papers = useRef<HTMLInputElement>(null)
  const qc = useQueryClient()
  const res = useJobPhotos(job, kind, { ...noFilter, q, from, to }, source)
  const s = res.data?.summary
  const remove = useAction((f: FileItem) => removeFile(f.id), { invalidate: [drwKeys.all, fileKeys.all], success: 'File removed', onSuccess: () => setRemoving(null) })
  const send = async (list: FileList | null, asKind?: string) => {
    const chosen = list ? [...list] : []
    if (!chosen.length) return
    setBusy(true)
    const { done, failed } = await uploadFiles(chosen, 'job', job, asKind ? { kind: asKind } : {})
    setBusy(false)
    await qc.invalidateQueries({ queryKey: drwKeys.all })
    if (failed.length) toast.error(failed.join(' - '))
    else if (done) toast.success(`${done} file${done === 1 ? '' : 's'} added`)
  }
  return (
    <>
      <StatGrid className="lg:grid-cols-4 xl:grid-cols-4">
        <Stat label="Drawings" value={s?.drawings ?? 0} loading={res.isPending} />
        <Stat label="Photos" value={s?.photos ?? 0} loading={res.isPending} />
        <Stat label="Documents" value={s?.documents ?? 0} loading={res.isPending} />
        <Stat label="Storage used" value={fileSize(s?.stored_bytes) || '0 KB'} loading={res.isPending} />
      </StatGrid>
      <div className="mb-3 flex flex-wrap gap-2">
        <input ref={camera} type="file" accept="image/*" capture="environment" multiple className="sr-only" aria-label="Photos of the site" onChange={(e) => { void send(e.target.files); e.target.value = '' }} />
        <input ref={papers} type="file" accept=".pdf,.dwg,.dxf,image/*" multiple className="sr-only" aria-label="Drawings for the project" onChange={(e) => { void send(e.target.files, 'drawing'); e.target.value = '' }} />
        <Button loading={busy} onClick={() => camera.current?.click()}><Camera /> Photos of the site</Button>
        <Button variant="outline" loading={busy} onClick={() => papers.current?.click()}><FileUp /> Drawings for the project</Button>
      </div>
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <Tabs label="Kind" value={kind} onChange={setKind} items={[{ value: '', label: 'All' }, { value: 'drawing', label: 'Drawings' }, { value: 'photo', label: 'Photos' }, { value: 'document', label: 'Documents' }]} />
        <div className="w-52"><Input aria-label="Search" placeholder="Search name or caption" value={q} onChange={(e) => setQ(e.target.value)} /></div>
        <div className="w-36"><Input aria-label="Taken from" type="date" value={from} onChange={(e) => setFrom(e.target.value)} /></div>
        <div className="w-36"><Input aria-label="Taken to" type="date" value={to} onChange={(e) => setTo(e.target.value)} /></div>
        <div className="w-56"><Select aria-label="Kept against" value={source} onChange={(e) => setSource(e.target.value)} options={SOURCES.map(([v, l]) => ({ value: v, label: l }))} /></div>
      </div>
      {res.isPending ? <Skeleton className="h-40 w-full" /> : res.data?.photos.length ? (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">{res.data.photos.map((f) => <Tile key={f.id} f={f} onRemove={f.attached_type === 'job' ? () => setRemoving(f) : undefined} />)}</div>
      ) : <p className="rounded-lg border border-border bg-muted/40 p-4 text-sm">{q || from || to || kind || source ? 'Nothing matches the filters.' : 'Nothing on this project yet. Photos and drawings added to work orders, diary days, measurements and variations appear here too.'}</p>}
      <ConfirmDialog open={!!removing} onOpenChange={(o) => !o && setRemoving(null)} title="Remove this file?" description={removing?.caption || removing?.name} confirmLabel="Remove" tone="danger" loading={remove.isPending} onConfirm={() => { if (removing) remove.mutate(removing) }} />
    </>
  )
}
