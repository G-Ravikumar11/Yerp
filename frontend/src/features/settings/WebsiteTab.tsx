import { useEffect, useMemo, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { ExternalLink, Eye, EyeOff, Save, Send, Undo2 } from 'lucide-react'
import { Badge, Button, ConfirmDialog, Skeleton } from '@/components/ui'
import { discardDraft, publishWebsite, saveDraft, siteUrl, useWebsiteSections, websiteKeys } from '@/api/website'
import { ApiError } from '@/lib/api'
import { toast } from '@/stores/toast'
import { Edit } from './website/fields'
import { HistoryPart, LayoutPart, PicturesPart, ProjectsPart } from './website/customParts'
import { PARTS, getAt, keysOf, setAt, type Part } from './website/parts'
import { Preview } from './website/Preview'
import { CareersPart } from './website/CareersPart'

const PRIVATE = new Set(['projects'])

/** The company website's admin panel: the Master, and whoever has been given "Manage website". Every section of the site is
 *  edited here. Changes are kept as a draft - visitors see none of it - until Publish puts the whole draft on the website,
 *  and every publishing is kept in the history, from which an earlier version can be put back. The preview beside it is the
 *  site itself, at a desktop's width and a phone's, showing the draft as it is typed. */
export default function WebsiteTab() {
  const qc = useQueryClient()
  const q = useWebsiteSections()
  const params = new URLSearchParams(window.location.search)
  const [partId, setPartId] = useState(() => (PARTS.some((p) => p.id === params.get('part')) ? params.get('part')! : 'hero'))
  const focus = Number(params.get('project')) || undefined
  // What has been typed and not yet saved as the draft, by section.
  const [edits, setEdits] = useState<Record<string, unknown>>({})
  const [busy, setBusy] = useState<'' | 'save' | 'publish' | 'discard'>('')
  const [asking, setAsking] = useState<'' | 'publish' | 'discard'>('')
  const [preview, setPreview] = useState(true)
  const [reload, setReload] = useState(0)

  const sections = useMemo(() => q.data?.sections ?? [], [q.data])
  const server = useMemo(() => Object.fromEntries(sections.map((s) => [s.key, s.draft])), [sections])
  const draft = (key: string) => (key in edits ? edits[key] : server[key])
  const set = (key: string, value: unknown) => setEdits((e) => ({ ...e, [key]: value }))
  const unsaved = Object.keys(edits).length > 0
  const unpublished = sections.filter((s) => s.unpublished_changes)
  const part = PARTS.find((p) => p.id === partId) ?? PARTS[0]
  const content = useMemo(() => Object.fromEntries(Object.keys(server).filter((k) => !PRIVATE.has(k)).map((k) => [k, k in edits ? edits[k] : server[k]])), [server, edits])

  // Leaving with words typed and not saved: the browser asks first.
  useEffect(() => {
    if (!unsaved) return
    const stop = (e: BeforeUnloadEvent) => e.preventDefault()
    addEventListener('beforeunload', stop)
    return () => removeEventListener('beforeunload', stop)
  }, [unsaved])

  const refresh = async () => {
    await qc.invalidateQueries({ queryKey: websiteKeys.all })
    setReload((n) => n + 1)
  }
  const fail = (e: unknown) => toast.error(e instanceof ApiError ? e.message : 'That did not work. Try again.')

  /** Saves what has been typed as the draft. False when the server refused part of it (that part stays unsaved). */
  const saveAll = async () => {
    for (const [key, value] of Object.entries(edits)) {
      try {
        await saveDraft(key, value)
        setEdits((e) => { const { [key]: _, ...rest } = e; return rest })
      } catch (e) {
        fail(e)
        await refresh()
        return false
      }
    }
    await refresh()
    return true
  }
  const run = async (what: 'save' | 'publish' | 'discard', note = '') => {
    setBusy(what)
    try {
      if (what === 'discard') {
        for (const s of unpublished) await discardDraft(s.key)
        setEdits({})
        await refresh()
        toast.success('The draft is thrown away. The panel shows what is on the website.')
      } else if (await saveAll()) {
        if (what === 'publish') {
          const res = await publishWebsite(note)
          await refresh()
          toast.success(res.message)
        } else toast.success('Draft saved. Visitors see none of it until it is published.')
      }
    } catch (e) {
      fail(e)
    } finally {
      setBusy('')
      setAsking('')
    }
  }

  if (q.isPending) return <Skeleton className="h-96 w-full" />
  if (q.isError) return <p className="text-sm text-danger">The website&apos;s sections could not be loaded. Try again in a moment.</p>

  const partState = (p: Part) => {
    const keys = keysOf(p)
    if (keys.some((k) => k in edits)) return 'unsaved'
    if (keys.some((k) => sections.find((s) => s.key === k)?.unpublished_changes)) return 'draft'
    return ''
  }

  return (
    <div className="grid gap-6">
      <div className="sticky top-0 z-10 -mx-1 flex flex-wrap items-center gap-3 rounded-lg border border-border bg-card/95 px-4 py-3 shadow-sm backdrop-blur">
        <div className="mr-auto min-w-0 text-sm" role="status">
          {unsaved ? <span className="font-medium text-warning">Changes not saved yet</span>
            : unpublished.length ? <span className="font-medium">Draft ready: {unpublished.length} section{unpublished.length > 1 ? 's' : ''} changed and not yet on the website</span>
              : <span className="text-muted-foreground">The website shows everything here.{q.data?.latest ? ` Version ${q.data.latest.number}, published ${q.data.latest.published_at}.` : ''}</span>}
        </div>
        <a href={siteUrl()} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1.5 text-sm font-medium text-primary hover:underline">Open the website <ExternalLink className="size-3.5" aria-hidden /></a>
        <Button variant="ghost" size="sm" onClick={() => setPreview((v) => !v)} aria-pressed={preview}>{preview ? <EyeOff /> : <Eye />} {preview ? 'Hide preview' : 'Show preview'}</Button>
        <Button variant="outline" size="sm" disabled={(!unsaved && !unpublished.length) || !!busy} onClick={() => setAsking('discard')}><Undo2 /> Discard draft</Button>
        <Button variant="outline" size="sm" disabled={!unsaved || !!busy} loading={busy === 'save'} onClick={() => run('save')}><Save /> Save draft</Button>
        <Button size="sm" disabled={(!unsaved && !unpublished.length) || !!busy} loading={busy === 'publish'} onClick={() => setAsking('publish')}><Send /> Publish</Button>
      </div>

      <div className="grid gap-6 lg:grid-cols-[13rem_minmax(0,1fr)]">
        <nav aria-label="Parts of the website" className="lg:sticky lg:top-20 lg:self-start">
          <ul className="flex gap-1 overflow-x-auto pb-1 lg:grid lg:overflow-visible">
            {PARTS.map((p) => {
              const st = partState(p)
              return (
                <li key={p.id} className="shrink-0">
                  <button type="button" onClick={() => setPartId(p.id)} aria-current={p.id === part.id ? 'page' : undefined}
                    className={`flex w-full items-center justify-between gap-2 rounded-md px-3 py-2 text-left text-sm ${p.id === part.id ? 'bg-primary-soft font-medium text-primary' : 'hover:bg-accent'}`}>
                    {p.label}
                    {st && <span className={`size-2 rounded-full ${st === 'unsaved' ? 'bg-warning' : 'bg-info'}`} aria-label={st === 'unsaved' ? 'not saved' : 'draft not published'} />}
                  </button>
                </li>
              )
            })}
          </ul>
        </nav>

        <section aria-labelledby="part-title" className="grid min-w-0 content-start gap-6">
          <div>
            <h2 id="part-title" className="text-lg font-semibold">{part.label}</h2>
            {part.hint && <p className="text-sm text-muted-foreground">{part.hint}</p>}
          </div>
          {part.custom === 'layout' && <LayoutPart draft={draft} set={set} />}
          {part.custom === 'history' && <HistoryPart onRestored={() => { setEdits({}); setReload((n) => n + 1) }} />}
          {part.custom === 'pictures' && <PicturesPart draft={draft} set={set} />}
          {(part.blocks ?? []).map((b, i) => (
            <div key={`${b.key}-${i}`} className="grid gap-3 rounded-lg border border-border p-4">
              {b.title && <h3 className="text-base font-semibold">{b.title}</h3>}
              <Edit spec={b.spec} value={getAt(draft(b.key), b.path)} onChange={(v) => set(b.key, setAt(draft(b.key), b.path ?? [], v))} />
            </div>
          ))}
          {part.custom === 'projects' && <ProjectsPart draft={draft} set={set} focus={focus} />}
          {part.custom === 'careers' && <CareersPart onChanged={() => setReload((n) => n + 1)} />}
          {keysOf(part).some((k) => k in edits) && (
            <div><Button variant="ghost" size="sm" onClick={() => setEdits((e) => Object.fromEntries(Object.entries(e).filter(([k]) => !keysOf(part).includes(k))))}><Undo2 /> Undo what is not saved here</Button></div>
          )}
        </section>
      </div>

      {preview && (
        <div className="grid gap-2">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-lg font-semibold">Preview</h2>
            <Badge tone="warning">Draft - not on the website</Badge>
            <p className="w-full text-[13px] text-muted-foreground">The website as it will look once published. Text and pictures change as you type; a project&apos;s card shows here once the draft is saved.</p>
          </div>
          <Preview content={content} reload={reload} />
        </div>
      )}

      <ConfirmDialog open={asking === 'publish'} onOpenChange={(o) => { if (!o) setAsking('') }} title="Publish the website?"
        description={`Everything in the draft${unsaved ? ', with what is not yet saved,' : ''} goes on the website now, and is kept in the history as the next version.`}
        confirmLabel="Publish" reason={{ label: 'What changed (optional)', placeholder: 'e.g. New photos of Giddaluru' }} loading={busy === 'publish'} onConfirm={(note) => run('publish', note)} />
      <ConfirmDialog open={asking === 'discard'} onOpenChange={(o) => { if (!o) setAsking('') }} title="Throw the draft away?"
        description="Every change not yet published - saved or not - is dropped, and the panel shows what is on the website. Pictures already uploaded stay in Pictures." confirmLabel="Discard draft" tone="danger"
        loading={busy === 'discard'} onConfirm={() => run('discard')} />
    </div>
  )
}
