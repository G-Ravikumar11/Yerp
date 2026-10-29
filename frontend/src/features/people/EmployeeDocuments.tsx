import { useRef, useState } from 'react'
import { Download, Trash2, Upload, X } from 'lucide-react'
import { useQueryClient } from '@tanstack/react-query'
import { Button, ConfirmDialog, Field, Input, Select } from '@/components/ui'
import { DOCUMENT_ACCEPT, ID_DOCUMENTS, deleteEmployeeDocument, downloadEmployeeDocument, peopleKeys, uploadEmployeeDocument, useEmployeeDocuments, type EmployeeDoc } from '@/api/people'
import { useAction } from '@/lib/mutate'
import { formatDate } from '@/lib/format'

/** Under a card's number. It stays out of the way until the number is clicked, then offers "Upload document". */
export function DocumentPick({ label, file, shown, onFile }: { label: string; file: File | null; shown: boolean; onFile: (file: File | null) => void }) {
  const input = useRef<HTMLInputElement>(null)
  if (!shown && !file) return null
  return (
    <div className="mt-1.5 flex flex-wrap items-center gap-2">
      <input ref={input} type="file" hidden aria-label={`Attach ${label}`} accept={DOCUMENT_ACCEPT} onChange={(e) => onFile(e.target.files?.[0] ?? null)} />
      <Button type="button" size="sm" variant="outline" onClick={() => input.current?.click()}><Upload /> Upload document</Button>
      {file && (
        <span className="flex min-w-0 items-center gap-1 text-[12px] text-muted-foreground">
          <span className="truncate">{file.name}</span>
          <Button type="button" size="sm" variant="ghost" aria-label={`Remove the attached ${label}`} onClick={() => { if (input.current) input.current.value = ''; onFile(null) }}><X /></Button>
        </span>
      )}
    </div>
  )
}

const size = (bytes: number) => (bytes >= 1048576 ? `${(bytes / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`)

/** The Aadhaar, PAN and ESI cards kept for one employee: what is on file, and a place to add or take one away. */
export function EmployeeDocuments({ id, canManage }: { id: number; canManage: boolean }) {
  const q = useEmployeeDocuments(id)
  const qc = useQueryClient()
  const [which, setWhich] = useState<string>(ID_DOCUMENTS[0].key)
  const [file, setFile] = useState<File | null>(null)
  const [removing, setRemoving] = useState<EmployeeDoc | null>(null)
  const input = useRef<HTMLInputElement>(null)
  const refresh = () => void qc.invalidateQueries({ queryKey: [...peopleKeys.all, 'documents', id] })
  const slot = ID_DOCUMENTS.find((d) => d.key === which) ?? ID_DOCUMENTS[0]
  const add = useAction(() => uploadEmployeeDocument(id, slot.title, slot.type, file as File), {
    success: `${slot.title} kept on file`,
    onSuccess: () => { setFile(null); if (input.current) input.current.value = ''; refresh() },
  })
  const remove = useAction((doc: EmployeeDoc) => deleteEmployeeDocument(id, doc.id), { success: 'Document removed', onSuccess: () => { setRemoving(null); refresh() } })
  const docs = q.data ?? []
  return (
    <section aria-label="Documents" className="mt-8 border-t border-border pt-5">
      <h3 className="text-base font-semibold">Documents</h3>
      <p className="mt-1 text-sm text-muted-foreground">Aadhaar, PAN and ESI cards, as a photo (JPG, PNG, WEBP) or a PDF, up to 5 MB each.</p>
      {docs.length === 0 ? <p className="mt-3 text-sm text-muted-foreground">Nothing on file yet.</p> : (
        <ul className="mt-3 divide-y divide-border rounded-lg border border-border">
          {docs.map((d) => (
            <li key={d.id} className="flex flex-wrap items-center gap-3 px-3 py-2.5 text-sm">
              <span className="min-w-32 font-medium">{d.title}</span>
              <span className="min-w-0 flex-1 truncate text-muted-foreground">{d.file_name}{d.file_size ? ` - ${size(d.file_size)}` : ''} - {formatDate(d.created_at.slice(0, 10))}</span>
              <Button size="sm" variant="outline" onClick={() => void downloadEmployeeDocument(id, d.id)}><Download /> Download</Button>
              {canManage && <Button size="sm" variant="ghost" className="text-danger" aria-label={`Remove ${d.title}`} onClick={() => setRemoving(d)}><Trash2 /></Button>}
            </li>
          ))}
        </ul>
      )}
      {canManage && (
        <div className="mt-4 grid items-end gap-3 sm:grid-cols-[12rem_1fr_auto]">
          <Field label="Document" htmlFor="doc-kind"><Select id="doc-kind" value={which} onChange={(e) => setWhich(e.target.value)} options={ID_DOCUMENTS.map((d) => ({ value: d.key, label: d.title }))} /></Field>
          <Field label="File" htmlFor="doc-file"><Input id="doc-file" ref={input} type="file" accept={DOCUMENT_ACCEPT} onChange={(e) => setFile(e.target.files?.[0] ?? null)} /></Field>
          <Button loading={add.isPending} disabled={!file} onClick={() => add.mutate()}><Upload /> Upload</Button>
        </div>
      )}
      <ConfirmDialog open={!!removing} onOpenChange={(o) => !o && setRemoving(null)} title={`Remove ${removing?.title ?? ''}?`} description="The file is deleted from this employee's record." confirmLabel="Remove it" tone="danger" loading={remove.isPending} onConfirm={() => { if (removing) remove.mutate(removing) }} />
    </section>
  )
}
