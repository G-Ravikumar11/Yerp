import { useState } from 'react'
import { MessageSquarePlus } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { ProjectPicker } from '@/components/data/ProjectPicker'
import { Button, Field, Input, Modal, Select, Skeleton, Textarea } from '@/components/ui'
import { chatKeys, startThread, useThreads } from '@/api/chat'
import { projectLabel, useProjects } from '@/api/projects'
import { useAction } from '@/lib/mutate'
import { cn } from '@/lib/utils'
import { MessagePane } from './MessagePane'

const when = (at: string) => (at ? `${at.slice(8, 10)}/${at.slice(5, 7)} ${at.slice(11, 16)}` : '')

/** Project threads: the office and the site in one conversation, photos beside the words. */
export default function ChatPage() {
  const [job, setJob] = useState(0)
  const [open, setOpen] = useState(0)
  const [creating, setCreating] = useState(false)
  const q = useThreads(job)
  const threads = q.data?.threads ?? []
  return (
    <>
      <PageHeader eyebrow="Projects" title="Project Chat" description="The office and the site in one conversation, with photos beside the words and @names that ring the bell." actions={<Button onClick={() => setCreating(true)}><MessageSquarePlus /> New thread</Button>} />
      <div className="mb-4"><ProjectPicker value={job} onChange={setJob} id="chat-job" allowAll /></div>
      <div className="grid h-[calc(100dvh-20rem)] min-h-[26rem] overflow-hidden rounded-xl border border-border bg-card shadow-card lg:grid-cols-[320px_1fr]">
        <div className={cn('min-h-0 overflow-y-auto border-border lg:border-r', open && 'max-lg:hidden')} role="list" aria-label="Threads">
          {q.isPending ? <Skeleton className="m-3 h-32" /> : threads.length === 0 ? <p className="p-6 text-center text-sm text-muted-foreground">No threads yet. Start one for anything the site and the office need to agree on.</p> : threads.map((t) => (
            <button key={t.id} type="button" role="listitem" onClick={() => setOpen(t.id)} className={cn('block w-full border-b border-border px-4 py-3 text-left transition-colors hover:bg-accent', t.id === open && 'bg-primary-soft/50', t.closed && 'opacity-60')}>
              <span className="flex items-start justify-between gap-2"><span className="text-sm font-semibold">{t.title}</span>{t.unread ? <span className="rounded-full bg-primary px-2 text-[11px] font-bold text-primary-foreground" aria-label={`${t.unread} unread`}>{t.unread}</span> : <span className="shrink-0 text-[11px] text-muted-foreground">{when(t.last_message_at)}</span>}</span>
              {!job && <span className="block text-xs text-primary">{t.project}</span>}
              {t.last && <span className="block truncate text-[13px] text-muted-foreground">{t.last.author_name}: {t.last.body}</span>}
              {t.closed && <span className="block text-[11px] text-muted-foreground">closed</span>}
            </button>
          ))}
        </div>
        <div className={cn('min-h-0', !open && 'max-lg:hidden')}>
          {open ? <MessagePane key={open} id={open} onBack={() => setOpen(0)} /> : <p className="grid h-full place-items-center p-6 text-center text-sm text-muted-foreground">Choose a thread, or start a new one.</p>}
        </div>
      </div>
      <NewThread job={job} open={creating} onClose={() => setCreating(false)} onStarted={(id) => { setCreating(false); setOpen(id) }} />
    </>
  )
}

function NewThread({ job, open, onClose, onStarted }: { job: number; open: boolean; onClose: () => void; onStarted: (id: number) => void }) {
  return (
    <Modal open={open} onOpenChange={(o) => !o && onClose()} title="New thread" description="One thread for one thing the site and the office need to agree on.">
      {open && <Form job={job} onClose={onClose} onStarted={onStarted} />}
    </Modal>
  )
}

function Form({ job, onClose, onStarted }: { job: number; onClose: () => void; onStarted: (id: number) => void }) {
  const jobs = useProjects()
  const [pick, setPick] = useState(job ? String(job) : '')
  const [title, setTitle] = useState('')
  const [text, setText] = useState('')
  const start = useAction(() => startThread({ job_id: Number(pick), title, body: text }), { invalidate: [chatKeys.all], success: 'Thread started', onSuccess: (r) => onStarted(r.thread.id) })
  return (
    <div>
      <div className="grid gap-4">
        <Field label="Project" htmlFor="ct-job"><Select id="ct-job" value={pick} placeholder="Which project is it about?" onChange={(e) => setPick(e.target.value)} options={(jobs.data ?? []).map((p) => ({ value: p.id, label: projectLabel(p) }))} /></Field>
        <Field label="Title" htmlFor="ct-title"><Input id="ct-title" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Slab cube results, Gate 2 diversion..." /></Field>
        <Field label="First message" htmlFor="ct-body"><Textarea id="ct-body" rows={3} value={text} onChange={(e) => setText(e.target.value)} /></Field>
      </div>
      <div className="mt-5 flex items-center justify-end gap-2 border-t border-border pt-4">
        {start.error && <p role="alert" className="mr-auto text-[13px] text-danger">{start.error.message}</p>}
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button loading={start.isPending} disabled={!pick || !title.trim()} onClick={() => start.mutate()}>Start the thread</Button>
      </div>
    </div>
  )
}
