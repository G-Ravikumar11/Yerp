import { useRef, useState } from 'react'
import { Download, Upload } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { Badge, Button, Field, Input, Modal, Skeleton } from '@/components/ui'
import { downloadMyFile, staffKeys, uploadDocument, useMyDocuments, type DocRequest, type MyFile } from '@/api/staff'
import { useAction } from '@/lib/mutate'
import { formatDate } from '@/lib/format'

const tone = (s: string) => (s === 'approved' ? 'success' : s === 'rejected' ? 'danger' : s === 'submitted' ? 'info' : 'warning') as 'success' | 'danger' | 'info' | 'warning'

/** What HR has asked this person for, and the files HR holds for them. */
export default function DocumentsPage() {
  const q = useMyDocuments()
  const [sending, setSending] = useState<DocRequest | null>(null)
  const files: TableColumn<MyFile>[] = [
    { id: 'title', header: 'Document', cell: (f) => f.title },
    { id: 'name', header: 'File', hideBelow: 'md', cell: (f) => <span className="text-muted-foreground">{f.file_name}</span> },
    { id: 'by', header: 'Added by', hideBelow: 'lg', cell: (f) => f.uploaded_by || '-' },
    { id: 'on', header: 'Added', hideBelow: 'md', cell: (f) => formatDate(f.created_at) },
    { id: 'dl', header: '', align: 'right', cell: (f) => <Button size="sm" variant="outline" onClick={() => void downloadMyFile(f.id)}><Download /> Download</Button> },
  ]
  return (
    <>
      <PageHeader eyebrow="My work" title="Documents" description="The documents HR has asked you for, and the files they hold for you." />
      <h2 className="mb-3 text-sm font-semibold">Asked of you</h2>
      {q.isPending ? <Skeleton className="h-28 w-full" /> : q.data?.requests.length ? (
        <div className="mb-8 grid gap-3">
          {q.data.requests.map((r) => (
            <section key={r.id} aria-label={r.name} className="flex flex-wrap items-center gap-3 rounded-xl border border-border bg-card p-4 shadow-card">
              <div className="min-w-0 flex-1">
                <p className="font-medium">{r.name}{r.is_mandatory && <span className="ml-1.5 text-xs text-muted-foreground">(required)</span>}</p>
                {r.description && <p className="text-[13px] text-muted-foreground">{r.description}</p>}
                <p className="mt-1 text-xs text-muted-foreground">{r.due_date ? `Due ${formatDate(r.due_date)}` : 'No due date'}{r.file_name && ` · ${r.file_name}`}{r.expires_on && ` · expires ${formatDate(r.expires_on)}`}</p>
                {r.status === 'rejected' && r.review_note && <p className="mt-1 text-[13px] text-danger">HR sent it back: {r.review_note}</p>}
              </div>
              {r.is_overdue && <Badge tone="danger">Overdue</Badge>}
              <Badge tone={tone(r.status)} dot>{r.status.charAt(0).toUpperCase() + r.status.slice(1)}</Badge>
              {r.status !== 'approved' && <Button size="sm" variant={r.status === 'submitted' ? 'outline' : 'primary'} onClick={() => setSending(r)}><Upload /> {r.status === 'submitted' ? 'Replace' : 'Upload'}</Button>}
            </section>
          ))}
        </div>
      ) : <p className="mb-8 rounded-lg border border-border bg-muted/40 p-4 text-sm">Nothing has been asked of you.</p>}
      <h2 className="mb-3 text-sm font-semibold">Your files</h2>
      <DataTable label="Files" rows={q.data?.files ?? []} columns={files} rowKey={(f) => f.id} loading={q.isPending} empty="No files yet." />
      <Modal open={!!sending} onOpenChange={(o) => !o && setSending(null)} title={sending ? `Upload ${sending.name}` : 'Upload'} description={q.data ? `PDF, Word, image or text, up to ${q.data.limits.max_mb} MB.` : undefined}>
        {sending && <UploadForm key={sending.id} request={sending} onClose={() => setSending(null)} />}
      </Modal>
    </>
  )
}

function UploadForm({ request, onClose }: { request: DocRequest; onClose: () => void }) {
  const input = useRef<HTMLInputElement>(null)
  const [file, setFile] = useState<File | null>(null)
  const [expires, setExpires] = useState('')
  const send = useAction(() => uploadDocument(request.id, file as File, expires), { invalidate: [staffKeys.all], success: 'Uploaded. HR will review it.', onSuccess: onClose })
  return (
    <div>
      <div className="grid gap-4">
        <Field label="File" htmlFor="doc-file"><Input id="doc-file" ref={input} type="file" accept=".pdf,.doc,.docx,.png,.jpg,.jpeg,.webp,.txt" onChange={(e) => setFile(e.target.files?.[0] ?? null)} /></Field>
        {request.requires_expiry && <Field label="Expiry date on the document" htmlFor="doc-exp"><Input id="doc-exp" type="date" value={expires} onChange={(e) => setExpires(e.target.value)} /></Field>}
      </div>
      <div className="mt-5 flex items-center justify-end gap-2 border-t border-border pt-4">
        {send.error && <p role="alert" className="mr-auto text-[13px] text-danger">{send.error.message}</p>}
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button loading={send.isPending} disabled={!file || (request.requires_expiry && !expires)} onClick={() => send.mutate()}>Upload</Button>
      </div>
    </div>
  )
}
