import { useEffect, useRef, useState } from 'react'
import { Monitor, Smartphone } from 'lucide-react'
import { siteUrl } from '@/api/website'

const DESKTOP = { w: 1280, h: 820 }
const PHONE = { w: 390, h: 780, scale: 0.78 }

/** The website itself, in two frames - a desktop screen and a phone - showing the draft as it is typed. They are the real
 *  site, so what shows here is what visitors will see once it is published. `reload` goes up when the saved draft changes
 *  (a project's card, a new photo), which the frames then fetch again. */
export function Preview({ content, reload }: { content: Record<string, unknown>; reload: number }) {
  const desk = useRef<HTMLIFrameElement>(null)
  const phone = useRef<HTMLIFrameElement>(null)
  const box = useRef<HTMLDivElement>(null)
  const [scale, setScale] = useState(0.5)
  const latest = useRef(content)
  latest.current = content
  const src = `${siteUrl()}?preview=1`

  const send = (f: HTMLIFrameElement | null, message: unknown) => f?.contentWindow?.postMessage(message, location.origin)

  // A frame says when it is ready; it is given the draft then, and again each time it changes.
  useEffect(() => {
    const on = (e: MessageEvent) => {
      if (e.origin !== location.origin || (e.data as { type?: string })?.type !== 'website-preview-ready') return
      const f = [desk.current, phone.current].find((x) => x?.contentWindow === e.source)
      send(f ?? null, { type: 'website-preview', content: latest.current })
    }
    addEventListener('message', on)
    return () => removeEventListener('message', on)
  }, [])
  useEffect(() => {
    const t = setTimeout(() => [desk.current, phone.current].forEach((f) => send(f, { type: 'website-preview', content })), 150)
    return () => clearTimeout(t)
  }, [content])
  useEffect(() => {
    if (reload) [desk.current, phone.current].forEach((f) => send(f, { type: 'website-preview-reload' }))
  }, [reload])

  useEffect(() => {
    const el = box.current
    if (!el) return
    const ro = new ResizeObserver(() => setScale(Math.min(1, (el.clientWidth || DESKTOP.w) / DESKTOP.w)))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  return (
    <section aria-label="Preview of the draft" className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_auto]">
      <figure className="min-w-0">
        <figcaption className="mb-2 flex items-center gap-1.5 text-[13px] font-medium text-muted-foreground"><Monitor className="size-4" aria-hidden /> Desktop, {DESKTOP.w} px wide</figcaption>
        <div ref={box} className="overflow-hidden rounded-lg border border-border bg-black" style={{ height: DESKTOP.h * scale }}>
          <iframe ref={desk} src={src} title="Preview of the draft on a desktop screen" style={{ width: DESKTOP.w, height: DESKTOP.h, transform: `scale(${scale})`, transformOrigin: '0 0', border: 0 }} />
        </div>
      </figure>
      <figure className="mx-auto">
        <figcaption className="mb-2 flex items-center gap-1.5 text-[13px] font-medium text-muted-foreground"><Smartphone className="size-4" aria-hidden /> Phone, {PHONE.w} px wide</figcaption>
        <div className="overflow-hidden rounded-[1.6rem] border-[6px] border-neutral-800 bg-black" style={{ width: PHONE.w * PHONE.scale + 12, height: PHONE.h * PHONE.scale + 12 }}>
          <iframe ref={phone} src={src} title="Preview of the draft on a phone" style={{ width: PHONE.w, height: PHONE.h, transform: `scale(${PHONE.scale})`, transformOrigin: '0 0', border: 0 }} />
        </div>
      </figure>
    </section>
  )
}
