import { useCallback, useEffect, useRef, useState } from 'react'
import { Button, Modal } from '@/components/ui'
import type { Place } from '@/api/website'

/** The shape each place on the website needs, and the size it is saved at: big enough for a wide screen, small enough
 *  for a phone on a slow connection. The server keeps them as they come (it makes nothing bigger). */
export const SHAPES: Record<Place, { w: number; h: number; label: string }> = {
  hero: { w: 1600, h: 900, label: 'Opening banner (wide, 16:9)' },
  section: { w: 1200, h: 900, label: 'A section (4:3)' },
  story: { w: 1200, h: 800, label: 'Our story (3:2)' },
  project: { w: 1200, h: 900, label: 'A project (4:3)' },
}
const QUALITY = 0.82

/** Draws the chosen part of the picture at the place's size, as a JPEG. */
export function cropToBlob(img: HTMLImageElement, place: Place, view: { x: number; y: number; scale: number; frameW: number }): Promise<Blob> {
  const { w, h } = SHAPES[place]
  const canvas = document.createElement('canvas')
  canvas.width = w
  canvas.height = h
  const ctx = canvas.getContext('2d')
  if (!ctx) return Promise.reject(new Error('This browser cannot crop pictures.'))
  const k = w / view.frameW
  ctx.fillStyle = '#fff'
  ctx.fillRect(0, 0, w, h)
  ctx.imageSmoothingQuality = 'high'
  ctx.drawImage(img, view.x * k, view.y * k, img.naturalWidth * view.scale * k, img.naturalHeight * view.scale * k)
  return new Promise((resolve, reject) => canvas.toBlob((b) => (b ? resolve(b) : reject(new Error('The picture could not be made.'))), 'image/jpeg', QUALITY))
}

/** Crop a photo to the shape its place needs: drag to move it in the frame, the slider (or + and -) to zoom. Saved small
 *  enough for the web, as a JPEG. */
export function Cropper({ file, place, onCancel, onDone, busy }: { file: File; place: Place; onCancel: () => void; onDone: (blob: Blob) => void; busy?: boolean }) {
  const { w, h, label } = SHAPES[place]
  const frame = useRef<HTMLDivElement>(null)
  const [img, setImg] = useState<HTMLImageElement | null>(null)
  const [url, setUrl] = useState('')
  const [frameW, setFrameW] = useState(480)
  const [zoom, setZoom] = useState(1)
  const [pos, setPos] = useState({ x: 0, y: 0 })
  const [error, setError] = useState('')
  const drag = useRef<{ x: number; y: number; px: number; py: number } | null>(null)
  const frameH = frameW * (h / w)

  useEffect(() => {
    const u = URL.createObjectURL(file)
    const im = new Image()
    im.onload = () => setImg(im)
    im.onerror = () => setError('That file is not a picture this browser can open. Try a JPEG or PNG.')
    im.src = u
    setUrl(u)
    return () => URL.revokeObjectURL(u)
  }, [file])

  // Measured when the frame appears (the dialog draws it after this component first renders) and whenever it resizes.
  const observer = useRef<ResizeObserver | null>(null)
  const frameRef = useCallback((el: HTMLDivElement | null) => {
    observer.current?.disconnect()
    frame.current = el
    if (!el) return
    setFrameW(el.clientWidth || 480)
    observer.current = new ResizeObserver(() => setFrameW(el.clientWidth || 480))
    observer.current.observe(el)
  }, [])
  useEffect(() => () => observer.current?.disconnect(), [])

  // The picture always covers the frame: at zoom 1 it just fills it.
  const cover = img ? Math.max(frameW / img.naturalWidth, frameH / img.naturalHeight) : 1
  const scale = cover * zoom
  const dispW = img ? img.naturalWidth * scale : 0
  const dispH = img ? img.naturalHeight * scale : 0
  const clamp = (x: number, y: number) => ({ x: Math.min(0, Math.max(frameW - dispW, x)), y: Math.min(0, Math.max(frameH - dispH, y)) })
  // Centred when a picture arrives or the frame changes size.
  useEffect(() => {
    if (img) setPos({ x: (frameW - img.naturalWidth * cover) / 2, y: (frameH - img.naturalHeight * cover) / 2 })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [img, frameW])
  const view = clamp(pos.x, pos.y)

  const setZoomAt = (z: number) => {
    const nz = Math.min(4, Math.max(1, z))
    // Zoom about the middle of the frame.
    const cx = frameW / 2, cy = frameH / 2
    const f = nz / zoom
    setPos({ x: cx - (cx - view.x) * f, y: cy - (cy - view.y) * f })
    setZoom(nz)
  }
  const small = img && (img.naturalWidth < w * 0.6 || img.naturalHeight < h * 0.6)

  return (
    <Modal open onOpenChange={(o) => { if (!o) onCancel() }} title="Crop the picture" description={`${label}. Drag the picture to choose what shows; zoom to frame it closer. It is saved at ${w} × ${h} for the web.`} size="lg"
      footer={<>
        <Button variant="ghost" onClick={onCancel}>Cancel</Button>
        <Button loading={busy} disabled={!img} onClick={() => img && cropToBlob(img, place, { ...view, scale, frameW }).then(onDone, (e: Error) => setError(e.message))}>Use this picture</Button>
      </>}>
      {error ? <p role="alert" className="text-sm text-danger">{error}</p> : (
        <div className="grid gap-3">
          <div ref={frameRef} className="relative w-full touch-none select-none overflow-hidden rounded-md bg-muted ring-1 ring-border" style={{ height: frameH, cursor: 'grab' }}
            role="img" aria-label="The crop: drag to move the picture, arrow keys move it too" tabIndex={0}
            onKeyDown={(e) => {
              const step = e.shiftKey ? 40 : 10
              const d = { ArrowLeft: [step, 0], ArrowRight: [-step, 0], ArrowUp: [0, step], ArrowDown: [0, -step] }[e.key]
              if (d) { e.preventDefault(); setPos(clamp(view.x + d[0], view.y + d[1])) }
              if (e.key === '+' || e.key === '=') setZoomAt(zoom + 0.1)
              if (e.key === '-') setZoomAt(zoom - 0.1)
            }}
            onPointerDown={(e) => { (e.target as HTMLElement).setPointerCapture?.(e.pointerId); drag.current = { x: e.clientX, y: e.clientY, px: view.x, py: view.y } }}
            onPointerMove={(e) => { const d = drag.current; if (d) setPos(clamp(d.px + e.clientX - d.x, d.py + e.clientY - d.y)) }}
            onPointerUp={() => { drag.current = null }}
            onWheel={(e) => setZoomAt(zoom - e.deltaY * 0.001)}>
            {img && <img src={url} alt="" draggable={false} className="absolute max-w-none" style={{ left: view.x, top: view.y, width: dispW, height: dispH }} />}
          </div>
          <label className="flex items-center gap-3 text-sm">
            <span className="w-12 text-muted-foreground">Zoom</span>
            <input type="range" min={1} max={4} step={0.01} value={zoom} onChange={(e) => setZoomAt(Number(e.target.value))} className="flex-1 accent-primary" aria-label="Zoom" />
          </label>
          {small && <p className="text-[13px] text-warning">This picture is smaller than the place it goes. It may look soft on a large screen.</p>}
        </div>
      )}
    </Modal>
  )
}
