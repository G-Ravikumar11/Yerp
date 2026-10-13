import { useEffect, useRef, useState } from 'react'
import { Box, Download, RefreshCw, ScanEye } from 'lucide-react'
import { Button, Modal } from '@/components/ui'
import { planTo3d, type Drawing, type Plan3D } from '@/api/drawings'
import { useAction } from '@/lib/mutate'

const WALL_H = 3
const WALL_T = 0.23
const DEFAULT_WIDTH_M = 20
const RETRY_WAIT_S = 4

/** What the buttons under the picture drive. */
interface PlanView {
  stop(): void
  reset(): void
  png(): string
}

/** A sheet already traced stays for the session, so closing and reopening the 3D view never asks the AI again. */
const traced = new Map<string, Plan3D>()

/** A room's name as a flat label to lay on its floor. */
function labelTexture(T: typeof import('three'), text: string, dark: boolean) {
  const c = document.createElement('canvas')
  c.width = 256
  c.height = 64
  const g = c.getContext('2d')
  if (g) {
    g.font = '600 26px system-ui, sans-serif'
    g.textAlign = 'center'
    g.textBaseline = 'middle'
    g.fillStyle = dark ? '#f4f4f5' : '#27272a'
    g.fillText(text.length > 18 ? `${text.slice(0, 17)}...` : text, 128, 32)
  }
  const tex = new T.CanvasTexture(c)
  tex.colorSpace = T.SRGBColorSpace
  return tex
}

/**
 * Stand the traced plan up as walls on a floor. Turned only by hand: drag to rotate, scroll to zoom. The scene is
 * drawn only when something changes (not 60 times a second), and all the walls are one merged mesh.
 */
async function mountPlan(canvas: HTMLCanvasElement, plan: Plan3D): Promise<PlanView> {
  const [T, utils] = await Promise.all([import('three'), import('three/examples/jsm/utils/BufferGeometryUtils.js')])
  const dark = document.documentElement.classList.contains('dark') || window.matchMedia('(prefers-color-scheme: dark)').matches

  // Where the plan sits in the picture, so it is centred however it was drawn.
  const xs: number[] = []
  const ys: number[] = []
  for (const w of plan.walls ?? []) {
    xs.push(w.x1, w.x2)
    ys.push(w.y1, w.y2)
  }
  for (const r of plan.rooms ?? []) {
    xs.push(r.x, r.x + r.w)
    ys.push(r.y, r.y + r.h)
  }
  const minX = Math.min(...xs), maxX = Math.max(...xs), minY = Math.min(...ys), maxY = Math.max(...ys)
  const spanPct = Math.max(maxX - minX, maxY - minY, 1)
  // The sheet's real width covers the whole picture (100%), so metres per percent comes from it.
  const metres = (plan.width_m || DEFAULT_WIDTH_M) / 100
  const cx = (minX + maxX) / 2, cy = (minY + maxY) / 2
  const wx = (x: number) => (x - cx) * metres
  const wz = (y: number) => (y - cy) * metres
  const size = Math.max(spanPct * metres, 4)

  const renderer = new T.WebGLRenderer({ canvas, antialias: true, alpha: true, powerPreference: 'high-performance' })
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
  renderer.shadowMap.enabled = true
  renderer.shadowMap.type = T.PCFSoftShadowMap
  renderer.toneMapping = T.ACESFilmicToneMapping
  renderer.toneMappingExposure = 1.05
  const scene = new T.Scene()
  const cam = new T.PerspectiveCamera(38, 1, 0.1, size * 20)

  scene.add(new T.HemisphereLight(0xdbeafe, dark ? 0x27272a : 0x9ca3af, dark ? 0.9 : 1.0))
  const sun = new T.DirectionalLight(0xfff4e0, dark ? 1.6 : 2.2)
  sun.position.set(size * 0.8, size * 1.4, size * 0.6)
  sun.castShadow = true
  sun.shadow.mapSize.set(2048, 2048)
  const sc = sun.shadow.camera
  sc.left = -size
  sc.right = size
  sc.top = size
  sc.bottom = -size
  sc.near = 0.5
  sc.far = size * 5
  sun.shadow.bias = -0.0004
  sun.shadow.normalBias = 0.03
  scene.add(sun)
  const fill = new T.DirectionalLight(0xbfdbfe, 0.5)
  fill.position.set(-size, size * 0.6, -size * 0.8)
  scene.add(fill)

  const disposables: { dispose(): void }[] = []
  const track = <D extends { dispose(): void }>(d: D): D => {
    disposables.push(d)
    return d
  }
  const root = new T.Group()
  scene.add(root)

  // Ground: a slab under the plan.
  const slab = new T.Mesh(track(new T.BoxGeometry(size * 1.08, 0.18, size * 1.08)), track(new T.MeshStandardMaterial({ color: dark ? 0x2d2d34 : 0xd4d4d8, roughness: 0.95 })))
  slab.position.y = -0.1
  slab.receiveShadow = true
  root.add(slab)

  // Room floors, each with its name laid on it.
  const floorBase = track(new T.PlaneGeometry(1, 1))
  ;(plan.rooms ?? []).forEach((r, i) => {
    const mat = track(new T.MeshStandardMaterial({ color: new T.Color().setHSL((0.08 + i * 0.137) % 1, 0.28, dark ? 0.36 : 0.8), roughness: 0.85 }))
    const m = new T.Mesh(floorBase, mat)
    m.rotation.x = -Math.PI / 2
    m.scale.set(r.w * metres, r.h * metres, 1)
    m.position.set(wx(r.x + r.w / 2), 0.012 + i * 0.0005, wz(r.y + r.h / 2))
    m.receiveShadow = true
    root.add(m)
    if (r.name) {
      const tex = track(labelTexture(T, r.name, dark))
      const lw = Math.min(Math.max(r.w * metres * 0.8, 1.6), 5)
      const label = new T.Mesh(track(new T.PlaneGeometry(lw, lw / 4)), track(new T.MeshBasicMaterial({ map: tex, transparent: true, depthWrite: false })))
      label.rotation.x = -Math.PI / 2
      label.position.set(m.position.x, 0.05, m.position.z)
      root.add(label)
    }
  })

  // Every wall into one geometry, so the whole building is a single draw.
  const parts: import('three').BufferGeometry[] = []
  const tmp = new T.Object3D()
  for (const w of plan.walls ?? []) {
    const x1 = wx(w.x1), z1 = wz(w.y1), x2 = wx(w.x2), z2 = wz(w.y2)
    const len = Math.hypot(x2 - x1, z2 - z1)
    if (len < 0.05) continue
    const g = new T.BoxGeometry(len + WALL_T, WALL_H, WALL_T) // a little long, so corners close
    tmp.position.set((x1 + x2) / 2, WALL_H / 2, (z1 + z2) / 2)
    tmp.rotation.set(0, -Math.atan2(z2 - z1, x2 - x1), 0)
    tmp.updateMatrix()
    g.applyMatrix4(tmp.matrix)
    parts.push(g)
  }
  if (parts.length) {
    const merged = track(utils.mergeGeometries(parts, false) ?? parts[0])
    parts.forEach((p) => p !== merged && p.dispose())
    const walls = new T.Mesh(merged, track(new T.MeshStandardMaterial({ color: dark ? 0xe4e4e7 : 0xf4f4f5, roughness: 0.8, metalness: 0 })))
    walls.castShadow = true
    walls.receiveShadow = true
    root.add(walls)
    const edges = new T.LineSegments(track(new T.EdgesGeometry(merged, 25)), track(new T.LineBasicMaterial({ color: dark ? 0x52525b : 0x71717a, transparent: true, opacity: 0.7 })))
    root.add(edges)
  }

  // Doors and windows, sitting just proud of the wall.
  const doorMat = track(new T.MeshStandardMaterial({ color: 0x92400e, roughness: 0.6 }))
  const glassMat = track(new T.MeshPhysicalMaterial({ color: 0x7dd3fc, roughness: 0.05, transparent: true, opacity: 0.55 }))
  const doorGeo = track(new T.BoxGeometry(0.95, 2.1, WALL_T + 0.06))
  const winGeo = track(new T.BoxGeometry(1.2, 1.1, WALL_T + 0.06))
  const nearestWallAngle = (px: number, pz: number) => {
    let best = 0
    let d = Infinity
    for (const w of plan.walls ?? []) {
      const x1 = wx(w.x1), z1 = wz(w.y1), x2 = wx(w.x2), z2 = wz(w.y2)
      const dx = x2 - x1, dz = z2 - z1
      const t = Math.max(0, Math.min(1, ((px - x1) * dx + (pz - z1) * dz) / (dx * dx + dz * dz || 1)))
      const dist = Math.hypot(px - (x1 + t * dx), pz - (z1 + t * dz))
      if (dist < d) { d = dist; best = -Math.atan2(dz, dx) }
    }
    return best
  }
  for (const o of plan.openings ?? []) {
    const win = o.type === 'window'
    const m = new T.Mesh(win ? winGeo : doorGeo, win ? glassMat : doorMat)
    const x = wx(o.x), z = wz(o.y)
    m.position.set(x, win ? 1.65 : 1.05, z)
    m.rotation.y = nearestWallAngle(x, z)
    m.castShadow = true
    root.add(m)
  }

  // Camera: turned by hand only, with a little momentum after a flick.
  const home = { yaw: 0.7, pitch: 0.7, dist: size * 1.45 }
  let { yaw, pitch, dist } = home
  let vyaw = 0
  let vpitch = 0
  let drag: { x: number; y: number } | null = null
  let raf = 0
  let alive = true
  const place = () => {
    cam.position.set(Math.sin(yaw) * Math.cos(pitch) * dist, Math.sin(pitch) * dist, Math.cos(yaw) * Math.cos(pitch) * dist)
    cam.lookAt(0, WALL_H / 4, 0)
  }
  const moving = () => !drag && (Math.abs(vyaw) > 1e-4 || Math.abs(vpitch) > 1e-4)
  const draw = () => { if (!raf && alive) raf = requestAnimationFrame(frame) }
  function frame() {
    raf = 0
    if (!alive) return
    if (moving()) {
      yaw += vyaw
      pitch = Math.max(0.05, Math.min(1.5, pitch + vpitch))
      vyaw *= 0.9
      vpitch *= 0.9
    }
    place()
    renderer.render(scene, cam)
    if (moving()) draw()
  }

  const resize = () => {
    const w = canvas.clientWidth, h = canvas.clientHeight
    if (!w || !h) return
    renderer.setSize(w, h, false)
    cam.aspect = w / h
    cam.updateProjectionMatrix()
    draw()
  }
  const down = (e: PointerEvent) => { drag = { x: e.clientX, y: e.clientY }; vyaw = vpitch = 0; canvas.setPointerCapture(e.pointerId) }
  const move = (e: PointerEvent) => {
    if (!drag) return
    vyaw = -(e.clientX - drag.x) * 0.008
    vpitch = (e.clientY - drag.y) * 0.006
    yaw += vyaw
    pitch = Math.max(0.05, Math.min(1.5, pitch + vpitch))
    drag = { x: e.clientX, y: e.clientY }
    draw()
  }
  const up = () => { drag = null; draw() }
  const wheel = (e: WheelEvent) => {
    e.preventDefault()
    dist = Math.max(size * 0.35, Math.min(size * 4, dist * (1 + e.deltaY * 0.0012)))
    draw()
  }
  canvas.addEventListener('pointerdown', down)
  canvas.addEventListener('pointermove', move)
  canvas.addEventListener('pointerup', up)
  canvas.addEventListener('pointercancel', up)
  canvas.addEventListener('wheel', wheel, { passive: false })
  const ro = new ResizeObserver(resize)
  ro.observe(canvas)
  resize()
  draw()

  return {
    stop: () => {
      alive = false
      cancelAnimationFrame(raf)
      ro.disconnect()
      canvas.removeEventListener('pointerdown', down)
      canvas.removeEventListener('pointermove', move)
      canvas.removeEventListener('pointerup', up)
      canvas.removeEventListener('pointercancel', up)
      canvas.removeEventListener('wheel', wheel)
      disposables.forEach((d) => d.dispose())
      renderer.dispose()
    },
    reset: () => { ({ yaw, pitch, dist } = home); vyaw = vpitch = 0; draw() },
    png: () => {
      place()
      renderer.render(scene, cam) // drawn again just before it is read, so the picture is never blank
      return canvas.toDataURL('image/png')
    },
  }
}

function Viewer({ plan, name }: { plan: Plan3D; name: string }) {
  const ref = useRef<HTMLCanvasElement>(null)
  const view = useRef<PlanView | null>(null)
  const [failed, setFailed] = useState(false)
  useEffect(() => {
    let dead = false
    if (ref.current) {
      mountPlan(ref.current, plan)
        .then((v) => { if (dead) v.stop(); else view.current = v })
        .then(() => { if (!dead) setFailed(false) })
        .catch(() => { if (!dead) setFailed(true) })
    }
    return () => { dead = true; view.current?.stop(); view.current = null }
  }, [plan])
  const download = () => {
    const url = view.current?.png()
    if (!url) return
    const a = document.createElement('a')
    a.href = url
    a.download = `${name.replace(/[^\w.-]+/g, '_')}-3d.png`
    a.click()
  }
  return (
    <div>
      <canvas ref={ref} aria-label="3D view of the plan" className="h-[60vh] w-full cursor-grab touch-none rounded-lg border border-border bg-surface active:cursor-grabbing" />
      {failed && <p role="alert" className="mt-2 text-[13px] text-danger">This browser could not start 3D drawing. Try another browser or turn on hardware acceleration.</p>}
      <div className="mt-3 flex flex-wrap gap-2">
        <Button size="sm" variant="outline" onClick={() => view.current?.reset()}><ScanEye className="size-4" />Reset view</Button>
        <Button size="sm" variant="outline" disabled={failed} onClick={download}><Download className="size-4" />Download picture</Button>
      </div>
    </div>
  )
}

/** The current sheet of a drawing, traced into walls and rooms and shown in 3D. A visual aid, never a measurement. */
export function Plan3DModal({ drawing, onClose }: { drawing: Drawing | null; onClose: () => void }) {
  return (
    <Modal open={!!drawing} onOpenChange={(o) => !o && onClose()} title={drawing ? `3D view - ${drawing.number}` : ''} size="lg">
      {drawing && <Plan3DBody key={drawing.id} drawing={drawing} onClose={onClose} />}
    </Modal>
  )
}

function Plan3DBody({ drawing, onClose }: { drawing: Drawing; onClose: () => void }) {
  const cacheKey = `${drawing.id}:${drawing.current_revision}:${drawing.current_file_id}`
  const run = useAction(() => planTo3d(drawing.id), {
    success: (r) => (r.available ? 'Plan traced in 3D' : r.message ?? 'Could not make the 3D view'),
    onSuccess: (r) => { if (r.available) traced.set(cacheKey, r) },
  })
  const plan = run.data?.available ? run.data : traced.get(cacheKey)
  const failure = run.data && !run.data.available ? run.data.message : run.error?.message
  // One try at a time, and a short wait after a failure, so repeated clicking cannot trip the provider's rate limit.
  const [wait, setWait] = useState(0)
  useEffect(() => {
    if (wait <= 0) return
    const t = setTimeout(() => setWait(wait - 1), 1000)
    return () => clearTimeout(t)
  }, [wait])
  const ask = () => {
    if (run.isPending || wait > 0) return
    run.mutate(undefined, { onSettled: (r) => { if (!r?.available) setWait(RETRY_WAIT_S) } })
  }
  const ok = !!plan?.available && ((plan.walls?.length ?? 0) > 0 || (plan.rooms?.length ?? 0) > 0)
  return (
    <div>
      {!ok && (
        <div className="grid place-items-center gap-3 rounded-lg border border-dashed border-border py-12 text-center">
          <Box className="size-8 text-muted-foreground" />
          <p className="max-w-sm text-[13px] text-muted-foreground">Reads the current sheet ({drawing.current_revision || 'no revision'}) and stands its walls and rooms up in 3D. Works best on a clear floor plan picture or PDF. It usually takes a few seconds.</p>
          <Button loading={run.isPending} disabled={wait > 0} onClick={ask}>
            {run.isPending ? 'Tracing the plan...' : wait > 0 ? `Try again in ${wait}s` : failure ? <><RefreshCw className="size-4" />Try again</> : 'Make the 3D view'}
          </Button>
          {failure && !run.isPending && <p role="alert" className="max-w-sm text-[13px] text-danger">{failure}</p>}
        </div>
      )}
      {plan && ok && (
        <>
          <Viewer plan={plan} name={`${drawing.number}-${drawing.current_revision}`} />
          <p className="mt-3 text-[12px] text-muted-foreground">
            {plan.walls?.length ?? 0} walls, {plan.rooms?.length ?? 0} rooms{plan.width_m ? `, about ${plan.width_m} m wide` : ', size estimated'}.
            {plan.low_confidence && ' The sheet was hard to read, so check this against the drawing.'} A visual aid only: do not take quantities from it. Drag to rotate, scroll to zoom.
          </p>
        </>
      )}
      <div className="mt-5 flex justify-end border-t border-border pt-4"><Button variant="ghost" onClick={onClose}>Close</Button></div>
    </div>
  )
}
