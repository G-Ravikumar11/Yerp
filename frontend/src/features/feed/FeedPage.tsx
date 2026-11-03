import { useEffect, useRef, useState } from 'react'
import { ImagePlus, Megaphone, Pencil, Pin, PinOff, Plus, Trash2, X } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { Badge, Button, ConfirmDialog, Field, Input, Modal, Select, Skeleton, Stat, StatGrid, Tabs, Textarea } from '@/components/ui'
import {
  addAnnouncementMedia, changeAnnouncement, FEED_SEEN, IMAGE_MAX_MB, MEDIA_MAX, removeAnnouncementMedia, VIDEO_MAX_MB, feedKeys, pinAnnouncement, postAnnouncement, removeAnnouncement, useAnnouncements,
  type Announcement, type AnnouncementInput, type AnnouncementKind, type AnnouncementMedia,
} from '@/api/feed'
import { useCelebrations } from '@/api/celebrations'
import { Card, Upcoming } from '@/features/celebrations/CelebrationsPage'
import { useAction } from '@/lib/mutate'

const KINDS: { value: AnnouncementKind; label: string; tone: 'neutral' | 'info' | 'success' | 'danger' }[] = [
  { value: 'general', label: 'General', tone: 'neutral' },
  { value: 'site', label: 'Site', tone: 'info' },
  { value: 'holiday', label: 'Holiday', tone: 'success' },
  { value: 'important', label: 'Important', tone: 'danger' },
]
const kind = (v: AnnouncementKind) => KINDS.find((k) => k.value === v) ?? KINDS[0]
const when = (iso: string) => new Date(iso.replace(' ', 'T')).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' })
const day = (iso: string) => new Date(iso + 'T00:00').toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })

const today = () => new Date().toLocaleDateString('en-IN', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' })
type Tab = 'announcements' | 'celebrations'

/**
 * The page everybody opens first, in two parts: the announcements HR has posted (sites, holidays, anything important),
 * and the celebrations - today's birthdays and special days, with what is coming. Everybody reads it; only HR and the
 * Master post.
 */
export default function FeedPage() {
  const feed = useAnnouncements()
  const celebrations = useCelebrations()
  const [tab, setTab] = useState<Tab>('announcements')
  const [editing, setEditing] = useState<Announcement | 'new' | null>(null)
  // Shown once: from now on the front page is the front page again until the next session.
  useEffect(() => { try { sessionStorage.setItem(FEED_SEEN, '1') } catch { /* private mode: it just shows again */ } }, [])
  const can = feed.data?.can_post ?? false
  const posts = feed.data?.announcements ?? []
  const live = posts.filter((a) => !a.expired)
  const todays = celebrations.data?.today ?? []
  const coming = celebrations.data?.upcoming ?? []
  return (
    <>
      <PageHeader eyebrow="Home" title="Feed" description={today()}
        actions={can && tab === 'announcements' && <Button onClick={() => setEditing('new')}><Plus /> Post an announcement</Button>} />
      <StatGrid className="lg:grid-cols-4 xl:grid-cols-4">
        <Stat label="Announcements" value={live.length} loading={feed.isPending} />
        <Stat label="Pinned" value={live.filter((a) => a.pinned).length} loading={feed.isPending} />
        <Stat label="Celebrating today" value={todays.length} loading={celebrations.isPending} />
        <Stat label="Coming up in 30 days" value={coming.length} loading={celebrations.isPending} />
      </StatGrid>
      <div className="mb-5">
        <Tabs label="Feed sections" size="lg" value={tab} onChange={setTab}
          items={[{ value: 'announcements', label: 'Announcements', count: live.length }, { value: 'celebrations', label: 'Celebrations', count: todays.length }]} />
      </div>
      {tab === 'announcements' && (
        <section aria-label="Announcements" className="max-w-3xl space-y-4">
          {feed.isPending && <Skeleton className="h-32 w-full" />}
          {feed.data && posts.length === 0 && (
            <div className="rounded-xl border border-dashed border-border bg-card p-10 text-center">
              <Megaphone className="mx-auto size-8 text-muted-foreground" aria-hidden />
              <p className="mt-3 text-sm font-medium">No announcements right now</p>
              <p className="mt-1 text-[13px] text-muted-foreground">{can ? 'Post one and everybody in the company will see it here.' : 'When HR posts one, it will appear here.'}</p>
            </div>
          )}
          {posts.map((a) => <AnnouncementCard key={a.id} a={a} onEdit={() => setEditing(a)} />)}
        </section>
      )}
      {tab === 'celebrations' && (
        <div className="grid gap-5 lg:grid-cols-[1fr_20rem]">
          <section aria-label="Celebrating today" className="space-y-4">
            <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">Today</h2>
            {celebrations.isPending && <Skeleton className="h-24 w-full" />}
            {celebrations.data && todays.length === 0 && <p className="rounded-xl border border-border bg-card p-6 text-sm text-muted-foreground">No birthdays or special days today. Look ahead on the right.</p>}
            {todays.map((c) => <Card key={c.key} c={c} emojis={celebrations.data?.emojis ?? []} />)}
          </section>
          <aside aria-label="Coming up" className="space-y-3">
            <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">Next 30 days</h2>
            {celebrations.data && coming.length === 0 && <p className="text-sm text-muted-foreground">Nothing coming up.</p>}
            <ul className="divide-y divide-border overflow-hidden rounded-xl border border-border bg-card">
              {coming.map((u) => <Upcoming key={u.key} u={u} />)}
            </ul>
          </aside>
        </div>
      )}
      {editing && <AnnouncementForm key={editing === 'new' ? 'new' : editing.id} existing={editing === 'new' ? null : editing} onClose={() => setEditing(null)} />}
    </>
  )
}

function AnnouncementCard({ a, onEdit }: { a: Announcement; onEdit: () => void }) {
  const [removing, setRemoving] = useState(false)
  const refresh = { invalidate: [feedKeys.all] }
  const pin = useAction(() => pinAnnouncement(a.id, !a.pinned), { ...refresh, success: false as const })
  const drop = useAction(() => removeAnnouncement(a.id), { ...refresh, success: 'Announcement removed', onSuccess: () => setRemoving(false) })
  const k = kind(a.category)
  return (
    <article className={'rounded-xl border bg-card p-5 shadow-card ' + (a.pinned ? 'border-primary/40' : 'border-border') + (a.expired ? ' opacity-70' : '')}>
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={k.tone}>{k.label}</Badge>
        {a.pinned && <span className="inline-flex items-center gap-1 text-[12px] font-medium text-primary"><Pin className="size-3.5" aria-hidden /> Pinned</span>}
        {a.expired && <Badge tone="warning">Expired</Badge>}
        {a.can_edit && (
          <div className="ml-auto flex gap-1">
            <Button size="sm" variant="ghost" aria-label={a.pinned ? `Unpin ${a.title}` : `Pin ${a.title}`} loading={pin.isPending} onClick={() => pin.mutate()}>{a.pinned ? <PinOff /> : <Pin />}</Button>
            <Button size="sm" variant="ghost" aria-label={`Edit ${a.title}`} onClick={onEdit}><Pencil /></Button>
            <Button size="sm" variant="ghost" aria-label={`Remove ${a.title}`} onClick={() => setRemoving(true)}><Trash2 /></Button>
          </div>
        )}
      </div>
      <h3 className="mt-2 text-lg font-semibold">{a.title}</h3>
      {a.body && <p className="mt-1.5 whitespace-pre-line break-words text-sm leading-relaxed">{a.body}</p>}
      {a.media.length > 0 && <MediaGrid media={a.media} />}
      <p className="mt-3 text-[12px] text-muted-foreground">
        {a.posted_by ? `${a.posted_by} · ` : ''}{when(a.created_at)}{a.updated_at ? ' (edited)' : ''}{a.expires_on ? ` · shows until ${day(a.expires_on)}` : ''}
      </p>
      <ConfirmDialog open={removing} onOpenChange={setRemoving} title={`Remove "${a.title}"?`} description="It disappears from everybody's Feed." confirmLabel="Remove it" tone="danger"
        loading={drop.isPending} onConfirm={() => drop.mutate()} />
    </article>
  )
}

function MediaGrid({ media }: { media: AnnouncementMedia[] }) {
  const single = media.length === 1
  return (
    <div className={'mt-3 grid gap-2 ' + (single ? '' : 'sm:grid-cols-2')}>
      {media.map((m) => m.kind === 'video'
        ? <video key={m.id} src={m.url} controls preload="metadata" className="max-h-96 w-full rounded-lg bg-black" aria-label={m.name} />
        : <a key={m.id} href={m.url} target="_blank" rel="noreferrer"><img src={m.url} alt={m.name} loading="lazy" className="max-h-96 w-full rounded-lg object-cover" /></a>)}
    </div>
  )
}

const isVideo = (f: File) => f.type.startsWith('video/')

function AnnouncementForm({ existing, onClose }: { existing: Announcement | null; onClose: () => void }) {
  const [f, setF] = useState<AnnouncementInput>({
    title: existing?.title ?? '', body: existing?.body ?? '', category: existing?.category ?? 'general',
    pinned: existing?.pinned ?? false, expires_on: existing?.expires_on ?? '', notify: true,
  })
  const set = <K extends keyof AnnouncementInput>(k: K, v: AnnouncementInput[K]) => setF((s) => ({ ...s, [k]: v }))
  const [files, setFiles] = useState<File[]>([])
  const [dropped, setDropped] = useState<number[]>([])
  const [tooBig, setTooBig] = useState('')
  const created = useRef<number | null>(null)               // a post that was made but whose files did not all go up: retrying must not post it twice
  const kept = (existing?.media ?? []).filter((m) => !dropped.includes(m.id))
  const room = MEDIA_MAX - kept.length - files.length
  const pick = (list: FileList | null) => {
    const chosen = Array.from(list ?? [])
    const bad = chosen.find((x) => !(x.type.startsWith('image/') || isVideo(x)) || x.size > (isVideo(x) ? VIDEO_MAX_MB : IMAGE_MAX_MB) * 1048576)
    setTooBig(bad ? `${bad.name}: photos up to ${IMAGE_MAX_MB} MB and videos up to ${VIDEO_MAX_MB} MB only.` : chosen.length > room ? `Up to ${MEDIA_MAX} photos and videos on one post.` : '')
    if (!bad) setFiles((cur) => [...cur, ...chosen].slice(0, MEDIA_MAX - kept.length))
  }
  const save = useAction(async () => {
    let id = existing?.id ?? created.current
    let told = 0
    if (existing) await changeAnnouncement(existing.id, f)
    else if (id == null) { const r = await postAnnouncement({ ...f, title: f.title.trim(), body: f.body.trim() }); id = r.id; told = r.told; created.current = id }
    for (const m of dropped) await removeAnnouncementMedia(id!, m)
    setDropped([])
    while (files.length) {
      const next = files[0]
      try { await addAnnouncementMedia(id!, next) } catch (e) { throw new Error(`Posted, but ${next.name} did not go up: ${e instanceof Error ? e.message : 'try again'}. Remove it or press Post again to retry.`) }
      files.shift()
      setFiles([...files])
    }
    return { told }
  }, {
    invalidate: [feedKeys.all],
    success: (r) => (existing ? 'Saved' : r.told ? `Posted, and ${r.told} ${r.told === 1 ? 'person has' : 'people have'} been told` : 'Posted'),
    onSuccess: onClose,
  })
  const ready = f.title.trim().length > 0
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} title={existing ? 'Edit announcement' : 'Post an announcement'}
      description="Everybody in the company sees it on their Feed: a site notice, a holiday, anything they need to know." size="lg">
      <form onSubmit={(e) => { e.preventDefault(); if (ready) save.mutate() }}>
        <div className="grid gap-4">
          <Field label="Title" htmlFor="an-title"><Input id="an-title" value={f.title} maxLength={120} autoFocus onChange={(e) => set('title', e.target.value)} placeholder="Site closed on Saturday, Diwali holidays..." /></Field>
          <Field label="Message" htmlFor="an-body" hint="Optional. Line breaks are kept."><Textarea id="an-body" rows={5} maxLength={2000} value={f.body} onChange={(e) => set('body', e.target.value)} /></Field>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Kind" htmlFor="an-kind"><Select id="an-kind" value={f.category} onChange={(e) => set('category', e.target.value as AnnouncementKind)} options={KINDS.map((k) => ({ value: k.value, label: k.label }))} /></Field>
            <Field label="Show until" htmlFor="an-until" hint="Optional. It leaves the Feed after this day."><Input id="an-until" type="date" value={f.expires_on} onChange={(e) => set('expires_on', e.target.value)} /></Field>
          </div>
          <Field label="Photos and videos" hint={`Optional. Up to ${MEDIA_MAX}; photos to ${IMAGE_MAX_MB} MB, videos to ${VIDEO_MAX_MB} MB.`}>
            <div className="grid gap-2">
              {(kept.length > 0 || files.length > 0) && (
                <ul className="grid grid-cols-3 gap-2 sm:grid-cols-4">
                  {kept.map((m) => <Thumb key={m.id} name={m.name} src={m.url} video={m.kind === 'video'} onRemove={() => setDropped((d) => [...d, m.id])} />)}
                  {files.map((x, i) => <Thumb key={x.name + i} name={x.name} file={x} video={isVideo(x)} onRemove={() => setFiles((cur) => cur.filter((_, j) => j !== i))} />)}
                </ul>
              )}
              {room > 0 && (
                <label className="inline-flex w-fit cursor-pointer items-center gap-2 rounded-lg border border-dashed border-border px-3 py-2 text-sm hover:bg-muted">
                  <ImagePlus className="size-4" aria-hidden /> Add photos or videos
                  <input type="file" multiple accept="image/jpeg,image/png,image/webp,image/gif,video/mp4,video/webm,video/quicktime" className="sr-only" aria-label="Add photos or videos"
                    onChange={(e) => { pick(e.target.files); e.target.value = '' }} />
                </label>
              )}
              {tooBig && <p role="alert" className="text-[13px] text-danger">{tooBig}</p>}
            </div>
          </Field>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={f.pinned} onChange={(e) => set('pinned', e.target.checked)} /> Keep at the top of the Feed</label>
          {!existing && <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={f.notify !== false} onChange={(e) => set('notify', e.target.checked)} /> Tell every employee now, on their notifications</label>}
        </div>
        <div className="mt-5 flex items-center justify-end gap-2 border-t border-border pt-4">
          {save.error && <p role="alert" className="mr-auto text-[13px] text-danger">{save.error.message}</p>}
          <Button type="button" variant="ghost" onClick={onClose}>Cancel</Button>
          <Button type="submit" loading={save.isPending} disabled={!ready}><Megaphone /> {existing ? 'Save' : 'Post'}</Button>
        </div>
      </form>
    </Modal>
  )
}

function Thumb({ name, src, file, video, onRemove }: { name: string; src?: string; file?: File; video: boolean; onRemove: () => void }) {
  const [url, setUrl] = useState(src ?? '')
  useEffect(() => {
    if (!file || typeof URL.createObjectURL !== 'function') return
    const u = URL.createObjectURL(file)
    setUrl(u)
    return () => URL.revokeObjectURL(u)
  }, [file])
  return (
    <li className="relative aspect-video overflow-hidden rounded-lg border border-border bg-muted">
      {video ? <video src={url} muted preload="metadata" className="size-full object-cover" /> : <img src={url} alt={name} className="size-full object-cover" />}
      <button type="button" aria-label={`Remove ${name}`} onClick={onRemove} className="absolute right-1 top-1 rounded-full bg-black/60 p-1 text-white hover:bg-black/80"><X className="size-3.5" /></button>
    </li>
  )
}
