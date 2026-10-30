import { useState } from 'react'
import { Plus, Trash2 } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { Button, ConfirmDialog, Field, Input, Modal, Skeleton, Textarea } from '@/components/ui'
import {
  addSpecialDay, addWish, celebrationKeys, react, removeSpecialDay, removeWish, useCelebrations, useSpecialDays,
  type SpecialDay, type TodayCelebration, type UpcomingCelebration,
} from '@/api/celebrations'
import { useAction } from '@/lib/mutate'

const KIND: Record<string, string> = { birthday: 'Birthday', festival: 'Festival', special: 'Special day' }
const short = (iso: string) => new Date(iso + 'T00:00').toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })
const away = (n: number) => (n === 1 ? 'Tomorrow' : `In ${n} days`)

/** Today's birthdays, festivals and special days - to react to with an emoji and answer with a message - and what is coming. HR adds days of its own. */
export default function CelebrationsPage() {
  const q = useCelebrations()
  const can = q.data?.can_manage ?? false
  const [adding, setAdding] = useState(false)
  return (
    <>
      <PageHeader eyebrow="People" title="Celebrations" description="Birthdays and special days across the company. Send a reaction or a message and they are told."
        actions={can && <Button onClick={() => setAdding(true)}><Plus /> Add a special day</Button>} />
      {q.isPending ? <Skeleton className="h-40 w-full" /> : (
        <div className="grid gap-5 lg:grid-cols-[1fr_20rem]">
          <section aria-label="Today" className="space-y-4">
            <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">Today</h2>
            {q.data?.today.length === 0 && <p className="rounded-xl border border-border bg-card p-6 text-sm text-muted-foreground">Nothing to celebrate today. Look ahead on the right.</p>}
            {q.data?.today.map((c) => <Card key={c.key} c={c} emojis={q.data.emojis} />)}
          </section>
          <aside aria-label="Coming up" className="space-y-3">
            <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">Next 30 days</h2>
            {q.data?.upcoming.length === 0 && <p className="text-sm text-muted-foreground">Nothing coming up.</p>}
            <ul className="divide-y divide-border overflow-hidden rounded-xl border border-border bg-card">
              {q.data?.upcoming.map((u) => <Upcoming key={u.key} u={u} />)}
            </ul>
          </aside>
        </div>
      )}
      {can && <SpecialDays />}
      <AddSpecialDay key={String(adding)} open={adding} onClose={() => setAdding(false)} />
    </>
  )
}

function Upcoming({ u }: { u: UpcomingCelebration }) {
  return (
    <li className="flex items-center gap-3 px-3 py-2.5">
      <span className="text-xl" aria-hidden>{u.emoji}</span>
      <span className="min-w-0 flex-1"><span className="block truncate text-[13px] font-medium">{u.title}</span><span className="block text-[12px] text-muted-foreground">{KIND[u.kind]} · {short(u.date)}</span></span>
      <span className="text-[12px] text-muted-foreground">{away(u.days_away)}</span>
    </li>
  )
}

function Card({ c, emojis }: { c: TodayCelebration; emojis: string[] }) {
  const [text, setText] = useState('')
  const refresh = { invalidate: [celebrationKeys.all], success: false as const }
  const toggle = useAction((emoji: string) => react(c.key, emoji), refresh)
  const send = useAction(() => addWish(c.key, text.trim()), { ...refresh, onSuccess: () => setText('') })
  const drop = useAction((id: number) => removeWish(id), refresh)
  return (
    <article className="rounded-xl border border-border bg-card p-5 shadow-card">
      <div className="flex items-start gap-3">
        <span className="text-3xl" aria-hidden>{c.emoji}</span>
        <div className="min-w-0">
          <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">{KIND[c.kind]}</p>
          <h3 className="text-lg font-semibold">{c.title}</h3>
          {c.job_title && <p className="text-[13px] text-muted-foreground">{c.job_title}</p>}
          {c.message && <p className="mt-1 text-sm">{c.message}</p>}
        </div>
      </div>
      <div className="mt-4 flex flex-wrap gap-1.5" role="group" aria-label={`React to ${c.title}`}>
        {emojis.map((e) => {
          const r = c.reactions.find((x) => x.emoji === e)
          return (
            <button key={e} type="button" aria-label={`React with ${e}`} aria-pressed={!!r?.mine} title={r?.names.join(', ') || undefined} onClick={() => toggle.mutate(e)}
              className={'flex items-center gap-1 rounded-full border px-2.5 py-1 text-sm transition-colors hover:bg-accent ' + (r?.mine ? 'border-primary bg-primary-soft' : 'border-border')}>
              <span aria-hidden>{e}</span>{r && <span className="text-[12px] font-medium">{r.count}</span>}
            </button>
          )
        })}
      </div>
      {c.wishes.length > 0 && (
        <ul className="mt-4 space-y-2">
          {c.wishes.map((w) => (
            <li key={w.id} className="flex items-start gap-2 rounded-lg bg-muted/40 px-3 py-2">
              <p className="min-w-0 flex-1 text-sm"><span className="font-medium">{w.author}</span> <span className="break-words text-muted-foreground">{w.message}</span></p>
              {w.can_delete && <Button size="sm" variant="ghost" aria-label={`Remove message from ${w.author}`} onClick={() => drop.mutate(w.id)}><Trash2 /></Button>}
            </li>
          ))}
        </ul>
      )}
      <form className="mt-4 flex gap-2" onSubmit={(e) => { e.preventDefault(); if (text.trim()) send.mutate() }}>
        <Input aria-label={`Write to ${c.title}`} value={text} maxLength={300} onChange={(e) => setText(e.target.value)}
          placeholder={c.kind === 'birthday' ? 'Write a birthday message...' : 'Write a message...'} />
        <Button type="submit" loading={send.isPending} disabled={!text.trim()}>Send</Button>
      </form>
      {send.error && <p role="alert" className="mt-2 text-[13px] text-danger">{send.error.message}</p>}
    </article>
  )
}

/** HR's list of the days it added: the one place to take one off again. */
function SpecialDays() {
  const q = useSpecialDays(true)
  const [removing, setRemoving] = useState<SpecialDay | null>(null)
  const drop = useAction((d: SpecialDay) => removeSpecialDay(d.id), { invalidate: [celebrationKeys.all], success: 'Special day removed' })
  if (!q.data?.length) return null
  return (
    <section aria-label="Special days added" className="mt-8">
      <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-muted-foreground">Days you added</h2>
      <ul className="divide-y divide-border overflow-hidden rounded-xl border border-border bg-card">
        {q.data.map((d) => (
          <li key={d.id} className="flex items-center gap-3 px-4 py-2.5">
            <span className="text-xl" aria-hidden>{d.emoji || '🎉'}</span>
            <span className="min-w-0 flex-1"><span className="block text-sm font-medium">{d.name}</span><span className="block text-[12px] text-muted-foreground">{short(d.date)}{d.yearly ? ', every year' : `, ${d.date.slice(0, 4)}`}</span></span>
            <Button size="sm" variant="ghost" aria-label={`Remove ${d.name}`} onClick={() => setRemoving(d)}><Trash2 /></Button>
          </li>
        ))}
      </ul>
      <ConfirmDialog open={!!removing} onOpenChange={(o) => !o && setRemoving(null)} title={`Remove ${removing?.name ?? 'this day'}?`}
        description="Its reactions and messages go with it." confirmLabel="Remove it" tone="danger"
        onConfirm={() => { if (removing) drop.mutate(removing); setRemoving(null) }} />
    </section>
  )
}

function AddSpecialDay({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [f, setF] = useState({ date: new Date().toISOString().slice(0, 10), name: '', message: '', emoji: '', yearly: false })
  const save = useAction(() => addSpecialDay({ ...f, name: f.name.trim(), message: f.message.trim(), emoji: f.emoji.trim() }), {
    invalidate: [celebrationKeys.all, celebrationKeys.special],
    success: (r) => (r.announced ? 'Added, and everybody has been told' : 'Added. Everybody is told on the day'),
    onSuccess: onClose,
  })
  return (
    <Modal open={open} onOpenChange={(o) => !o && onClose()} title="Add a special day" description="A festival, an anniversary, a milestone. Everybody is notified on the day, and can react and write a message.">
      <form onSubmit={(e) => { e.preventDefault(); if (f.name.trim() && f.date) save.mutate() }}>
        <div className="grid gap-4">
          <div className="grid gap-4 sm:grid-cols-[1fr_6rem]">
            <Field label="Date" htmlFor="sd-date"><Input id="sd-date" type="date" value={f.date} onChange={(e) => setF((s) => ({ ...s, date: e.target.value }))} /></Field>
            <Field label="Emoji" htmlFor="sd-emoji" hint="Optional."><Input id="sd-emoji" value={f.emoji} maxLength={8} onChange={(e) => setF((s) => ({ ...s, emoji: e.target.value }))} placeholder="🎉" /></Field>
          </div>
          <Field label="Name" htmlFor="sd-name"><Input id="sd-name" value={f.name} maxLength={100} onChange={(e) => setF((s) => ({ ...s, name: e.target.value }))} placeholder="Company anniversary, Safety week..." autoFocus /></Field>
          <Field label="Message" htmlFor="sd-msg" hint="Optional. What everybody is told."><Textarea id="sd-msg" rows={2} maxLength={300} value={f.message} onChange={(e) => setF((s) => ({ ...s, message: e.target.value }))} /></Field>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={f.yearly} onChange={(e) => setF((s) => ({ ...s, yearly: e.target.checked }))} /> Every year on this date</label>
        </div>
        <div className="mt-5 flex items-center justify-end gap-2 border-t border-border pt-4">
          {save.error && <p role="alert" className="mr-auto text-[13px] text-danger">{save.error.message}</p>}
          <Button type="button" variant="ghost" onClick={onClose}>Cancel</Button>
          <Button type="submit" loading={save.isPending} disabled={!f.name.trim() || !f.date}>Add</Button>
        </div>
      </form>
    </Modal>
  )
}
