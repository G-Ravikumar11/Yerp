import { useEffect, useRef, useState } from 'react'
import { ArrowLeft, Paperclip } from 'lucide-react'
import { Button, ConfirmDialog, Skeleton } from '@/components/ui'
import { MasterDelete } from '@/features/deleteorder/MasterDelete'
import { chatKeys, removeMessage, setClosed, useThread, type Message } from '@/api/chat'
import { useAction } from '@/lib/mutate'
import { cn } from '@/lib/utils'
import { Composer } from './Composer'

const when = (at: string) => {
  if (!at) return ''
  const d = new Date()
  const today = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
  return at.slice(0, 10) === today ? at.slice(11, 16) : `${at.slice(8, 10)}/${at.slice(5, 7)} ${at.slice(11, 16)}`
}

/** Words with the @names picked out. */
const body = (text: string) => text.split(/(@[A-Za-z][\w.]*(?: [A-Z][\w.]*)?)/g).map((part, i) => (part.startsWith('@') ? <strong key={i}>{part}</strong> : <span key={i}>{part}</span>))

/** One conversation: the messages, and a box to write in unless it is closed. */
export function MessagePane({ id, onBack }: { id: number; onBack: () => void }) {
  const q = useThread(id)
  const end = useRef<HTMLDivElement>(null)
  const [removing, setRemoving] = useState<Message | null>(null)
  const remove = useAction((m: Message) => removeMessage(m.id), { invalidate: [chatKeys.all], success: false, onSuccess: () => setRemoving(null) })
  const toggle = useAction((v: { closed: boolean }) => setClosed(id, v.closed), { invalidate: [chatKeys.all], success: (r) => r.message })
  const last = q.data?.messages.at(-1)?.id
  useEffect(() => { end.current?.scrollIntoView({ block: 'end' }) }, [last, id])
  const t = q.data?.thread
  if (q.isPending || !t) return <Skeleton className="m-4 h-64" />
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center gap-3 border-b border-border px-4 py-3">
        <Button variant="ghost" size="icon" className="lg:hidden" aria-label="Back to threads" onClick={onBack}><ArrowLeft /></Button>
        <div className="min-w-0 flex-1"><h2 className="truncate font-semibold">{t.title}</h2><p className="truncate text-xs text-muted-foreground">{t.project} - started by {t.started_by_name}</p></div>
        <Button size="sm" variant="outline" loading={toggle.isPending} onClick={() => toggle.mutate({ closed: !t.closed })}>{t.closed ? 'Reopen' : 'Close'}</Button>
        <MasterDelete kind="thread" id={id} label={t.title} noun="thread" onDeleted={onBack} />
      </div>
      <div className="flex min-h-0 flex-1 flex-col gap-2.5 overflow-y-auto p-4" aria-live="polite" aria-label="Messages">
        {q.data?.messages.length === 0 && <p className="m-auto text-sm text-muted-foreground">Nothing said yet.</p>}
        {q.data?.messages.map((m) => (
          <div key={m.id} className={cn('max-w-[78%]', m.mine ? 'self-end text-right' : 'self-start')}>
            {!m.mine && <p className="ml-1 text-xs text-muted-foreground">{m.author_name}</p>}
            <div className={cn('inline-block whitespace-pre-wrap rounded-2xl px-3 py-2 text-left text-sm', m.mine ? 'bg-primary text-primary-foreground' : 'bg-muted')}>
              {m.deleted ? <em className="opacity-70">message removed</em> : body(m.body)}
              {m.files.map((f) => f.is_image
                ? <a key={f.id} href={f.url} target="_blank" rel="noopener"><img src={f.thumb_url} alt={f.name} className="mt-1 block max-h-56 max-w-56 rounded-lg" onError={(e) => { e.currentTarget.src = f.url }} /></a>
                : <a key={f.id} href={f.url} target="_blank" rel="noopener" className="mt-1 flex items-center gap-1 text-xs underline"><Paperclip className="size-3" /> {f.name}</a>)}
            </div>
            <p className="mx-1.5 mt-0.5 text-[11px] text-subtle">{when(m.created_at)}{m.mine && !m.deleted && <> - <button type="button" className="underline-offset-2 hover:underline" onClick={() => setRemoving(m)}>remove</button></>}</p>
          </div>
        ))}
        <div ref={end} />
      </div>
      {t.closed ? <p className="border-t border-border p-3 text-center text-sm text-muted-foreground">This thread is closed. Reopen it to say more.</p> : <Composer thread={id} />}
      <ConfirmDialog open={!!removing} onOpenChange={(o) => !o && setRemoving(null)} title="Take this message back?" description="It stays in the thread as removed." confirmLabel="Remove it" tone="danger" loading={remove.isPending} onConfirm={() => { if (removing) remove.mutate(removing) }} />
    </div>
  )
}
