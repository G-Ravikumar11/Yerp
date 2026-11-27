import { useEffect, useState } from 'react'
import { AlertTriangle, CheckCircle2, Inbox } from 'lucide-react'
import { Button } from '@/components/ui'
import { pictureUrl } from '@/api/website'
import { credentialShown } from '@/features/site/data/content'

type Draft = (key: string) => unknown
interface Item { ok: boolean; title: string; detail: string; part: string }

/** Each picture's width in pixels, as the browser reads it (0 until known, -1 if it will not load). */
function useWidths(paths: string[]) {
  const [w, setW] = useState<Record<string, number>>({})
  const key = paths.join('|')
  useEffect(() => {
    let gone = false
    for (const p of paths) {
      if (!p || w[p] !== undefined) continue
      const img = new Image()
      img.onload = () => { if (!gone) setW((x) => ({ ...x, [p]: img.naturalWidth })) }
      img.onerror = () => { if (!gone) setW((x) => ({ ...x, [p]: -1 })) }
      img.src = pictureUrl(p)
    }
    return () => { gone = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key])
  return w
}

/** What still needs doing before the website is complete - in the draft, so it shows what Publish would put up - and this
 *  week's enquiries from it. Each item opens the part where it is put right. */
export function OverviewPart({ draft, overview, go }: { draft: Draft; overview?: { enquiries_this_week: number; project_photos: number }; go: (part: string) => void }) {
  const hero = (draft('hero') ?? {}) as { photo?: { img?: string } }
  const company = (draft('company') ?? {}) as { whatsapp?: string; founded?: number | null; staff?: number | null }
  const sheets = ((draft('sitePhotos') ?? []) as { img: string; site: string }[]).filter((s) => s.img)
  const tiles = ((draft('capabilities') ?? []) as { img: string; title: string; line?: boolean }[]).filter((c) => c.img && !c.line)
  const creds = ((draft('credentials') ?? []) as { label: string; value: string }[]).filter(credentialShown)
  const story = ((draft('timeline') ?? []) as { t: string; y: string }[]).filter((m) => (m.t || m.y).trim())
  const clients = ((draft('clients') ?? []) as string[]).filter((c) => c.trim())
  const heroImg = hero.photo?.img ?? ''
  const widths = useWidths([heroImg, ...sheets.map((s) => s.img), ...tiles.map((t) => t.img)])
  const narrow = [...sheets.map((s) => ({ name: s.site || 'A sheet', img: s.img, part: 'projects' })), ...tiles.map((t) => ({ name: t.title, img: t.img, part: 'build' }))]
    .filter((x) => widths[x.img] > 0 && widths[x.img] < 1000)
  const photos = sheets.length + (overview?.project_photos ?? 0)
  const heroW = widths[heroImg] ?? 0

  const items: Item[] = [
    { ok: !!heroImg && heroW >= 1600, part: 'hero', title: 'Opening photograph at least 1600 px wide',
      detail: !heroImg ? 'There is no photograph in the opening.' : heroW > 0 ? `It is ${heroW} px wide.` : 'Checking its size…' },
    { ok: photos >= 6, part: 'projects', title: 'At least 6 project photographs', detail: `${photos} so far, on drawing sheets and on the projects shown.` },
    { ok: !!(company.whatsapp ?? '').replace(/\D/g, ''), part: 'contact', title: 'WhatsApp number', detail: 'The WhatsApp button shows on phones once it is set.' },
    { ok: creds.length > 0, part: 'quality', title: 'Credentials with their values', detail: creds.length ? `${creds.length} shown.` : 'None has a value yet, so the credentials are left off.' },
    { ok: clients.length > 0, part: 'hero', title: '"Building for": the clients', detail: clients.length ? clients.join(', ') : 'Left off the page while empty.' },
    { ok: story.length > 0, part: 'story', title: 'Our story', detail: story.length ? `${story.length} milestone(s).` : 'Left off the page until it has a milestone.' },
    { ok: !!company.founded && !!company.staff, part: 'contact', title: 'Year founded and staff count', detail: 'Each adds a figure to the opening once set.' },
    { ok: narrow.length === 0, part: narrow[0]?.part ?? 'pictures', title: 'Tiles and sheets at least 1000 px wide',
      detail: narrow.length ? narrow.map((x) => `${x.name} (${widths[x.img]} px)`).join('; ') : 'All are wide enough.' },
  ]
  const todo = items.filter((i) => !i.ok)
  return (
    <div className="grid gap-5">
      <div className="flex flex-wrap items-center gap-4 rounded-lg border border-border p-4">
        <Inbox className="size-6 text-primary" aria-hidden />
        <div className="min-w-0 flex-1">
          <p className="text-2xl font-semibold tabular-nums">{overview?.enquiries_this_week ?? 0}</p>
          <p className="text-sm text-muted-foreground">Enquiries from the website in the last 7 days. They are leads in the Tender Pipeline.</p>
        </div>
        <a href="/next/clients/pipeline" className="text-sm font-medium text-primary hover:underline">Open the Tender Pipeline</a>
      </div>
      <p className="text-sm text-muted-foreground">{todo.length ? `${todo.length} thing${todo.length > 1 ? 's' : ''} to see to.` : 'Nothing left to see to.'} Anything empty is left off the website - it never shows as missing.</p>
      <ul className="divide-y divide-border rounded-lg border border-border" aria-label="Checklist">
        {items.map((i) => (
          <li key={i.title} className="flex flex-wrap items-start gap-3 px-4 py-3">
            {i.ok ? <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-success" aria-label="Done" /> : <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warning" aria-label="To do" />}
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium">{i.title}</p>
              <p className="text-[13px] text-muted-foreground">{i.detail}</p>
            </div>
            {!i.ok && <Button type="button" variant="outline" size="sm" onClick={() => go(i.part)}>Put it right</Button>}
          </li>
        ))}
      </ul>
    </div>
  )
}
