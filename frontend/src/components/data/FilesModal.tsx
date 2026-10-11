import { useRef, useState } from 'react'
import { Camera, Paperclip } from 'lucide-react'
import { Button, ConfirmDialog, Input, Modal, Skeleton, Tabs } from '@/components/ui'
import { fileKeys, fileSize, noFilter, removeFile, uploadFiles, useFiles, type FileItem } from '@/api/files'
import { useAction } from '@/lib/mutate'
import { useQueryClient } from '@tanstack/react-query'
import { toast } from '@/stores/toast'

const KIND: Record<string, string> = { drawing: 'Drawing', photo: 'Photo', document: 'Document' }

/** The photos and papers kept against one record: a diary day, a measurement, an inspection. On a phone "Take a photo" opens the camera. */
export function FilesModal({ type, id, title, onClose }: { type: string; id: number; title: string; onClose: () => void }) {
  const [kind, setKind] = useState('')
  const [caption, setCaption] = useState('')
  const [busy, setBusy] = useState(false)
  const [removing, setRemoving] = useState<FileItem | null>(null)
  const pick = useRef<HTMLInputElement>(null)
  const camera = useRef<HTMLInputElement>(null)
  const qc = useQueryClient()
  const q = useFiles(type, id, { ...noFilter, kind })
  const remove = useAction((f: FileItem) => removeFile(f.id), { invalidate: [fileKeys.all], success: 'File removed', onSuccess: () => setRemoving(null) })
  const s = q.data?.summary
  const send = async (list: FileList | null) => {
    if (!list?.length) return
    setBusy(true)
    const { done, failed } = await uploadFiles([...list], type, id, caption.trim() ? { caption: caption.trim() } : {})
    setBusy(false)
    setCaption('')
    await qc.invalidateQueries({ queryKey: fileKeys.all })
    if (failed.length) toast.error(failed.join(' - '))
    else if (done) toast.success(`${done} file${done === 1 ? '' : 's'} added`)
  }
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} title={`Photos and files - ${title}`} size="xl">
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <Tabs label="Kind" value={kind} onChange={setKind} items={[{ value: '', label: 'All' }, { value: 'photo', label: 'Photos', count: kind ? undefined : s?.photos }, { value: 'drawing', label: 'Drawings', count: kind ? undefined : s?.drawings }, { value: 'document', label: 'Documents', count: kind ? undefined : s?.documents }]} />
        {!q.data?.locked && (
          <div className="ml-auto flex flex-wrap items-center gap-2">
            <div className="w-56"><Input aria-label="Caption" placeholder="Caption (optional)" value={caption} onChange={(e) => setCaption(e.target.value)} /></div>
            <input ref={camera} type="file" accept="image/*" capture="environment" className="sr-only" aria-label="Take a photo" onChange={(e) => { void send(e.target.files); e.target.value = '' }} />
            <input ref={pick} type="file" multiple className="sr-only" aria-label="Choose files" onChange={(e) => { void send(e.target.files); e.target.value = '' }} />
            <Button variant="outline" loading={busy} onClick={() => camera.current?.click()}><Camera /> Take a photo</Button>
            <Button loading={busy} onClick={() => pick.current?.click()}><Paperclip /> Add files</Button>
          </div>
        )}
      </div>
      {q.data?.locked && <p className="mb-3 rounded-lg bg-muted/50 p-2.5 text-[13px]">This has been signed off, so its photographs are kept as they are.</p>}
      {q.isPending ? <Skeleton className="h-40 w-full" /> : q.data?.files.length ? (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
          {q.data.files.map((f) => <Tile key={f.id} f={f} onRemove={q.data?.locked ? undefined : () => setRemoving(f)} />)}
        </div>
      ) : <p className="text-sm text-muted-foreground">Nothing kept against this yet. On a phone, Take a photo opens the camera.</p>}
      {s && s.count ? <p className="mt-3 text-xs text-muted-foreground">{s.count} file{s.count === 1 ? '' : 's'} - {fileSize(s.stored_bytes)} stored{(s.saved_bytes ?? 0) > 1024 ? ` - ${fileSize(s.saved_bytes)} saved by making them smaller and keeping each once` : ''}</p> : null}
      <ConfirmDialog open={!!removing} onOpenChange={(o) => !o && setRemoving(null)} title="Remove this file?" description={removing?.caption || removing?.name} confirmLabel="Remove" tone="danger" loading={remove.isPending} onConfirm={() => { if (removing) remove.mutate(removing) }} />
    </Modal>
  )
}

export function Tile({ f, onRemove }: { f: FileItem; onRemove?: () => void }) {
  return (
    <figure className="rounded-lg border border-border p-1.5">
      <a href={f.url} target="_blank" rel="noopener">
        {f.is_image ? <img src={f.thumb_url} alt={f.caption || f.name} loading="lazy" className="h-28 w-full rounded-md object-cover" /> : <span className="grid h-28 place-items-center rounded-md bg-muted text-sm font-bold text-muted-foreground">{(f.name.split('.').pop() || 'file').toUpperCase()}</span>}
      </a>
      <figcaption className="mt-1 text-xs leading-snug">
        <span className="mr-1 rounded bg-primary-soft px-1 text-[10px] font-semibold text-primary">{KIND[f.kind] ?? f.kind}</span>{f.caption || f.name}
        <span className="block text-[11px] text-muted-foreground">{fileSize(f.size)}{f.taken_on && ` - ${f.taken_on}`}{f.uploaded_by_name && ` - ${f.uploaded_by_name}`}</span>
      </figcaption>
      {onRemove && <button type="button" className="mt-1 text-[11px] text-danger underline-offset-2 hover:underline" onClick={onRemove}>Remove</button>}
    </figure>
  )
}
