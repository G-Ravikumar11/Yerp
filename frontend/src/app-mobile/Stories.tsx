import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { BookOpen, Plus, X } from 'lucide-react'
import { markStorySeen, useStories, type Story, type StorySite } from '@/api/stories'
import { useFileBlob } from '@/components/data/FileView'
import { formatDate } from '@/lib/format'
import { useSession } from '@/lib/session'
import { cn } from '@/lib/utils'
import { letters, useCurrentSite } from './site'

/** How long one photo stays up before the next. Holding a finger on it stops the count. */
const SECONDS = 5
const RING = 'conic-gradient(from 210deg, #1f6fc4, #38bdf8, #6366f1, #1f6fc4)'

/** The first photo of a site this person has not looked at; its first photo if they have seen them all. */
const firstNew = (site: StorySite) => Math.max(0, site.stories.findIndex((s) => !s.seen))

const timeLeft = (seconds: number) => {
  const m = Math.max(1, Math.round(seconds / 60))
  return m >= 60 ? `${Math.floor(m / 60)}h ${String(m % 60).padStart(2, '0')}m` : `${m} min`
}

/**
 * Site stories, at the top of the phone's Home: one circle for each site that has photos from its diary, with a blue ring
 * while there is one this person has not looked at. A story does not go by itself: it stays until the Master or an admin
 * has opened it and leaves the row 24 hours after that. The photos themselves stay in the diary.
 * The story being watched is in the address (?story=), so the phone's back button closes it.
 */
export function StoriesRow() {
  const q = useStories()
  const go = useNavigate()
  const { can } = useSession()
  const { site: current } = useCurrentSite()
  const [params, setParams] = useSearchParams()
  const open = Number(params.get('story')) || 0
  const sites = q.data?.sites ?? []
  const mayAdd = can('site.record') && !!current
  if (!q.data || (!sites.length && !mayAdd)) return null

  const waiting = sites.reduce((n, s) => n + s.unopened, 0)
  const close = () => ((window.history.state as { idx?: number } | null)?.idx ? go(-1) : setParams({}, { replace: true }))
  return (
    <section aria-label="Site stories" className="mb-4">
      <div className="mb-2 flex items-baseline justify-between gap-3 px-1">
        <h2 className="text-[15px] font-bold tracking-tight">Site stories</h2>
        <span className="truncate text-xs text-muted-foreground">
          {q.data.admin ? (waiting ? `${waiting} waiting for you to open` : sites.length ? 'You have opened them all' : 'No photos yet') : 'Stay until the Master has seen them'}
        </span>
      </div>
      <div className="-mx-4 flex gap-3.5 overflow-x-auto px-4 pb-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
        {mayAdd && (
          <Link to={`/projects/diary?job=${current.id}&today=1`} className="w-[68px] shrink-0 text-center active:scale-95" aria-label={`Add photos to today's diary for ${current.name}`}>
            <span className="grid size-[68px] place-items-center rounded-full border-2 border-dashed border-primary text-primary"><Plus className="size-6" /></span>
            <span className="mt-1.5 block truncate text-[11.5px] text-muted-foreground">Add photo</span>
          </Link>
        )}
        {sites.map((s) => <Circle key={s.job_id} site={s} onOpen={() => setParams({ story: String(s.job_id) })} />)}
      </div>
      {open > 0 && sites.some((s) => s.job_id === open) && <Viewer sites={sites} admin={q.data.admin} hours={q.data.hours} start={open} onClose={close} />}
    </section>
  )
}

function Circle({ site, onOpen }: { site: StorySite; onOpen: () => void }) {
  const cover = site.stories.find((s) => !s.seen) ?? site.stories[site.stories.length - 1]
  const thumb = useFileBlob(cover.thumb_url)
  const fresh = site.unseen > 0
  const n = site.stories.length
  return (
    <button type="button" onClick={onOpen} aria-label={`${site.name}: ${n} ${n === 1 ? 'photo' : 'photos'}${fresh ? `, ${site.unseen} new` : ''}`} className="relative w-[68px] shrink-0 text-center active:scale-95">
      <span className="block size-[68px] rounded-full p-[3px]" style={{ background: fresh ? RING : 'var(--border)' }}>
        <span className="grid size-full place-items-center overflow-hidden rounded-full border-[3px] border-background bg-muted text-base font-bold text-muted-foreground">
          {thumb.src ? <img src={thumb.src} alt="" className="size-full object-cover" /> : letters(site.name)}
        </span>
      </span>
      {fresh && <span className="absolute right-0 top-0 grid h-5 min-w-5 place-items-center rounded-full bg-primary px-1 text-[11px] font-bold text-primary-foreground ring-2 ring-background">{site.unseen}</span>}
      <span className={cn('mt-1.5 block truncate text-[11.5px]', fresh ? 'font-semibold text-foreground' : 'text-muted-foreground')}>{site.name}</span>
    </button>
  )
}

/** One photo, loaded for this story alone, so a picture is never counted as seen before it is this story's own picture on screen. */
function Photo({ story, onShown }: { story: Story; onShown: () => void }) {
  const img = useFileBlob(story.url)
  if (img.failed) return <p className="px-8 text-center text-sm text-white/80">This photo could not be loaded. Check the connection, then tap to go on.</p>
  if (!img.src) return <span className="text-sm text-white/70" role="status">Loading the photo...</span>
  return (
    <>
      <img src={img.src} alt="" aria-hidden className="absolute inset-0 size-full scale-110 object-cover opacity-40 blur-2xl" />
      <img src={img.src} alt={story.caption || `Site photo of ${formatDate(story.diary_date)}`} onLoad={onShown} draggable={false} className="relative max-h-full max-w-full select-none object-contain" />
    </>
  )
}

/** Fetches the next photo while this one is up, so it is there when the count ends. Draws nothing. */
function Preload({ url }: { url: string }) {
  useFileBlob(url)
  return null
}

function Viewer({ sites, admin, hours, start, onClose }: { sites: StorySite[]; admin: boolean; hours: number; start: number; onClose: () => void }) {
  const go = useNavigate()
  // The row as it was when the story was opened: a photo marked seen must not move what is being watched.
  const [list] = useState(sites)
  const [at, setAt] = useState(() => {
    const i = Math.max(0, list.findIndex((s) => s.job_id === start))
    return { site: i, photo: firstNew(list[i]) }
  })
  const [held, setHeld] = useState(false)
  const [loaded, setLoaded] = useState(0)                 // the story whose own picture is on screen
  const told = useRef(new Set<number>())                  // stories the server has been told about in this sitting
  const press = useRef({ x: 0, y: 0, t: 0 })
  const site = list[at.site]
  const story = site.stories[at.photo]
  const after = site.stories[at.photo + 1] ?? list[at.site + 1]?.stories[firstNew(list[at.site + 1])]

  const next = () => {
    if (at.photo + 1 < site.stories.length) setAt({ site: at.site, photo: at.photo + 1 })
    else if (at.site + 1 < list.length) setAt({ site: at.site + 1, photo: firstNew(list[at.site + 1]) })
    else onClose()
  }
  const back = () => {
    if (at.photo > 0) setAt({ site: at.site, photo: at.photo - 1 })
    else if (at.site > 0) setAt({ site: at.site - 1, photo: list[at.site - 1].stories.length - 1 })
  }
  const step = useRef({ next, back, onClose })
  useEffect(() => { step.current = { next, back, onClose } })

  // The page behind does not scroll, and a keyboard works it too (a tablet with keys, or a browser).
  useEffect(() => {
    const was = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    const key = (e: KeyboardEvent) => {
      if (e.key === 'Escape') step.current.onClose()
      else if (e.key === 'ArrowRight') step.current.next()
      else if (e.key === 'ArrowLeft') step.current.back()
    }
    window.addEventListener('keydown', key)
    return () => {
      document.body.style.overflow = was
      window.removeEventListener('keydown', key)
    }
  }, [])

  const shown = () => {
    setLoaded(story.id)
    if (told.current.has(story.id) || (story.seen && (!admin || story.opened_at))) return
    told.current.add(story.id)
    void markStorySeen(story.id, admin, hours)
  }
  const onScreen = loaded === story.id
  // The count for this photo: it runs only while the photo is on screen and no finger is on it, and at its end the next
  // photo comes. Kept by the clock, not by a CSS animation: a phone set to reduce motion ends every animation at once,
  // and the photos would all go by in a blink.
  const bar = useRef<HTMLSpanElement>(null)
  const playing = useRef(false)
  useEffect(() => { playing.current = onScreen && !held })
  useEffect(() => {
    let elapsed = 0
    let last = performance.now()
    let frame = 0
    const tick = (now: number) => {
      if (playing.current) elapsed += Math.min(now - last, 250)      // a long gap is the app in the background, not time watched
      last = now
      const done = Math.min(1, elapsed / (SECONDS * 1000))
      if (bar.current) bar.current.style.transform = `scaleX(${done})`
      if (done >= 1) return step.current.next()
      frame = requestAnimationFrame(tick)
    }
    frame = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame)
  }, [story.id])
  const status = story.opened_at
    ? `Opened by ${story.opened_by || 'the Master'} · leaves the row in ${timeLeft(story.leaves_in_s ?? 0)}`
    : admin
      ? onScreen ? `Opened by you · leaves the row in ${hours} hours` : ''
      : 'Stays in the row until the Master or an admin opens it'

  return createPortal(
    <div role="dialog" aria-modal="true" aria-label={`Stories of ${site.name}`} className="fixed inset-0 z-[70] flex flex-col bg-black text-white">
      {/* The photo, and under the finger: tap the right to go on, the left to go back, hold to stop the count, pull down to close. */}
      <div
        className="absolute inset-0 grid touch-none place-items-center overflow-hidden"
        onPointerDown={(e) => { press.current = { x: e.clientX, y: e.clientY, t: Date.now() }; setHeld(true) }}
        onPointerCancel={() => setHeld(false)}
        onPointerUp={(e) => {
          setHeld(false)
          const dx = e.clientX - press.current.x
          const dy = e.clientY - press.current.y
          if (dy > 90 && Math.abs(dx) < 80) return onClose()
          if (Date.now() - press.current.t > 350 || Math.abs(dx) > 12 || Math.abs(dy) > 12) return
          if (e.clientX < window.innerWidth / 3) back()
          else next()
        }}
      >
        <Photo key={story.id} story={story} onShown={shown} />
      </div>
      {after && <Preload key={after.id} url={after.url} />}

      <div className="pointer-events-none relative z-10 bg-gradient-to-b from-black/70 to-transparent px-3 pb-8 pt-[max(0.75rem,env(safe-area-inset-top))]">
        <div className="flex gap-1" aria-hidden>
          {site.stories.map((s, i) => (
            <span key={s.id} className="h-[3px] flex-1 overflow-hidden rounded-full bg-white/30">
              <span key={i === at.photo ? `on-${s.id}` : `off-${i < at.photo}`} ref={i === at.photo ? bar : undefined} className="block h-full origin-left bg-white" style={{ transform: `scaleX(${i < at.photo ? 1 : 0})` }} />
            </span>
          ))}
        </div>
        <div className="mt-3 flex items-center gap-2.5">
          <span className="grid size-9 shrink-0 place-items-center rounded-full bg-white/15 text-[13px] font-bold">{letters(site.name)}</span>
          <div className="min-w-0 flex-1 leading-tight">
            <div className="truncate text-[15px] font-semibold">{site.name}</div>
            <div className="truncate text-xs text-white/75">{formatDate(story.diary_date)}{story.by && ` · ${story.by}`} · {at.photo + 1} of {site.stories.length}</div>
          </div>
          <button type="button" onClick={onClose} aria-label="Close" className="pointer-events-auto grid size-10 place-items-center rounded-full bg-white/10 active:bg-white/25"><X className="size-5" /></button>
        </div>
      </div>

      <div className="pointer-events-none relative z-10 mt-auto bg-gradient-to-t from-black/80 to-transparent px-4 pb-[max(1.25rem,env(safe-area-inset-bottom))] pt-12">
        {(story.caption || story.work_done) && <p className="line-clamp-3 text-[14.5px] leading-snug">{story.caption || story.work_done}</p>}
        <p aria-live="polite" className="mt-2 min-h-4 text-xs text-white/75">{status}</p>
        <button type="button" onClick={() => go(`/projects/diary?job=${site.job_id}&day=${story.diary_id}`, { replace: true })} className="pointer-events-auto mt-3 inline-flex h-10 items-center gap-2 rounded-full bg-white/15 px-4 text-sm font-semibold active:bg-white/30">
          <BookOpen className="size-4" /> Open this day&apos;s diary
        </button>
      </div>
    </div>,
    document.body,
  )
}
