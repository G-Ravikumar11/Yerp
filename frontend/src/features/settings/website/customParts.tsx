import { useEffect, useState } from 'react'
import { ArrowDown, ArrowUp, Check, History, ImagePlus, RotateCcw, Trash2, Upload } from 'lucide-react'
import { Badge, Button, ConfirmDialog, Field, Input, Select, Skeleton, Textarea } from '@/components/ui'
import {
  pictureUrl, removeImage, restoreVersion, useWebsiteImages, useWebsiteProjects, useWebsiteVersions, websiteKeys,
  type Place, type ProjectCard, type WebsiteProject,
} from '@/api/website'
import { useAction } from '@/lib/mutate'
import { PAGE_SECTIONS, type PageSection } from '@/features/site/data/content'
import { SHAPES } from './Cropper'
import { useUpload } from './ImageField'

type Draft = (key: string) => unknown
type SetDraft = (key: string, value: unknown) => void
type Row = { id: PageSection; shown: boolean }

/** Which sections the page shows, and in what order. */
export function LayoutPart({ draft, set }: { draft: Draft; set: SetDraft }) {
  const rows = (draft('layout') as Row[] | undefined) ?? []
  const label = (id: string) => PAGE_SECTIONS.find((p) => p.id === id)?.label ?? id
  const put = (next: Row[]) => set('layout', next)
  const move = (i: number, by: number) => {
    const j = i + by
    if (j < 0 || j >= rows.length) return
    const out = [...rows]
    ;[out[i], out[j]] = [out[j], out[i]]
    put(out)
  }
  return (
    <ol className="divide-y divide-border rounded-lg border border-border" aria-label="Sections of the page">
      {rows.map((r, i) => (
        <li key={r.id} className="flex items-center gap-3 px-4 py-2.5">
          <span className="w-6 text-right text-[13px] tabular-nums text-muted-foreground">{i + 1}</span>
          <label className="flex flex-1 items-center gap-2 text-sm">
            <input type="checkbox" className="size-4 accent-primary" checked={r.shown} onChange={(e) => put(rows.map((x, k) => (k === i ? { ...x, shown: e.target.checked } : x)))} />
            <span className={r.shown ? 'font-medium' : 'text-muted-foreground line-through'}>{label(r.id)}</span>
          </label>
          {!r.shown && <Badge>Hidden</Badge>}
          <Button type="button" variant="ghost" size="icon-sm" aria-label={`Move ${label(r.id)} up`} disabled={i === 0} onClick={() => move(i, -1)}><ArrowUp /></Button>
          <Button type="button" variant="ghost" size="icon-sm" aria-label={`Move ${label(r.id)} down`} disabled={i === rows.length - 1} onClick={() => move(i, 1)}><ArrowDown /></Button>
        </li>
      ))}
    </ol>
  )
}

/** Every project, with its card on the website and the photos it shows. Changes are part of the draft like everything
 *  else: a project goes on (or off) the website when the website is published. */
export function ProjectsPart({ draft, set, focus }: { draft: Draft; set: SetDraft; focus?: number }) {
  const q = useWebsiteProjects()
  const [filter, setFilter] = useState<'all' | 'shown'>('all')
  const cards = (draft('projects') as Record<string, ProjectCard> | undefined) ?? {}
  const most = q.data?.most_photos ?? 6
  const cardOf = (p: WebsiteProject): ProjectCard => cards[String(p.id)] ?? p.draft
  const put = (p: WebsiteProject, card: ProjectCard) => set('projects', { ...cards, [String(p.id)]: card })
  useEffect(() => {
    if (focus && q.data) document.getElementById(`web-project-${focus}`)?.scrollIntoView({ block: 'center' })
  }, [focus, q.data])
  if (q.isPending) return <Skeleton className="h-40 w-full" />
  const list = (q.data?.projects ?? []).filter((p) => filter === 'all' || cardOf(p).show)
  return (
    <section className="grid gap-3" aria-label="Projects on the website">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-base font-semibold">Projects on the website</h3>
        <Select aria-label="Which projects" value={filter} onChange={(e) => setFilter(e.target.value as 'all' | 'shown')} options={[{ value: 'all', label: 'Every project' }, { value: 'shown', label: 'Shown on the website' }]} />
      </div>
      <p className="text-[13px] text-muted-foreground">Only the card below and the client&apos;s name are shown - never a value or a cost. Photos are the ones kept against the project (not its diary photos).</p>
      {list.length === 0 && <p className="text-sm text-muted-foreground">No projects here.</p>}
      {list.map((p) => <ProjectRow key={p.id} p={p} card={cardOf(p)} most={most} focused={p.id === focus} onChange={(c) => put(p, c)} />)}
    </section>
  )
}

function ProjectRow({ p, card, most, focused, onChange }: { p: WebsiteProject; card: ProjectCard; most: number; focused: boolean; onChange: (c: ProjectCard) => void }) {
  const upload = useUpload('project', p.id)
  const chosen = card.photos ?? p.photos.slice(0, most)
  const toggle = (fid: number) => onChange({ ...card, photos: chosen.includes(fid) ? chosen.filter((x) => x !== fid) : chosen.length < most ? [...chosen, fid] : chosen })
  const set = (k: 'sector' | 'location' | 'scope') => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => onChange({ ...card, [k]: e.target.value })
  const changed = JSON.stringify(card) !== JSON.stringify(p.published)
  return (
    <details id={`web-project-${p.id}`} className={`rounded-lg border bg-card ${focused ? 'border-primary' : 'border-border'}`} open={focused}>
      <summary className="flex cursor-pointer flex-wrap items-center gap-2 px-4 py-2.5 text-sm">
        <span className="font-medium">{[p.number, p.name].filter(Boolean).join(' - ')}</span>
        <span className="text-muted-foreground">{p.client}</span>
        <span className="ml-auto flex gap-1.5">
          {card.show ? <Badge tone="success">On the website</Badge> : <Badge>Not shown</Badge>}
          {changed && <Badge tone="warning">Changed</Badge>}
        </span>
      </summary>
      <div className="grid gap-4 border-t border-border p-4">
        <label className="flex items-center gap-2 text-sm font-medium">
          <input type="checkbox" className="size-4 accent-primary" checked={card.show} onChange={(e) => onChange({ ...card, show: e.target.checked })} /> Show on the website
        </label>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Sector" hint="e.g. Residential, Roads, Water" htmlFor={`ps-${p.id}`}><Input id={`ps-${p.id}`} maxLength={60} value={card.sector} onChange={set('sector')} /></Field>
          <Field label="Place" hint="City, as the public should see it" htmlFor={`pl-${p.id}`}><Input id={`pl-${p.id}`} maxLength={80} value={card.location} onChange={set('location')} /></Field>
        </div>
        <Field label="Scope" hint="One or two lines on what we did there" htmlFor={`pc-${p.id}`}><Textarea id={`pc-${p.id}`} rows={2} maxLength={600} value={card.scope} onChange={set('scope')} /></Field>
        <fieldset className="grid gap-2">
          <legend className="text-sm font-medium">Photos ({chosen.length} of at most {most} shown, in the order ticked)</legend>
          {p.photos.length === 0 && <p className="text-[13px] text-muted-foreground">No photos kept against this project yet.</p>}
          <ul className="grid grid-cols-3 gap-2 sm:grid-cols-6">
            {p.photos.map((fid) => {
              const on = chosen.includes(fid)
              return (
                <li key={fid}>
                  <button type="button" aria-pressed={on} aria-label={`${on ? 'Shown' : 'Not shown'}: photo ${fid}`} onClick={() => toggle(fid)}
                    className={`relative block w-full overflow-hidden rounded-md ring-2 ${on ? 'ring-primary' : 'ring-transparent opacity-60'}`}>
                    <img src={`/api/website/images/${fid}?thumb=1`} alt="" className="aspect-[4/3] w-full object-cover" loading="lazy" />
                    {on && <span className="absolute right-1 top-1 grid size-5 place-items-center rounded-full bg-primary text-[11px] font-semibold text-primary-foreground">{chosen.indexOf(fid) + 1}</span>}
                  </button>
                </li>
              )
            })}
          </ul>
          <div><Button type="button" variant="outline" size="sm" onClick={() => upload.pick((_, id) => { if (chosen.length < most) onChange({ ...card, photos: [...chosen, id] }) })}><ImagePlus /> Upload a photo</Button></div>
          {upload.ui}
        </fieldset>
      </div>
    </details>
  )
}

/** Upload a photo, crop it to where it goes, and put it there - or manage the pictures already up. */
export function PicturesPart({ draft, set }: { draft: Draft; set: SetDraft }) {
  const q = useWebsiteImages()
  const projects = useWebsiteProjects()
  const [where, setWhere] = useState('hero')
  const [project, setProject] = useState('')
  const caps = (draft('capabilities') as { title: string; img: string }[] | undefined) ?? []
  const story = (draft('timeline') as { y: string; t: string; img: string }[] | undefined) ?? []
  const place: Place = where === 'hero' ? 'hero' : where === 'project' ? 'project' : where === 'sitePhoto' ? 'sheet' : where.startsWith('story:') ? 'story' : 'section'
  const upload = useUpload(place, place === 'project' ? Number(project) : 0)
  const remove = useAction((id: number) => removeImage(id), { invalidate: [websiteKeys.images] })
  const [removing, setRemoving] = useState<number | null>(null)

  const options = [
    { value: 'hero', label: 'The opening photograph (replaces it)' },
    ...caps.map((c, i) => ({ value: `cap:${i}`, label: `What we build: ${c.title || 'item ' + (i + 1)}` })),
    { value: 'sitePhoto', label: 'Projects: a new drawing sheet' },
    ...story.map((m, i) => ({ value: `story:${i}`, label: `Our story: ${[m.y, m.t].filter(Boolean).join(' - ') || 'milestone ' + (i + 1)}` })),
    { value: 'project', label: 'A project' },
  ]
  const put = (path: string) => {
    if (where === 'hero') { const h = (draft('hero') ?? {}) as { photo?: Record<string, string> }; set('hero', { ...h, photo: { ...(h.photo ?? {}), img: path } }) }
    else if (where === 'sitePhoto') set('sitePhotos', [...((draft('sitePhotos') as unknown[]) ?? []), { img: path, site: '', ref: '', block: '', stage: '', shown: '' }])
    else if (where.startsWith('cap:')) { const i = Number(where.slice(4)); set('capabilities', caps.map((c, k) => (k === i ? { ...c, img: path } : c))) }
    else if (where.startsWith('story:')) { const i = Number(where.slice(6)); set('timeline', story.map((m, k) => (k === i ? { ...m, img: path } : m))) }
  }
  const { w, h } = SHAPES[place]
  return (
    <div className="grid gap-6">
      <section className="grid gap-3 rounded-lg border border-border p-4" aria-label="Upload a picture">
        <h3 className="text-base font-semibold">Upload a picture</h3>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Where it goes" htmlFor="pic-where"><Select id="pic-where" value={where} onChange={(e) => setWhere(e.target.value)} options={options} /></Field>
          {where === 'project' && (
            <Field label="Project" htmlFor="pic-project"><Select id="pic-project" value={project} placeholder="Choose a project" onChange={(e) => setProject(e.target.value)}
              options={(projects.data?.projects ?? []).map((p) => ({ value: String(p.id), label: [p.number, p.name].filter(Boolean).join(' - ') }))} /></Field>
          )}
        </div>
        <p className="text-[13px] text-muted-foreground">It is cropped to {w} × {h} ({SHAPES[place].label.toLowerCase()}) and made small for the web. {where === 'project' ? 'It joins the project\'s photos; choose which show under Projects.' : 'It goes into the draft: publish to put it on the website.'}</p>
        <div><Button type="button" disabled={where === 'project' && !project} onClick={() => upload.pick((path) => put(path))}><Upload /> Choose a photo</Button></div>
        {upload.ui}
      </section>
      <section aria-label="Pictures uploaded">
        <h3 className="mb-2 text-base font-semibold">Pictures uploaded</h3>
        {q.isPending ? <Skeleton className="h-32 w-full" /> : (q.data?.images ?? []).length === 0 ? <p className="text-sm text-muted-foreground">None yet.</p> : (
          <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
            {q.data!.images.map((i) => (
              <li key={i.id} className="overflow-hidden rounded-lg border border-border bg-card">
                <img src={pictureUrl(i.path, true)} alt={i.name} className="aspect-[4/3] w-full object-cover" loading="lazy" />
                <div className="flex flex-wrap items-center gap-1.5 p-2 text-[12px]">
                  <span className="mr-auto truncate text-muted-foreground">{SHAPES[i.place]?.label.split(' (')[0].replace(/^(The|A) /, '') ?? i.place}</span>
                  {i.published ? <Badge tone="success">On the website</Badge> : i.in_draft ? <Badge tone="warning">In the draft</Badge> : (
                    <Button type="button" variant="ghost" size="icon-sm" aria-label={`Remove ${i.name}`} onClick={() => setRemoving(i.id)}><Trash2 /></Button>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
      <ConfirmDialog open={removing !== null} onOpenChange={(o) => { if (!o) setRemoving(null) }} title="Remove this picture?" description="It is not used anywhere on the website or in the draft." confirmLabel="Remove" tone="danger"
        loading={remove.isPending} onConfirm={async () => { if (removing) await remove.mutateAsync(removing); setRemoving(null) }} />
    </div>
  )
}

/** Every time the website was published, newest first. An earlier version can be put back on the website. */
export function HistoryPart({ onRestored }: { onRestored: () => void }) {
  const q = useWebsiteVersions()
  const [asking, setAsking] = useState<{ id: number; number: number } | null>(null)
  const restore = useAction((id: number) => restoreVersion(id), { invalidate: [websiteKeys.all], onSuccess: onRestored })
  if (q.isPending) return <Skeleton className="h-32 w-full" />
  const list = q.data?.versions ?? []
  return (
    <>
      {list.length === 0 ? <p className="text-sm text-muted-foreground">Nothing has been published from here yet. The website shows the text it was built with.</p> : (
        <ol className="divide-y divide-border rounded-lg border border-border" aria-label="Published versions">
          {list.map((v, i) => (
            <li key={v.id} className="flex flex-wrap items-center gap-3 px-4 py-3">
              <History className="size-4 text-muted-foreground" aria-hidden />
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium">Version {v.number}{v.note ? ` - ${v.note}` : ''}</p>
                <p className="text-[13px] text-muted-foreground">{v.published_at}{v.published_by ? ` by ${v.published_by}` : ''}</p>
              </div>
              {i === 0 ? <Badge tone="success"><Check className="size-3" /> On the website now</Badge>
                : <Button type="button" variant="outline" size="sm" onClick={() => setAsking({ id: v.id, number: v.number })}><RotateCcw /> Restore this version</Button>}
            </li>
          ))}
        </ol>
      )}
      <ConfirmDialog open={!!asking} onOpenChange={(o) => { if (!o) setAsking(null) }} title={`Put version ${asking?.number} back on the website?`}
        description="It is published straight away, as a new version, and becomes the draft too. Any draft not yet published is replaced. The version on the website now stays in the history."
        confirmLabel="Restore this version" loading={restore.isPending} onConfirm={async () => { if (asking) await restore.mutateAsync(asking.id); setAsking(null) }} />
    </>
  )
}
