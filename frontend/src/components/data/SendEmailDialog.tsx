import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Paperclip } from 'lucide-react'
import { Button, Field, Input, Modal, Skeleton, Textarea } from '@/components/ui'
import { get, post } from '@/lib/api'
import { useAction } from '@/lib/mutate'

interface Draft { to: string; subject: string; body: string; attachment?: string }

/**
 * Email a document from its own page. The wording is read first and can be changed; nothing leaves until Send is pressed.
 * `draftUrl` gives the wording and the address on file, `sendUrl` takes the (possibly edited) To, Subject and Body.
 */
export function SendEmailDialog({ open, onOpenChange, title, draftUrl, sendUrl, invalidate = [] }: {
  open: boolean
  onOpenChange: (o: boolean) => void
  title: string
  draftUrl: string
  sendUrl: string
  invalidate?: readonly unknown[][]
}) {
  const q = useQuery({ queryKey: ['email-draft', draftUrl], queryFn: () => get<Draft>(draftUrl), enabled: open, gcTime: 0, staleTime: 0 })
  const [f, setF] = useState({ to: '', subject: '', body: '' })
  useEffect(() => {
    if (q.data) setF({ to: q.data.to, subject: q.data.subject, body: q.data.body })
  }, [q.data])
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => setF((s) => ({ ...s, [k]: e.target.value }))
  const send = useAction(() => post<{ message?: string }>(sendUrl, f), { invalidate: [...invalidate], success: (r) => r.message || 'Email sent', onSuccess: () => onOpenChange(false) })
  return (
    <Modal
      open={open}
      onOpenChange={onOpenChange}
      title={title}
      description="Read it, change what you like, then send. The document goes with it as a PDF."
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button loading={send.isPending} disabled={!q.data || !f.to.trim()} onClick={() => send.mutate()}>Send email</Button>
        </>
      }
    >
      {q.isPending ? (
        <Skeleton className="h-48 w-full" />
      ) : (
        <div className="grid gap-4">
          <Field label="To" htmlFor="se-to" hint={f.to ? undefined : 'No email address on file. Type one here.'}>
            <Input id="se-to" type="email" value={f.to} onChange={set('to')} placeholder="name@company.com" />
          </Field>
          <Field label="Subject" htmlFor="se-subject">
            <Input id="se-subject" value={f.subject} onChange={set('subject')} />
          </Field>
          <Field label="Message" htmlFor="se-body">
            <Textarea id="se-body" rows={9} value={f.body} onChange={set('body')} />
          </Field>
          {q.data?.attachment && <p className="flex items-center gap-1.5 text-xs text-muted-foreground"><Paperclip className="size-3.5" /> {q.data.attachment}</p>}
        </div>
      )}
    </Modal>
  )
}
