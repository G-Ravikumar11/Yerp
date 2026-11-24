import { useEffect, useRef, useState } from 'react'
import { Download, X } from 'lucide-react'
import { useFileSheet, type HeldFile } from '@/stores/fileSheet'
import { toast } from '@/stores/toast'

/**
 * A PDF or an Excel sheet opened inside the phone app, to look at and nothing more: no copy is put in Documents and nothing is
 * handed to another app unless the person taps Save / Share in the top bar. Only the native app fills the store
 * (lib/download.ts), so in a browser this draws nothing. The PDF and spreadsheet readers are loaded only when a file is opened.
 */

function bytesOf(base64: string): Uint8Array<ArrayBuffer> {
  const bin = atob(base64)
  const out = new Uint8Array(bin.length)
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i)
  return out
}

export function FileViewer() {
  const { viewing, closeView, show } = useFileSheet()

  useEffect(() => {
    if (!viewing) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') closeView() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [viewing, closeView])

  if (!viewing) return null
  // Whatever cannot be shown here is not lost: it goes to the Save / Share box instead.
  const cannotShow = () => { closeView(); toast.error('This file could not be shown here. You can save or share it instead.'); show(viewing) }
  return (
    <div className="fixed inset-0 z-[90] flex flex-col bg-background" role="dialog" aria-modal="true" aria-label={viewing.name}>
      <div className="flex items-center gap-2 border-b border-border bg-card px-3 py-2" style={{ paddingTop: 'max(0.5rem, env(safe-area-inset-top))' }}>
        <p className="min-w-0 flex-1 truncate text-sm font-semibold">{viewing.name}</p>
        <button type="button" onClick={() => show(viewing)} className="inline-flex h-10 items-center gap-1.5 rounded-md border border-border px-3 text-sm font-medium">
          <Download className="size-4" />Save / Share
        </button>
        <button type="button" onClick={closeView} aria-label="Close" className="grid size-10 place-items-center rounded-md border border-border"><X className="size-5" /></button>
      </div>
      <div data-viewer-scroll className="min-h-0 flex-1 overflow-auto bg-muted" style={{ touchAction: 'pan-x pan-y pinch-zoom' }}>
        {/\.pdf$/i.test(viewing.name) ? <PdfBody file={viewing} onFail={cannotShow} /> : <SheetBody file={viewing} onFail={cannotShow} />}
      </div>
    </div>
  )
}

function PdfBody({ file, onFail }: { file: HeldFile; onFail: () => void }) {
  const [pages, setPages] = useState<number | null>(null)
  // Each page's height over its width, learned in the background so pages of different shapes (a landscape sheet among portrait ones) hold their places.
  const [ratios, setRatios] = useState<number[]>([])
  const docRef = useRef<unknown>(null)
  const failRef = useRef(onFail)
  failRef.current = onFail

  useEffect(() => {
    let dead = false
    ;(async () => {
      try {
        const pdfjs = await import('pdfjs-dist/legacy/build/pdf.mjs')
        const worker = (await import('pdfjs-dist/legacy/build/pdf.worker.min.mjs?url')).default
        pdfjs.GlobalWorkerOptions.workerSrc = worker
        const doc = await pdfjs.getDocument({ data: bytesOf(file.data) }).promise
        if (dead) return
        docRef.current = doc
        setPages(doc.numPages)
        const found: number[] = []
        for (let i = 1; i <= doc.numPages && !dead; i++) {
          const v = (await doc.getPage(i)).getViewport({ scale: 1 })
          found.push(v.height / v.width)
          if (i % 25 === 0 || i === doc.numPages) setRatios(found.slice())
        }
      } catch {
        if (!dead) failRef.current()
      }
    })()
    return () => { dead = true }
  }, [file])

  if (pages === null) return <p className="p-6 text-center text-sm text-muted-foreground">Opening...</p>
  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-3 p-2">
      {Array.from({ length: pages }, (_, i) => <PdfPage key={i} doc={docRef.current as PdfDoc} number={i + 1} ratio={ratios[i] ?? ratios[0] ?? 1.414} />)}
    </div>
  )
}

interface PdfDoc { getPage: (n: number) => Promise<PdfPageHandle> }
interface PdfPageHandle {
  getViewport: (o: { scale: number }) => { width: number; height: number }
  render: (o: { canvasContext: CanvasRenderingContext2D; viewport: { width: number; height: number } }) => { promise: Promise<void>; cancel: () => void }
}

/**
 * One page. It is drawn when it is within about two screens of the one being read, and let go again when it is far away,
 * so a long PDF neither fills the phone's memory nor shows blank pages while scrolling.
 */
function PdfPage({ doc, number, ratio }: { doc: PdfDoc; number: number; ratio: number }) {
  const box = useRef<HTMLDivElement>(null)
  const canvas = useRef<HTMLCanvasElement>(null)
  const [near, setNear] = useState(number <= 3)
  // The width the page is drawn for: turning the phone sideways draws it again at the new width.
  const [width, setWidth] = useState(0)

  useEffect(() => {
    const el = box.current
    if (!el) return
    // Watched from the scrolling box itself: a margin only reaches past the edge of the box the page sits in when that box is the root.
    const io = new IntersectionObserver((e) => { for (const x of e) setNear(x.isIntersecting) }, { root: el.closest('[data-viewer-scroll]'), rootMargin: '2000px 0px' })
    io.observe(el)
    const ro = new ResizeObserver(() => setWidth(Math.round(el.clientWidth)))
    ro.observe(el)
    return () => { io.disconnect(); ro.disconnect() }
  }, [])

  useEffect(() => {
    const c = canvas.current
    if (!c) return
    if (!near || !width) { c.width = 0; c.height = 0; return }
    let dead = false
    let task: { cancel: () => void } | null = null
    ;(async () => {
      const page = await doc.getPage(number)
      const base = page.getViewport({ scale: 1 })
      const scale = (width / base.width) * Math.min(window.devicePixelRatio || 1, 2)
      const viewport = page.getViewport({ scale })
      if (dead) return
      c.width = viewport.width
      c.height = viewport.height
      const ctx = c.getContext('2d')
      if (!ctx) return
      const t = page.render({ canvasContext: ctx, viewport })
      task = t
      await t.promise
    })().catch(() => undefined)
    return () => { dead = true; task?.cancel() }
  }, [near, doc, number, width])

  return (
    <div ref={box} className="w-full overflow-hidden bg-white shadow-sm" style={{ aspectRatio: `1 / ${ratio}` }}>
      <canvas ref={canvas} className="block size-full" />
    </div>
  )
}

const MAX_ROWS = 2000

/** 01/11/2026, the way dates are written here. A date in a sheet has no time zone, so its own (UTC) parts are used. */
function dayFirst(d: Date): string {
  if (Number.isNaN(d.getTime())) return ''
  const p = (n: number) => String(n).padStart(2, '0')
  const time = d.getUTCHours() || d.getUTCMinutes() ? ` ${p(d.getUTCHours())}:${p(d.getUTCMinutes())}` : ''
  return `${p(d.getUTCDate())}/${p(d.getUTCMonth() + 1)}/${d.getUTCFullYear()}${time}`
}

function SheetBody({ file, onFail }: { file: HeldFile; onFail: () => void }) {
  const [sheets, setSheets] = useState<string[]>([])
  const [active, setActive] = useState(0)
  const [rows, setRows] = useState<unknown[][] | null>(null)
  const failRef = useRef(onFail)
  failRef.current = onFail
  const blob = useRef<Blob | null>(null)

  useEffect(() => {
    let dead = false
    ;(async () => {
      try {
        const lib = await import('read-excel-file')
        blob.current = new Blob([bytesOf(file.data)], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' })
        const names = await lib.readSheetNames(blob.current)
        if (dead) return
        setSheets(names)
        setActive(0)
      } catch {
        if (!dead) failRef.current()
      }
    })()
    return () => { dead = true }
  }, [file])

  useEffect(() => {
    if (!sheets.length || !blob.current) return
    let dead = false
    setRows(null)
    ;(async () => {
      try {
        const read = (await import('read-excel-file')).default
        const data = (await read(blob.current as Blob, { sheet: active + 1 })) as unknown[][]
        if (!dead) setRows(data)
      } catch {
        if (!dead) failRef.current()
      }
    })()
    return () => { dead = true }
  }, [sheets, active])

  if (!sheets.length || rows === null) return <p className="p-6 text-center text-sm text-muted-foreground">Opening...</p>
  const shown = rows.slice(0, MAX_ROWS)
  return (
    <div className="flex min-h-full flex-col">
      {sheets.length > 1 && (
        <div className="sticky left-0 flex gap-1 overflow-x-auto border-b border-border bg-card p-2">
          {sheets.map((n, i) => (
            <button key={n + i} type="button" onClick={() => setActive(i)} className={`shrink-0 rounded-md px-3 py-1.5 text-sm ${i === active ? 'bg-primary text-primary-foreground' : 'border border-border'}`}>{n}</button>
          ))}
        </div>
      )}
      <table className="w-max min-w-full border-collapse bg-card text-sm">
        <tbody>
          {shown.map((r, i) => (
            <tr key={i} className={i === 0 ? 'bg-muted font-semibold' : ''}>
              {r.map((c, j) => <td key={j} className="whitespace-nowrap border border-border px-2 py-1.5">{c instanceof Date ? dayFirst(c) : c == null ? '' : String(c)}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length > MAX_ROWS && <p className="p-3 text-center text-xs text-muted-foreground">Showing the first {MAX_ROWS} of {rows.length} rows. Save or share the file to see all of it.</p>}
      {rows.length === 0 && <p className="p-6 text-center text-sm text-muted-foreground">This sheet is empty.</p>}
    </div>
  )
}
