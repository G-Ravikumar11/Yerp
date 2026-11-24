import { useState } from 'react'
import { Pencil, Plus, Power, RotateCcw } from 'lucide-react'
import { Badge, Button, ConfirmDialog, Field, Input, Modal, Skeleton, Textarea } from '@/components/ui'
import { closeOpening, editOpening, postOpening, reopenOpening, useWebsiteOpenings, type OpeningInput, type WebsiteOpening } from '@/api/website'
import { useAction } from '@/lib/mutate'

const BLANK: OpeningInput = { title: '', location: '', experience: '', description: '' }
const KEYS = [['website'], ['recruitment']]

/** The openings on the website's Careers section. They are Recruitment's jobs: posting one here opens it with its own
 *  application form, and what people send arrives in Recruitment. Unlike the words and pictures, an opening is live as soon as
 *  it is posted, and comes off the website when it is closed. */
export function CareersPart({ onChanged }: { onChanged: () => void }) {
  const q = useWebsiteOpenings()
  const [editing, setEditing] = useState<{ id: number | null; form: OpeningInput } | null>(null)
  const [closing, setClosing] = useState<WebsiteOpening | null>(null)
  const save = useAction(({ id, form }: { id: number | null; form: OpeningInput }) => (id ? editOpening(id, form) : postOpening(form)),
    { invalidate: KEYS, onSuccess: () => { setEditing(null); onChanged() } })
  const close = useAction((id: number) => closeOpening(id), { invalidate: KEYS, onSuccess: () => { setClosing(null); onChanged() } })
  const reopen = useAction((id: number) => reopenOpening(id), { invalidate: KEYS, onSuccess: onChanged })
  const set = (k: keyof OpeningInput) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
    setEditing((x) => (x ? { ...x, form: { ...x.form, [k]: e.target.value } } : x))
  const list = q.data?.openings ?? []
  const open = list.filter((o) => o.on_website)
  const rest = list.filter((o) => !o.on_website)

  const row = (o: WebsiteOpening) => (
    <li key={o.id} className="flex flex-wrap items-start gap-3 px-4 py-3">
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium">{o.title} <span className="font-normal text-muted-foreground">{o.reference}</span></p>
        <p className="text-[13px] text-muted-foreground">{[o.location, o.experience && `${o.experience} experience`, `${o.applications} application${o.applications === 1 ? '' : 's'}`].filter(Boolean).join(' · ')}</p>
      </div>
      {o.on_website ? <Badge tone="success">On the website</Badge> : <Badge>{o.status === 'open' ? 'Not on the website' : 'Closed'}</Badge>}
      <div className="flex gap-1">
        <Button type="button" variant="ghost" size="sm" aria-label={`Edit ${o.title}`} onClick={() => setEditing({ id: o.id, form: { title: o.title, location: o.location, experience: o.experience, description: o.description } })}><Pencil /> Edit</Button>
        {o.on_website
          ? <Button type="button" variant="ghost" size="sm" aria-label={`Close ${o.title}`} onClick={() => setClosing(o)}><Power /> Close</Button>
          : <Button type="button" variant="ghost" size="sm" aria-label={`Reopen ${o.title}`} loading={reopen.isPending && reopen.variables === o.id} onClick={() => reopen.mutate(o.id)}><RotateCcw /> Reopen</Button>}
      </div>
    </li>
  )

  return (
    <section className="grid gap-4" aria-label="Openings">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-base font-semibold">Openings</h3>
        <Button type="button" size="sm" onClick={() => setEditing({ id: null, form: BLANK })}><Plus /> Post an opening</Button>
      </div>
      {q.isPending ? <Skeleton className="h-24 w-full" /> : list.length === 0 ? <p className="text-sm text-muted-foreground">No openings yet. While there are none, the website asks for CVs by email.</p> : (
        <>
          {open.length > 0 && <ul className="divide-y divide-border rounded-lg border border-border" aria-label="Open">{open.map(row)}</ul>}
          {rest.length > 0 && (
            <details className="rounded-lg border border-border">
              <summary className="cursor-pointer px-4 py-2.5 text-sm font-medium">Closed and not shown ({rest.length})</summary>
              <ul className="divide-y divide-border border-t border-border" aria-label="Closed">{rest.map(row)}</ul>
            </details>
          )}
        </>
      )}

      <Modal open={!!editing} onOpenChange={(o) => { if (!o) setEditing(null) }} title={editing?.id ? 'Edit the opening' : 'Post an opening'}
        description={editing?.id ? 'Saved changes show on the website straight away.' : 'It goes on the website straight away, with an application form whose replies arrive in Recruitment.'}>
        {editing && (
          <form className="grid gap-4" onSubmit={(e) => { e.preventDefault(); save.mutate(editing) }}>
            <Field label="Title" htmlFor="op-title"><Input id="op-title" required maxLength={120} value={editing.form.title} onChange={set('title')} placeholder="e.g. Site Engineer (Civil)" /></Field>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Site or location" htmlFor="op-loc"><Input id="op-loc" maxLength={120} value={editing.form.location} onChange={set('location')} placeholder="e.g. Ongole, Andhra Pradesh" /></Field>
              <Field label="Experience" htmlFor="op-exp"><Input id="op-exp" maxLength={80} value={editing.form.experience} onChange={set('experience')} placeholder="e.g. 3-5 years" /></Field>
            </div>
            <Field label="Description" hint="What the job is and what it needs." htmlFor="op-desc"><Textarea id="op-desc" rows={5} maxLength={4000} value={editing.form.description} onChange={set('description')} /></Field>
            <div className="flex justify-end gap-2 border-t border-border pt-4">
              <Button type="button" variant="ghost" onClick={() => setEditing(null)}>Cancel</Button>
              <Button type="submit" loading={save.isPending}>{editing.id ? 'Save' : 'Post on the website'}</Button>
            </div>
          </form>
        )}
      </Modal>
      <ConfirmDialog open={!!closing} onOpenChange={(o) => { if (!o) setClosing(null) }} title={`Close ${closing?.title ?? 'this opening'}?`}
        description="It comes off the website now. Its applications stay in Recruitment, and it can be reopened." confirmLabel="Close the opening"
        loading={close.isPending} onConfirm={() => { if (closing) close.mutate(closing.id) }} />
    </section>
  )
}
